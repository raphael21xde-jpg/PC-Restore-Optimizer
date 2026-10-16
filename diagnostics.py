"""Diagnóstico Windows *somente leitura*. Nenhum comando modifica discos, registro ou serviços.
As identificações físicas precisam ser conferidas independentemente antes de reinstalar.
"""
from __future__ import annotations
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from storage_safety import assess_boot_layout
from storage_consistency import assess_storage_mapping
from storage_extents_diagnostic import collect_extent_mapping
from storage_cross_source import assess_cross_source_storage
from boot_physical_evidence import collect_bcd_evidence, reconcile_diskdrive_evidence
from wmi_partition_evidence import summarize_wmi_partitions
from nt_volume_mapping import summarize_nt_aliases
from boot_dependency import assess_bootmgr_disk_dependency
from firmware_order_evidence import collect_firmware_order


def _powershell_json(code: str, timeout=30):
    if os.name != 'nt':
        raise RuntimeError('Este diagnóstico só está disponível no Windows.')
    program = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not program:
        raise RuntimeError('PowerShell não foi encontrado.')
    result = subprocess.run([program, '-NoProfile', '-NonInteractive', '-Command',
                             "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); $ErrorActionPreference='Stop'; " + code],
                            capture_output=True, text=True, encoding='utf-8-sig',
                            errors='replace', timeout=timeout, check=False,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Erro PowerShell')[-500:])
    value = result.stdout.strip()
    if not value:
        return []
    return json.loads(value)


def _list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def disk_inventory():
    """Get-Disk inclui discos virtuais. Nunca presume que letra = disco físico."""
    disks = _list(_powershell_json('Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType,Size,PartitionStyle,OperationalStatus,HealthStatus,IsBoot,IsSystem,IsOffline | ConvertTo-Json -Depth 4'))
    try:
        physical = _list(_powershell_json('Get-PhysicalDisk | Select-Object FriendlyName,SerialNumber,MediaType,BusType,Size | ConvertTo-Json -Depth 3'))
    except Exception:
        physical = []
    volumes = _list(_powershell_json('Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining,HealthStatus,Path | ConvertTo-Json -Depth 3'))
    try:
        partitions = _list(_powershell_json('Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,Size,IsBoot,IsSystem,GptType | ConvertTo-Json -Depth 3'))
        part_error = None
    except Exception as err:
        partitions,part_error=[],str(err)
    alerts = []
    for d in disks:
        name = str(d.get('FriendlyName',''))
        if str(d.get('BusType','')).casefold() in ('spaces','storage spaces') or 'space' in name.casefold():
            alerts.append(f'Disco {d.get("Number")}: dispositivo de Espaços de Armazenamento; mapeie seu pool e discos físicos antes de alterar partições.')
        if d.get('IsBoot') or d.get('IsSystem'):
            alerts.append(f'Disco {d.get("Number")}: Windows identificou dependência de inicialização/sistema. NÃO apagar.')
        if str(d.get('HealthStatus','')).casefold() not in ('healthy','saudável','ok',''):
            alerts.append(f'Disco {d.get("Number")}: saúde reportada como {d.get("HealthStatus")}; investigar.')
    for p in partitions:
        if p.get('IsSystem') or p.get('IsBoot') or str(p.get('Type','')).casefold() in ('system','efi system partition'):
            alerts.append(f'Disco {p.get("DiskNumber")}, partição {p.get("PartitionNumber")}: contém ou pode conter componentes de inicialização.')
    if part_error:
        alerts.append('Não foi possível enumerar todas as partições: '+part_error)
    layout = assess_boot_layout(disks, partitions)
    alerts.extend(layout['alerts'])
    mapping = assess_storage_mapping(disks, partitions, volumes, partition_error=part_error)
    alerts.extend(mapping['issues'])
    extents_mapping = collect_extent_mapping(disks)
    alerts.extend(extents_mapping['issues'])
    try:
        win32_drives = _list(_powershell_json(
            'Get-CimInstance -ClassName Win32_DiskDrive | '
            'Select-Object Index,Model,Size,Status | ConvertTo-Json -Depth 3',
            timeout=20))
        win32_error = None
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        win32_drives, win32_error = [], type(exc).__name__
    physical_evidence = reconcile_diskdrive_evidence(
        disks, win32_drives, extents_mapping, wmi_error=win32_error)
    alerts.extend(physical_evidence['issues'])
    try:
        wmi_partition_rows = _list(_powershell_json(
            'Get-CimInstance -ClassName Win32_DiskPartition | '
            'Select-Object DiskIndex,Index,Type,Size,BootPartition | ConvertTo-Json -Depth 3',
            timeout=20))
        wmi_partition_error = None
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        wmi_partition_rows, wmi_partition_error = [], type(exc).__name__
    partition_evidence = summarize_wmi_partitions(
        wmi_partition_rows,
        disk_numbers_of_interest=physical_evidence['getdisk_missing_extent_numbers'],
        error=wmi_partition_error)
    alerts.extend(partition_evidence['issues'])
    boot_evidence = collect_bcd_evidence()
    alerts.extend(boot_evidence['issues'])
    nt_volume_mapping = summarize_nt_aliases(extents_mapping, boot_evidence)
    alerts.extend(nt_volume_mapping['issues'])
    boot_dependency = assess_bootmgr_disk_dependency(nt_volume_mapping, layout)
    alerts.extend(boot_dependency['issues'])
    firmware_order = collect_firmware_order(nt_volume_mapping, layout)
    alerts.extend(firmware_order['issues'])
    cross_source = assess_cross_source_storage(disks, extents_mapping, mapping, layout)
    alerts.extend(cross_source['issues'])
    alerts.append('Discos dinâmicos, partições EFI ocultas e pools podem exigir conferência no Gerenciamento de Disco e DiskPart (somente leitura).')
    return dict(timestamp=datetime.now().isoformat(), disks=disks, physical_disks=physical, volumes=volumes,
                partitions=partitions, boot_layout=layout, storage_mapping=mapping,
                extent_mapping=extents_mapping, cross_source=cross_source,
                physical_evidence=physical_evidence, partition_evidence=partition_evidence,
                boot_evidence=boot_evidence, nt_volume_mapping=nt_volume_mapping,
                boot_dependency=boot_dependency, firmware_order=firmware_order,
                alerts=sorted(set(alerts)))


def system_inventory():
    info={'timestamp':datetime.now().isoformat(), 'platform':platform.platform(), 'alerts': []}
    if os.name != 'nt':
        info['alerts'].append('Inventário completo disponível somente no Windows.')
        return info
    commands={
      'system': 'Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory | ConvertTo-Json',
      'cpu': 'Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage | ConvertTo-Json',
      'gpus': 'Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Depth 2',
      'memory': 'Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory,TotalVisibleMemorySize,Caption,Version | ConvertTo-Json',
    }
    for key,code in commands.items():
        try: info[key]=_powershell_json(code)
        except Exception as exc: info['alerts'].append(f'{key}: não foi possível coletar: {exc}')
    info['alerts'].append('Leituras são pontuais. Temperatura, desgaste SMART e desempenho sob carga não foram medidos.')
    return info


def make_recommendations(disks,hardware):
    recommendations=[]
    for vol in disks.get('volumes',[]):
        total=vol.get('Size') or 0
        remain=vol.get('SizeRemaining')
        if isinstance(total,(int,float)) and total>0 and isinstance(remain,(int,float)):
            ratio=remain/total
            if ratio < .10:
                recommendations.append(f'Volume {vol.get("DriveLetter") or vol.get("FileSystemLabel") or "sem letra"}: menos de 10% livre ({ratio:.0%}). Avaliar espaço, sem apagar automaticamente.')
    recommendations.extend(disks.get('alerts',[]))
    if not recommendations:
        recommendations.append('Nenhuma recomendação automática de disco disparada. Isto não comprova ausência de gargalos.')
    recommendations.append('Não aplicar limpadores de registro, ajustes genéricos de BIOS nem desativação em massa de serviços.')
    return recommendations


def save_report(path, content):
    path=Path(path)
    path.write_text(json.dumps(content,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return path
