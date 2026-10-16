"""Conservative Windows boot/physical-disk evidence. READ-ONLY.

Queries:
  - BCDEdit /enum BOOTMGR /v (read-only; may require admin)
  - Win32_DiskDrive WMI from diagnostics.py (read-only)
Neither is proof of an active EFI partition or safe storage operation.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

NT_DEVICE = re.compile(r'\\Device\\HarddiskVolume[0-9]+', re.IGNORECASE)
MAX_BCD_BYTES = 250000


def _integer_number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def classify_bcd_output(stdout='', *, returncode=0, error=None, stderr=''):
    """Retain only anonymous NT volume device targets, never raw BCD identifiers."""
    if error is not None or returncode:
        raw = (str(error or '') + ' ' + str(stderr or '')).casefold()
        if 'permission' in raw or 'access is denied' in raw or 'acesso negado' in raw or 'acesso é negado' in raw:
            reason = 'permission_denied'
            explanation = 'Acesso negado ao repositório BCD. O aplicativo não tentará elevar privilégios.'
        elif 'timeout' in raw or 'tempo limite' in raw:
            reason = 'timeout'
            explanation = 'A consulta excedeu o tempo limite. Nenhuma alteração foi executada.'
        elif error == 'tool_missing':
            reason = 'tool_missing'
            explanation = 'BCDEdit não foi encontrado no ambiente atual.'
        elif error == 'unsupported_os':
            reason = 'unsupported_os'
            explanation = 'Consulta disponível apenas no Windows.'
        else:
            reason = 'query_failed'
            explanation = 'A consulta BCDEdit não pôde ser concluída; não é possível inferir o motivo.'
        return {
            'status': 'unavailable',
            'reason': reason,
            'nt_volume_devices': [],
            'issues': [explanation + ' EFI ativa permanece não verificada.'],
            'efi_active_verified': False, 'approved_for_format': False,
        }
    targets = sorted(set(s.lower() for s in NT_DEVICE.findall(str(stdout)[:MAX_BCD_BYTES])))
    return {
        'status': 'bootmgr_store_observed' if targets else 'bootmgr_device_unresolved',
        'nt_volume_devices': targets,
        'reason': 'none' if targets else 'unresolved_device',
        'issues': [
            ('BCDEdit apontou para identificador(es) NT de volume. '
             'Ainda é necessário correlacioná-los com GUID/EFI e firmware de boot.'
             if targets else
             'BCDEdit respondeu, mas o dispositivo de boot não foi resolvido em um volume NT.')],
        'efi_active_verified': False,
        'approved_for_format': False,
    }


def collect_bcd_evidence(*, runner=subprocess.run):
    """No elevation, no BCD changes; timeout and failure remain UNKNOWN."""
    if os.name != 'nt':
        return classify_bcd_output(error='unsupported_os')
    bcd = shutil.which('bcdedit.exe')
    if not bcd:
        return classify_bcd_output(error='tool_missing')
    try:
        result = runner([bcd, '/enum', 'BOOTMGR', '/v'], text=True,
                        encoding='utf-8', errors='replace', capture_output=True,
                        timeout=12, check=False,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return classify_bcd_output(result.stdout, returncode=result.returncode,
                                   stderr=(result.stderr or '')[:400])
    except subprocess.TimeoutExpired:
        return classify_bcd_output(error='timeout')
    except PermissionError:
        return classify_bcd_output(error='permission_denied')
    except (OSError, ValueError):
        return classify_bcd_output(error='query_failed')


def reconcile_diskdrive_evidence(disks, wmi_disks, extent_mapping, *, wmi_error=None):
    """Compare Windows storage API logical numbers against WMI physical indices.

    WMI Index is supporting metadata only: it does not prove that the same
    physical device is healthy, connected, or independent of a Storage Space.
    """
    storage_numbers = {_integer_number(d.get('Number')) for d in disks
                       if isinstance(d, dict)}
    storage_numbers.discard(None)
    wmi_by_index = {}
    for row in wmi_disks:
        if isinstance(row, dict) and (n := _integer_number(row.get('Index'))) is not None:
            wmi_by_index[n] = {
                'index': n,
                'model': str(row.get('Model') or '')[:96],
                'status': str(row.get('Status') or 'unknown')[:48],
            }
    extent_numbers = set()
    for row in extent_mapping.get('volumes', []) if isinstance(extent_mapping, dict) else ():
        if not isinstance(row, dict):
            continue
        for v in row.get('disk_numbers', ()):
            if (n := _integer_number(v)) is not None:
                extent_numbers.add(n)
    missing_getdisk = sorted(extent_numbers - storage_numbers)
    matches = []
    issues = []
    for n in missing_getdisk:
        other = wmi_by_index.get(n)
        matches.append({'disk_number': n, 'present_in_wmi': other is not None,
                        'wmi_model': other['model'] if other else None,
                        'wmi_status': other['status'] if other else None})
        if other:
            issues.append(f'Disco {n}: presente em Win32_DiskDrive (WMI), mas ausente em Get-Disk. '
                          'Identidade e saúde física ainda exigem confirmação.')
        else:
            issues.append(f'Disco {n}: não apareceu em Get-Disk nem Win32_DiskDrive. '
                          'Pode existir armazenamento legado/virtual; não presumir remoção segura.')
    if wmi_error is not None:
        issues.append('Consulta Win32_DiskDrive indisponível; presença física não confirmada.')
    if not wmi_by_index:
        issues.append('Win32_DiskDrive não retornou dispositivos; inventário WMI incompleto.')
    return {
        'schema': 'pcro-physical-evidence-v1',
        'status': 'requires_review',
        'wmi_device_count': len(wmi_by_index),
        'getdisk_missing_extent_numbers': missing_getdisk,
        'disagreements': matches, 'issues': issues,
        'efi_active_verified': False,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'note': 'Win32_DiskDrive Index é metadado adicional; não garante identidade física estável.',
    }
