"""Best-effort physical extent metadata for Windows volumes (read-only).

The low-level IOCTL runs in a separate process with a strict timeout.
It is not a backup-destination validator and does not establish the physical
members of Storage Spaces. If inaccessible or ambiguous, status stays unknown.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from volume_inventory import collect_volume_inventory, normalize_volume_id

LETTER_ROOT = re.compile(r'^[A-Za-z]:\\$')
MAX_PROBED_VOLUMES = 128
PROBE_TIMEOUT_SECONDS = 25


def _disk_number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def describe_extents(snapshot, rows, disks, *, error=None):
    """Merge observed GUID->extent->Get-Disk evidence; never claim safe mapping."""
    issues = []
    if error:
        issues.append('Consulta de extensões indisponível: ' + str(error)[:180])
    if snapshot.get('status') != 'ok':
        issues.append('Inventário GUID parcial ou indisponível; associação incompleta.')
    if snapshot.get('issues'):
        issues += ['Inventário GUID: ' + str(x)[:180] for x in snapshot['issues'][:15]]

    disks_by_number = {number: d for d in disks if isinstance(d, dict)
                       if (number := _disk_number(d.get('Number'))) is not None}
    rows_by_id = {}
    for row in rows:
        try:
            identifier = normalize_volume_id(row.get('device_id'))
        except (ValueError, TypeError, AttributeError):
            issues.append('Resposta de extensão com identificador inválido.')
            continue
        if identifier in rows_by_id:
            issues.append('Resposta duplicada para um identificador GUID.')
            continue
        rows_by_id[identifier] = row

    mappings = []
    for volume in snapshot.get('volumes', []):
        guid = volume['volume_id']
        letters = sorted({p[0].upper() for p in volume.get('mount_points', [])
                          if LETTER_ROOT.fullmatch(p)})
        row = rows_by_id.get(guid)
        numbers, reason = [], ''
        if not row or row.get('status') != 'mapped':
            status = 'unknown'
            reason = (str(row.get('error', 'sem resposta') if row else 'sem resposta')[:180])
        else:
            extents = row.get('extents', [])
            if not isinstance(extents, list) or not extents:
                status = 'unknown'
                reason = 'A API não retornou extensões válidas.'
            else:
                invalid = any(not isinstance(e, dict) or
                              _disk_number(e.get('disk_number')) is None
                              for e in extents)
                numbers = sorted({_disk_number(e['disk_number'])
                                  for e in extents if isinstance(e, dict)
                                  and _disk_number(e.get('disk_number')) is not None})
                if invalid or not numbers:
                    status = 'unknown'
                    numbers = []
                    reason = 'Resposta incompleta ou inválida.'
                elif len(numbers) > 1:
                    status = 'multi_disk'
                    reason = 'Volume ocupa mais de um disco lógico; verificar composição.'
                elif numbers[0] not in disks_by_number:
                    status = 'disk_not_listed'
                    reason = 'Número de disco reportado pela API não aparece em Get-Disk.'
                elif str(disks_by_number[numbers[0]].get('BusType', '')).casefold() in ('spaces', 'storage spaces'):
                    status = 'virtual_spaces'
                    reason = 'Disco lógico de Storage Spaces; membros físicos não confirmados.'
                else:
                    status = 'logical_disk_reported'
                    reason = 'Extensão observada em disco lógico; não confirma independência.'
        mappings.append({
            'volume_id': guid, 'letters': letters,
            'disk_numbers': numbers, 'status': status, 'reason': reason
        })
        if status != 'logical_disk_reported':
            label = ','.join(letters) or 'volume sem letra'
            issues.append(f'{label}: extensão {status}; {reason}')

    if not mappings:
        issues.append('Nenhuma correspondência de volume foi obtida.')
    return {
        'schema': 'pcro-extent-mapping-v1',
        'status': 'requires_review' if issues else 'observed_metadata',
        'volumes': mappings, 'issues': issues,
        'approved_for_format': False,
        'backup_destination_verified': False,
        'note': 'Consultas somente leitura: números de disco podem representar volumes virtuais.',
    }


def collect_extent_mapping(disks, *, snapshot=None, runner=subprocess.run, timeout=PROBE_TIMEOUT_SECONDS):
    """Bounded subprocess query; injectable for tests, fails closed on any error."""
    if snapshot is None:
        snapshot = collect_volume_inventory()
    volume_ids = [v['volume_id'] for v in snapshot.get('volumes', [])]
    if os.name != 'nt':
        return describe_extents(snapshot, [], disks, error='Consulta de extents disponível somente no Windows.')
    if not volume_ids or len(volume_ids) > MAX_PROBED_VOLUMES:
        return describe_extents(snapshot, [], disks, error='Quantidade de volumes fora do limite seguro.')
    try:
        checked = [normalize_volume_id(guid) for guid in volume_ids]
        helper = Path(__file__).resolve().with_name('volume_extents.py')
        run = runner(
            [sys.executable, str(helper)],
            input=json.dumps([{'device_id': x} for x in checked]),
            text=True, capture_output=True, encoding='utf-8', errors='replace',
            timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            check=False,
        )
        if run.returncode:
            raise RuntimeError('Consulta retornou erro: ' + str(run.stderr)[-180:])
        raw = json.loads(run.stdout)
        if not isinstance(raw, list):
            raise ValueError('Formato inesperado de resposta das extensões.')
        return describe_extents(snapshot, raw, disks)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return describe_extents(snapshot, [], disks, error=str(exc))
