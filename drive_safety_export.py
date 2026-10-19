"""Privacy-minimal report for an explicit user clipboard action.

Never serialize an unfiltered Windows inventory, any PowerShell output,
SerialNumber, model, device path, GUID, username, or raw issue strings.
Only individually whitelisted scalar fields can leave the local UI.
This is a *diagnostic*, never permission for disk operations.
"""
from __future__ import annotations

import json
import re

DRIVE = re.compile(r'[A-Z]:\Z')
VALID_REPORT_STATUS = frozenset({'blocked', 'incomplete', 'requires_review'})
VALID_TARGET_STATUS = frozenset({'blocked', 'requires_review'})
VALID_EXTENT = frozenset({'incomplete', 'observed_logical_only'})
VALID_CAPACITY = frozenset({
    'insufficient', 'unknown', 'not_evaluated', 'reported_sufficient',
})


def _drive(value):
    if not isinstance(value, str) or not DRIVE.fullmatch(value):
        raise ValueError('Letra de volume inválida no relatório.')
    return value


def _disk_numbers(value):
    if (not isinstance(value, list) or len(value) > 128 or
            any(type(x) is not int or x < 0 or x >= 65536 for x in value) or
            len(set(value)) != len(value)):
        raise ValueError('Números de disco inválidos no relatório.')
    return sorted(value)


def _enum(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError('Estado inválido no relatório.')
    return value


def sanitized_drive_report(data):
    """Strict allowlist; reject malformed data instead of dumping extras.

    The source report is treated as untrusted input, including strings nested
    under non-exported fields. This function does not read any hardware.
    """
    if not isinstance(data, dict) or data.get('schema') != 'pcro-readonly-drive-safety-v1':
        raise ValueError('Relatório incompatível.')
    if data.get('raw_identifiers_included') is not False:
        raise ValueError('Relatório contém ou pode conter dados brutos.')
    for field in ('copy_authorized', 'backup_verified',
                  'physical_independence_verified', 'ready_for_format',
                  'installation_authorized'):
        if data.get(field) is not False:
            raise ValueError('Relatório contém autorização inesperada.')

    sources = data.get('source_volumes')
    targets = data.get('destinations')
    if (not isinstance(sources, list) or not isinstance(targets, list)
            or not 1 <= len(sources) <= 32 or not 1 <= len(targets) <= 8):
        raise ValueError('Conjunto de volumes incompleto.')
    selected = set()
    preview_sources = []
    preview_targets = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError('Origem inválida.')
        letter = _drive(row.get('letter'))
        if letter in selected:
            raise ValueError('Unidade duplicada.')
        selected.add(letter)
        preview_sources.append({
            'letter': letter,
            'logical_disk_numbers': _disk_numbers(row.get('logical_disk_numbers')),
            'extent_status': _enum(row.get('extent_status'), VALID_EXTENT),
        })
    for row in targets:
        if not isinstance(row, dict):
            raise ValueError('Destino inválido.')
        letter = _drive(row.get('letter'))
        if letter in selected:
            raise ValueError('Unidade duplicada.')
        selected.add(letter)
        blockers = row.get('blockers')
        if not isinstance(blockers, list) or len(blockers) > 200:
            raise ValueError('Bloqueios inválidos.')
        # Only share the count; the underlying string messages are never
        # copied because they may contain collector-controlled descriptions.
        preview_targets.append({
            'letter': letter,
            'logical_disk_numbers': _disk_numbers(row.get('logical_disk_numbers')),
            'extent_status': _enum(row.get('extent_status'), VALID_EXTENT),
            'capacity_status': _enum(row.get('capacity_status'), VALID_CAPACITY),
            'status': _enum(row.get('status'), VALID_TARGET_STATUS),
            'blocker_count': len(blockers),
        })
    boot = _disk_numbers(data.get('boot_related_logical_disks'))
    return {
        'schema': 'pcro-drive-diagnostic-safe-share-v1',
        'status': _enum(data.get('status'), VALID_REPORT_STATUS),
        'inventory_status': 'fresh_collected' if data.get('inventory_status') == 'fresh_collected'
                            else 'incomplete',
        'sources': preview_sources,
        'destinations': preview_targets,
        'boot_related_logical_disks': boot,
        'raw_identifiers_included': False,
        'physical_independence_verified': False,
        'copy_authorized': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'warning': (
            'Relatório somente leitura. Letras de unidade e discos lógicos '
            'não comprovam dispositivos físicos independentes. '
            'Nenhum backup ou formatação foi autorizado.'
        ),
    }


def safe_drive_report_json(report):
    """Return only the explicitly approved, non-raw fields as JSON text."""
    return json.dumps(sanitized_drive_report(report),
                      ensure_ascii=False, indent=2, sort_keys=True)
