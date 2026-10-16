"""Read-only secondary partition inventory from Win32_DiskPartition.

WMI partition metadata may include hidden or legacy disk structures omitted
by Get-Partition, but cannot prove the currently active EFI or physical health.
Do not change disk state or infer that 'BootPartition' means the active EFI.
"""
from __future__ import annotations


def _number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def summarize_wmi_partitions(rows, *, disk_numbers_of_interest=(), error=None):
    issues = []
    if error:
        issues.append('Consulta Win32_DiskPartition indisponível; não foi possível comparar partições.')
    targets = sorted({n for x in disk_numbers_of_interest
                      if (n := _number(x)) is not None})
    by_disk = {}
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        disk = _number(item.get('DiskIndex'))
        part = _number(item.get('Index'))
        if disk is None or part is None:
            issues.append('Registro WMI de partição sem índice confiável; ignorado.')
            continue
        size = item.get('Size')
        size = size if type(size) is int and size >= 0 else None
        kind = str(item.get('Type') or 'não informado')[:96]
        boot_hint = item.get('BootPartition') is True
        # An EFI *candidate* is not proof of the UEFI firmware boot target.
        lowkind = kind.casefold()
        efi_candidate = 'efi' in lowkind or lowkind in (
            'gpt: system', 'gpt: system partition')
        by_disk.setdefault(disk, []).append({
            'disk_index': disk,
            'partition_index': part,
            'bytes': size,
            'type': kind,
            'boot_partition_hint': boot_hint,
            'efi_type_candidate': efi_candidate,
        })

    reported = []
    for disk in targets:
        partitions = sorted(by_disk.get(disk, []), key=lambda p: p['partition_index'])
        reported.append({'disk_index': disk, 'partitions': partitions,
                         'status': 'wmi_partitions_reported' if partitions else 'not_reported'})
        if not partitions:
            issues.append(
                f'Disco {disk}: WMI reconhece o dispositivo, mas não retornou partições '
                'para este índice; situação desconhecida.')
        elif any(p['efi_type_candidate'] for p in partitions):
            issues.append(
                f'Disco {disk}: possível partição de tipo EFI identificada pela WMI, '
                'sem confirmar qual é utilizada pelo firmware.')
    if error or not targets:
        status = 'partial'
    elif all(entry['partitions'] for entry in reported) and not issues:
        status = 'observed_metadata'
    else:
        status = 'requires_review'

    return {
        'schema': 'pcro-wmi-partitions-v1',
        'status': status,
        'disks_of_interest': reported,
        'issues': issues,
        'efi_active_verified': False,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'notice': ('Win32_DiskPartition oferece evidência auxiliar de partições. '
                   'O campo BootPartition não comprova a partição EFI ativa.'),
    }
