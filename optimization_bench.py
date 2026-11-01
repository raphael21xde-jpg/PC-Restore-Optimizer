"""Offline, read-only benchmark CSV comparison for CapFrameX/OCAT-like exports.

A numeric FPS or frame-time column is required; unknown CSVs are rejected, never
silently interpreted as a performance measurement. Benchmarks are descriptive,
not proof of causal improvement.
"""
from __future__ import annotations
import csv
import io
import json
import math
from pathlib import Path
import re
from statistics import mean, median
from datetime import datetime, timezone
from atomic_write import atomic_write_text

FPS_KEYS = ('fps', 'framerate', 'framespersecond', 'avgfps', 'averagefps')
FT_KEYS = ('frametime', 'frametimems', 'msbetweenpresents', 'frametimeduration', 'msbetweenframestarts', 'presentdurationms')


def _column_key(raw):
    raw = raw.strip().replace('\ufeff','')
    return re.sub('[^a-z0-9]', '', raw.casefold().replace('μ', 'u'))


def _number(v):
    v = str(v).strip().strip('"')
    if not v:
        return None
    v = v.replace(' ', '').replace('\u00a0','')
    if ',' in v and '.' in v:
        v = v.replace('.', '').replace(',', '.') if v.rfind(',') > v.rfind('.') else v.replace(',', '')
    elif ',' in v:
        v = v.replace(',', '.')
    try:
        result = float(v)
        return result if math.isfinite(result) and result > 0 else None
    except ValueError:
        return None


def _percentile(values, percent):
    values = sorted(values)
    if not values:
        raise ValueError('Sem amostras.')
    rank = (len(values)-1) * percent / 100.0
    left = math.floor(rank)
    right = min(len(values)-1, left+1)
    return values[left] + (values[right]-values[left])*(rank-left)


def parse_benchmark_text(content: str):
    if len(content) > 25_000_000:
        raise ValueError('CSV muito grande (limite 25 MB).')
    if '\x00' in content:
        raise ValueError('Arquivo CSV inválido.')
    sample = content[:6000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ';' if sample.count(';') > sample.count(',') else ','
    rows = csv.reader(io.StringIO(content), delimiter=delimiter)
    try:
        header = next(rows)
    except StopIteration:
        raise ValueError('CSV vazio.')
    cols = [_column_key(c) for c in header]
    idx = next((i for i, c in enumerate(cols) if c in FT_KEYS), None)
    source = 'frametime_ms' if idx is not None else 'fps'
    if idx is None:
        idx = next((i for i, c in enumerate(cols) if c in FPS_KEYS), None)
    if idx is None:
        raise ValueError('Não reconheci uma coluna de FPS ou frametime. Exporte amostras por quadro do CapFrameX/OCAT.')
    values = []
    for row in rows:
        if idx >= len(row):
            continue
        number = _number(row[idx])
        if number is None:
            continue
        if source == 'frametime_ms':
            # reject impossible data rather than treating microseconds as milliseconds
            if not 0.2 <= number <= 2000:
                continue
            values.append(number)
        else:
            if 0.1 <= number <= 10000:
                values.append(number)
        if len(values) > 1_000_000:
            raise ValueError('CSV excedeu um milhão de quadros.')
    if len(values) < 30:
        raise ValueError('São necessárias pelo menos 30 amostras válidas.')
    if source == 'frametime_ms':
        fps = [1000/x for x in values]
        avg = 1000/mean(values)
        low1 = 1000/_percentile(values,99)
        low02 = 1000/_percentile(values,99.8)
    else:
        fps = values
        avg = mean(fps)
        low1 = _percentile(fps,1)
        low02 = _percentile(fps,0.2)
    return {'samples': len(values), 'column':header[idx], 'source':source,
            'avg_fps': round(avg,2), 'low_1': round(low1,2),
            'low_02': round(low02,2), 'min_fps': round(min(fps),2), 'max_fps': round(max(fps),2)}


def parse_csv_file(path):
    path = Path(path)
    if path.stat().st_size > 25_000_000:
        raise ValueError('Arquivo maior que 25 MB.')
    data = path.read_bytes()
    for encoding in ('utf-8-sig','utf-16','cp1252'):
        try:
            content = data.decode(encoding)
            return parse_benchmark_text(content)
        except UnicodeDecodeError:
            pass
    raise ValueError('Não consegui ler a codificação do arquivo CSV.')


def insert_run(journal: Path, scenario: str, phase: str, metrics: dict):
    journal=Path(journal)
    scenario=' '.join(scenario.strip().split())
    if not scenario or len(scenario)>100:
        raise ValueError('Identifique o jogo e o cenário (até 100 caracteres).')
    if phase not in ('antes','depois'):
        raise ValueError('Fase inválida.')
    try:
        data=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {'schema':'pcro-bench-1','runs':[]}
    except (OSError,ValueError) as exc:
        raise ValueError('Histórico de benchmarks ilegível; nenhuma alteração.') from exc
    if data.get('schema')!='pcro-bench-1' or not isinstance(data.get('runs'),list):
        raise ValueError('Histórico desconhecido; nenhuma alteração.')
    data['runs'].append({'scenario': scenario, 'phase': phase, 'metrics': metrics,
                         'timestamp':datetime.now(timezone.utc).isoformat()})
    # FIX-P3-06-07: temporário de nome único, apagado se a gravação falhar.
    atomic_write_text(journal, json.dumps(data,ensure_ascii=False,indent=2))
    return data


def summarize(data: dict, scenario: str):
    runs = data.get('runs',[])
    groups = {key:[r['metrics'] for r in runs if r.get('scenario')==scenario and r.get('phase')==key]
              for key in ('antes','depois')}
    result = {'scenario':scenario, 'count':{k:len(v) for k,v in groups.items()}, 'median':{},'delta_pct':{}}
    for key, group in groups.items():
        if group:
            result['median'][key]={col:round(median([r[col] for r in group]),2)
                                   for col in ('avg_fps','low_1','low_02')}
    if groups['antes'] and groups['depois']:
        for col in ('avg_fps','low_1','low_02'):
            base=result['median']['antes'][col]
            if base>0:
                result['delta_pct'][col]=round(100*(result['median']['depois'][col]/base-1),2)
    result['sufficient_repeats']=len(groups['antes'])>=3 and len(groups['depois'])>=3
    return result


def read_history(path):
    path=Path(path)
    if not path.exists():
        return {'schema':'pcro-bench-1','runs':[]}
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='pcro-bench-1':
        raise ValueError('Histórico de benchmarks desconhecido.')
    return data
