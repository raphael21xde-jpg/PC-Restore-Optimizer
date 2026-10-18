"""Read-only safety preview for backup targets of multiple selected source roots.

No copying, filesystem creation, deletions, or installation authorization.
Same-volume checks are conservative: actual physical independence remains unproven.
"""
from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
import shutil

from multi_backup_destinations import _resolved_folder, _under
from volume_paths import volume_of
from backup_target_preflight import assess_backup_target


def diagnostic_fingerprint(diagnostic):
    """Fingerprint observed topology; never interpret it as physical proof."""
    if not isinstance(diagnostic, dict):
        raise ValueError('Diagnóstico de discos inválido.')
    try:
        payload = json.dumps(
            {key: diagnostic.get(key) for key in
             ('disks', 'volumes', 'extent_mapping', 'spaces_membership')},
            ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Diagnóstico de discos inválido.') from exc
    return hashlib.sha256(payload).hexdigest()


def preview_multi_source_targets(plan, destinations, *, usage=shutil.disk_usage,
                                 volume_lookup=volume_of, disk_diagnostic=None):
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
    fingerprint = None
    if disk_diagnostic is not None:
        fingerprint = diagnostic_fingerprint(disk_diagnostic)
        source_letters = [v[:-1] for v in sorted(source_volumes)
                          if len(v) == 2 and v[1] == ':' and v[0].isalpha()]
        if len(source_letters) != len(source_volumes):
            raise ValueError('Origens sem letra de unidade verificável.')
        for target in targets:
            letter = target['volume']
            if len(letter) != 2 or letter[1] != ':' or not letter[0].isalpha():
                raise ValueError('Destino sem letra de unidade verificável.')
            assessment = assess_backup_target(
                disk_diagnostic.get('disks', []),
                disk_diagnostic.get('volumes', []),
                disk_diagnostic.get('extent_mapping', {}),
                disk_diagnostic.get('spaces_membership', {}),
                target_letter=letter, source_letters=source_letters,
                expected_backup_bytes=int(plan.total))
            target['logical_disk_numbers'] = assessment['destination_logical_disks']
            target['disk_preflight_issues'] = assessment['issues']
            target['disk_preflight_blockers'] = assessment['blockers']
            if assessment['status'] == 'blocked':
                raise ValueError('Conflito entre discos detectado: ' +
                                 '; '.join(assessment['blockers']))
            # Missing/ambiguous associations remain unverified. A preview
            # is never authorization to run the real backup executor.
            target['preflight_status'] = 'requires_review'
    return {'schema': 'pcro-multi-source-target-preview-v1',
            'source_volumes': sorted(source_volumes),
            'destinations': targets,
            'bytes_per_copy': plan.total,
            'disk_diagnostic_sha256': fingerprint,
            'physical_independence_verified': False,
            'backup_verified': False,
            'ready_for_format': False,
            'installation_authorized': False}
