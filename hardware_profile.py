"""P3-01: perfil de hardware a partir do inventário que o app já leu.

Funções puras: não executam comandos, não acessam registro nem disco e não
importam outros módulos do projeto. Toda entrada estranha vira "desconhecido",
nunca exceção. O perfil não guarda número de série, nome do PC, usuário,
caminhos, placa-mãe nem BIOS.

Limites fixos (escolha mais segura, documentada em docs/BACKLOG.md):
- alto desempenho: GPU dedicada + 16 threads ou mais + 32 GiB ou mais;
- gamer: GPU dedicada + 6 núcleos ou mais + 16 GiB ou mais;
- intermediário: 4 núcleos ou mais + 8 GiB ou mais;
- básico: o resto.
Sem CPU ou RAM legível a classe é "indefinido"; notebook vem antes da potência.

Fatia 2: discos (Get-PhysicalDisk), gabinete e bateria (notebook x desktop) e
dual channel confirmado só quando o Windows diz o canal ("Channel A/B").
"""
from __future__ import annotations

import math
import re

GIB = 1024 ** 3
UNKNOWN = 'desconhecido'

TIER_LABELS = {
    'basico': 'básico',
    'intermediario': 'intermediário',
    'gamer': 'gamer',
    'alto_desempenho': 'alto desempenho',
    'notebook': 'notebook',
    'indefinido': 'indefinido',
}

_BASIC_ADAPTER = re.compile(r'basic (display|render)', re.I)
_DEDICATED = re.compile(r'geforce|\brtx\b|\bgtx\b|quadro|radeon\s*(\(tm\)\s*)?(rx|pro)\b'
                        r'|\barc\s*(\(tm\)\s*)?[ab]\d{2,3}', re.I)
_INTEGRATED = re.compile(r'uhd|\bhd graphics|iris|vega|radeon\s*(\(tm\)\s*)?graphics', re.I)
_CHANNEL = re.compile(r'channel\s*[-_]?\s*([a-h])(?![a-z])', re.I)

SCAN_CONFIRMATION = (
    'O app vai ler informações deste PC: processador, memória RAM, placa de vídeo, '
    'discos (tipo e tamanho), gabinete e bateria (para saber se é notebook ou PC de mesa) '
    'e a versão do Windows.\n\n'
    'É só leitura: nada é alterado, apagado ou instalado. Pode levar alguns segundos.\n\n'
    'Deseja continuar?'
)

NOTEBOOK_CHASSIS = frozenset({8, 9, 10, 14, 30, 31, 32})
DESKTOP_CHASSIS = frozenset({3, 4, 5, 6, 7, 15, 16, 35, 36})

DISK_NVME = 'NVMe'
DISK_SSD = 'SSD'
DISK_HDD = 'HDD'
DISK_EXTERNAL = 'externo/virtual'
DISK_TYPE_LABELS = {
    DISK_NVME: 'NVMe (SSD rápido)',
    DISK_SSD: 'SSD',
    DISK_HDD: 'HD (disco mecânico)',
    DISK_EXTERNAL: 'externo ou virtual',
    UNKNOWN: 'tipo não identificado',
}
# Get-PhysicalDisk: BusType numérico -> nome curto; só estes nomes saem no perfil.
_BUS_NAMES = {1: 'SCSI', 3: 'ATA', 4: '1394', 6: 'Fibre Channel', 7: 'USB', 8: 'RAID',
              9: 'iSCSI', 10: 'SAS', 11: 'SATA', 12: 'SD', 14: 'virtual', 15: 'virtual',
              16: 'Spaces', 17: 'NVMe'}
_BUS_TEXT = {'scsi': 'SCSI', 'ata': 'ATA', '1394': '1394', 'fibre channel': 'Fibre Channel',
             'usb': 'USB', 'raid': 'RAID', 'iscsi': 'iSCSI', 'sas': 'SAS',
             'sata': 'SATA', 'sd': 'SD', 'virtual': 'virtual', 'file backed virtual': 'virtual',
             'storage spaces': 'Spaces', 'spaces': 'Spaces', 'nvme': 'NVMe'}
# Externo, de rede ou virtual: nunca vira SSD/NVMe, mesmo que o MediaType diga SSD.
_EXTERNAL_BUSES = frozenset({'USB', 'virtual', 'Spaces', '1394', 'Fibre Channel', 'iSCSI'})
_MEDIA_NUMBERS = {3: DISK_HDD, 4: DISK_SSD}
_MEDIA_TEXT = {'hdd': DISK_HDD, 'ssd': DISK_SSD}

BATTERY_ONLY_WARNING = ('Aviso: só a bateria indicou notebook; se este é um PC de mesa com nobreak (UPS) '
                        'ligado por USB, o app o trata como notebook por cuidado.')

_PATHLIKE = re.compile(r'[a-z]:[\\/]|\\\\|[\\/](users|home)[\\/]|\\', re.I)


def _items(value):
    """Lista de dicionários; qualquer outra coisa é descartada."""
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _num(value):
    """Número positivo e finito; bool, texto, negativos, NaN e infinito viram None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if value > 0 else None


def _text(value, limit=100):
    """Texto curto e sem cara de caminho; senão None."""
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    if not value or _PATHLIKE.search(value):
        return None
    return value[:limit]


def is_dedicated_gpu(name):
    """True = placa de vídeo dedicada, False = integrada/genérica, None = não sei."""
    if not isinstance(name, str):
        return None
    if not name.strip() or _BASIC_ADAPTER.search(name):
        return False
    if _DEDICATED.search(name):
        return True
    if _INTEGRATED.search(name):
        return False
    return None


def _cpu(hardware):
    entries = _items(hardware.get('cpu'))
    cores = [_num(item.get('NumberOfCores')) for item in entries]
    threads = [_num(item.get('NumberOfLogicalProcessors')) for item in entries]
    names = [_text(item.get('Name')) for item in entries]
    total_cores = int(sum(cores)) if cores and all(cores) else None
    total_threads = int(sum(threads)) if threads and all(threads) else None
    if total_threads is not None and total_cores is not None and total_threads < total_cores:
        total_threads = None
    return {'name': next((n for n in names if n), None), 'cores': total_cores, 'threads': total_threads}


def _gpus(hardware):
    gpus = []
    for item in _items(hardware.get('gpu')):
        name = _text(item.get('Name'))
        gpus.append({'name': name, 'dedicated': is_dedicated_gpu(name) if name else None})
    return gpus


def _channel(entry):
    """Letra do canal só quando DeviceLocator/BankLabel diz "Channel X"; senão None."""
    for key in ('DeviceLocator', 'BankLabel'):
        value = entry.get(key)
        if isinstance(value, str):
            found = _CHANNEL.search(value)
            if found:
                return found.group(1).upper()
    return None


def _dual_channel(entries):
    """Texto do dual channel; "sim (confirmado)" só com prova explícita de 2 canais."""
    entries = _items(entries)
    capacities = [_num(item.get('Capacity')) for item in entries]
    valid = [c for c in capacities if c]
    if not entries or len(valid) != len(entries):
        return UNKNOWN
    if len(valid) == 1:
        return 'não (1 módulo)'
    if len(set(valid)) != 1:
        return 'não confirmado (módulos de tamanhos diferentes)'
    channels = [_channel(item) for item in entries]
    if all(channels) and len(set(channels)) >= 2:
        return 'sim (confirmado)'
    if all(channels):  # todos com canal e todos o mesmo: o dado lido aponta o contrário (R-26)
        return 'não confirmado (módulos no mesmo canal)'
    return 'provável (não confirmado)'


def _ram(hardware):
    entries = _items(hardware.get('ram'))
    capacities = [_num(item.get('Capacity')) for item in entries]
    valid = [c for c in capacities if c]
    total = round(sum(valid) / GIB, 1) if valid and len(valid) == len(entries) else None
    if total is not None and total == int(total):
        total = int(total)
    speeds = [int(s) for s in (_num(item.get('ConfiguredClockSpeed')) for item in entries) if s]
    return {'total_gib': total, 'modules': len(valid) if total is not None else None,
            'configured_mts': min(speeds) if speeds else None, 'dual_channel': _dual_channel(entries)}


def _code(value):
    """Código inteiro (enum do Windows); bool, NaN, frações e negativos viram None."""
    number = _num(value)
    if number is None or number != int(number):
        return None
    return int(number)


def _bus(value):
    code = _code(value)
    if code is not None:
        return _BUS_NAMES.get(code)
    if isinstance(value, str):
        return _BUS_TEXT.get(' '.join(value.split()).lower())
    return None


def _media(value):
    code = _code(value)
    if code is not None:
        return _MEDIA_NUMBERS.get(code)
    if isinstance(value, str):
        return _MEDIA_TEXT.get(value.strip().lower())
    return None


def _disks(hardware):
    """Discos físicos (linhas de Get-PhysicalDisk) -> [{type, bus, size_gib}].

    Só tipo, barramento e tamanho saem daqui: número de série e nome do disco nunca.
    """
    if not isinstance(hardware, dict):
        return []
    disks = []
    for item in _items(hardware.get('disks')):
        bus = _bus(item.get('BusType'))
        media = _media(item.get('MediaType'))
        if bus in _EXTERNAL_BUSES:
            kind = DISK_EXTERNAL
        elif bus == 'NVMe':
            kind = DISK_NVME
        elif media:
            kind = media
        else:
            kind = UNKNOWN
        size = _num(item.get('Size'))
        size_gib = round(size / GIB, 1) if size else None
        if not size_gib:  # menos de 0,05 GiB: dado sem sentido
            size_gib = None
        if size_gib is not None and size_gib == int(size_gib):
            size_gib = int(size_gib)
        disks.append({'type': kind, 'bus': bus, 'size_gib': size_gib})
    return disks


def _chassis_types(hardware):
    """Códigos de gabinete (Win32_SystemEnclosure.ChassisTypes) válidos."""
    codes = []
    for item in _items(hardware.get('chassis')):
        value = item.get('ChassisTypes')
        values = value if isinstance(value, list) else [value]
        codes.extend(c for c in (_code(v) for v in values) if c is not None)
    return codes


def _battery(hardware):
    """True = tem bateria, False = o Windows não listou bateria, None = não sei."""
    if 'battery' not in hardware:
        return None
    value = hardware.get('battery')
    if value is None or value == []:
        return False
    if isinstance(value, dict):
        return True
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return True
    return None


def _form_factor(hardware):
    entries = _items(hardware.get('pc'))
    kind = _code(entries[0].get('PCSystemType')) if entries else None
    chassis = _chassis_types(hardware)
    battery = _battery(hardware)
    if kind == 2 or any(c in NOTEBOOK_CHASSIS for c in chassis) or battery is True:
        return 'notebook'
    if (kind in (1, 3) and chassis and all(c in DESKTOP_CHASSIS for c in chassis)
            and battery is False):
        return 'desktop'
    return UNKNOWN


def _notebook_by_battery_only(hardware):
    """True quando só a bateria fez o PC virar notebook (pode ser um nobreak USB)."""
    if not isinstance(hardware, dict) or _form_factor(hardware) != 'notebook':
        return False
    entries = _items(hardware.get('pc'))
    kind = _code(entries[0].get('PCSystemType')) if entries else None
    if kind == 2 or any(c in NOTEBOOK_CHASSIS for c in _chassis_types(hardware)):
        return False
    return _battery(hardware) is True


def _windows(hardware):
    entries = _items(hardware.get('os'))
    first = entries[0] if entries else {}
    return {'caption': _text(first.get('Caption')), 'version': _text(first.get('Version'), 40),
            'build': _text(first.get('BuildNumber'), 20)}


def classify(profile):
    """Devolve (classe, motivos) a partir de um perfil de build_profile."""
    if not isinstance(profile, dict):
        return 'indefinido', ['Não há dados do PC para classificar.']
    cpu = profile.get('cpu') if isinstance(profile.get('cpu'), dict) else {}
    ram = profile.get('ram') if isinstance(profile.get('ram'), dict) else {}
    gpus = profile.get('gpus') if isinstance(profile.get('gpus'), list) else []
    cores = _num(cpu.get('cores'))
    threads = _num(cpu.get('threads')) or cores
    total = _num(ram.get('total_gib'))
    missing = []
    if not cores:
        missing.append('processador')
    if not total:
        missing.append('memória RAM')
    if missing:
        return 'indefinido', ['Não consegui ler: ' + ' e '.join(missing) + '. Por segurança, sem classificação.']
    if profile.get('form_factor') == 'notebook':
        return 'notebook', ['O Windows informa que este PC é um notebook: bateria e calor vêm antes do desempenho.']
    dedicated = any(isinstance(g, dict) and g.get('dedicated') is True for g in gpus)
    reasons = [f'Processador com {int(cores)} núcleos e {int(threads)} threads.',
               f'{total:g} GiB de memória RAM.',
               'Tem placa de vídeo dedicada.' if dedicated else 'Não encontrei placa de vídeo dedicada.']
    if dedicated and threads >= 16 and total >= 32:
        return 'alto_desempenho', reasons + ['Passa dos limites de alto desempenho (16 threads e 32 GiB).']
    if dedicated and cores >= 6 and total >= 16:
        return 'gamer', reasons + ['Passa dos limites de PC gamer (6 núcleos e 16 GiB).']
    if cores >= 4 and total >= 8:
        return 'intermediario', reasons + ['Bom para uso geral (4 núcleos e 8 GiB ou mais).']
    return 'basico', reasons + ['Abaixo de 4 núcleos ou de 8 GiB: PC de uso básico.']


def build_profile(hardware):
    """Monta o perfil a partir de optimization_engine.inspect_pc()['hardware']."""
    if not isinstance(hardware, dict):
        hardware = {}
    profile = {
        'cpu': _cpu(hardware),
        'gpus': _gpus(hardware),
        'ram': _ram(hardware),
        'form_factor': _form_factor(hardware),
        'battery_only_notebook': _notebook_by_battery_only(hardware),
        'windows': _windows(hardware),
        'disks': _disks(hardware),
    }
    unknown = []
    if profile['cpu']['cores'] is None:
        unknown.append('cpu')
    if not profile['gpus'] or all(g['dedicated'] is None for g in profile['gpus']):
        unknown.append('gpu')
    if profile['ram']['total_gib'] is None:
        unknown.append('ram')
    if profile['form_factor'] == UNKNOWN:
        unknown.append('form_factor')
    if profile['windows']['caption'] is None:
        unknown.append('windows')
    if not profile['disks']:
        unknown.append('disks')
    profile['unknown'] = unknown
    profile['tier'], profile['reasons'] = classify(profile)
    return profile


def _show(value, suffix=''):
    return f'{value}{suffix}' if value not in (None, '') else 'não disponível'


def profile_lines(profile):
    """Linhas em português simples para a aba de diagnóstico."""
    if not isinstance(profile, dict):
        profile = {}
    cpu = profile.get('cpu') if isinstance(profile.get('cpu'), dict) else {}
    ram = profile.get('ram') if isinstance(profile.get('ram'), dict) else {}
    win = profile.get('windows') if isinstance(profile.get('windows'), dict) else {}
    gpus = profile.get('gpus') if isinstance(profile.get('gpus'), list) else []
    tier = profile.get('tier') if profile.get('tier') in TIER_LABELS else 'indefinido'
    reasons = profile.get('reasons') if isinstance(profile.get('reasons'), list) else []
    form = {'notebook': 'notebook', 'desktop': 'computador de mesa'}.get(profile.get('form_factor'), 'não identificado')
    lines = ['PERFIL DO SEU PC',
             f"  Processador: {_show(cpu.get('name'))} | {_show(cpu.get('cores'), ' núcleos')}"
             f" | {_show(cpu.get('threads'), ' threads')}"]
    if gpus:
        for gpu in gpus:
            gpu = gpu if isinstance(gpu, dict) else {}
            kind = {True: 'dedicada', False: 'integrada'}.get(gpu.get('dedicated'), 'tipo não identificado')
            lines.append(f"  Placa de vídeo: {_show(gpu.get('name'))} ({kind})")
    else:
        lines.append('  Placa de vídeo: não disponível')
    lines.extend([
        f"  Memória RAM: {_show(ram.get('total_gib'), ' GiB')} | velocidade configurada "
        f"{_show(ram.get('configured_mts'), ' MT/s')} | dual channel: {_show(ram.get('dual_channel'))}",
    ])
    disks = profile.get('disks') if isinstance(profile.get('disks'), list) else []
    if disks:
        for disk in disks:
            disk = disk if isinstance(disk, dict) else {}
            kind = DISK_TYPE_LABELS.get(disk.get('type'), DISK_TYPE_LABELS[UNKNOWN])
            lines.append(f"  Disco: {kind} | {_show(disk.get('size_gib'), ' GiB')}")
    else:
        lines.append('  Discos: não disponível')
    lines.extend([
        f'  Tipo de PC: {form}',
    ])
    if profile.get('battery_only_notebook') is True:
        lines.append(f'  {BATTERY_ONLY_WARNING}')
    lines.extend([
        f"  Windows: {_show(win.get('caption'))}" + (f" (versão {win['version']})" if win.get('version') else ''),
        f'  Classe: {TIER_LABELS[tier]}',
    ])
    lines.extend('    - ' + str(reason) for reason in reasons if isinstance(reason, str))
    lines.append('')
    return lines
