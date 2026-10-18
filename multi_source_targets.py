"""Read-only safety preview for backup targets of multiple selected source roots.

No copying, filesystem creation, deletions, or installation authorization.
Same-volume checks are conservative: actual physical independence remains unproven.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from multi_backup_destinations import _resolved_folder, _under
from volume_paths import volume_of
from backup_core import human_size


def preview_multi_source_targets(plan, destinations, *, usage=shutil.disk_usage,
                                 volume_lookup=volume_of):
    """Require existing, disjoint destinations on volumes outside every source.

    This preview cannot certify separate physical devices and is not an
    authorization to run the legacy C:-specific backup executor.
    """
    files = getattr(plan, 'files', None)
    if not files or getattr(plan, 'warnings', None):
        raise ValueError('Plano de origem ausente ou incompleto.')
    if not isinstance(destinations, (list, tuple)) or not 1 <= len(destinations) <= 8:
        raise ValueError('Selecione entre um e oito destinos.')
    source_volumes = set()
    for task in files:
        origin = Path(task.source)
        if not origin.is_absolute() or not origin.is_file():
            raise ValueError('Arquivo de origem inválido ou ausente.')
        vol = volume_lookup(str(origin))
        if not vol or vol == 'SEM UNIDADE':
            raise ValueError('Unidade de origem desconhecida.')
        source_volumes.add(vol.upper())
    targets = []
    for raw in destinations:
        if not isinstance(raw, str):
            raise ValueError('Destino inválido.')
        folder = _resolved_folder(raw)
        volume = volume_lookup(str(folder))
        if not volume or volume == 'SEM UNIDADE':
            raise ValueError('Unidade de destino desconhecida.')
        if volume.upper() in source_volumes:
            raise ValueError('Destino na mesma unidade de uma das origens.')
        for task in files:
            if _under(folder, task.source) or _under(task.source, folder):
                raise ValueError('Destino sobrepõe arquivo de origem.')
        for previous in targets:
            if _under(folder, previous['path']) or _under(previous['path'], folder):
                raise ValueError('Destinos duplicados ou aninhados.')
        free = usage(folder).free
        if type(free) is not int or free < 0:
            raise ValueError('Capacidade informada inválida.')
        reserve = max(10 * 1024**3, int(free * .10))
        if plan.total > free - reserve:
            raise ValueError('Espaço insuficiente, incluindo reserva de segurança.')
        targets.append({'path': str(folder), 'volume': volume.upper(),
                        'free_bytes': free, 'reserve_bytes': reserve,
                        'preflight_status': 'requires_review'})
    return {'schema': 'pcro-multi-source-target-preview-v1',
            'source_volumes': sorted(source_volumes),
            'destinations': targets,
            'bytes_per_copy': plan.total,
            'physical_independence_verified': False,
            'backup_verified': False,
            'ready_for_format': False,
            'installation_authorized': False}
