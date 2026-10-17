"""Autotestes #38-40: many tiny files, bounded read-only drive survey, isolated restore.

No disk formatting, original-file overwrite, boot writes or real-backup restore.
#39 intentionally surveys metadata only and cannot certify complete inventory
or dependencies. #38 and #40 use private synthetic TemporaryDirectory trees.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import time

from backup_core import build_plan, copy_backup, sha256_file
from backup_features import restore_selected, safe_relative, verified_entries
from runtime_volumes import discover_drive_letters
from selective_recovery import verify_complete_manifest


def _check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError('Autoteste interrompido; resultado não aprovado.')


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _report(number, **values):
    return {
        'schema': f'pcro-autoteste-bateria-v{number}',
        'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'aprovado',
        **values,
        'real_user_backups_accessed': False,
        'physical_independence_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
    }


def _verify(manifest, count, total, cancelled=None):
    result = verify_complete_manifest(manifest, cancelled=cancelled)
    _require(result['files_verified'] == count and result['bytes_verified'] == total,
             'Backup incompleto ou SHA-256 divergente.')
    entries = verified_entries(manifest)
    _require(len(entries) == count, 'Manifesto verificado contém número inesperado de arquivos.')
    return entries


def _check_restored(folder, entries, cancelled=None):
    for relative, item in entries.items():
        _check(cancelled)
        restored = folder / relative
        _require(restored.is_file() and restored.stat().st_size == item['bytes']
                 and sha256_file(restored, cancelled) == item['sha256'],
                 'Arquivo restaurado não corresponde ao SHA-256 original.')


def run_tiny_files_stress_autotest(*, cancelled=None, count=2048):
    """#38: 2048 small files by default; CI can use a bounded count for speed."""
    _check(cancelled)
    if not 1 <= count <= 4096:
        raise ValueError('Quantidade sintética fora dos limites de teste.')
    with tempfile.TemporaryDirectory(prefix='PCRO-AUTOTESTE38-') as temp:
        root = Path(temp).resolve(strict=True)
        source, backups, restores = (root / n for n in ('source', 'backups', 'restores'))
        for folder in (source, backups, restores):
            folder.mkdir()
        original = {}
        for index in range(count):
            _check(cancelled)
            folder = source / f'grupo-{index % 32:02d}'
            folder.mkdir(exist_ok=True)
            file = folder / f'item-{index:05d}.txt'
            payload = f'PCRO38::{index:05d}::{index*17}\n'.encode('utf-8')
            file.write_bytes(payload)
            original[file] = hashlib.sha256(payload).hexdigest()
        plan = build_plan({str(source): 'keep'}, [str(root)], cancelled=cancelled)
        _require(plan.count == count and not plan.warnings, 'Inventário de arquivos pequenos falhou.')
        start = time.perf_counter()
        folder, outcome = copy_backup(plan, backups, cancelled=cancelled, strategy_inventory={})
        backup_seconds = time.perf_counter() - start
        _require(outcome['status'] == 'concluido', 'Cópia de arquivos pequenos não terminou.')
        entries = _verify(folder / 'manifest.json', count, plan.total, cancelled)
        _check(cancelled)
        start = time.perf_counter()
        restored, restored_count = restore_selected(
            folder / 'manifest.json', list(entries), restores, cancelled=cancelled,
            strategy_inventory={},
        )
        restore_seconds = time.perf_counter() - start
        _require(restored_count == count, 'Restauração não recuperou todos os arquivos.')
        _check_restored(restored, entries, cancelled)
        for path, sha in original.items():
            _check(cancelled)
            _require(sha256_file(path, cancelled) == sha, 'Arquivo sintético original modificado.')
        report = _report(
            38, fixture_files=count, fixture_bytes=plan.total, groups=32,
            backup_elapsed_seconds=round(backup_seconds, 4),
            restore_elapsed_seconds=round(restore_seconds, 4),
            backup_sha256_verified=True, restore_sha256_verified=True,
            all_filenames_preserved=True, originals_preserved=True,
            note=('Arquivos exclusivamente sintéticos; tempos não certificam desempenho em '
                  'milhões de arquivos nem em discos com erros.'),
        )
    report['temporary_data_cleaned'] = not root.exists()
    _require(report['temporary_data_cleaned'], 'Diretório temporário permaneceu no disco.')
    return report


CANDIDATE_NAMES = {
    'steamapps', 'common', 'saved games', 'games', 'jogos',
    'program files', 'program files (x86)', 'appdata', 'osu!',
}


def _fixed_or_removable_drive(letter):
    """Do not probe mapped network shares, CD/DVD or unsupported Windows drives."""
    if os.name != 'nt':
        return False
    import ctypes
    path = letter + ':\\'
    api = ctypes.windll.kernel32.GetDriveTypeW
    api.argtypes = [ctypes.c_wchar_p]
    api.restype = ctypes.c_uint
    kind = api(path)
    return kind in (2, 3)  # DRIVE_REMOVABLE, DRIVE_FIXED


def scan_readonly_metadata(roots, *, cancelled=None, max_entries_per_root=3000, max_depth=2):
    """No file reads/writes: bounded os.scandir metadata, skips reparse points.

    Returns counts, NOT a full catalog, confirmed program associations or file paths.
    """
    if not 1 <= max_entries_per_root <= 10000 or not 0 <= max_depth <= 4:
        raise ValueError('Limites inválidos para a auditoria.')
    _check(cancelled)
    results = []
    for raw_root in roots:
        _check(cancelled)
        root = Path(raw_root)
        _require(root.is_dir() and not root.is_symlink(), 'Raiz não é diretório acessível.')
        counts = dict(root=str(root), examined=0, files=0, directories=0,
                      reparse_skipped=0, errors=0, candidate_folders=0,
                      truncated=False)
        work = deque([(root, 0)])
        while work:
            _check(cancelled)
            folder, depth = work.popleft()
            try:
                with os.scandir(folder) as stream:
                    for entry in stream:
                        _check(cancelled)
                        if counts['examined'] >= max_entries_per_root:
                            counts['truncated'] = True
                            break
                        counts['examined'] += 1
                        try:
                            info = entry.stat(follow_symlinks=False)
                            reparse = bool(getattr(info, 'st_file_attributes', 0) & 0x400)
                            if entry.is_symlink() or reparse:
                                counts['reparse_skipped'] += 1
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                counts['directories'] += 1
                                if entry.name.casefold() in CANDIDATE_NAMES:
                                    counts['candidate_folders'] += 1
                                if depth < max_depth:
                                    work.append((Path(entry.path), depth + 1))
                            elif stat.S_ISREG(info.st_mode):
                                counts['files'] += 1
                        except OSError:
                            counts['errors'] += 1
            except OSError:
                counts['errors'] += 1
            if counts['truncated']:
                break
        results.append(counts)
    _require(bool(results), 'Nenhuma raiz acessível para auditoria de leitura.')
    return results


def run_readonly_inventory_autotest(*, cancelled=None, roots=None):
    """#39: user-triggered, metadata-only survey; no backup data content accessed."""
    _check(cancelled)
    if roots is None:
        if os.name != 'nt':
            raise RuntimeError('Auditoria automática #39 disponível apenas no Windows.')
        roots = [letter + ':\\' for letter in discover_drive_letters()
                 if _fixed_or_removable_drive(letter) and Path(letter + ':\\').is_dir()]
    results = scan_readonly_metadata(roots, cancelled=cancelled)
    count = sum(item['examined'] for item in results)
    _require(count > 0, 'Nenhum item foi examinado na auditoria.')
    return _report(
        39, roots_seen=len(results), entries_examined=count,
        files_observed=sum(x['files'] for x in results),
        folders_observed=sum(x['directories'] for x in results),
        candidate_folder_names_observed=sum(x['candidate_folders'] for x in results),
        reparse_points_skipped=sum(x['reparse_skipped'] for x in results),
        scan_errors=sum(x['errors'] for x in results),
        partial_coverage=True, volume_surveys=results,
        content_files_opened=0, no_write_calls=True,
        note=('Apenas nomes de diretórios e metadados foram observados; limite de '
              'profundidade e entradas por unidade. Não é inventário completo '
              'nem confirma softwares, saves, dependências ou independência física.'),
    )


def run_isolated_full_restore_autotest(*, cancelled=None):
    """#40: selected synthetic items, exclusions and isolated full restore."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix='PCRO-AUTOTESTE40-') as temp:
        root = Path(temp).resolve(strict=True)
        source, backups, restores = (root / n for n in ('source', 'backups', 'restores'))
        for folder in (source, backups, restores):
            folder.mkdir()
        files = {}
        for group in ('jogo', 'programa', 'saves'):
            subdir = source / group
            subdir.mkdir()
            for index in range(2):
                _check(cancelled)
                file = subdir / f'dado-{index}.bin'
                payload = (f'PCRO40:{group}:{index}'.encode('utf-8') * (index + 1))
                file.write_bytes(payload)
                files[file] = hashlib.sha256(payload).hexdigest()
        skipped = source / 'saves' / 'dado-1.bin'
        choices = {str(source): 'keep', str(skipped): 'skip'}
        plan = build_plan(choices, [str(root)], cancelled=cancelled)
        _require(plan.count == 5 and not plan.warnings,
                 'Seleção granular incluiu item excluído ou falhou.')
        _require(all(Path(item.source) != skipped for item in plan.files),
                 'Arquivo marcado não copiar entrou no plano.')
        untouched = restores / 'marcador-preexistente.txt'
        untouched.write_text('preservar', encoding='utf-8')
        folder, outcome = copy_backup(plan, backups, cancelled=cancelled, strategy_inventory={})
        _require(outcome['status'] == 'concluido', 'Backup seletivo não concluiu.')
        entries = _verify(folder / 'manifest.json', 5, plan.total, cancelled)
        _require(all(Path(item.source) != skipped for item in plan.files)
                 and len(entries) == 5, 'Manifesto incluiu itens excluídos.')
        restored, count = restore_selected(
            folder / 'manifest.json', list(entries), restores, cancelled=cancelled,
            strategy_inventory={},
        )
        _require(count == 5 and restored.parent == restores,
                 'Restauração não foi isolada ou não foi completa.')
        _check_restored(restored, entries, cancelled)
        _require(not any(path.name == skipped.name and path.parent.name == 'saves'
                         for path in restored.rglob('*')),
                 'Arquivo excluído apareceu na restauração.')
        _require(untouched.read_text(encoding='utf-8') == 'preservar',
                 'Arquivo preexistente do destino foi alterado.')
        try:
            safe_relative('../caminho-externo')
        except ValueError:
            path_traversal_blocked = True
        else:
            raise AssertionError('Manifesto aceitou escape de pasta.')
        for path, sha in files.items():
            _check(cancelled)
            _require(sha256_file(path, cancelled) == sha, 'Fonte sintética foi alterada.')
        report = _report(
            40, fixture_files=6, selected_files=5, excluded_files=1,
            backup_sha256_verified=True, restore_sha256_verified=True,
            excluded_item_absent=True, existing_destination_file_preserved=True,
            restore_isolated=True, originals_preserved=True,
            unsafe_relative_path_blocked=path_traversal_blocked,
            note=('Restauração ponta a ponta de arquivos fictícios apenas. '
                  'Não reinstala programas, não testa permissões NTFS nem valida discos reais.'),
        )
    report['temporary_data_cleaned'] = not root.exists()
    _require(report['temporary_data_cleaned'], 'Diretório temporário permaneceu no disco.')
    return report
