"""Read-only, privacy-minimal review of fresh Windows disk inventory.

Not a backup executor and NEVER authorization for copying, formatting or
Windows installation. Logical disk numbers and volume letters alone do NOT
prove two destinations are separate physical devices. Raw serial numbers,
device paths and other inventory details are deliberately not returned.
"""
from __future__ import annotations

import re

from backup_target_preflight import assess_backup_target
from diagnostics import disk_inventory

DRIVE = re.compile(r'[A-Za-z]:?\Z')
OBSERVED = frozenset({'logical_disk_reported', 'reported'})
MAX_SOURCES = 32
MAX_TARGETS = 8


def _normalize_letters(values, *, maximum, field):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= maximum:
        raise ValueError(f'{field}: quantidade de unidades inválida.')
    letters = []
    for item in values:
        if not isinstance(item, str) or not DRIVE.fullmatch(item.strip()):
            raise ValueError(f'{field}: letra de unidade inválida.')
        letter = item.strip()[0].upper()
        if letter in letters:
            raise ValueError(f'{field}: letra repetida.')
        letters.append(letter)
    return letters


def _drive_extents(report, letter):
    """Accept only one unambiguous extent record for this drive letter."""
    mapping = report.get('extent_mapping')
    raw = mapping.get('volumes') if isinstance(mapping, dict) else None
    if not isinstance(raw, list):
        return [], False
    matching = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        letters = row.get('letters')
        if not isinstance(letters, (list, tuple)):
            continue
        names = [entry.strip().rstrip(':').upper()
                 for entry in letters if isinstance(entry, str)]
        if letter in names:
            matching.append(row)
    if len(matching) != 1:
        return [], False
    record = matching[0]
    numbers = record.get('disk_numbers')
    if (record.get('status') not in OBSERVED or
            not isinstance(numbers, (list, tuple)) or not numbers or
            any(type(n) is not int or n < 0 or n >= 65536 for n in numbers) or
            len(numbers) != len(set(numbers))):
        return [], False
    return sorted(numbers), True


def _boot_disk_numbers(report):
    """Observed boot/EFI risk is a veto; absence is not evidence of safety."""
    found = set()
    for field in ('disks', 'partitions'):
        rows = report.get(field, [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            number = item.get('Number') if field == 'disks' else item.get('DiskNumber')
            if type(number) is not int or number < 0 or number >= 65536:
                continue
            sensitive = item.get('IsBoot') is True or item.get('IsSystem') is True
            if field == 'partitions':
                kind = str(item.get('Type') or '').strip().casefold()
                sensitive |= kind in ('system', 'efi system partition')
            if sensitive:
                found.add(number)
    return found


def inspect_fresh_drive_safety(source_letters, target_letters, *,
                               collector=disk_inventory,
                               expected_backup_bytes=None):
    """Use a NEW inventory and report blockers without leaking raw hardware IDs.

    Inputs are selected logical drive letters, not fixed C/D/F/G assumptions.
    A successful inspection never certifies device independence nor enables a
    real backup. Collector injection exists solely for deterministic fixtures.
    """
    sources = _normalize_letters(source_letters, maximum=MAX_SOURCES,
                                 field='Origens')
    targets = _normalize_letters(target_letters, maximum=MAX_TARGETS,
                                 field='Destinos')
    if (expected_backup_bytes is not None and
            (type(expected_backup_bytes) is not int or
             expected_backup_bytes < 0 or expected_backup_bytes > (1 << 63))):
        raise ValueError('Tamanho de backup inválido.')

    # Only one call, never a cached snapshot. Missing/failed evidence blocks.
    try:
        report = collector()
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        raise ValueError('Não foi possível coletar o inventário atualizado.') from exc
    required = ('disks', 'volumes', 'extent_mapping', 'spaces_membership')
    if (not isinstance(report, dict) or
            any(key not in report for key in required) or
            not isinstance(report['disks'], list) or
            not isinstance(report['volumes'], list) or
            not isinstance(report['extent_mapping'], dict) or
            not isinstance(report['spaces_membership'], dict)):
        raise ValueError('Inventário atualizado incompleto.')

    source_info = {}
    for letter in sources:
        disks, observed = _drive_extents(report, letter)
        source_info[letter] = (disks, observed)
    boot_disks = _boot_disk_numbers(report)
    any_incomplete = not all(ok for _, ok in source_info.values())
    outcomes = []

    for letter in targets:
        disks, observed = _drive_extents(report, letter)
        any_incomplete |= not observed
        assessment = assess_backup_target(
            report['disks'], report['volumes'],
            report['extent_mapping'], report['spaces_membership'],
            target_letter=letter, source_letters=sources,
            expected_backup_bytes=expected_backup_bytes)
        blockers = list(assessment['blockers'])
        if letter in sources:
            blockers.append('Destino coincide com uma unidade selecionada como origem.')
        for source, (origin_disks, origin_ok) in source_info.items():
            if observed and origin_ok and set(disks) & set(origin_disks):
                blockers.append(
                    f'Destino {letter}: e origem {source}: compartilham disco lógico.')
        if observed and set(disks) & boot_disks:
            blockers.append(
                'Destino contém disco lógico associado a inicialização, sistema ou EFI.')
        if not observed:
            blockers.append('Mapeamento de extents do destino desconhecido ou ambíguo.')
        if any(not ok for _, ok in source_info.values()):
            blockers.append('Mapeamento de extents de uma ou mais origens incompleto.')
        if assessment['capacity_status'] in ('insufficient', 'unknown'):
            blockers.append('Espaço insuficiente ou não confirmável.')
        # The underlying assessment may be review-only even with disjoint
        # extents. Never interpret that as approval.
        outcomes.append({
            'letter': letter + ':',
            'logical_disk_numbers': disks if observed else [],
            'extent_status': 'observed_logical_only' if observed else 'incomplete',
            'capacity_status': assessment['capacity_status'],
            'status': 'blocked' if blockers else 'requires_review',
            'blockers': list(dict.fromkeys(blockers)),
            'issues': [
                'Discos lógicos distintos não comprovam mídias fisicamente independentes.',
                'Diagnóstico pontual; revise também alterações de hardware e inicialização.',
            ],
        })

    return {
        'schema': 'pcro-readonly-drive-safety-v1',
        'inventory_status': 'fresh_collected',
        'status': ('blocked' if any(x['status'] == 'blocked' for x in outcomes)
                   else 'incomplete' if any_incomplete else 'requires_review'),
        'source_volumes': [
            {'letter': letter + ':',
             'logical_disk_numbers': disks if observed else [],
             'extent_status': 'observed_logical_only' if observed else 'incomplete'}
            for letter, (disks, observed) in source_info.items()
        ],
        'destinations': outcomes,
        'boot_related_logical_disks': sorted(boot_disks),
        'raw_identifiers_included': False,
        'physical_independence_verified': False,
        'backup_verified': False,
        'copy_authorized': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'note': ('Somente leitura. Números lógicos, USB, discos virtuais e '
                 'Storage Spaces exigem verificação física independente; '
                 'nenhuma ação sobre discos foi autorizada.'),
    }
