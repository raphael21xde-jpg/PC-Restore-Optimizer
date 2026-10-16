"""Read-only classification of Windows boot layout from storage metadata.

No formatting, mounting, EFI editing, commands, or permission escalation.
Labels from Windows are evidence, not permission to modify any disk.
"""
from __future__ import annotations


def _numbers(records, flag):
    numbers = set()
    for row in records:
        if not isinstance(row, dict) or row.get(flag) is not True:
            continue
        number = row.get('DiskNumber', row.get('Number'))
        if type(number) is int and number >= 0:
            numbers.add(number)
    return numbers


def assess_boot_layout(disks, partitions):
    """Assess reported Windows boot/system partitions. Never approve a reinstall.

    IsBoot means Windows currently in use; IsSystem generally identifies the
    startup/system partition. Missing facts => not verified, not safe.
    """
    all_disks = [d for d in disks if isinstance(d, dict)]
    all_parts = [p for p in partitions if isinstance(p, dict)]
    boot = _numbers(all_parts, 'IsBoot') or _numbers(all_disks, 'IsBoot')
    system = _numbers(all_parts, 'IsSystem') or _numbers(all_disks, 'IsSystem')
    alerts = []

    if boot and system and boot.isdisjoint(system):
        status = 'cross_disk'
        alerts.append(
            'ATENÇÃO: Windows em uso e partição de inicialização/sistema '
            'aparecem em discos diferentes. Não remover, desconectar, '
            'formatar ou reinstalar sem confirmar EFI/BCD e recuperação.')
    elif not boot or not system:
        status = 'unverified'
        alerts.append(
            'ATENÇÃO: não foi possível confirmar em qual disco ficam '
            'Windows e arquivos de inicialização. Conferência manual obrigatória.')
    else:
        status = 'same_disk_reported'
        alerts.append(
            'Windows e arquivos de inicialização foram reportados no mesmo '
            'disco; isso NÃO confirma independência do boot nem autoriza formatação.')

    return {
        'status': status,
        'boot_disks': sorted(boot),
        'system_disks': sorted(system),
        'alerts': alerts,
        'approved_for_format': False,
    }
