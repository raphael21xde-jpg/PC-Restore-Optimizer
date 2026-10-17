"""Autoteste #25: corrupt data is detected and its restoration is refused.

All files are synthetic and live in a newly created TemporaryDirectory.
No user-selected backup or restoration path is ever read, modified or removed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import tempfile

from backup_core import atomic_json, sha256_file
from selective_recovery import verify_complete_manifest, run_isolated_restore_test


_FIXTURES = {
    'teste-A.txt': b'PCRO-AUTOTEST-25-A\n',
    'teste-B.txt': b'PCRO-AUTOTEST-25-B\n',
}


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError('Autoteste #25 cancelado.')


def _expect_sha256_rejection(action, description):
    """Only a genuine SHA-256 mismatch qualifies as successful rejection."""
    try:
        action()
    except (OSError, ValueError) as exc:
        if 'SHA-256 divergente' not in str(exc):
            raise AssertionError(
                f'{description}: bloqueio por causa inesperada: {exc}'
            ) from exc
        return str(exc)
    raise AssertionError(f'{description}: dado corrompido foi aceito indevidamente.')


def run_integrity_autotest(*, cancelled=None):
    """Exercise the real manifest verifier and restore guard on throwaway data.

    No paths from the user's current plan or from earlier backups are accepted.
    All generated files are small, self-owned and automatically deleted.
    The returned JSON-compatible report must be explicitly exported in the UI.
    """
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix='PCRO-AUTOTESTE25-') as scratch:
        root = Path(scratch).resolve(strict=True)
        generated = root / 'origens-ficticias'
        healthy = root / 'backup-saudavel'
        damaged = root / 'backup-corrompido'
        restore_dest = root / 'restauracao-isolada'
        for directory in (generated, healthy, restore_dest):
            directory.mkdir()

        entries = []
        source_hashes = {}
        for filename, payload in _FIXTURES.items():
            _check_cancel(cancelled)
            source = generated / filename
            source.write_bytes(payload)
            relative = Path('C', 'PCRO-AUTOTESTE25', filename)
            target = healthy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            source_hashes[filename] = digest
            entries.append({
                'source': str(source), 'relative': relative.as_posix(),
                'bytes': len(payload), 'sha256': digest, 'verified': True,
            })

        manifest_data = {
            'schema': 'pc-restore-backup-v0.4',
            'status': 'concluido', 'errors': [],
            'file_count_expected': len(entries),
            'bytes_expected': sum(item['bytes'] for item in entries),
            'files': entries,
        }
        original_manifest = healthy / 'manifest.json'
        atomic_json(original_manifest, manifest_data)
        before = verify_complete_manifest(original_manifest, cancelled=cancelled)
        if before['files_verified'] != len(entries):
            raise AssertionError('Falha na validação inicial do backup fictício.')

        _check_cancel(cancelled)
        shutil.copytree(healthy, damaged)
        damaged_manifest = damaged / 'manifest.json'
        copied = verify_complete_manifest(damaged_manifest, cancelled=cancelled)
        if copied['files_verified'] != len(entries):
            raise AssertionError('A cópia isolada não passou na conferência inicial.')

        # Same-length corruption: a size-only check would NOT catch this.
        relative = Path(entries[0]['relative'])
        victim = damaged / relative
        original_size = victim.stat().st_size
        with victim.open('r+b') as stream:
            byte = stream.read(1)
            if not byte:
                raise AssertionError('Arquivo fictício vazio; não pode ser corrompido.')
            stream.seek(0)
            stream.write(bytes((byte[0] ^ 1,)))
        if victim.stat().st_size != original_size:
            raise AssertionError('A alteração de teste mudou o tamanho do arquivo.')
        if sha256_file(victim, cancelled) == entries[0]['sha256']:
            raise AssertionError('O hash não mudou após a alteração controlada.')

        _check_cancel(cancelled)
        verify_error = _expect_sha256_rejection(
            lambda: verify_complete_manifest(damaged_manifest, cancelled=cancelled),
            'Verificação do manifesto',
        )
        _check_cancel(cancelled)
        restore_error = _expect_sha256_rejection(
            lambda: run_isolated_restore_test(
                damaged_manifest, restore_dest, cancelled=cancelled,
                test_root=root,
            ),
            'Restauração do backup corrompido',
        )
        if any(restore_dest.iterdir()):
            raise AssertionError('A restauração corrompida criou arquivos indevidamente.')

        still_healthy = verify_complete_manifest(original_manifest, cancelled=cancelled)
        if still_healthy['files_verified'] != len(entries):
            raise AssertionError('O backup saudável fictício foi alterado.')
        if any(sha256_file(generated / name, cancelled) != digest
               for name, digest in source_hashes.items()):
            raise AssertionError('Um dos arquivos de origem fictícios foi alterado.')

        result = {
            'schema': 'pcro-autoteste-integridade-v1',
            'executed_at_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'aprovado',
            'scenario': 'Corrupção de 1 byte com o mesmo tamanho de arquivo',
            'fixture_files': len(entries),
            'fixture_bytes': manifest_data['bytes_expected'],
            'healthy_manifest_verified': True,
            'copy_verified_before_corruption': True,
            'sha256_mismatch_detected': True,
            'unsafe_restore_blocked': True,
            'restore_output_empty': True,
            'healthy_fixture_preserved': True,
            'verify_rejection': verify_error,
            'restore_rejection': restore_error,
            'temporary_data_cleaned': True,
            'real_user_backups_accessed': False,
            'physical_independence_verified': False,
            'ready_for_format': False,
            'installation_authorized': False,
            'note': ('Autoteste sintético isolado do verificador e da proteção de restauração. '
                     'Não testa os backups reais, a integridade física dos discos nem autoriza formatar.'),
        }
    # TemporaryDirectory removed only data that this function created.
    return result
