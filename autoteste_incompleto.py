"""Autoteste #26: missing files and incomplete manifests must block restoration.

Only tiny synthetic files inside a new TemporaryDirectory are used.
The routine never accepts paths to the user's existing backups or disks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from backup_core import atomic_json, sha256_file
from selective_recovery import verify_complete_manifest, run_isolated_restore_test


_FIXTURES = {
    'arquivo-A.txt': b'PCRO-AUTOTESTE26-ARQUIVO-A\n',
    'arquivo-B.txt': b'PCRO-AUTOTESTE26-ARQUIVO-B\n',
}


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError('Autoteste #26 cancelado.')


def _expect_rejection(action, expected_text, label):
    """Reject success or an unrelated failure; assert the expected safety guard."""
    try:
        action()
    except (OSError, ValueError) as exc:
        if expected_text not in str(exc):
            raise AssertionError(
                f'{label}: rejeição por motivo inesperado: {exc}'
            ) from exc
        return str(exc)
    raise AssertionError(f'{label}: backup inseguro foi aceito indevidamente.')


def _verify_and_refuse_restore(manifest, destination, expected_text, label, *, cancelled):
    _check_cancel(cancelled)
    verify_error = _expect_rejection(
        lambda: verify_complete_manifest(manifest, cancelled=cancelled),
        expected_text, f'{label} / conferir backup',
    )
    _check_cancel(cancelled)
    restore_error = _expect_rejection(
        lambda: run_isolated_restore_test(
            manifest, destination, cancelled=cancelled,
            test_root=destination.parent,
        ),
        expected_text, f'{label} / recuperação',
    )
    if any(destination.iterdir()):
        raise AssertionError(f'{label}: recuperação criou arquivos antes de bloquear.')
    return {'verification_error': verify_error, 'restoration_error': restore_error}


def run_incomplete_backup_autotest(*, cancelled=None):
    """Check the production verifier and restore guard with disposable fixtures.

    Scenarios: a physically missing file, a partially completed backup, and a
    completed-looking manifest with fewer recorded files than expected.
    Returns JSON-compatible evidence suitable for explicit UI export.
    """
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix='PCRO-AUTOTESTE26-') as temp:
        root = Path(temp).resolve(strict=True)
        generated = root / 'fontes-ficticias'
        good = root / 'backup-integro'
        missing = root / 'backup-arquivo-ausente'
        partial = root / 'backup-parcial'
        truncated = root / 'backup-manifesto-incompleto'
        for folder in (generated, good):
            folder.mkdir()

        entries = []
        original_hashes = {}
        for filename, contents in _FIXTURES.items():
            _check_cancel(cancelled)
            source = generated / filename
            source.write_bytes(contents)
            relative = Path('C', 'PCRO-AUTOTESTE26', filename)
            copy = good / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(contents)
            digest = hashlib.sha256(contents).hexdigest()
            original_hashes[filename] = digest
            entries.append({
                'source': str(source),
                'relative': relative.as_posix(),
                'bytes': len(contents),
                'sha256': digest,
                'verified': True,
            })

        manifest_doc = {
            'schema': 'pc-restore-backup-v0.4',
            'status': 'concluido',
            'errors': [],
            'file_count_expected': len(entries),
            'bytes_expected': sum(entry['bytes'] for entry in entries),
            'files': entries,
        }
        good_manifest = good / 'manifest.json'
        atomic_json(good_manifest, manifest_doc)
        if verify_complete_manifest(good_manifest, cancelled=cancelled)['files_verified'] != 2:
            raise AssertionError('Backup sintético íntegro não foi aprovado.')

        # Never remove or alter a user file: copies are under the new temp root.
        _check_cancel(cancelled)
        for destination in (missing, partial, truncated):
            shutil.copytree(good, destination)

        for destination in (missing, partial, truncated):
            check = verify_complete_manifest(destination / 'manifest.json', cancelled=cancelled)
            if check['files_verified'] != 2:
                raise AssertionError('Cópia de teste não passou na conferência inicial.')

        restore_missing = root / 'restauracao-arquivo-ausente'
        restore_partial = root / 'restauracao-parcial'
        restore_truncated = root / 'restauracao-manifesto-incompleto'
        for destination in (restore_missing, restore_partial, restore_truncated):
            destination.mkdir()

        # Scenario 1: missing physical file, still referenced by the manifest.
        absent = missing / Path(entries[0]['relative'])
        if not absent.is_file() or absent.stat().st_size != entries[0]['bytes']:
            raise AssertionError('Arquivo de teste ausente antes da simulação.')
        absent.unlink()
        missing_result = _verify_and_refuse_restore(
            missing / 'manifest.json', restore_missing,
            'Arquivo de backup ausente ou SHA-256 divergente',
            'Arquivo ausente', cancelled=cancelled,
        )

        # Scenario 2: interrupted/partial status must never certify a backup.
        _check_cancel(cancelled)
        partial_manifest = partial / 'manifest.json'
        doc = json.loads(partial_manifest.read_text(encoding='utf-8'))
        doc['status'] = 'parcial_com_erros'
        doc['errors'] = [{'error': 'Falha fictícia: cópia não concluída.'}]
        atomic_json(partial_manifest, doc)
        partial_result = _verify_and_refuse_restore(
            partial_manifest, restore_partial,
            'Backup parcial, interrompido ou com erros. Não aprovado.',
            'Backup parcial', cancelled=cancelled,
        )

        # Scenario 3: dishonest completed state with a missing manifest entry.
        _check_cancel(cancelled)
        truncated_manifest = truncated / 'manifest.json'
        doc = json.loads(truncated_manifest.read_text(encoding='utf-8'))
        doc['files'] = doc['files'][:1]  # expected count remains 2
        atomic_json(truncated_manifest, doc)
        truncated_result = _verify_and_refuse_restore(
            truncated_manifest, restore_truncated,
            'Número de arquivos do manifesto não corresponde ao plano.',
            'Manifesto incompleto', cancelled=cancelled,
        )

        _check_cancel(cancelled)
        if verify_complete_manifest(good_manifest, cancelled=cancelled)['files_verified'] != 2:
            raise AssertionError('Backup fictício íntegro foi alterado.')
        if any(sha256_file(generated / name, cancelled) != digest
               for name, digest in original_hashes.items()):
            raise AssertionError('Arquivo fictício de origem foi alterado.')

        result = {
            'schema': 'pcro-autoteste-backup-incompleto-v1',
            'executed_at_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'aprovado',
            'scenarios': 3,
            'fixture_files': len(entries),
            'fixture_bytes': manifest_doc['bytes_expected'],
            'healthy_manifest_verified': True,
            'copies_verified_before_faults': True,
            'missing_file_detected': True,
            'missing_file_restore_blocked': True,
            'partial_backup_detected': True,
            'partial_backup_restore_blocked': True,
            'truncated_manifest_detected': True,
            'truncated_manifest_restore_blocked': True,
            'restore_output_empty': True,
            'healthy_fixture_preserved': True,
            'missing_file_rejection': missing_result,
            'partial_backup_rejection': partial_result,
            'truncated_manifest_rejection': truncated_result,
            'real_user_backups_accessed': False,
            'physical_independence_verified': False,
            'ready_for_format': False,
            'installation_authorized': False,
            'note': ('Teste isolado com dados fictícios. Verifica bloqueios para '
                     'arquivo ausente, backup parcial e manifesto incompleto. '
                     'Não comprova a integridade dos backups reais ou dos discos '
                     'e não autoriza formatar ou reinstalar o Windows.'),
        }

    # The context manager has finished deleting only the temporary test tree.
    result['temporary_data_cleaned'] = not root.exists()
    if not result['temporary_data_cleaned']:
        raise AssertionError('A pasta temporária não foi removida.')
    return result
