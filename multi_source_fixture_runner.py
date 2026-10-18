"""Experimental multi-source backup runner limited to an isolated test sandbox.

This module deliberately refuses operation without an explicit test_root.
Production multi-drive execution needs further physical device safety checks.
"""
from __future__ import annotations

from pathlib import Path

from selective_recovery import run_selected_backup, verify_complete_manifest
from multi_source_recheck import recheck_multi_source_preview


def run_multi_source_fixture_backup(plan, target_preview, *, test_root,
                                    volume_lookup, usage, cancelled=None):
    """Copy verified fixtures only after rechecking scope and all source metadata."""
    if test_root is None:
        raise ValueError('Executor experimental exige raiz de testes isolada.')
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz de testes inválida.')
    # Every source and destination must lie strictly inside the synthetic sandbox.
    originals = [Path(task.source).resolve(strict=True) for task in plan.files]
    requested = target_preview.get('destinations', []) if isinstance(target_preview, dict) else []
    folders = [Path(entry['path']).resolve(strict=True) for entry in requested
               if isinstance(entry, dict) and isinstance(entry.get('path'), str)]
    if not originals or not folders or len(folders) != len(requested):
        raise ValueError('Plano ou destinos de testes inválidos.')
    for path in originals + folders:
        if path == sandbox or sandbox not in path.parents:
            raise ValueError('Arquivo ou destino fora da raiz isolada.')
    if len(folders) != 1:
        raise ValueError('Executor experimental suporta exatamente um destino.')
    fresh = recheck_multi_source_preview(
        plan, target_preview, volume_lookup=volume_lookup, usage=usage)
    if fresh['destinations'][0]['path'] != str(folders[0]):
        raise ValueError('Destino divergente após revalidação.')
    result = run_selected_backup(plan, str(folders[0]), cancelled=cancelled,
                                 test_root=str(sandbox))
    verification = verify_complete_manifest(result['manifest'], cancelled=cancelled)
    if not verification['backup_verified']:
        raise OSError('Manifesto não foi verificado.')
    return {'schema': 'pcro-multi-source-fixture-result-v1',
            'manifest': result['manifest'],
            'files_verified': verification['files_verified'],
            'backup_verified': True,
            'physical_independence_verified': False,
            'ready_for_format': False,
            'installation_authorized': False}
