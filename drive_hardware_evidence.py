"""Privacy-minimal interpretation of existing Windows diagnostic evidence.

Reads only an in-memory snapshot collected elsewhere. Never identifies a
physical device conclusively, reads disks, modifies files, or approves copying.
Do not expose raw WMI models, device IDs, serials, pool names or paths.
"""
from __future__ import annotations

MAX_LOGICAL = 65536
MAX_MEMBERS = 256


def _disk(n):
    return n if type(n) is int and 0 <= n < MAX_LOGICAL else None


def _numbers(values):
    if not isinstance(values, (list, tuple)) or len(values) > 128:
        return ()
    if any(_disk(n) is None for n in values):
        return ()
    return tuple(sorted(set(values)))


def _safe_resiliency(value):
    # Only map a small whitelist; other strings may contain private metadata.
    norm = str(value or '').strip().casefold()
    if norm in ('simple', 'simples'):
        return 'simple'
    if norm in ('mirror', 'espelho'):
        return 'mirror'
    if norm in ('parity', 'paridade'):
        return 'parity'
    return 'unknown'


def summarize_hardware_evidence(snapshot, logical_numbers, extent_status):
    """Summarize auxiliary evidence WITHOUT asserting physical independence.

    The WMI DiskDrive index and Get-PhysicalDisk DeviceId are not interchangeable
    physical identifiers. A member count is an observation, not certified
    redundancy, physical uniqueness or backup suitability.
    """
    if not isinstance(snapshot, dict):
        snapshot = {}
    numbers = _numbers(logical_numbers)
    summary = {
        'spaces_membership_status': 'not_applicable',
        'spaces_members_count': None,
        'spaces_resiliency': 'unknown',
        'wmi_diskdrive_status': 'not_applicable',
        'wmi_partition_status': 'not_applicable',
        'wmi_partition_count': None,
    }

    if extent_status == 'virtual_spaces':
        summary['spaces_membership_status'] = 'not_confirmed'
        spaces = snapshot.get('spaces_membership')
        entries = spaces.get('virtual_disks') if isinstance(spaces, dict) else None
        if isinstance(entries, list) and len(numbers) == 1:
            matches = [row for row in entries if isinstance(row, dict)
                       and numbers[0] in _numbers(row.get('logical_disk_numbers'))]
            if len(matches) > 1:
                summary['spaces_membership_status'] = 'ambiguous'
            elif len(matches) == 1:
                match = matches[0]
                members = match.get('member_count')
                summary['spaces_resiliency'] = _safe_resiliency(
                    match.get('resiliency_reported'))
                if (type(members) is int and 0 <= members <= MAX_MEMBERS):
                    summary['spaces_members_count'] = members
                if (match.get('status') == 'members_reported'
                        and summary['spaces_members_count'] is not None
                        and summary['spaces_members_count'] > 0):
                    summary['spaces_membership_status'] = 'members_reported_unverified'
                else:
                    summary['spaces_membership_status'] = 'incomplete'

    if extent_status == 'disk_not_listed':
        summary['wmi_diskdrive_status'] = 'not_confirmed'
        summary['wmi_partition_status'] = 'not_confirmed'
        if len(numbers) == 1:
            physical = snapshot.get('physical_evidence')
            differences = (physical.get('disagreements')
                           if isinstance(physical, dict) else None)
            if isinstance(differences, list):
                matches = [row for row in differences if isinstance(row, dict)
                           and _disk(row.get('disk_number')) == numbers[0]]
                if len(matches) > 1:
                    summary['wmi_diskdrive_status'] = 'ambiguous'
                elif len(matches) == 1:
                    flag = matches[0].get('present_in_wmi')
                    if flag is True:
                        summary['wmi_diskdrive_status'] = 'reported'
                    elif flag is False:
                        summary['wmi_diskdrive_status'] = 'not_reported'
            partition = snapshot.get('partition_evidence')
            interest = (partition.get('disks_of_interest')
                        if isinstance(partition, dict) else None)
            if isinstance(interest, list):
                matches = [row for row in interest if isinstance(row, dict)
                           and _disk(row.get('disk_index')) == numbers[0]]
                if len(matches) > 1:
                    summary['wmi_partition_status'] = 'ambiguous'
                elif len(matches) == 1:
                    row = matches[0]
                    records = row.get('partitions')
                    if (row.get('status') == 'wmi_partitions_reported'
                            and isinstance(records, list) and len(records) <= 256):
                        summary['wmi_partition_status'] = 'reported'
                        summary['wmi_partition_count'] = len(records)
                    elif row.get('status') == 'not_reported':
                        summary['wmi_partition_status'] = 'not_reported'

    return summary
