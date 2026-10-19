"""Read-only inspection for the experimental multi-copy recovery center.

The live application does not import this module. Every path must be inside
the caller's isolated fixture root. Inspection performs no writes; it never
approves a Windows installation or asserts physical independence of copies.
"""
from __future__ import annotations

from pathlib import Path

from backup_features import read_manifest, safe_relative, verified_entries
from multi_source_fixture_restore import _inside, _overlaps
from selective_recovery import _any_reparse_ancestor, verify_complete_manifest

SCHEMA = 'pcro-fixture-recovery-center-v1'


def inspect_fixture_recovery(plan, copies_report, restore_parent, *,
                             test_root, cancelled=None):
    """Inspect all copies, compare inventories and rehash every completed copy.

    An invalid/missing copy can be bypassed only when another complete copy
    agrees with every other readable, structurally valid manifest. The result
    is a read-only snapshot, NOT permission to trust that data later without
    the restore engine's independent rechecks.
    """
    if test_root is None:
        raise ValueError('Central experimental exige raiz de testes isolada.')
    _any_reparse_ancestor(Path(test_root))
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz de testes inválida.')
    if not getattr(plan, 'files', None) or getattr(plan, 'warnings', None):
        raise ValueError('Plano incompleto.')
    if not isinstance(copies_report, dict) or (
        copies_report.get('schema') != 'pcro-multi-source-fixture-copies-v1'
    ):
        raise ValueError('Relatório de cópias incompatível.')
    rows = copies_report.get('destinations')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Relatório de cópias inválido.')
    parent = _inside(sandbox, restore_parent)
    if not parent.is_dir():
        raise ValueError('Pasta de recuperação inexistente.')

    expected = {}
    source_paths = []
    for task in plan.files:
        source = _inside(sandbox, task.source, existing=False)
        source_paths.append(source)
        key = safe_relative(task.destination).as_posix()
        if key in expected or type(task.size) is not int or task.size < 0:
            raise ValueError('Plano contém destinos duplicados ou tamanho inválido.')
        expected[key] = task.size
    if any(_overlaps(parent, source) for source in source_paths):
        raise ValueError('Recuperação não pode sobrepor arquivos de origem.')

    statuses = []
    candidates = []
    backup_roots = []
    for index, row in enumerate(rows, 1):
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Inspeção interrompida.')
        if not isinstance(row, dict):
            raise ValueError('Registro de cópia inválido.')
        base = _inside(sandbox, row.get('path'))
        if not base.is_dir() or _overlaps(base, parent):
            raise ValueError('Cópia e destino de recuperação sobrepostos.')
        if any(_overlaps(base, prior) for prior in backup_roots):
            raise ValueError('Pastas de cópia duplicadas ou aninhadas.')
        backup_roots.append(base)
        status = {'copy_index': index, 'path': str(base),
                  'status': 'not_verified', 'files_verified': 0}
        statuses.append(status)
        if row.get('status') not in ('local_copy_verified', 'discovered_unverified'):
            status['status'] = 'not_completed_at_backup'
            continue

        manifest = row.get('manifest')
        if not isinstance(manifest, str):
            status['status'] = 'manifest_missing'
            continue
        file = _inside(sandbox, manifest, existing=False)
        if file.name != 'manifest.json' or file.parent.parent != base:
            raise ValueError('Manifesto fora da cópia autorizada.')
        if not file.is_file():
            status['status'] = 'manifest_missing'
            continue
        try:
            doc = read_manifest(file)
            entries = verified_entries(file)
            if (doc.get('status') != 'concluido' or doc.get('errors') or
                doc.get('file_count_expected') != len(expected) or
                doc.get('bytes_expected') != sum(expected.values()) or
                len(doc['files']) != len(expected) or
                set(entries) != set(expected) or
                any(type(item.get('bytes')) is not int or
                    item['bytes'] != expected[key]
                    for key, item in entries.items())):
                raise ValueError('Inventário não corresponde ao plano.')
            signature = {key: (item['bytes'], item['sha256'].lower())
                         for key, item in entries.items()}
            candidates.append((file, status, signature))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            status['status'] = 'manifest_invalid'

    divergent = bool(candidates) and any(
        signature != candidates[0][2]
        for _, _, signature in candidates[1:])
    if divergent:
        for _, row, _ in candidates:
            row['status'] = 'manifest_conflict'
    else:
        for file, row, _ in candidates:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError('Inspeção interrompida.')
            try:
                verification = verify_complete_manifest(
                    file, cancelled=cancelled)
                if verification.get('backup_verified') is not True:
                    raise OSError('Verificação do backup incompleta.')
                row['status'] = 'copy_verified'
                row['files_verified'] = verification['files_verified']
            except InterruptedError:
                raise
            except (OSError, ValueError, TypeError, KeyError):
                row['status'] = 'integrity_failed'

    good = next((row['copy_index'] for row in statuses
                 if row['status'] == 'copy_verified'), None)
    return {
        'schema': SCHEMA,
        'status': ('manifest_conflict' if divergent else
                   'copy_available' if good is not None else 'no_usable_copy'),
        'copies_checked': len(rows),
        'copies_verified': sum(row['status'] == 'copy_verified'
                               for row in statuses),
        'copies': statuses,
        'suggested_copy_index': good,
        'files': [{'key': key, 'bytes': size}
                  for key, size in sorted(expected.items())],
        'can_restore_in_fixture': good is not None and not divergent,
        'backup_verified': good is not None and not divergent,
        'restore_verified': False,
        'physical_independence_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'note': ('Inspeção dos backups de TESTE. O motor verificará novamente '
                 'as cópias antes de recuperar qualquer arquivo.'),
    }
