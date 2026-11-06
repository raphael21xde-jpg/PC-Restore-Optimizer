"""P3-02: medição do PC antes e depois dos ajustes (só leitura, sem administrador).

Mede em cerca de 1 minuto: uso médio do processador, memória em uso, número de
processos, quantos programas abrem com o Windows (só a contagem, sem nomes) e o
plano de energia ativo. Guarda as medições em ``otimizacao-medicoes.json`` (no
máximo 50) e compara a última ANTES com a última DEPOIS.

A medição é descritiva: mostra como o PC estava em cada momento, não prova que
um ajuste causou a diferença. Dado ausente ou ilegível é ``None`` (nunca um 0
inventado) e aparece como "sem dado"; nada é concluído a partir dele.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import atomic_write_text, exclusive_lock
from security_checkup import RUN_KEYS, _as_list, _clean_name, _env

MEASURE_FILE = 'otimizacao-medicoes.json'
SCHEMA = 'pcro-measure-1'
PHASES = ('antes', 'depois')
MAX_MEASURES = 50
MEASURE_SAMPLES = 12
MEASURE_INTERVAL = 5
MEASURE_TIMEOUT = 180
METRICS = ('cpu', 'memory', 'processes', 'startup', 'power_plan')
MAX_PLAN_NAME = 80

MEASURE_CONFIRMATION = (
    'O app vai medir o PC por cerca de 1 minuto: uso do processador, memória em uso, '
    'quantos programas estão abertos, quantos abrem com o Windows e o plano de energia.\n\n'
    'Só lê: nada é mudado. Não use o PC durante a medição (o resultado fica mais justo).\n\n'
    'Continuar?')
MEASURE_FAILED = 'Não foi possível medir o PC. Nada foi mudado.'
MEASURE_WARNING = ('A medição mostra como o PC estava em cada momento; não prova que um ajuste causou '
                   'a diferença. Meça nas mesmas condições (mesmos programas abertos).')
MISSING_BEFORE = 'Falta a medição ANTES: clique em "Medir ANTES (1 min)" antes de aplicar os ajustes.'
MISSING_AFTER = 'Falta a medição DEPOIS: depois de aplicar os ajustes, clique em "Medir DEPOIS (1 min)".'
NO_DATA = 'sem dado'
LABELS = {
    'cpu': 'Uso do processador (média)',
    'memory': 'Memória em uso',
    'processes': 'Processos abertos',
    'startup': 'Programas que abrem com o Windows',
    'power_plan': 'Plano de energia',
}


class MeasureError(Exception):
    """Falha da medição, sempre com a mesma mensagem (nunca o texto do Windows)."""

    def __init__(self):
        super().__init__(MEASURE_FAILED)


# Só leitura (Get-CimInstance, Get-ItemProperty, Get-ChildItem), sem administrador.
# Cada parte tem seu try: uma parte que falha vira null e não derruba as outras.
# CPU: 12 leituras de _Total com 5 s entre elas; a primeira é descartada na
# análise (costuma vir zerada). Inicialização: só a CONTAGEM das entradas das
# chaves Run/RunOnce e dos arquivos das pastas de Inicialização (nomes não saem);
# se alguma parte não puder ser lida, a contagem inteira vira null.
# Plano de energia: só o nome do plano ativo (Win32_PowerPlan, sem powercfg).
_CPU_CLASS = 'Win32_PerfFormattedData_PerfOS_Processor'
MEASURE_QUERY = (
    "$q=\"Name='_Total'\"; $cpu=@(); "
    'for($i=0; $i -lt ' + str(MEASURE_SAMPLES) + '; $i++){ '
    'if($i -gt 0){ Start-Sleep ' + str(MEASURE_INTERVAL) + ' }; '
    'try{ $c=Get-CimInstance ' + _CPU_CLASS + ' -Filter $q -Property PercentProcessorTime -ErrorAction Stop; '
    'if($c){ $cpu+=[double]$c.PercentProcessorTime } }catch{} }; '
    '$free=$null; $total=$null; '
    'try{ $os=Get-CimInstance Win32_OperatingSystem -Property FreePhysicalMemory,TotalVisibleMemorySize '
    '-ErrorAction Stop; $free=[double]$os.FreePhysicalMemory; $total=[double]$os.TotalVisibleMemorySize }catch{}; '
    '$procs=$null; '
    'try{ $procs=@(Get-CimInstance Win32_Process -Property ProcessId -ErrorAction Stop).Count }catch{}; '
    "$skip=@('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider'); "
    '$keys=@(' + ','.join("'" + key + "'" for key in RUN_KEYS) + '); $start=0; '
    'try{ foreach($k in $keys){ if(Test-Path -LiteralPath $k){ '
    '$p=Get-ItemProperty -LiteralPath $k -ErrorAction Stop; '
    '$start+=@($p.PSObject.Properties | Where-Object { $skip -notcontains $_.Name }).Count } }; '
    "foreach($d in @([Environment]::GetFolderPath('Startup'),[Environment]::GetFolderPath('CommonStartup'))){ "
    'if($d -and (Test-Path -LiteralPath $d)){ '
    "$start+=@(Get-ChildItem -LiteralPath $d -File -Force -ErrorAction Stop | "
    "Where-Object { $_.Name -ne 'desktop.ini' }).Count } } }catch{ $start=$null }; "
    '$plan=$null; '
    "try{ $w=Get-CimInstance -Namespace 'root\\cimv2\\power' -ClassName Win32_PowerPlan "
    "-Filter 'IsActive=True' -ErrorAction Stop | Select-Object -First 1; "
    'if($w){ $plan=[string]$w.ElementName } }catch{}; '
    'ConvertTo-Json -InputObject ([pscustomobject]@{Cpu=$(if($cpu.Count){$cpu}else{$null});'
    'Free=$free;Total=$total;Procs=$procs;Startup=$start;Plan=$plan}) -Depth 3 -Compress')


def _number(value):
    """Número finito (não bool), ou None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _percent(value):
    value = _number(value)
    return value if value is not None and 0 <= value <= 100 else None


def _count(value, minimum):
    value = _number(value)
    if value is None or value != int(value) or value < minimum:
        return None
    return int(value)


def _plan_name(value, env):
    """Nome do plano limpo; texto com cara de caminho (\\ ou /) nunca é guardado."""
    if not isinstance(value, str) or '\\' in value or '/' in value:
        return None
    name = _clean_name(value, env)
    return name[:MAX_PLAN_NAME + 3] or None


def _clean_values(values, env=None):
    """Confere de novo cada valor (guardado ou lido). Ilegível = None (R-32)."""
    values = values if isinstance(values, dict) else {}
    cpu = _percent(values.get('cpu'))
    memory = _percent(values.get('memory'))
    return {
        'cpu': None if cpu is None else int(cpu + 0.5),
        'memory': None if memory is None else int(memory + 0.5),
        'processes': _count(values.get('processes'), 1),
        'startup': _count(values.get('startup'), 0),
        'power_plan': _plan_name(values.get('power_plan'), _env(env)),
    }


def parse_measure(dados, env=None):
    """Dados da consulta -> dict com números (ou None). Nunca levanta erro.

    CPU: descarta a primeira leitura; sem leitura válida, ou todas em 0, = None
    (a leitura pode ter falhado, como no uso parado do check-up). Memória: % em uso.
    """
    rows = _as_list(dados)
    data = rows[0] if rows and isinstance(rows[0], dict) else {}
    samples = data.get('Cpu')
    samples = samples if isinstance(samples, list) else []
    found = [v for v in (_percent(s) for s in samples[1:]) if v is not None]
    cpu = sum(found) / len(found) if found and any(found) else None
    free, total = _number(data.get('Free')), _number(data.get('Total'))
    memory = None
    if free is not None and total is not None and total > 0 and 0 <= free <= total:
        memory = 100 * (total - free) / total
    return _clean_values({'cpu': cpu, 'memory': memory, 'processes': data.get('Procs'),
                          'startup': data.get('Startup'), 'power_plan': data.get('Plan')}, env)


def read_measure(ps=None, env=None):
    """Mede (só leitura, ~1 minuto). Falha ou nenhum dado = MeasureError genérico (R-07)."""
    if ps is None:
        from optimization_engine import _ps  # noqa: PLC0415 - preguiçoso de propósito

        def ps(code):
            return _ps(code, timeout=MEASURE_TIMEOUT)
    try:
        data = ps(MEASURE_QUERY)
    except Exception:  # noqa: BLE001 - R-07: a mensagem original não é guardada
        raise MeasureError() from None
    result = parse_measure(data, env)
    if all(result[key] is None for key in METRICS):
        raise MeasureError()
    return result


def _empty():
    return {'schema': SCHEMA, 'measures': []}


def read_measures(path):
    """Histórico guardado. Arquivo que não existe = vazio; ilegível = ValueError."""
    path = Path(path)
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Histórico de medições ilegível; nenhuma alteração.') from exc
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or not isinstance(data.get('measures'), list):
        raise ValueError('Histórico de medições desconhecido; nenhuma alteração.')
    return data


def save_measure(path, phase, medida, env=None):
    """Acrescenta uma medição (com a hora em UTC) e guarda só as 50 mais novas.

    Gravação atômica dentro de uma trava; o histórico é relido dentro da trava.
    Só os valores conferidos entram no arquivo (nada de caminho nem nome de usuário).
    """
    if phase not in PHASES:
        raise ValueError('Fase inválida.')
    path = Path(path)
    entry = {'phase': phase, 'at': datetime.now(timezone.utc).isoformat(),
             'values': _clean_values(medida, env)}
    try:
        with exclusive_lock(path):
            data = read_measures(path)
            data['measures'].append(entry)
            data['measures'] = data['measures'][-MAX_MEASURES:]
            atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    except TimeoutError as exc:
        raise ValueError('Histórico de medições em uso por outra janela; nenhuma alteração.') from exc
    return data


def _when(entry):
    """Hora da medição (com fuso), ou None se ilegível."""
    at = entry.get('at')
    if not isinstance(at, str):
        return None
    try:
        when = datetime.fromisoformat(at)
    except ValueError:
        return None
    return when if when.utcoffset() is not None else None


def _latest(entries, phase, after=None):
    best = None
    for when, entry in entries:
        if entry.get('phase') != phase or (after is not None and when <= after):
            continue
        if best is None or when >= best[0]:
            best = (when, entry)
    return best


def _difference(key, before, after):
    if key == 'power_plan':
        return '(igual)' if before == after else '(mudou)'
    delta = after - before
    unit = ' pontos' if key in ('cpu', 'memory') else ''
    if delta == 0:
        return '(igual)'
    if key in ('cpu', 'memory') and abs(delta) == 1:
        unit = ' ponto'
    return f'({abs(delta)}{unit} a {"menos" if delta < 0 else "mais"})'


def _shown(key, value):
    return f'{value}%' if key in ('cpu', 'memory') else str(value)


def compare_measures(historico, env=None):
    """Linhas de texto: a última ANTES contra a última DEPOIS feita depois dela.

    Métrica que falta em um dos lados = "sem dado" (nunca conclui nada). Sem
    ANTES ou sem DEPOIS, diz o que falta. O aviso fixo sempre aparece.
    """
    raw = historico.get('measures') if isinstance(historico, dict) else None
    entries = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get('phase'), str):
            when = _when(entry)
            if when is not None:
                entries.append((when, entry))
    lines = ['MEDIÇÃO ANTES E DEPOIS (só leitura)']
    before = _latest(entries, 'antes')
    after = _latest(entries, 'depois', before[0]) if before else None
    if before is None:
        lines.append(MISSING_BEFORE)
    if after is None:
        lines.append(MISSING_AFTER)
    if before is not None and after is not None:
        old = _clean_values(before[1].get('values'), env)
        new = _clean_values(after[1].get('values'), env)
        lines.append('ANTES: medido em ' + before[0].astimezone().strftime('%d/%m/%Y %H:%M'))
        lines.append('DEPOIS: medido em ' + after[0].astimezone().strftime('%d/%m/%Y %H:%M'))
        lines.append('')
        for key in METRICS:
            if old[key] is None or new[key] is None:
                lines.append(f'{LABELS[key]}: {NO_DATA}')
                continue
            lines.append(f'{LABELS[key]}: {_shown(key, old[key])} → {_shown(key, new[key])} '
                         + _difference(key, old[key], new[key]))
    elif before is not None:
        lines.append('ANTES: medido em ' + before[0].astimezone().strftime('%d/%m/%Y %H:%M'))
    lines += ['', MEASURE_WARNING]
    return lines
