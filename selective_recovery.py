"""PCRO v0.6.6: narrowly scoped, non-destructive preservation test.

This module does not format, remove files or restore into original locations.
The existing verified transfer engine performs the actual I/O; this wrapper
requires confirmed C: selections and a separate destination. It explicitly
never certifies the machine ready for Windows installation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import ntpath
import os
import shutil
import stat

from backup_core import (build_plan, copy_backup, sha256_file, atomic_json,
                         is_reparse, human_size)
from backup_features import read_manifest, verified_entries
from restore_elevation import guarded_restore_selected, require_not_elevated
from backup_destination_guard import (destination_ancestry_identity,
                                      verify_committed_backup_file)
from drive_catalog import safe_to_mark
from volume_paths import volume_of
from copy_refusal import (KIND_LINK, KIND_SOBREPOR, KIND_UNIDADE,
                          CopyRefusal)

FILE_LIMIT = 400_000
REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _any_reparse_ancestor(path):
    """Reject a selected path under any existing symlink or Windows junction."""
    p = Path(path)
    for current in (p, *p.parents):
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                bool((getattr(info, 'st_file_attributes', 0) or 0) & REPARSE_FLAG)):
            raise CopyRefusal(KIND_LINK,
                              f'Link/junção proibido no caminho: {current}')


def prepare_selected_c(paths, *, choices=None, test_root=None, cancelled=None):
    """Make a file-level plan, with errors instead of silent omission.

    test_root is ONLY for portable filesystem unit tests. Production UI never
    supplies it; with it omitted Windows is mandatory and only C: is allowed.
    """
    selected = list(dict.fromkeys(str(p) for p in paths if isinstance(p, str) and p.strip()))
    if not selected:
        raise ValueError('Nenhum caminho do C: está marcado para preservação.')
    if test_root is None:
        if os.name != 'nt':
            raise RuntimeError('O backup real de C: só pode ser iniciado no Windows.')
        for p in selected:
            if volume_of(p) != 'C:' or not safe_to_mark(p):
                raise ValueError(f'Origem insegura ou fora do C: {p}')
        allowed = ['C:\\']
    else:
        allowed = [str(Path(test_root).resolve(strict=True))]
        for p in selected:
            if not Path(p).is_absolute():
                raise ValueError(f'Caminho de teste não é absoluto: {p}')
            if not os.path.commonpath((str(Path(p).resolve()), allowed[0])) == allowed[0]:
                raise ValueError(f'Caminho de teste fora da raiz permitida: {p}')
    for p in selected:
        _any_reparse_ancestor(p)
        if not os.path.lexists(p):
            raise ValueError(f'Fonte não encontrada: {p}')

    final_choices = {p: 'keep' for p in selected}
    for p, decision in (choices or {}).items():
        if decision == 'skip' and (test_root is not None or volume_of(p) == 'C:'):
            final_choices[str(p)] = 'skip'
    # Explicitly selected parent must remain keep; skips can exclude children.
    for p in selected:
        final_choices[p] = 'keep'
    plan = build_plan(final_choices, allowed, cancelled=cancelled)
    if plan.warnings:
        raise ValueError('Varredura incompleta. Corrija antes de copiar:\n' + '\n'.join(plan.warnings[:12]))
    if not plan.files:
        raise ValueError('Os caminhos escolhidos não contêm arquivos comuns acessíveis.')
    if plan.count > FILE_LIMIT:
        raise ValueError(f'Quantidade muito grande ({plan.count} arquivos). Divida o backup em lotes.')
    if len({t.destination.casefold() for t in plan.files}) != plan.count:
        raise ValueError('Colisão de nomes detectada no plano de backup.')
    for t in plan.files:
        _any_reparse_ancestor(t.source)
    return plan


def validate_target(destination, *, restore=False, test_root=None, forbidden=()):
    """Require an existing writable volume other than C:, outside protected sources."""
    target = Path(destination)
    if not target.is_dir():
        raise CopyRefusal(KIND_UNIDADE,
                          'Selecione uma pasta de destino existente e acessível.')
    _any_reparse_ancestor(target)
    if test_root is None:
        drive = volume_of(str(target))
        if os.name != 'nt' or drive == 'SEM UNIDADE' or drive == 'C:':
            raise CopyRefusal(KIND_UNIDADE,
                              'Escolha uma pasta existente em unidade diferente de C:. '
                              'Este fluxo preserva somente origens selecionadas no C:.')
    resolved = target.resolve(strict=True)
    for source in forbidden:
        other = Path(source).resolve(strict=True)
        if (resolved == other or resolved in other.parents or other in resolved.parents):
            raise CopyRefusal(KIND_SOBREPOR,
                              'A pasta de destino não pode se sobrepor à origem/backup.')
    return resolved


def verify_complete_manifest(manifest_path, *, cancelled=None):
    """Independently re-hash every backed-up file before calling it verified."""
    path = Path(manifest_path).resolve(strict=True)
    doc = read_manifest(path)
    if doc.get('status') != 'concluido' or doc.get('errors'):
        raise ValueError('Backup parcial, interrompido ou com erros. Não aprovado.')
    entries = verified_entries(path)
    expected = doc.get('file_count_expected')
    if not isinstance(expected, int) or expected < 1 or len(entries) != expected:
        raise ValueError('Número de arquivos do manifesto não corresponde ao plano.')
    if len(doc['files']) != expected:
        raise ValueError('Manifesto contém entradas duplicadas ou não verificadas.')
    checked = 0
    for rel, item in entries.items():
        if cancelled and cancelled.is_set():
            raise InterruptedError('Verificação interrompida.')
        target = path.parent / rel
        _any_reparse_ancestor(target)
        # Reuse the identity-bound verifier from the copy engine. A path-only
        # hash could accept a different file swapped between stat and open.
        try:
            ancestry = destination_ancestry_identity(path.parent, target)
            expected_size = int(item['bytes'])
            verify_committed_backup_file(
                path.parent, target, ancestry, expected_size,
                item['sha256'].lower(), cancelled)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OSError(
                f'Arquivo de backup ausente, alterado ou SHA-256 divergente: {rel}') from exc
        checked += expected_size
    if checked != doc.get('bytes_expected'):
        raise ValueError('O tamanho verificado não corresponde ao esperado.')
    return {'files_verified': len(entries), 'bytes_verified': checked,
            'manifest': str(path), 'verified_at_utc': datetime.now(timezone.utc).isoformat(),
            'backup_verified': True, 'restore_verified': False,
            'ready_for_format': False, 'installation_authorized': False}


def run_selected_backup(plan, destination, *, cancelled=None, progress=None, test_root=None):
    """Create unique backup folder, verify it, and record its safety limits."""
    base = validate_target(destination, test_root=test_root,
                           forbidden=[t.source for t in plan.files])
    if cancelled and cancelled.is_set():
        raise InterruptedError('Backup cancelado antes de iniciar.')
    folder, manifest = copy_backup(plan, base, cancelled=cancelled, progress=progress,
                                   display_name='Dados selecionados do C - ensaio v066')
    path = folder / 'manifest.json'
    if manifest.get('status') != 'concluido':
        raise OSError(f'Backup não concluído ({manifest.get("status")}). Confira {path}')
    result = verify_complete_manifest(path, cancelled=cancelled)
    result.update(schema='pcro-selective-safety-v066', backup_folder=str(folder),
                  source_paths=list(plan.selected), notice=
                  'Cópia verificada neste armazenamento; não substitui uma segunda cópia independente.')
    atomic_json(folder / 'VERIFICACAO-PCRO-066.json', result)
    return result


def run_isolated_restore_test(manifest_path, destination, *, cancelled=None,
                              progress=None, test_root=None, elevation_probe=None):
    """Restore EVERY verified file into an isolated new directory and recheck it.

    P2-02: refused before any check or write when the process is elevated.
    """
    require_not_elevated(probe=elevation_probe)
    manifest = Path(manifest_path).resolve(strict=True)
    destination_parent = validate_target(destination, restore=True, test_root=test_root,
                                         forbidden=[manifest.parent])
    precheck = verify_complete_manifest(manifest, cancelled=cancelled)
    entries = verified_entries(manifest)
    # Check real disk space; do not risk filling another drive during a test.
    usage = shutil.disk_usage(destination_parent)
    required = precheck['bytes_verified']
    reserve = max(2 * 1024**3, int(usage.free * 0.05))
    if usage.free < required + reserve:
        raise OSError(f'Espaço insuficiente para teste ({human_size(required)} necessários, '
                      f'{human_size(usage.free)} livres; manter reserva de {human_size(reserve)}).')
    folder, count = guarded_restore_selected(manifest, list(entries), destination_parent,
                                             elevation_probe=elevation_probe,
                                             cancelled=cancelled, progress=progress)
    if count != precheck['files_verified']:
        raise OSError('Restauração incompleta; verifique o relatório parcial.')
    report = dict(schema='pcro-selective-restore-test-v066',
                  completed_utc=datetime.now(timezone.utc).isoformat(),
                  manifest=str(manifest), restored_folder=str(folder),
                  files_verified=count, bytes_verified=required,
                  backup_verified=True, restore_verified=True,
                  ready_for_format=False, installation_authorized=False,
                  notice='Teste isolado de restauração. Nenhum arquivo foi devolvido ao C:.')
    atomic_json(folder / 'RESULTADO-TESTE-PCRO-066.json', report)
    return report
