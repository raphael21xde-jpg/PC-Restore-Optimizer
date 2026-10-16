"""Conservative cross-disk BOOTMGR risk assessment (metadata only).

The BCD BOOTMGR volume correlation is NOT firmware boot-current evidence.
The names Disk 1 / HarddiskVolume5 are not interchangeable.
The assessment cannot authorize formatting, disconnection, backup selection,
boot modification or a Windows reinstall.
"""
from __future__ import annotations


def _numbers(values):
    if not isinstance(values, (tuple, list)):
        return []
    return sorted({value for value in values if type(value) is int and 0 <= value < 65536})


def assess_bootmgr_disk_dependency(nt_mapping, boot_layout):
    """Compare BOOTMGR BCD->NT->extents mapping against Windows IsBoot disk."""
    nt_mapping = nt_mapping if isinstance(nt_mapping, dict) else {}
    boot_layout = boot_layout if isinstance(boot_layout, dict) else {}
    windows = _numbers(boot_layout.get('boot_disks'))
    matched = [entry for entry in nt_mapping.get('volumes', [])
               if isinstance(entry, dict) and entry.get('bootmgr_device_match') is True
               and entry.get('status') == 'observed']
    correlated = nt_mapping.get('bootmgr_status') == 'bootmgr_device_correlated'
    bootmgr = (_numbers(matched[0].get('disk_numbers'))
               if correlated and len(matched) == 1 else [])
    issues = []
    if len(windows) == 1 and len(bootmgr) == 1:
        if windows[0] != bootmgr[0]:
            status = 'separate_disks_reported'
            issues.append(
                f'ALERTA DE INICIALIZAÇÃO: Windows em uso no Disco {windows[0]}, '
                f'mas o BOOTMGR registrado no BCD aponta para volume do Disco {bootmgr[0]}. '
                'Não desconectar, apagar, formatar ou reinstalar sem validar a '
                'entrada UEFI efetivamente utilizada e preparar recuperação.')
        else:
            status = 'same_disk_reported'
            issues.append(
                'Windows e BOOTMGR foram relacionados ao mesmo disco lógico. '
                'Isso não garante EFI ativa, boot independente ou segurança para formatação.')
    else:
        status = 'unverified'
        issues.append(
            'Não foi possível relacionar de forma única Windows em uso e BOOTMGR '
            'a discos lógicos. Verificação de inicialização pendente.')
    if not correlated:
        issues.append('Correlação BCD/GUID/NT não confirmada; risco de boot permanece desconhecido.')
    return {
        'schema': 'pcro-boot-dependency-v1',
        'status': status,
        'windows_disk_numbers': windows,
        'bootmgr_disk_numbers': bootmgr,
        'issues': issues,
        'risk_requires_manual_review': True,
        'efi_active_verified': False,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'notice': ('Metadados apenas. A consulta BCDEdit não comprova qual entrada '
                   'de firmware inicializou esta sessão Windows.')
    }
