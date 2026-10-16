"""Read-only Storage Spaces virtual-to-physical membership evidence.

Get-Disk often exposes a Storage Spaces virtual disk, not its physical members.
This report is NOT a proof of off-device backup, disk health, or redundancy.
Never initialize, repair, import, optimize, pool, mount, or format storage.
"""
from __future__ import annotations

MAX_VIRTUAL_DISKS = 128
MAX_PHYSICAL_MEMBERS = 256

# All commands are read-only. Association calls are also read-only.
# Individual association failures remain explicit instead of becoming empty lists.
SPACES_QUERY = """
$ErrorActionPreference='Stop'
$records = @(
  foreach ($vd in @(Get-VirtualDisk -ErrorAction Stop)) {
    $diskNumbers = @()
    $physicalMembers = @()
    $diskAssociationOk = $true
    $physicalAssociationOk = $true
    try {
      $diskNumbers = @($vd | Get-Disk -ErrorAction Stop |
        Select-Object -ExpandProperty Number)
    } catch { $diskAssociationOk = $false }
    try {
      $physicalMembers = @($vd | Get-PhysicalDisk -ErrorAction Stop |
        Select-Object DeviceId,FriendlyName,Size,HealthStatus)
    } catch { $physicalAssociationOk = $false }
    [pscustomobject]@{
      Name = [string]$vd.FriendlyName
      Resiliency = [string]$vd.ResiliencySettingName
      HealthStatus = [string]$vd.HealthStatus
      LogicalDiskNumbers = @($diskNumbers)
      PhysicalMembers = @($physicalMembers)
      DiskAssociationOk = $diskAssociationOk
      PhysicalAssociationOk = $physicalAssociationOk
    }
  }
)
ConvertTo-Json -InputObject @($records) -Depth 6 -Compress
""".strip()


def _disk_number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def _member(member):
    if not isinstance(member, dict):
        return None
    number = member.get('DeviceId')
    if isinstance(number, str):
        number = number[:24] if number.isdigit() else None
    elif type(number) is int and number >= 0:
        number = str(number)
    else:
        number = None
    size = member.get('Size')
    if type(size) is not int or size < 0:
        size = None
    return {
        'device_id': number,
        'model': str(member.get('FriendlyName') or 'não informado')[:100],
        'size_bytes': size,
        'health': str(member.get('HealthStatus') or 'desconhecida')[:60],
    }


def assess_spaces_membership(disks, raw_virtual_disks, *, error=None):
    """Cross-check logical Spaces disk numbers against virtual disks and members.

    Get-VirtualDisk / Get-PhysicalDisk association is useful evidence but never
    proof of the actual physical backup independence from system/source drives.
    """
    disks = disks if isinstance(disks, list) else []
    spaces = sorted({n for d in disks if isinstance(d, dict)
                     if (n := _disk_number(d.get('Number'))) is not None
                     and str(d.get('BusType', '')).strip().casefold()
                     in ('spaces', 'storage spaces')})
    issues = []
    if error:
        issues.append('Consulta de Storage Spaces indisponível; membros físicos não verificados.')
    raw = raw_virtual_disks if isinstance(raw_virtual_disks, list) else []
    if len(raw) > MAX_VIRTUAL_DISKS:
        raw = []
        issues.append('Muitos discos virtuais retornados; análise interrompida por limite.')
    result = []
    for row in raw:
        if not isinstance(row, dict):
            issues.append('Registro de disco virtual inválido.')
            continue
        logical = row.get('LogicalDiskNumbers', [])
        logical = logical if isinstance(logical, list) else [logical]
        logical = sorted({n for x in logical if (n := _disk_number(x)) is not None})
        members_raw = row.get('PhysicalMembers', [])
        members_raw = members_raw if isinstance(members_raw, list) else [members_raw]
        if len(members_raw) > MAX_PHYSICAL_MEMBERS:
            members_raw = []
            issues.append('Quantidade de membros físicos excedeu o limite seguro.')
        members = [valid for m in members_raw if (valid := _member(m)) is not None]
        disks_ok = row.get('DiskAssociationOk') is True
        members_ok = row.get('PhysicalAssociationOk') is True
        complete = bool(logical and members and disks_ok and members_ok
                        and len(members) == len(members_raw))
        item = {
            'virtual_name': str(row.get('Name') or 'disco virtual sem nome')[:100],
            'logical_disk_numbers': logical,
            'resiliency_reported': str(row.get('Resiliency') or 'não informada')[:60],
            'health_reported': str(row.get('HealthStatus') or 'desconhecida')[:60],
            'member_count': len(members),
            'members': members,
            'status': 'members_reported' if complete else 'membership_incomplete',
        }
        result.append(item)
        if not complete:
            issues.append('Disco virtual ' + item['virtual_name'] +
                          ': associação lógica/física incompleta ou inacessível.')
        if item['resiliency_reported'].casefold() in ('simple', 'simples'):
            issues.append('Disco virtual ' + item['virtual_name'] +
                          ': resilência Simple informada; não presumir tolerância a falhas.')
        if item['health_reported'].casefold() not in ('healthy', 'saudável', 'ok'):
            issues.append('Disco virtual ' + item['virtual_name'] +
                          ': saúde informada como ' + item['health_reported'] + '.')
    for number in spaces:
        matches = [entry for entry in result if number in entry['logical_disk_numbers']]
        if len(matches) != 1:
            issues.append(f'Disco lógico {number} (Spaces): '
                          'não houve associação única a um disco virtual. Conferir manualmente.')
        elif matches[0]['status'] != 'members_reported':
            issues.append(f'Disco lógico {number} (Spaces): '
                          'membros físicos parcialmente conhecidos.')
        else:
            issues.append(f'Disco lógico {number} (Spaces): '
                          f'{matches[0]["member_count"]} membro(s) físico(s) reportado(s); '
                          'NÃO comprova independência do backup nem proteção dos dados.')
    if spaces:
        status = 'requires_review'
    elif error:
        status = 'unavailable'
    else:
        status = 'not_applicable'
    return {
        'schema': 'pcro-storage-spaces-members-v1',
        'status': status,
        'spaces_logical_disks': spaces,
        'virtual_disks': result,
        'issues': issues,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'note': ('Get-VirtualDisk e Get-PhysicalDisk mostram associações relatadas pelo Windows. '
                 'Redundância de pool não substitui backup independente.')
    }
