"""Pure judge: are the backup destinations on other disks than the sources?

Works only on data that was already collected (the result of
``drive_safety_report.inspect_fresh_drive_safety`` and the Get-Disk rows of
the same inventory). It runs no command, reads no file, writes nothing and
never reads or changes any safety lock. The verdict is advice for a later
step; it never authorizes copying, formatting or installing anything.

Verdicts, from worst to best (the overall verdict is the worst one found):
    'mesmo_disco'   a destination shares a disk number with a source;
    'duvida'        anything not clearly proven (the default);
    'independentes' every rule below holds for every source and destination.

Rules for 'independentes' (all of them, for every source and destination):
    * extent_status == 'observed_logical_only' with exactly one disk number;
    * partition_crosscheck == 'logical_match' ('limited_match' -> 'duvida');
    * destination status == 'requires_review' (missing, unknown or
      'blocked' -> 'duvida');
    * boot_related_logical_disks is a non-empty list (a Windows in use
      always has a boot disk, so an empty list is not proof);
    * destination disks contain no source disk and no boot/system/EFI disk;
    * every disk involved appears once in Get-Disk with a BusType in
      NVMe, SATA, ATA or USB (SCSI, SAS, Spaces, RAID, iSCSI, virtual,
      numeric codes, empty or unknown -> 'duvida'). SCSI and SAS are not
      accepted because Hyper-V/VMware virtual disks show up as SCSI/SAS;
    * the disk's FriendlyName is a text without "virtual", "vmware",
      "vbox", "qemu" or "msft" (any case); a virtual-looking or missing
      name -> 'duvida' on any bus. The model name is never shown.

Malformed input never raises: it becomes 'duvida'. The output carries only
drive letters, verdicts and short Portuguese reasons (no serial numbers,
models, device paths or folder paths).
"""
from __future__ import annotations

import re

INDEPENDENT = 'independentes'
SAME_DISK = 'mesmo_disco'
DOUBT = 'duvida'

# Worst first: anything that is not 'independentes' prevents that verdict.
SEVERITY = {INDEPENDENT: 0, DOUBT: 1, SAME_DISK: 2}

# SCSI/SAS are left out on purpose: virtual disks (Hyper-V/VMware) report
# them, so they become 'duvida' (safest choice, P2-09 slice 2b).
ACCEPTED_BUS_TYPES = frozenset({'nvme', 'sata', 'ata', 'usb'})
VIRTUAL_NAME_MARKERS = ('virtual', 'vmware', 'vbox', 'qemu', 'msft')
ACCEPTED_CROSSCHECK = frozenset({'logical_match'})
ACCEPTED_TARGET_STATUS = 'requires_review'
MAX_DISK_NUMBER = 65536
MAX_ENTRIES = 64

_LETTER = re.compile(r'[A-Za-z]:?\Z')

MSG_SAME = ('O destino {unidade} fica no mesmo disco de uma das unidades '
            'de origem. Se esse disco estragar, o original e a cópia se '
            'perdem juntos.')
MSG_BOOT = ('O destino {unidade} fica no disco onde o Windows inicia. '
            'Esse disco pode ser apagado na reinstalação.')
MSG_OK = ('O destino {unidade} fica em outro disco, separado das unidades '
          'de origem.')
MSG_DEST_BAD = ('Não foi possível confirmar em qual disco fica o destino '
                '{unidade}.')
MSG_DEST_BLOCKED = ('O destino {unidade} foi barrado pela conferência de '
                    'segurança dos discos.')
MSG_DEST_STATUS = ('A conferência de segurança dos discos não informou se o '
                   'destino {unidade} pode ser usado.')
MSG_BOOT_UNKNOWN = ('Não foi possível saber em qual disco o Windows inicia. '
                    'Por segurança, nada foi considerado separado.')
MSG_CROSS = ('As informações do Windows sobre o disco do destino {unidade} '
             'não batem ou estão incompletas.')
MSG_BUS = ('Não deu para confirmar que o disco do destino {unidade} é um '
           'disco físico comum (por exemplo RAID, disco virtual, disco de '
           'servidor ou tipo desconhecido).')
MSG_SOURCE_BAD = ('Não foi possível confirmar em qual disco fica uma das '
                  'unidades de origem.')
MSG_SOURCE_BUS = ('Não deu para confirmar que o disco de uma das unidades '
                  'de origem é um disco físico comum (por exemplo RAID, disco '
                  'virtual, disco de servidor ou tipo desconhecido).')
MSG_REPORT_BAD = ('A conferência dos discos está incompleta ou em formato '
                  'inesperado. Por segurança, nada foi considerado separado.')
MSG_NO_TARGET = 'Nenhum destino foi informado.'
MSG_READ_ONLY = ('Esta conferência só lê informações; nada foi copiado, '
                 'apagado ou alterado.')
MSG_ALL_OK = ('Todos os destinos ficam em discos diferentes dos discos de '
              'origem.')


def _valid_number(value):
    return type(value) is int and 0 <= value < MAX_DISK_NUMBER


def _number_list(value):
    """Return a sorted list of disk numbers, or None when malformed."""
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ENTRIES:
        return None
    if any(not _valid_number(item) for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return sorted(value)


def _unit(value):
    if isinstance(value, str) and _LETTER.fullmatch(value.strip()):
        return value.strip()[0].upper() + ':'
    return None


def _read_volume(item):
    """Validate one source/destination entry of the safety report.

    Returns a dict with the parsed fields, or None when malformed.
    """
    if not isinstance(item, dict):
        return None
    unit = _unit(item.get('letter'))
    numbers = _number_list(item.get('logical_disk_numbers'))
    partition = item.get('partition_logical_disk_numbers', [])
    partition = _number_list(partition)
    extent_status = item.get('extent_status')
    crosscheck = item.get('partition_crosscheck')
    if (unit is None or numbers is None or partition is None or
            not isinstance(extent_status, str) or
            not isinstance(crosscheck, str)):
        return None
    return {
        'unidade': unit,
        'numbers': numbers,
        'candidates': set(numbers) | set(partition),
        'extent_status': extent_status,
        'crosscheck': crosscheck,
        'status': item.get('status'),
    }


def _bus_ok(number, disks):
    """True only when the disk appears exactly once with an accepted BusType
    and a FriendlyName that does not look like a virtual disk."""
    rows = [row for row in disks
            if isinstance(row, dict) and row.get('Number') == number
            and _valid_number(row.get('Number'))]
    if len(rows) != 1:
        return False
    bus = rows[0].get('BusType')
    name = rows[0].get('FriendlyName')
    if not isinstance(bus, str) or not isinstance(name, str):
        return False
    folded = name.casefold()
    if any(marker in folded for marker in VIRTUAL_NAME_MARKERS):
        return False
    return bus.strip().casefold() in ACCEPTED_BUS_TYPES


def _mapping_ok(entry):
    return (entry['extent_status'] == 'observed_logical_only' and
            len(entry['numbers']) == 1 and
            entry['crosscheck'] in ACCEPTED_CROSSCHECK)


def _doubt_result(reason, destinos=()):
    return {'veredito': DOUBT, 'motivos': [reason], 'destinos': list(destinos)}


def _judge(safety_report, disks):
    if not isinstance(safety_report, dict) or not isinstance(disks, list):
        return _doubt_result(MSG_REPORT_BAD)
    raw_sources = safety_report.get('source_volumes')
    raw_targets = safety_report.get('destinations')
    boot = _number_list(safety_report.get('boot_related_logical_disks'))
    if (not isinstance(raw_sources, list) or not isinstance(raw_targets, list)
            or len(raw_sources) > MAX_ENTRIES or len(raw_targets) > MAX_ENTRIES):
        return _doubt_result(MSG_REPORT_BAD)
    if not raw_targets:
        return _doubt_result(MSG_NO_TARGET)

    sources = [_read_volume(item) for item in raw_sources]
    sources_ok = bool(sources) and all(item is not None for item in sources)
    valid_sources = [item for item in sources if item is not None]
    source_disks = set()
    for item in valid_sources:
        source_disks |= item['candidates']
    source_problem = None
    if not sources_ok or boot is None:
        source_problem = MSG_SOURCE_BAD if boot is not None else MSG_REPORT_BAD
    elif not boot:
        source_problem = MSG_BOOT_UNKNOWN
    elif any(not _mapping_ok(item) for item in valid_sources):
        source_problem = MSG_SOURCE_BAD
    elif any(not _bus_ok(n, disks) for item in valid_sources
             for n in item['numbers']):
        source_problem = MSG_SOURCE_BUS
    boot_disks = set(boot or [])

    destinos = []
    for position, raw in enumerate(raw_targets, start=1):
        entry = _read_volume(raw)
        if entry is None:
            label = _unit(raw.get('letter')) if isinstance(raw, dict) else None
            unidade = label or f'destino {position}'
            destinos.append({'unidade': unidade, 'veredito': DOUBT,
                             'motivo': MSG_DEST_BAD.format(unidade=unidade)})
            continue
        unidade = entry['unidade']
        # A shared disk number is a conclusive veto, even with other doubts.
        if entry['candidates'] & source_disks or any(
                item['unidade'] == unidade for item in valid_sources):
            verdict, reason = SAME_DISK, MSG_SAME
        elif entry['candidates'] & boot_disks:
            verdict, reason = DOUBT, MSG_BOOT
        elif source_problem is not None:
            verdict, reason = DOUBT, source_problem
        elif entry['status'] == 'blocked':
            verdict, reason = DOUBT, MSG_DEST_BLOCKED
        elif entry['status'] != ACCEPTED_TARGET_STATUS:
            verdict, reason = DOUBT, MSG_DEST_STATUS
        elif (entry['extent_status'] != 'observed_logical_only' or
              len(entry['numbers']) != 1):
            verdict, reason = DOUBT, MSG_DEST_BAD
        elif entry['crosscheck'] not in ACCEPTED_CROSSCHECK:
            verdict, reason = DOUBT, MSG_CROSS
        elif not _bus_ok(entry['numbers'][0], disks):
            verdict, reason = DOUBT, MSG_BUS
        else:
            verdict, reason = INDEPENDENT, MSG_OK
        destinos.append({'unidade': unidade, 'veredito': verdict,
                         'motivo': reason.format(unidade=unidade)})

    overall = max((item['veredito'] for item in destinos),
                  key=SEVERITY.__getitem__)
    if overall == INDEPENDENT:
        motivos = [MSG_ALL_OK]
    else:
        motivos = list(dict.fromkeys(
            item['motivo'] for item in destinos
            if item['veredito'] != INDEPENDENT))
    return {'veredito': overall, 'motivos': motivos, 'destinos': destinos}


def judge_physical_disks(safety_report, disks):
    """Judge whether each destination is on a different disk than the sources.

    ``safety_report`` is the dict returned by
    ``drive_safety_report.inspect_fresh_drive_safety``; ``disks`` is the
    Get-Disk list from the same inventory. Returns
    ``{'veredito', 'motivos', 'destinos': [{'unidade', 'veredito', 'motivo'}]}``.
    Never raises: anything unexpected becomes 'duvida'.
    """
    try:
        return _judge(safety_report, disks)
    except Exception:  # noqa: BLE001 - malformed input must never crash
        return _doubt_result(MSG_REPORT_BAD)


_TITLES = {
    INDEPENDENT: 'Discos separados: os destinos ficam em outros discos.',
    SAME_DISK: 'Atenção: um destino fica no mesmo disco da origem.',
    DOUBT: 'Não deu para confirmar que os discos são separados.',
}
_SHORT = {
    INDEPENDENT: 'disco separado',
    SAME_DISK: 'mesmo disco da origem',
    DOUBT: 'não confirmado',
}


def format_verdict_pt(result):
    """Plain Portuguese text for the verdict. Never raises."""
    if not isinstance(result, dict) or result.get('veredito') not in SEVERITY:
        result = _doubt_result(MSG_REPORT_BAD)
    lines = [_TITLES[result['veredito']]]
    destinos = result.get('destinos')
    if isinstance(destinos, list):
        for item in destinos:
            if not isinstance(item, dict):
                continue
            verdict = item.get('veredito')
            unidade = _unit(item.get('unidade')) or 'destino'
            lines.append(f'- {unidade} {_SHORT.get(verdict, _SHORT[DOUBT])}')
    motivos = result.get('motivos')
    if isinstance(motivos, list) and motivos:
        lines.append('Por quê:')
        lines.extend(f'- {text}' for text in motivos if isinstance(text, str))
    if result['veredito'] != INDEPENDENT:
        lines.append('Por segurança, escolha um destino em outro disco ou '
                     'confira os discos antes de copiar.')
    lines.append(MSG_READ_ONLY)
    return '\n'.join(lines)
