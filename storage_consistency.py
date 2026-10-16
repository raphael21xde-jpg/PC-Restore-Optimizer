"""Read-only consistency audit for Windows storage metadata.

Get-Disk, Get-Partition and Get-Volume can report different subsets, notably
legacy dynamic disks and Storage Spaces. Missing relationships must remain
UNKNOWN, never treated as evidence that a partition does not exist.
This module does not enumerate all physical extents and never authorizes
backup destinations, deletion, or formatting.
"""
from __future__ import annotations


def _disk_number(value):
    return value if type(value) is int and value >= 0 else None


def _drive_letter(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip().rstrip(':').upper()
    if len(normalized) != 1 or not ('A' <= normalized <= 'Z'):
        return None
    return normalized


def assess_storage_mapping(disks, partitions, volumes, *, partition_error=None):
    """Cross-check positive evidence; report unknown relationships as gaps."""
    disk_numbers = {number for row in disks if isinstance(row, dict)
                    if (number := _disk_number(row.get('Number'))) is not None}
    by_letter = {}
    partition_disk_numbers = set()
    for row in partitions:
        if not isinstance(row, dict):
            continue
        number = _disk_number(row.get('DiskNumber'))
        if number is not None:
            partition_disk_numbers.add(number)
        letter = _drive_letter(row.get('DriveLetter'))
        if letter:
            by_letter.setdefault(letter, set())
            if number is not None:
                by_letter[letter].add(number)

    volume_letters = sorted({letter for row in volumes if isinstance(row, dict)
                             if (letter := _drive_letter(row.get('DriveLetter'))) is not None})
    mapping = []
    gaps = []
    missing_in_disk_list = sorted(partition_disk_numbers - disk_numbers)
    if missing_in_disk_list:
        gaps.append(
            'ATENÇÃO: Get-Partition referencia disco(s) '
            + ', '.join(str(n) for n in missing_in_disk_list)
            + ' ausentes na lista Get-Disk. Conferir discos dinâmicos e volumes legados.')

    for letter in volume_letters:
        references = sorted(by_letter.get(letter, set()))
        if not references:
            mapping.append({'letter': letter, 'disk_numbers': [], 'status': 'unverified'})
            gaps.append(
                f'ATENÇÃO: volume {letter}: apareceu em Get-Volume, mas não foi possível '
                'vinculá-lo a um disco usando Get-Partition. Associação não verificada.')
        elif len(references) != 1:
            mapping.append({'letter': letter, 'disk_numbers': references, 'status': 'ambiguous'})
            gaps.append(
                f'ATENÇÃO: volume {letter}: está associado a mais de um disco reportado. '
                'É necessário verificar extents e discos físicos.')
        elif references[0] not in disk_numbers:
            mapping.append({'letter': letter, 'disk_numbers': references, 'status': 'disk_not_listed'})
            gaps.append(
                f'ATENÇÃO: volume {letter}: referenciado no disco {references[0]}, '
                'que não aparece na lista Get-Disk. Associação física não confirmada.')
        else:
            mapping.append({'letter': letter, 'disk_numbers': references, 'status': 'reported'})

    spaces = sorted(n for row in disks if isinstance(row, dict)
                    if (n := _disk_number(row.get('Number'))) is not None
                    and str(row.get('BusType', '')).strip().lower()
                    in ('spaces', 'storage spaces'))
    if spaces:
        gaps.append(
            'ATENÇÃO: Espaços de Armazenamento presente(s), disco(s) lógicos '
            + ', '.join(str(n) for n in spaces)
            + '. Get-Disk NÃO confirma quais discos físicos sustentam esses volumes '
            'nem independência para backup.')

    if partition_error:
        gaps.append('ATENÇÃO: Get-Partition falhou: ' + str(partition_error)[:180])
    if not disk_numbers:
        gaps.append('ATENÇÃO: nenhum disco enumerado em Get-Disk.')
    if not volume_letters:
        gaps.append('ATENÇÃO: nenhuma letra de volume encontrada em Get-Volume.')

    return {
        'schema': 'pcro-storage-consistency-v1',
        'status': 'requires_review' if gaps else 'metadata_consistent',
        'reported_disks': sorted(disk_numbers),
        'partition_disks_not_listed': missing_in_disk_list,
        'letter_mapping': mapping,
        'issues': gaps,
        'approved_for_format': False,
        'backup_destination_verified': False,
        'note': ('Sem lacunas detectadas NÃO equivale a inventário completo. '
                 'Get-Disk, Get-Partition e Get-Volume podem omitir discos dinâmicos, '
                 'partições ocultas e vínculos de armazenamento.'),
    }
