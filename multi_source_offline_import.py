"""Reopen synthetic backed-up copies without an original PC inventory.

Explicitly TEST-ONLY. Reads manifest files in at most eight user-selected
fixture backup roots, never enumerates real disks, never writes or formats.

The reconstructed Plan contains *unavailable placeholders*, NOT trustworthy
original source paths. It is exclusively for the existing sandbox-only restore
center. A manifest's SHA-256 does not authenticate an untrusted provider.
"""
from __future__ import annotations

import re
from pathlib import Path

from backup_core import FileTask, Plan
from backup_features import read_manifest, safe_relative, verified_entries
from multi_source_fixture_restore import _inside, _overlaps
from selective_recovery import _any_reparse_ancestor

SCHEMA = 'pcro-offline-fixture-session-v1'
MAX_FILES = 400_000
FINGERPRINT = re.compile(r'[0-9a-fA-F]{64}\Z')


def _inventory_from_manifest(manifest):
    """Validate manifest structure without asserting payload integrity."""
    doc = read_manifest(manifest)
    entries = verified_entries(manifest)
    fingerprint = doc.get('plan_fingerprint')
    expected_count = doc.get('file_count_expected')
    expected_bytes = doc.get('bytes_expected')
    if (doc.get('status') != 'concluido' or doc.get('errors') or
            not isinstance(fingerprint, str) or
            not FINGERPRINT.fullmatch(fingerprint) or
            type(expected_count) is not int or
            not 1 <= expected_count <= MAX_FILES or
            type(expected_bytes) is not int or expected_bytes < 0 or
            len(doc['files']) != expected_count or
            len(entries) != expected_count):
        raise ValueError('Manifesto não contém inventário completo confiável.')

    signature = {}
    folded = set()
    for raw, item in entries.items():
        key = safe_relative(raw).as_posix()
        normalized = key.casefold()
        size = item.get('bytes')
        if (normalized in folded or type(size) is not int or size < 0):
            raise ValueError('Caminhos duplicados ou tamanho inválido.')
        folded.add(normalized)
        signature[key] = (size, item['sha256'].lower())
    if sum(value[0] for value in signature.values()) != expected_bytes:
        raise ValueError('Somatório de tamanhos divergente.')
    return fingerprint.lower(), signature


def reopen_fixture_backup_session(backup_roots, restore_parent, *,
                                  test_root, cancelled=None):
    """Reconstruct a read-only recoverable selection from existing copies.

    One backup-* child per selected root is allowed to prevent accidentally
    combining different backup jobs. Malformed copies can be skipped only if
    another structurally valid manifest supplies the full inventory. Readable
    but conflicting manifests ALWAYS block the session.
    """
    if test_root is None:
        raise ValueError('Reabertura experimental exige raiz de testes isolada.')
    _any_reparse_ancestor(Path(test_root))
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz de testes inválida.')
    if not isinstance(backup_roots, (list, tuple)) or not 1 <= len(backup_roots) <= 8:
        raise ValueError('Escolha entre uma e oito pastas de cópias de testes.')
    restored = _inside(sandbox, restore_parent)
    if not restored.is_dir():
        raise ValueError('Destino de restauração inexistente.')

    rows = []
    inventories = []
    known = []
    for raw in backup_roots:
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Reabertura de backups cancelada.')
        root = _inside(sandbox, raw)
        if (not root.is_dir() or _overlaps(root, restored) or
                any(_overlaps(root, earlier) for earlier in known)):
            raise ValueError('Pastas de cópias duplicadas ou sobrepostas.')
        known.append(root)
        # Intentionally shallow: never walk a disk or guess between sessions.
        backup_dirs = []
        for child in root.iterdir():
            if not child.name.startswith('backup-'):
                continue
            _any_reparse_ancestor(child)
            if not child.is_dir():
                continue
            checked = _inside(sandbox, child)
            if checked.parent != root:
                raise ValueError('Backup encontrado fora da pasta informada.')
            backup_dirs.append(checked)
            if len(backup_dirs) > 1:
                raise ValueError(
                    'Mais de um backup na pasta. Escolha uma pasta sem ambiguidade.')
        row = {'path': str(root), 'status': 'not_completed_at_backup'}
        rows.append(row)
        if not backup_dirs:
            continue
        path = backup_dirs[0] / 'manifest.json'
        _any_reparse_ancestor(path)
        row.update(status='discovered_unverified', manifest=str(path))
        if not path.is_file():
            continue
        try:
            fingerprint, signature = _inventory_from_manifest(path)
            inventories.append((fingerprint, signature))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Do not treat a bad manifest as valid. The integrity viewer will
            # report it separately; another good copy may remain usable.
            pass

    if not inventories:
        raise ValueError(
            'Nenhum manifesto de teste completo para reconstruir o inventário.')
    reference_fp, reference_files = inventories[0]
    if any((fp != reference_fp or files != reference_files)
           for fp, files in inventories[1:]):
        raise ValueError(
            'Manifestos de backups diferentes; não combinar as cópias.')

    # The former computer's source paths are never trusted or required here.
    # These paths are deliberately nonexistent synthetic placeholders, and
    # cannot grant any access to an original file or disk.
    unavailable = sandbox / '.pcro-origens-ausentes'
    if unavailable.exists():
        raise ValueError('Área reservada para origens ausentes já existe.')
    tasks = [
        FileTask(
            str(unavailable / safe_relative(key)),
            size, 0, key,
        )
        for key, (size, _digest) in sorted(reference_files.items())
    ]
    reconstructed_plan = Plan(
        files=tasks, total=sum(size for size, _ in reference_files.values()))
    report = {
        'schema': 'pcro-multi-source-fixture-copies-v1',
        'status': 'discovered_unverified',
        'copies_requested': len(rows),
        'copies_verified_locally': 0,
        'destinations': rows,
        'backup_verified': False,
        'restore_test_verified': False,
        'physical_independence_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
    }
    return {
        'schema': SCHEMA,
        'offline_mode': True,
        'plan': reconstructed_plan,
        'copies_report': report,
        'restore_parent': str(restored),
        'original_sources_required': False,
        'backup_verified': False,
        'restore_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'note': (
            'Plano reconstruído de manifestos, não dos arquivos originais. '
            'A recuperação sempre recalcula SHA-256 e permanece isolada.'
        ),
    }
