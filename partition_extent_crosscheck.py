"""Pure read-only comparison of Get-Partition and observed IOCTL extents.

Independent metadata can corroborate a reported logical mapping, or reveal
disagreement. This is NOT proof of device identity, independent media,
safe backup destination, or formatting authorization. No hardware I/O here.
"""
from __future__ import annotations


def _valid_number(number):
    return type(number) is int and 0 <= number < 65536


def _letter(value):
    if not isinstance(value, str):
        return None
    value = value.strip().upper().rstrip(':')
    return value if len(value) == 1 and 'A' <= value <= 'Z' else None


def crosscheck_partitions(report, letter, extent_numbers, extent_status):
    """Return a privacy-safe positive-evidence comparison for one drive.

    Get-Partition can be incomplete for legacy, virtual and dynamic volumes.
    A 'matched' result corroborates ONLY logical metadata, not a physical disk.
    Duplicate/invalid partition associations never become clean evidence.
    """
    letter = _letter(letter)
    if letter is None:
        raise ValueError('Unidade inválida para conferência de partições.')
    if (not isinstance(extent_numbers, list) or
            any(not _valid_number(x) for x in extent_numbers) or
            len(extent_numbers) != len(set(extent_numbers))):
        raise ValueError('Lista de extents inválida.')
    partitions = report.get('partitions') if isinstance(report, dict) else None
    if not isinstance(partitions, list):
        return {'status': 'unavailable', 'partition_logical_disks': [],
                'extent_logical_disks': sorted(extent_numbers)}
    found = []
    malformed = False
    for row in partitions:
        if not isinstance(row, dict):
            continue
        if _letter(row.get('DriveLetter')) != letter:
            continue
        number = row.get('DiskNumber')
        if not _valid_number(number):
            malformed = True
        else:
            found.append(number)
    numbers = sorted(set(found))
    extents = sorted(extent_numbers)
    if malformed:
        status = 'inconclusive'
    elif not numbers and not extents:
        status = 'unavailable'
    elif not numbers:
        status = 'extent_only'
    elif not extents:
        status = 'partition_only'
    elif set(numbers) != set(extents):
        status = 'conflict'
    elif extent_status != 'observed_logical_only':
        # Extents on virtual/missing disks can correlate with Get-Partition,
        # but must never be shown as a normal hardware-confirmed mapping.
        status = 'limited_match'
    else:
        status = 'logical_match'
    return {
        'status': status,
        'partition_logical_disks': numbers,
        'extent_logical_disks': extents,
    }
