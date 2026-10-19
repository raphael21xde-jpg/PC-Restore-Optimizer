"""Select a verified backup copy and restore chosen files in an isolated sandbox.

This module has NO production/UI entry point, never deletes originals, and
does not establish physical backup independence or permission to format.
It intentionally does not combine files from different backup manifests.
"""
from __future__ import annotations

from pathlib import Path

from backup_destination_guard import (
    destination_ancestry_identity, verify_committed_backup_file,
)
from backup_features import (
    read_manifest, restore_selected, safe_relative, verified_entries,
)
from selective_recovery import _any_reparse_ancestor, verify_complete_manifest


def _inside(sandbox, value, *, existing=True):
    if not isinstance(value, (str, Path)):
        raise ValueError('Caminho de teste inválido.')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Caminho de teste não é absoluto.')
    _any_reparse_ancestor(path)
    path = path.resolve(strict=existing)
    if path == sandbox or sandbox not in path.parents:
        raise ValueError('Caminho fora da raiz isolada.')
    return path


def _overlaps(first, second):
    return first == second or first in second.parents or second in first.parents


def recover_from_fixture_copies(plan, copies_report, selected, restore_parent, *,
                                test_root, cancelled=None):
    """Verify entire copies first, then recover explicit keys from ONE copy.

    Files are never combined between manifests. A bad payload can be rescued
    from another copy only when the available readable manifest inventories
    agree. Changes during the actual restore are rejected by restore_selected.
    The caller must use synthetic fixture paths under test_root.
    """
    if test_root is None:
        raise ValueError('Recuperação experimental exige raiz de testes isolada.')
    _any_reparse_ancestor(Path(test_root))
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz isolada inválida.')
    if not getattr(plan, 'files', None) or getattr(plan, 'warnings', None):
        raise ValueError('Plano de origem ausente ou incompleto.')
    if not isinstance(copies_report, dict) or (
        copies_report.get('schema') != 'pcro-multi-source-fixture-copies-v1'
    ):
        raise ValueError('Relatório de cópias incompatível.')
    rows = copies_report.get('destinations')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Relatório não contém cópias de teste válidas.')
    if not isinstance(selected, (list, tuple)) or not selected:
        raise ValueError('Selecione explicitamente os arquivos a recuperar.')
    keys = [safe_relative(key).as_posix() for key in selected]
    if len(keys) != len(set(keys)):
        raise ValueError('Seleção contém arquivos repetidos.')

    expected = {}
    for task in plan.files:
        source = _inside(sandbox, task.source, existing=False)
        key = safe_relative(task.destination).as_posix()
        if key in expected or type(task.size) is not int or task.size < 0:
            raise ValueError('Plano contém destino duplicado ou tamanho inválido.')
        expected[key] = task.size
    if not set(keys) <= set(expected):
        raise ValueError('Arquivo escolhido não pertence ao plano original.')

    parent = _inside(sandbox, restore_parent)
    if not parent.is_dir():
        raise ValueError('Pasta de recuperação inexistente.')
    for task in plan.files:
        source = _inside(sandbox, task.source, existing=False)
        if _overlaps(parent, source):
            raise ValueError('Recuperação não pode sobrepor arquivo de origem.')

    candidates = []
    report_rows = []
    targets = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Entrada de cópia inválida.')
        destination = _inside(sandbox, row.get('path'))
        if not destination.is_dir() or _overlaps(parent, destination):
            raise ValueError('Destino de cópia e recuperação sobrepostos.')
        if any(_overlaps(destination, previous) for previous in targets):
            raise ValueError('Destinos de cópia duplicados ou sobrepostos.')
        targets.append(destination)
        outcome = {'copy_index': len(report_rows) + 1,
                   'status': 'not_verified'}
        report_rows.append(outcome)
        if row.get('status') != 'local_copy_verified':
            outcome['status'] = 'not_completed_at_backup'
            continue
        manifest = row.get('manifest')
        if not isinstance(manifest, str):
            outcome['status'] = 'manifest_missing'
            continue
        path = _inside(sandbox, manifest, existing=False)
        if path.name != 'manifest.json' or path.parent.parent != destination:
            raise ValueError('Manifesto fora da pasta autorizada para cópia.')
        if not path.is_file():
            outcome['status'] = 'manifest_missing'
            continue
        try:
            doc = read_manifest(path)
            entries = verified_entries(path)
            if (doc.get('status') != 'concluido' or doc.get('errors') or
                doc.get('file_count_expected') != len(expected) or
                doc.get('bytes_expected') != sum(expected.values()) or
                len(doc['files']) != len(expected) or
                set(entries) != set(expected) or
                any(type(item.get('bytes')) is not int or
                    item['bytes'] != expected[name]
                    for name, item in entries.items())):
                raise ValueError('Manifesto não corresponde ao plano aprovado.')
            signature = {name: (item['bytes'], item['sha256'].lower())
                         for name, item in entries.items()}
            candidates.append((path, outcome, signature))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            outcome['status'] = 'manifest_invalid'

    # A readable complete inventory disagreeing with another copy means
    # uncertain provenance. Never choose one and silently ignore the other.
    if candidates and any(signature != candidates[0][2]
                          for _, _, signature in candidates[1:]):
        raise ValueError('Manifestos das cópias divergem; restauração bloqueada.')

    usable = None
    for path, outcome, _ in candidates:
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Verificação de cópias cancelada.')
        try:
            verification = verify_complete_manifest(path, cancelled=cancelled)
            if verification.get('backup_verified') is not True:
                raise OSError('Cópia sem verificação concluída.')
            outcome['status'] = 'copy_verified'
            if usable is None:
                usable = path
        except InterruptedError:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            outcome['status'] = 'integrity_failed'

    result = {
        'schema': 'pcro-fixture-smart-restore-v1',
        'status': 'no_usable_copy' if usable is None else 'ready_for_restore',
        'copies_checked': len(rows), 'copy_checks': report_rows,
        'files_requested': len(keys), 'files_restored': 0,
        'restore_verified': False, 'backup_verified': usable is not None,
        'physical_independence_verified': False, 'ready_for_format': False,
        'installation_authorized': False,
    }
    if usable is None:
        return result

    # Only one manifest is passed to restore_selected; never merge entries.
    chosen = next(outcome for path, outcome, _ in candidates if path == usable)
    chosen['status'] = 'selected_for_restore'
    result['chosen_copy_index'] = chosen['copy_index']
    try:
        folder, count = restore_selected(
            usable, keys, parent, cancelled=cancelled, strategy_inventory={})
        if count != len(keys):
            raise OSError('Recuperação parcial; quantidade incorreta.')
        # A distinct identity-bound read of every restored item is required
        # before this wrapper claims that the recovery is verified.
        matching = dict(candidates[0][2])
        for key in keys:
            destination = folder / safe_relative(key)
            ancestry = destination_ancestry_identity(folder, destination)
            size, digest = matching[key]
            verify_committed_backup_file(
                folder, destination, ancestry, size, digest, cancelled)
        result.update(status='restored_verified', restore_verified=True,
                      files_restored=count, restored_folder=str(folder),
                      chosen_manifest=str(usable))
    except InterruptedError:
        raise
    except (OSError, ValueError, TypeError):
        result['status'] = 'restore_failed'
        chosen['status'] = 'restore_failed'
    return result
