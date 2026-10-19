"""Windows volume GUID -> NT device path mapping via QueryDosDeviceW (read-only).

Microsoft "Displaying Volume Paths" documents this Win32 lookup.
The NT HarddiskVolume number is NOT the physical disk number.
Neither a mapping nor BCDEdit output proves an EFI is firmware-active.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re

from volume_inventory import normalize_volume_id

NT_VOLUME = re.compile(r'^\\Device\\HarddiskVolume[0-9]+$', re.IGNORECASE)
MAX_MAPPINGS = 128
MAX_BUFFER_CHARS = 65536


def query_nt_device(volume_guid):
    r"""Returns current NT volume target for an enumerated volume GUID only.

    QueryDosDeviceW uses "Volume{GUID}" (no \\?\ prefix/trailing slash).
    It never creates/assigns drive letters, opens or modifies any disk.
    """
    guid = normalize_volume_id(volume_guid)
    if os.name != 'nt':
        raise OSError('A consulta de nomes NT só funciona no Windows.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.QueryDosDeviceW.restype = wintypes.DWORD
    alias = guid[4:-1]
    size = 256
    while size <= MAX_BUFFER_CHARS:
        buffer = ctypes.create_unicode_buffer(size)
        length = kernel.QueryDosDeviceW(alias, buffer, size)
        if length:
            first = buffer.value
            if NT_VOLUME.fullmatch(first):
                return first
            raise ValueError('Nome NT não é um volume HarddiskVolume reconhecido.')
        error = ctypes.get_last_error()
        if error != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise ctypes.WinError(error)
        size *= 2
    raise OSError('Consulta de nome NT excedeu o limite seguro.')


def summarize_nt_aliases(extent_mapping, boot_evidence, *, query=query_nt_device):
    """Join volume GUID/extents/NT aliases; preserve all unresolved evidence."""
    volumes = extent_mapping.get('volumes', []) if isinstance(extent_mapping, dict) else []
    if not isinstance(volumes, list) or len(volumes) > MAX_MAPPINGS:
        return _incomplete('Quantidade de volumes acima do limite suportado.')
    boot_evidence = boot_evidence if isinstance(boot_evidence, dict) else {}
    targets = {str(x).casefold() for x in boot_evidence.get('nt_volume_devices', [])
               if NT_VOLUME.fullmatch(str(x))}
    rows = []
    issues = []
    nt_counts = {}
    for v in volumes:
        if not isinstance(v, dict):
            issues.append('Registro de volume inválido; correspondência omitida.')
            continue
        guid = v.get('volume_id')
        letters = [letter for letter in v.get('letters', [])
                   if isinstance(letter, str) and len(letter) == 1 and letter.isascii() and letter.isalpha()]
        numbers = [n for n in v.get('disk_numbers', [])
                   if type(n) is int and 0 <= n < 65536]
        try:
            device = query(guid)
            if not isinstance(device, str) or not NT_VOLUME.fullmatch(device):
                raise ValueError('Resposta da API não identifica um volume NT.')
            status = 'observed'
            reason = 'Alias NT observado; número de disco físico não comprovado.'
            nt_counts[device.casefold()] = nt_counts.get(device.casefold(), 0) + 1
        except (OSError, ValueError, TypeError) as exc:
            device = None
            status = 'unavailable'
            reason = type(exc).__name__ + ': não foi possível associar GUID ao alias NT.'
            issues.append('Alias NT não disponível para volume sem letra ou com letra ' +
                          (', '.join(letters) if letters else '(nenhuma)') + '.')
        rows.append({'letters': sorted(set(x.upper() for x in letters)),
                     'disk_numbers': sorted(set(numbers)),
                     'nt_device': device,
                     'status': status,
                     'source_status': str(v.get('status', 'unknown'))[:40],
                     'note': reason,
                     'bootmgr_device_match': False})

    for row in rows:
        device = row['nt_device']
        if device and nt_counts.get(device.casefold(), 0) > 1:
            row['status'] = 'ambiguous'
            issues.append('Alias NT duplicado na consulta; correlação não verificada.')
        elif device and device.casefold() in targets:
            row['bootmgr_device_match'] = True

    matched = [r for r in rows if r['bootmgr_device_match'] and r['status'] == 'observed']
    if not targets:
        boot_status = 'bootmgr_unavailable'
        issues.append('BCDEdit não trouxe volume NT correlacionável; não inferir EFI ativa.')
    elif len(matched) == 1:
        boot_status = 'bootmgr_device_correlated'
        issues.append('Dispositivo do BOOTMGR correlacionado por nome NT; '
                      'a EFI efetivamente selecionada pelo firmware NÃO foi comprovada.')
    else:
        boot_status = 'bootmgr_device_unverified'
        issues.append('Nome NT do BOOTMGR não corresponde unicamente aos GUIDs consultados.')
    return {
        'schema': 'pcro-nt-volume-map-v1',
        'status': 'requires_review',
        'bootmgr_status': boot_status,
        'volumes': rows,
        'bootmgr_correlated_disks': matched[0]['disk_numbers'] if len(matched) == 1 else [],
        'issues': issues,
        'efi_active_verified': False,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'notice': ('HarddiskVolume5 é um identificador NT de volume, NÃO é o Disco 5. '
                   'Sem prova de EFI ativa e sem autorização para operações destrutivas.')
    }


def _incomplete(reason):
    return {'schema': 'pcro-nt-volume-map-v1',
            'status': 'requires_review', 'bootmgr_status': 'unknown',
            'volumes': [], 'bootmgr_correlated_disks': [], 'issues': [reason],
            'efi_active_verified': False, 'backup_destination_verified': False,
            'approved_for_format': False}
