"""Static, privacy-safe advice for ANY selected Windows volume.

These are only explanations of evidence already collected in read-only mode.
Codes are stable and data-independent: never interpolate device descriptions,
serials, pool names, GUIDs, user paths or raw collector error messages.
"""
from __future__ import annotations

FINDING_TEXT = {
    'boot_dependency_reported': (
        'Este volume possui associação lógica relatada com inicialização, '
        'sistema ou EFI. Não modificar nem formatar por este diagnóstico.'),
    'partition_extent_conflict': (
        'Get-Partition e extents apresentam discos lógicos divergentes. '
        'Revisar o mapeamento antes de qualquer plano de recuperação.'),
    'unlisted_disk_wmi_partitions': (
        'Get-Disk não listou este disco lógico, mas a WMI relatou partições. '
        'Não presumir que está vazio ou pode ser apagado.'),
    'unlisted_disk_wmi_seen': (
        'Get-Disk não listou este disco lógico, mas Win32_DiskDrive o relatou. '
        'Isso não comprova sua identidade física.'),
    'unlisted_disk_unknown': (
        'A relação deste volume com o hardware permanece incompleta. '
        'Não presumir ausência de disco nem dados.'),
    'spaces_simple_single_member': (
        'Storage Spaces relata um único membro e resiliência Simple: '
        'não há redundância do membro relatado; sua falha pode causar perda '
        'de dados. Isso não comprova independência física para backup.'),
    'spaces_simple_no_redundancy': (
        'Storage Spaces informa resiliência Simple, que não fornece '
        'redundância para falha de dispositivo. Não confundir com backup.'),
    'spaces_members_unverified': (
        'Membros de Storage Spaces foram relatados, mas sua identidade '
        'e independência física não foram verificadas.'),
    'spaces_members_unknown': (
        'Não foi possível confirmar a associação do volume virtual '
        'aos membros físicos de Storage Spaces.'),
    'capacity_not_evaluated': (
        'O espaço disponível para a cópia planejada ainda não foi avaliado. '
        'Este diagnóstico não aprovou o destino.'),
    'backup_target_blocked': (
        'Este candidato a destino está bloqueado para operações reais. '
        'Apenas consultas de diagnóstico são permitidas.'),
    'physical_independence_unverified': (
        'Letras de volumes e números de discos lógicos não comprovam '
        'independência física. Nenhuma operação em disco foi autorizada.'),
}

VALID_FINDINGS = frozenset(FINDING_TEXT)


def classify_drive_findings(row, *, boot_related_disks=(), is_target=False):
    """Return ordered, unique allowlisted codes without user/device strings."""
    if not isinstance(row, dict):
        return ['physical_independence_unverified']
    codes = []
    nums = row.get('logical_disk_numbers')
    boot = boot_related_disks
    if not isinstance(nums, (tuple, list)):
        nums = ()
    if not isinstance(boot, (tuple, list, set, frozenset)):
        boot = ()
    if (any(type(n) is int and n in boot for n in nums)):
        codes.append('boot_dependency_reported')
    if row.get('partition_crosscheck') == 'conflict':
        codes.append('partition_extent_conflict')

    extent = row.get('extent_status')
    hardware = row.get('hardware_evidence')
    if not isinstance(hardware, dict):
        hardware = {}
    if extent == 'disk_not_listed':
        if (hardware.get('wmi_partition_status') == 'reported'
                and type(hardware.get('wmi_partition_count')) is int
                and hardware['wmi_partition_count'] > 0):
            codes.append('unlisted_disk_wmi_partitions')
        elif hardware.get('wmi_diskdrive_status') == 'reported':
            codes.append('unlisted_disk_wmi_seen')
        else:
            codes.append('unlisted_disk_unknown')

    if extent == 'virtual_spaces':
        members = hardware.get('spaces_members_count')
        res = hardware.get('spaces_resiliency')
        if (res == 'simple' and type(members) is int and members == 1
                and hardware.get('spaces_membership_status')
                == 'members_reported_unverified'):
            codes.append('spaces_simple_single_member')
        elif res == 'simple':
            codes.append('spaces_simple_no_redundancy')
        state = hardware.get('spaces_membership_status')
        if state == 'members_reported_unverified':
            codes.append('spaces_members_unverified')
        else:
            codes.append('spaces_members_unknown')

    if is_target:
        if row.get('capacity_status') == 'not_evaluated':
            codes.append('capacity_not_evaluated')
        if row.get('status') == 'blocked':
            codes.append('backup_target_blocked')
    codes.append('physical_independence_unverified')
    return list(dict.fromkeys(codes))
