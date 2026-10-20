"""Read-only fresh Windows disk inventory gate for multi-source backup previews.

The default collector is diagnostics.disk_inventory (PowerShell read-only).
It is never invoked by the experimental fixture runner or production UI yet.
"""
from __future__ import annotations

from diagnostics import disk_inventory
from multi_source_recheck import recheck_multi_source_preview


def recheck_with_fresh_inventory(plan, target_preview, *, volume_lookup,
                                 usage, collector=disk_inventory):
    """Collect a NEW snapshot, reject missing/changed topology, never authorize copy."""
    if (not isinstance(target_preview, dict)
            or not isinstance(target_preview.get('disk_diagnostic_sha256'), str)
            or len(target_preview['disk_diagnostic_sha256']) != 64):
        raise ValueError('Prévia sem diagnóstico de discos verificável.')
    try:
        report = collector()
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        raise ValueError('Não foi possível atualizar o inventário de discos.') from exc
    if not isinstance(report, dict) or not all(
            key in report for key in
            ('disks', 'volumes', 'extent_mapping', 'spaces_membership')):
        raise ValueError('Inventário de discos atualizado incompleto.')
    # No cached report and no fallback to the old preview on collection failure.
    fresh = recheck_multi_source_preview(
        plan, target_preview, volume_lookup=volume_lookup,
        usage=usage, disk_diagnostic=report)
    fresh['fresh_inventory_rechecked'] = True
    fresh['backup_verified'] = False
    fresh['ready_for_format'] = False
    fresh['installation_authorized'] = False
    return fresh
