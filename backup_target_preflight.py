"""Fail-closed, metadata-only backup target preflight.

A volume letter is not a physical disk. Different disk *numbers* are not
proof of independent hardware, especially with Storage Spaces or dynamic disks.
This module NEVER authorizes writing, formatting, deleting, or reinstalling.
No file copies or filesystem modifications are performed.
"""
from __future__ import annotations

import re

LETTER = re.compile(r'^[A-Za-z]$')
MAX_ESTIMATED_BYTES = 1 << 63


def _letter(value):
    if not isinstance(value, str):
        return None
    value = value.strip().rstrip(':').upper()
    return value if LETTER.fullmatch(value) else None


def _number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def _bytes(value):
    return value if type(value) is int and 0 <= value <= MAX_ESTIMATED_BYTES else None


def _extent_by_letter(extents):
    result = {}
    for entry in extents.get('volumes', []) if isinstance(extents, dict) else []:
        if not isinstance(entry, dict):
            continue
        numbers = entry.get('disk_numbers', [])
        numbers = (numbers if isinstance(numbers, list) else [])
        indices = sorted({n for x in numbers if (n := _number(x)) is not None})
        for raw in entry.get('letters', []):
            letter = _letter(raw)
            if letter is not None:
                result.setdefault(letter, []).append({
                    'disk_numbers': indices, 'status': entry.get('status', 'unknown')
                })
    return result


def _volume_by_letter(volumes):
    found = {}
    for row in volumes if isinstance(volumes, list) else []:
        if isinstance(row, dict) and (letter := _letter(row.get('DriveLetter'))):
            found.setdefault(letter, []).append(row)
    return found


def _spaces_disks(disks):
    return sorted({n for d in disks if isinstance(d, dict)
                   if (n := _number(d.get('Number'))) is not None and
                   str(d.get('BusType', '')).strip().casefold() in ('spaces', 'storage spaces')})


def assess_backup_target(disks, volumes, extent_mapping, spaces_membership,
                         *, target_letter, source_letters=None,
                         expected_backup_bytes=None):
    """Check candidate metadata without assuming source selection or backup size.

    A logical-disk collision is a definite reason to reject this candidate.
    Non-collision never proves physical independence. The destination may be
    nested in a source tree even if letters differ; external data is required
    before any real copy.
    """
    target = _letter(target_letter)
    if target is None:
        raise ValueError('Letra de destino inválida.')
    sources_provided = source_letters is not None
    raw_sources = source_letters if source_letters is not None else []
    if not isinstance(raw_sources, (list, tuple)) or len(raw_sources) > 128:
        raise ValueError('Lista de origens inválida.')
    sources = []
    for item in raw_sources:
        parsed = _letter(item)
        if parsed is None:
            raise ValueError('Origem inválida.')
        if parsed not in sources:
            sources.append(parsed)

    if expected_backup_bytes is not None and _bytes(expected_backup_bytes) is None:
        raise ValueError('Tamanho planejado inválido.')
    extents = _extent_by_letter(extent_mapping)
    vmap = _volume_by_letter(volumes)
    spaces = _spaces_disks(disks if isinstance(disks, list) else [])
    issues = []
    blockers = []

    entries = extents.get(target, [])
    if len(entries) == 1 and len(entries[0]['disk_numbers']) == 1 and entries[0]['status'] != 'unknown':
        destination_numbers = entries[0]['disk_numbers']
    else:
        destination_numbers = []
        issues.append('Destino: associação GUID/extents para um único disco lógico não confirmada.')
    volume_rows = vmap.get(target, [])
    capacity_free = _bytes(volume_rows[0].get('SizeRemaining')) if len(volume_rows) == 1 else None
    if capacity_free is None:
        issues.append('Destino: capacidade disponível não confirmada.')
    if expected_backup_bytes is None:
        issues.append('Tamanho do backup ainda não calculado; capacidade não aprovada.')
        capacity_status = 'not_evaluated'
    elif capacity_free is None:
        capacity_status = 'unknown'
    elif expected_backup_bytes > capacity_free:
        capacity_status = 'insufficient'
        blockers.append('Espaço disponível menor que o tamanho estimado do backup.')
    else:
        capacity_status = 'reported_sufficient'
        issues.append('Espaço reportado é apenas uma estimativa pontual, sem reserva de segurança.')

    if not sources_provided or not sources:
        issues.append('Origens a preservar ainda não foram selecionadas; não inferir origens.')
        source_status = 'not_selected'
    else:
        source_status = 'reported'
        for source in sources:
            if source == target:
                blockers.append('Destino coincide com a unidade de origem ' + source + ':.')
                continue
            rows = extents.get(source, [])
            if len(rows) != 1 or not rows[0]['disk_numbers'] or rows[0]['status'] == 'unknown':
                issues.append('Origem '+source+': não possui associação confiável a discos lógicos.')
                source_status = 'partial'
                continue
            if destination_numbers and set(rows[0]['disk_numbers']) & set(destination_numbers):
                blockers.append('Destino '+target+': e origem '+source+
                                ': compartilham pelo menos um disco lógico segundo extents.')
    related_spaces = sorted(set(destination_numbers) & set(spaces))
    spaces_detail = []
    membership = spaces_membership if isinstance(spaces_membership, dict) else {}
    for number in related_spaces:
        matches = [row for row in membership.get('virtual_disks', [])
                   if isinstance(row, dict) and number in row.get('logical_disk_numbers', [])]
        if len(matches) != 1:
            issues.append('Storage Spaces no Disco '+str(number)+
                          ': associação física incompleta ou ambígua.')
        else:
            item = matches[0]
            members = item.get('members', [])
            count = item.get('member_count')
            spaces_detail.append({
                'logical_disk_number': number,
                'member_count_reported': count if type(count) is int and count >= 0 else None,
                'virtual_name': str(item.get('virtual_name') or '')[:100],
                'resiliency_reported': str(item.get('resiliency_reported') or '')[:60],
                'membership_status': str(item.get('status') or 'unknown')[:48],
            })
            if item.get('status') != 'members_reported' or not isinstance(members, list) or not members:
                issues.append('Disco '+str(number)+': membros físicos do pool não confirmados.')
            if str(item.get('resiliency_reported') or '').casefold() in ('simple', 'simples'):
                issues.append('Disco '+str(number)+': pool Simple sem redundância informada.')
    if related_spaces:
        issues.append('Número de disco Storage Spaces é virtual; DeviceId de membro físico não '
                      'equivale ao índice Win32_DiskDrive nem prova independência.')
    if source_status == 'reported' and not blockers and destination_numbers:
        issues.append('Discos lógicos sem conflito conhecido NÃO comprovam hardware físico independente.')
    if not sources or any(s not in vmap for s in sources):
        issues.append('Seleção de fontes e/ou volumes exige revisão antes da cópia.')
    issues.append('Integridade SHA-256, restauração de amostra e cópia independente não verificadas.')

    return {
        'schema': 'pcro-backup-target-preflight-v1',
        'target_letter': target,
        'source_letters': sources,
        'source_status': source_status,
        'destination_logical_disks': destination_numbers,
        'free_bytes_reported': capacity_free,
        'expected_backup_bytes': expected_backup_bytes,
        'capacity_status': capacity_status,
        'storage_spaces_membership': spaces_detail,
        'status': 'blocked' if blockers else 'requires_review',
        'blockers': blockers,
        'issues': issues,
        'physical_independence_verified': False,
        'backup_destination_verified': False,
        'backup_integrity_verified': False,
        'approved_for_copy': False,
        'approved_for_format': False,
        'notice': ('Relatório de pré-checagem, sem escrita. Nenhum disco, volume, '
                   'cópia ou instalação é autorizado automaticamente.')
    }


def list_backup_target_candidates(disks, volumes, extent_mapping, spaces_membership):
    """Present available drive-letter candidates, NOT automatic destinations."""
    unique_letters = sorted({_letter(v.get('DriveLetter')) for v in volumes
                             if isinstance(v, dict) and _letter(v.get('DriveLetter'))})
    return [assess_backup_target(disks, volumes, extent_mapping, spaces_membership,
                                 target_letter=letter)
            for letter in unique_letters]
