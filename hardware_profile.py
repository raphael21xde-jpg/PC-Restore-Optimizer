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


def _ram(hardware):
    entries = _items(hardware.get('ram'))
    capacities = [_num(item.get('Capacity')) for item in entries]
    valid = [c for c in capacities if c]
    total = round(sum(valid) / GIB, 1) if valid and len(valid) == len(entries) else None
    if total is not None and total == int(total):
        total = int(total)
    speeds = [int(s) for s in (_num(item.get('ConfiguredClockSpeed')) for item in entries) if s]
    if not entries or len(valid) != len(entries):
        dual = UNKNOWN
    elif len(valid) == 1:
        dual = 'não (1 módulo)'
    elif len(set(valid)) == 1:
        dual = 'provável (não confirmado)'
    else:
        dual = 'não confirmado (módulos de tamanhos diferentes)'
    return {'total_gib': total, 'modules': len(valid) if total is not None else None,
            'configured_mts': min(speeds) if speeds else None, 'dual_channel': dual}


def _form_factor(hardware):
    entries = _items(hardware.get('pc'))
    kind = _num(entries[0].get('PCSystemType')) if entries else None
    if kind == 2:
        return 'notebook'
    if kind in (1, 3):
        return 'desktop'
    return UNKNOWN


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
        'windows': _windows(hardware),
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
        f'  Tipo de PC: {form}',
        f"  Windows: {_show(win.get('caption'))}" + (f" (versão {win['version']})" if win.get('version') else ''),
        f'  Classe: {TIER_LABELS[tier]}',
    ])
    lines.extend('    - ' + str(reason) for reason in reasons if isinstance(reason, str))
    lines.append('')
    return lines
