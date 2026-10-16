"""Safe UEFI firmware *registered order* evidence from BCDEdit.

Only invokes 'bcdedit.exe /enum firmware /v'; never sets the boot order.
The firmware's displayed order does NOT establish UEFI BootCurrent.
No full BCD contents or entry GUIDs are persisted in the report.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

MAX_TEXT = 250000
MAX_ENTRIES = 128
GUID = r'\{[0-9a-fA-F-]{36}\}'
IDENTIFIER = re.compile(r'^\s*(?:identifier|identificador)\s+(' + GUID + r')\s*$', re.I)
ORDER = re.compile(r'^\s*displayorder\s+(' + GUID + r')\s*$', re.I)
GUID_LINE = re.compile(r'^\s*(' + GUID + r')\s*$')
NT = re.compile(r'\\Device\\HarddiskVolume[0-9]+', re.I)
DEVICE = re.compile(r'^\s*device\s+partition=(\\Device\\HarddiskVolume[0-9]+)\s*$', re.I)
PATH = re.compile(r'^\s*path\s+(\S+)\s*$', re.I)


def _numbers(values):
    if not isinstance(values, (list, tuple)):
        return []
    return sorted({x for x in values if type(x) is int and 0 <= x < 65536})


def _unknown(reason, issue):
    return {'schema': 'pcro-firmware-order-v1', 'status': 'unavailable',
            'reason': reason, 'order_entry_count': None, 'bootmgr_in_order': None,
            'bootmgr_nt_device': None, 'bootmgr_disks': [], 'windows_disks': [],
            'issues': [issue], 'bootcurrent_verified': False,
            'efi_active_verified': False, 'backup_destination_verified': False,
            'approved_for_format': False}


def _sections(raw):
    if not isinstance(raw, str) or not raw or len(raw) > MAX_TEXT:
        return []
    parsed = []
    for section in re.split(r'(?:\r?\n)\s*(?:\r?\n)', raw):
        identifier, order, device, path = None, [], None, None
        collecting_order = False
        for line in section.splitlines():
            if (match := IDENTIFIER.fullmatch(line)):
                identifier = match.group(1).casefold()
                collecting_order = False
            elif (match := ORDER.fullmatch(line)):
                order.append(match.group(1).casefold())
                collecting_order = True
            elif collecting_order and (match := GUID_LINE.fullmatch(line)):
                order.append(match.group(1).casefold())
            else:
                collecting_order = False
                if (match := DEVICE.fullmatch(line)):
                    device = match.group(1).casefold()
                elif (match := PATH.fullmatch(line)):
                    path = match.group(1).casefold()
        if identifier:
            parsed.append({'id': identifier, 'order': order, 'device': device, 'path': path})
    return parsed if len(parsed) <= MAX_ENTRIES else []


def assess_firmware_order(stdout, nt_mapping, boot_layout):
    """Observe a firmware-manager order referencing a BOOTMGFW entry.

    No match -> uncertainty. One match -> registered entry, NOT proof it booted.
    """
    entries = _sections(stdout)
    if not entries:
        return _unknown('unparseable', 'Saída de firmware vazia, truncada ou não reconhecida.')
    managers = [e for e in entries if e['order'] and not e['device'] and not e['path']]
    if len(managers) != 1:
        return _unknown('ambiguous_manager', 'Não foi possível identificar um único gerenciador de firmware.')
    order = managers[0]['order']
    if len(order) > MAX_ENTRIES:
        return _unknown('oversized_order', 'Ordem de firmware excede limite seguro.')
    bootmgrs = [e for e in entries if e['id'] in order and e['device']
                and e['path'] and e['path'].startswith('\\efi\\')
                and e['path'].endswith('\\bootmgfw.efi')]
    if len(bootmgrs) != 1:
        return {'schema': 'pcro-firmware-order-v1',
                'status': 'bootmgr_not_unique_in_order', 'reason': 'ambiguous_entry',
                'order_entry_count': len(order), 'bootmgr_in_order': False,
                'bootmgr_nt_device': None, 'bootmgr_disks': [],
                'windows_disks': _numbers(
                    boot_layout.get('boot_disks') if isinstance(boot_layout, dict) else None),
                'issues': ['Entrada Windows Boot Manager não foi correlacionada '
                           'de forma única com a ordem do firmware.'],
                'bootcurrent_verified': False, 'efi_active_verified': False,
                'backup_destination_verified': False, 'approved_for_format': False}
    target = bootmgrs[0]['device']
    nt_mapping = nt_mapping if isinstance(nt_mapping, dict) else {}
    matched = [v for v in nt_mapping.get('volumes', [])
               if isinstance(v, dict) and v.get('status') == 'observed'
               and str(v.get('nt_device', '')).casefold() == target]
    bootdisks = _numbers(matched[0].get('disk_numbers')) if len(matched) == 1 else []
    windows = _numbers(boot_layout.get('boot_disks')) if isinstance(boot_layout, dict) else []
    if len(windows) == 1 and len(bootdisks) == 1:
        if windows[0] != bootdisks[0]:
            state = 'registered_bootmgr_cross_disk'
            issue = (f'ATENÇÃO: ordem UEFI registra BOOTMGR no Disco {bootdisks[0]}, '
                     f'mas Windows em uso no Disco {windows[0]}. '
                     'Não formatar/desconectar discos; BootCurrent permanece não verificado.')
        else:
            state = 'registered_bootmgr_same_disk'
            issue = ('Ordem UEFI registra BOOTMGR no disco lógico do Windows, '
                     'mas isso não confirma a EFI usada no último boot.')
    else:
        state = 'registered_bootmgr_disk_unknown'
        issue = ('Ordem UEFI contém Windows Boot Manager, mas o volume ou disco '
                 'não pôde ser correlacionado sem ambiguidades.')
    return {'schema': 'pcro-firmware-order-v1',
            'status': state, 'reason': 'none', 'order_entry_count': len(order),
            'bootmgr_in_order': True, 'bootmgr_nt_device': target,
            'bootmgr_disks': bootdisks, 'windows_disks': windows,
            'issues': [issue], 'bootcurrent_verified': False,
            'efi_active_verified': False, 'backup_destination_verified': False,
            'approved_for_format': False,
            'notice': 'Ordem registrada no UEFI não prova BootCurrent nem autoriza reinstalação.'}


def collect_firmware_order(nt_mapping, boot_layout, *, runner=subprocess.run):
    """No automatic privilege escalation; only query BCD firmware registry."""
    if os.name != 'nt':
        return _unknown('unsupported_os', 'Consulta firmware disponível somente no Windows.')
    bcd = shutil.which('bcdedit.exe')
    if not bcd:
        return _unknown('tool_missing', 'BCDEdit não encontrado.')
    try:
        result = runner([bcd, '/enum', 'firmware', '/v'],
                        text=True, encoding='utf-8', errors='replace',
                        capture_output=True, check=False, timeout=12,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            err = str(getattr(result, 'stderr', '') or '').casefold()
            denied = any(x in err for x in (
                'access is denied', 'acesso negado', 'acesso é negado', 'permission'))
            return _unknown('permission_denied' if denied else 'query_failed',
                            'BCDEdit /enum firmware não foi acessível; '
                            'consulta pode exigir privilégios de administrador.')
        return assess_firmware_order(result.stdout, nt_mapping, boot_layout)
    except subprocess.TimeoutExpired:
        return _unknown('timeout', 'Consulta firmware atingiu limite de tempo.')
    except PermissionError:
        return _unknown('permission_denied', 'Consulta firmware teve acesso negado.')
    except (OSError, ValueError):
        return _unknown('query_failed', 'Não foi possível consultar o firmware com BCDEdit.')
