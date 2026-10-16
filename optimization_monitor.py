"""Read-only monitoring of GPU via NVIDIA SMI and MSI Afterburner .hml history.

No driver hacks, fan/voltage/clock changes, injection, elevated privileges or
use of undocumented binary shared-memory layouts. Afterburner must itself be
configured to log history. Samples are periodic, not per-frame benchmark data.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time

KEYS = ('cpu_temp_c', 'gpu_temp_c', 'cpu_usage_pct', 'gpu_usage_pct',
        'gpu_power_w', 'cpu_power_w', 'vram_used_mb', 'fps_sampled', 'frametime_sampled_ms')
LABELS = {'cpu_temp_c':'CPU °C','gpu_temp_c':'GPU °C',
          'cpu_usage_pct':'CPU %','gpu_usage_pct':'GPU %',
          'gpu_power_w':'GPU W','cpu_power_w':'CPU W','vram_used_mb':'VRAM MiB',
          'fps_sampled':'FPS amostrado','frametime_sampled_ms':'Frametime amostrado ms'}


def numeric(value):
    """Return finite numeric reading, without treating N/A as zero."""
    t = str(value).strip().strip('"').replace('\xa0', ' ')
    if not t or t.lower() in ('n/a','na','none','nan','not supported','-'):
        return None
    t = re.sub(r'(?i)\s*(?:°c|c|%|w|watts|mib|mhz|ms|fps)\s*$', '', t).strip()
    if t.count(',') == 1 and '.' not in t:
        t = t.replace(',', '.')
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def metric_from_name(name):
    """Explicit sensor matching; avoid mislabeling GPU hotspot as GPU core."""
    s = re.sub(r'\s+', ' ', str(name).strip().casefold())
    localized={'temperatura da cpu':'CPU temperature',
               'temperatura do processador':'CPU temperature',
               'temperatura da gpu':'GPU temperature',
               'temperatura da placa de vídeo':'GPU temperature',
               'uso da gpu':'GPU usage','uso da cpu':'CPU usage',
               'potência da gpu':'GPU power','consumo da gpu':'GPU power',
               'taxa de quadros':'Framerate'}
    s=localized.get(s,s).casefold()
    if any(x in s for x in ('hotspot', 'hot spot', 'junction', 'memory temperature')):
        return None
    if re.search(r'\bcpu\b.*(temperature|temp)', s) or s in ('cpu package', 'cpu (tctl/tdie)', 'tctl/tdie'):
        return 'cpu_temp_c'
    if re.search(r'\bgpu\d*\b.*(temperature|temp)', s):
        return 'gpu_temp_c'
    if re.search(r'\bcpu\b.*(usage|utilization)', s) and not re.search(r'cpu\s*\d+',s):
        return 'cpu_usage_pct'
    if re.search(r'\bgpu\d*\b.*(usage|utilization)', s) and 'memory' not in s:
        return 'gpu_usage_pct'
    if re.search(r'\bgpu\d*\b.*(power|watt)',s) or s == 'power (gpu)':
        return 'gpu_power_w'
    if re.search(r'\bcpu\b.*(power|watt)',s):
        return 'cpu_power_w'
    if (('memory usage' in s or 'vram' in s) and ('gpu' in s or 'vram' in s)):
        return 'vram_used_mb'
    if s in ('framerate','frame rate','fps','framerate avg') or s.startswith('framerate '):
        return 'fps_sampled'
    if s in ('frametime','frame time','frametime ms','frame time ms'):
        return 'frametime_sampled_ms'
    return None


def _bounds(key, value):
    limits = {'cpu_temp_c':(-30,130),'gpu_temp_c':(-30,130),
              'cpu_usage_pct':(0,100),'gpu_usage_pct':(0,100),
              'cpu_power_w':(0,1200),'gpu_power_w':(0,1200),
              'vram_used_mb':(0,200000),'fps_sampled':(0.01,10000),
              'frametime_sampled_ms':(0.01,2000)}
    return value is not None and limits[key][0] <= value <= limits[key][1]


def parse_hml_text(text):
    """Parse Afterburner Hardware Monitoring Log v1.x (02=headers, 80=data).

    Returns (metrics, token). A missing metric is absent, not replaced by zero.
    Token incorporates the last raw record to distinguish updates.
    """
    headers = None
    latest = None
    latest_raw = None
    # CSV format is one record per line; csv.reader respects quotes in labels.
    for raw in text.splitlines():
        if not raw.startswith(('02,','80,','02;','80;')):
            continue
        delimiter = ';' if raw[2:3] == ';' else ','
        try:
            row = next(csv.reader([raw], delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        if not row:
            continue
        if row[0].strip() == '02':
            headers = [x.strip() for x in row[2:]]
        elif row[0].strip() == '80' and headers is not None:
            latest = row[2:]
            latest_raw = raw
    if headers is None:
        raise ValueError('Histórico do Afterburner sem cabeçalho 02. Ative o registro no menu Monitoramento.')
    if latest is None:
        raise ValueError('Histórico do Afterburner ainda não contém amostras 80.')
    readings = {}
    for name, raw in zip(headers, latest):
        key = metric_from_name(name)
        if key is None:
            continue
        v = numeric(raw)
        if _bounds(key,v) and key not in readings:
            readings[key] = round(v, 3)
    return readings, latest_raw


def read_afterburner_log(path, max_size=150*1024*1024):
    """Read bounded header and latest 1MB, handling files being appended to."""
    p = Path(path)
    if p.suffix.casefold() not in ('.hml','.txt','.csv') or not p.is_file():
        raise ValueError('Selecione o arquivo .hml gerado pelo MSI Afterburner.')
    size=p.stat().st_size
    if size > max_size:
        raise ValueError('Histórico muito grande (limite 150 MB). Crie um novo log.')
    with p.open('rb') as f:
        begin=f.read(65536)
        if size>1024*1024:
            f.seek(max(0,size-1024*1024))
            end=f.read(1024*1024)
        else:
            end=f.read()
    # Trimming a partial first tail line avoids spurious 80 records.
    if size>1024*1024:
        end=end.partition(b'\n')[2]
    text=(begin+b'\n'+end).decode('utf-8-sig',errors='replace')
    metrics, token=parse_hml_text(text)
    return metrics, (size,token)


def find_afterburner_logs():
    """Only bounded known folders. Never recurse the user's entire SSDs."""
    dirs=[]
    for name in ('PROGRAMFILES(X86)','PROGRAMFILES'):
        if os.environ.get(name):
            dirs.append(Path(os.environ[name])/'MSI Afterburner')
    home=Path.home()
    dirs.extend([home/'Documents',home/'Documents'/'MSI Afterburner',
                 home/'Desktop',home/'Downloads'])
    found=[]
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            for path in d.iterdir():
                if path.is_file() and path.suffix.casefold()=='.hml':
                    found.append(path)
        except OSError:
            continue
    return sorted(set(found),key=lambda p:p.stat().st_mtime,reverse=True)


def _nvidia_executable():
    exe=shutil.which('nvidia-smi')
    if exe:
        return exe
    root=os.environ.get('SystemRoot',r'C:\Windows')
    candidate=Path(root)/'System32'/'nvidia-smi.exe'
    return str(candidate) if candidate.is_file() else None


def parse_nvidia_csv(text):
    try:
        row=next(csv.reader(io.StringIO(text.strip())))
    except (csv.Error,StopIteration):
        return {}
    # The query ordering is fixed; older driver unsupported fields may report N/A.
    labels=('gpu_temp_c','gpu_usage_pct','gpu_power_w','vram_used_mb')
    out={}
    for key, value in zip(labels,row):
        v=numeric(value)
        if _bounds(key,v):
            out[key]=round(v,3)
    return out


def poll_nvidia(timeout=4):
    if os.name != 'nt':
        return {}, 'Disponível somente no Windows.'
    exe=_nvidia_executable()
    if not exe:
        return {}, 'nvidia-smi não encontrado; dados NVIDIA indisponíveis.'
    command=[exe,'--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used',
             '--format=csv,noheader,nounits']
    try:
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',
                              errors='replace',timeout=timeout,check=False,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):
        return {}, 'Consulta NVIDIA falhou ou excedeu o tempo limite.'
    if result.returncode!=0:
        return {}, 'Driver NVIDIA não forneceu métricas agora.'
    raw=result.stdout.splitlines()
    return (parse_nvidia_csv(raw[0]) if raw else {}), None


def combine(nvidia, afterburner):
    """Prefer Afterburner for CPU/FPS, NVIDIA SMI for GPU (driver direct)."""
    merged={**afterburner,**nvidia}
    return {key:value for key,value in merged.items() if key in KEYS and _bounds(key,value)}


def summarized(rows):
    result={}
    for key in KEYS:
        values=[r.get('metrics',{}).get(key) for r in rows]
        valid=[v for v in values if isinstance(v,(int,float)) and math.isfinite(v)]
        if valid:
            result[key]={'count':len(valid),'mean':round(statistics.mean(valid),2),
                         'max':round(max(valid),2),'min':round(min(valid),2),
                         'median':round(statistics.median(valid),2)}
    return result


def new_session(scenario,phase):
    if phase not in ('antes','depois'):
        raise ValueError('Fase inválida')
    if not scenario or len(scenario)>100:
        raise ValueError('Cenário precisa ter entre 1 e 100 caracteres.')
    return {'schema':'pcro-monitor-1','scenario':scenario,'phase':phase,
            'started':datetime.now(timezone.utc).isoformat(),
            'sampling_note':'Sensores periódicos: FPS/frametime aqui NÃO são métricas por quadro (não calcular 1% low).',
            'rows':[]}


def append_sample(session,metrics,sources,now=None):
    if not metrics:
        return False
    session['rows'].append({'timestamp':now or datetime.now(timezone.utc).isoformat(),
                            'metrics':dict(metrics),'source':sorted(set(sources))})
    return True


def finish_session(session,folder):
    """Write JSON and CSV of sensor metrics, no credentials/files/disks touched."""
    session['finished']=datetime.now(timezone.utc).isoformat()
    session['summary']=summarized(session['rows'])
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    import uuid
    base=folder/('sessao-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    j=base.with_suffix('.json')
    c=base.with_suffix('.csv')
    j.write_text(json.dumps(session,indent=2,ensure_ascii=False),encoding='utf-8')
    with c.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['timestamp','sources',*KEYS])
        for row in session['rows']:
            writer.writerow([row['timestamp'],'+'.join(row['source']),
                             *(row['metrics'].get(key,'') for key in KEYS)])
    return j,c


def session_comparison(folder,scenario):
    """Medians of run-level averages; at least 3 runs/phase recommended."""
    matches={'antes':[],'depois':[]}
    root=Path(folder)
    if root.is_dir():
        for p in sorted(root.glob('sessao-*.json'))[-300:]:
            try:
                if p.stat().st_size>5_000_000:
                    continue
                d=json.loads(p.read_text(encoding='utf-8'))
                if d.get('schema')=='pcro-monitor-1' and d.get('scenario')==scenario and d.get('phase') in matches:
                    matches[d['phase']].append(d.get('summary',{}))
            except (OSError,ValueError,TypeError):
                continue
    result={'count':{p:len(rows) for p,rows in matches.items()}, 'median':{},'delta_pct':{}}
    for phase, rows in matches.items():
        result['median'][phase]={}
        for key in KEYS:
            vals=[r[key]['mean'] for r in rows if key in r]
            if vals:
                result['median'][phase][key]=round(statistics.median(vals),2)
    for key,base in result['median']['antes'].items():
        after=result['median']['depois'].get(key)
        if after is not None and base>0:
            result['delta_pct'][key]=round(100*(after/base-1),2)
    return result
