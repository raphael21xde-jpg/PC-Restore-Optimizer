"""Safe per-frame stutter measurement and correlation with existing sensor logs.

Read-only parser for PresentMon (v1/v2), CapFrameX/OCAT-style frame CSV.
Events are *candidate stalls*, never a claim about causality or thermal throttling.
"""
from __future__ import annotations
from collections import Counter
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from statistics import mean, median

MAX_FILE_BYTES=150*1024*1024
MAX_FRAMES=1_500_000


def key(text):
    return re.sub(r'[^a-z0-9]', '', text.casefold().replace('\ufeff',''))


def number(value):
    raw=str(value or '').strip().replace('\u00a0','').replace(' ','')
    if not raw or raw.lower() in ('n/a','nan','na','-','none'):
        return None
    if ',' in raw and '.' not in raw:raw=raw.replace(',','.')
    try: n=float(raw)
    except (ValueError,TypeError):return None
    return n if math.isfinite(n) else None


def _p(sorted_values,p):
    if not sorted_values:raise ValueError('Sem quadros.')
    k=(len(sorted_values)-1)*p/100
    a=math.floor(k);b=min(len(sorted_values)-1,a+1)
    return sorted_values[a]*(1-(k-a))+sorted_values[b]*(k-a)


def parse_frames(path, process='cs2.exe'):
    """Collect frame start intervals. Avoid mixing overlay or unrelated swapchains.

    Returns list of (relative_seconds, interval_ms), plus metadata. Relative time
    is relative to first selected present, not wall-clock, unless externally synced.
    """
    path=Path(path)
    if not path.is_file() or path.suffix.lower() not in ('.csv','.txt'):
        raise ValueError('Selecione um CSV de quadros do PresentMon/CapFrameX/OCAT.')
    if path.stat().st_size>MAX_FILE_BYTES:
        raise ValueError('Arquivo acima do limite de 150 MB. Faça uma captura menor.')
    stream=None
    for enc in ('utf-8-sig','utf-16','cp1252'):
        try:
            stream=path.open('r',encoding=enc,newline='')
            probe=stream.read(4096)
            if '\x00' in probe: raise UnicodeError()
            stream.seek(0)
            break
        except UnicodeError:
            if stream:stream.close()
            stream=None
    if stream is None:raise ValueError('Codificação CSV desconhecida.')
    with stream:
        sample=stream.read(4096);stream.seek(0)
        try: delimiter=csv.Sniffer().sniff(sample,delimiters=',;\t').delimiter
        except csv.Error:delimiter=';' if sample.count(';')>sample.count(',') else ','
        reader=csv.DictReader(stream,delimiter=delimiter)
        if not reader.fieldnames:raise ValueError('CSV vazio.')
        columns={key(k):k for k in reader.fieldnames if k}
        # PresentMon v2: app frame cadence. A display interval and a Present
        # interval mean different things under frame generation/composition.
        source=next((c for c in ('msbetweenappstart','msbetweenpresents','frametime','frametimems',
                                  'frametimeduration','msbetweenframestarts','msbetweendisplaychange') if c in columns),None)
        fps_col=next((c for c in ('fps','framerate','framespersecond') if c in columns),None)
        if not source and not fps_col:
            raise ValueError('Não há coluna de quadros individuais (MsBetweenPresents/Frametime/FPS).')
        time_col=next((c for c in ('timeinseconds','timeinms','cpustarttimeinms','time') if c in columns),None)
        app_col=next((c for c in ('application','processname') if c in columns),None)
        chain_col=columns.get('swapchainaddress')
        records=[];counter=Counter();filtered_process=0
        process=process.strip().lower()
        for row in reader:
            if app_col and process and Path(str(row.get(columns[app_col],'')).replace('\\','/')).name.lower()!=process:
                continue
            filtered_process+=1
            raw=number(row.get(columns[source])) if source else None
            if raw is None and not source:
                fps=number(row.get(columns[fps_col]))
                raw=1000/fps if fps and 0.1<=fps<=10000 else None
            if raw is None or not 0.1<=raw<=2000:continue
            tick=number(row.get(columns[time_col])) if time_col else None
            if tick is not None and time_col in ('timeinms','cpustarttimeinms'):
                tick/=1000
            chain=str(row.get(chain_col,'')).strip() if chain_col else ''
            records.append((tick,raw,chain))
            counter[chain]+=1
            if len(records)>MAX_FRAMES:raise ValueError('CSV excedeu 1,5 milhão de quadros.')
        if app_col and not filtered_process:
            raise ValueError('Não encontrei quadros de '+process+'. Confira o processo capturado.')
        if len(records)<30:raise ValueError('Menos de 30 quadros válidos no arquivo.')
        if chain_col:
            # Multi-swapchain processes can present overlay, game, and UI frames.
            main_chain=counter.most_common(1)[0][0]
            records=[r for r in records if r[2]==main_chain]
        if len(records)<30:raise ValueError('Swapchain principal com menos de 30 quadros.')
        first=next((t for t,_,_ in records if t is not None),None)
        elapsed=0.;frames=[]
        for tick,interval,_ in records:
            elapsed=(tick-first) if tick is not None and first is not None else elapsed+interval/1000
            if elapsed<0:continue
            frames.append((round(elapsed,5),interval))
        if len(frames)<30:raise ValueError('Sem quadros suficientes após normalização.')
        return frames,{'column':columns[source] if source else columns[fps_col],
                       'process':process if app_col else 'CSV sem coluna de processo',
                       'swapchain':counter.most_common(1)[0][0] if chain_col else None,
                       'time_axis':time_col or 'estimado por soma dos intervalos',
                       'frame_interpretation':'intervalo entre inícios/apresentações; não equivale sempre a quadros exibidos',
                       'filename':path.name}


def analyze_frames(frames,metadata=None):
    """Slowest 1% mean FPS and 0.2% mean FPS, no fabricated sampling lows."""
    if len(frames)<30:raise ValueError('São necessários 30 quadros.')
    times=[x[1] for x in frames]
    total=sum(times)
    ranked=sorted(times,reverse=True)
    def low(frac):
        n=max(1,math.ceil(len(times)*frac))
        return round(1000/mean(ranked[:n]),2)
    base=median(times)
    # Adaptive events: >3x baseline OR >=50ms; 50ms marks a perceptible hitch,
    # while 3x baseline captures frame pacing on fast monitors. We exclude menus
    # only by process and swapchain and cannot infer when gameplay is active.
    threshold=max(33.33,base*3)
    events=[]
    for i,(stamp,duration) in enumerate(frames):
        if duration>=threshold:
            events.append({'t_s':round(stamp,2),'ms':round(duration,2),
                           'fps_equiv':round(1000/duration,1)})
    worst=sorted(events,key=lambda e:e['ms'],reverse=True)[:12]
    return {'count':len(frames),'duration_s':round(frames[-1][0]-frames[0][0],1),
            'avg_fps':round(1000*len(times)/total,2),
            'low_1':low(.01),'low_02':low(.002),
            'p99_frametime_ms':round(_p(sorted(times),99),2),
            'p998_frametime_ms':round(_p(sorted(times),99.8),2),
            'median_frametime_ms':round(base,2),'worst_ms':round(max(times),2),
            'event_threshold_ms':round(threshold,2),
            'event_count':len(events),'event_rate_per_min':round(60*len(events)/max(total/1000,.001),2),
            'worst_events':worst,'metadata':metadata or {},
            'limitations':('Eventos são candidatos a stutter; menus, carregamento, alt-tab e frame generation podem afetar dados. '
                           '1% low/0,2% low = FPS equivalente da média dos intervalos mais lentos; método explícito.')}


def analyze_file(path,process='cs2.exe'):
    frames,meta=parse_frames(path,process)
    return analyze_frames(frames,meta)


def correlate_with_session(analysis,session,launch_utc=None):
    """Correlate cautiously ONLY if launch UTC from a capture initiated by this app.

    CSV user-imports lack a grounded wall-clock anchor; must not guess alignment.
    """
    if not launch_utc:return []
    try:origin=datetime.fromisoformat(launch_utc.replace('Z','+00:00'))
    except ValueError:return []
    matches=[]
    for event in analysis.get('worst_events',[]):
        absolute=origin.timestamp()+event['t_s']
        nearest=None;distance=float('inf')
        for row in session.get('rows',[]):
            try:ts=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).timestamp()
            except (KeyError,ValueError):continue
            delta=abs(ts-absolute)
            if delta<distance:nearest=row;distance=delta
        if nearest is not None and distance<=4:
            matches.append({'t_s':event['t_s'],'frametime_ms':event['ms'],
                            'offset_seconds':round(distance,1),
                            'sensor_readings':dict(nearest.get('metrics',{})),
                            'note':'Correlação aproximada (amostragem ~2s; relógios não sincronizados por hardware).'})
    return matches


def summary_text(result):
    lines=[f"Quadros reais: {result['count']} | duração aproximada: {result['duration_s']} s",
           f"FPS médio: {result['avg_fps']} | 1% low: {result['low_1']} | 0,2% low: {result['low_02']}",
           f"P99: {result['p99_frametime_ms']} ms | P99.8: {result['p998_frametime_ms']} ms",
           f"Maior intervalo: {result['worst_ms']} ms | candidatos a travada: {result['event_count']}",
           f"Critério desta sessão: quadro >= {result['event_threshold_ms']} ms",'']
    for evt in result['worst_events'][:8]:
        lines.append(f"{evt['t_s']:7.1f}s   {evt['ms']:7.1f} ms   (~{evt['fps_equiv']} FPS instantâneo)")
    lines.extend(['','ATENÇÃO:',result['limitations']])
    return '\n'.join(lines)


def analyze_sampled_fps_session(session):
    """Find drop *observations* in periodic logs; never infer full-frame lows."""
    if session.get('schema')!='pcro-monitor-1' or not isinstance(session.get('rows'),list):
        raise ValueError('Não é uma sessão do nosso monitoramento.')
    samples=[]
    for row in session['rows']:
        m=row.get('metrics',{})
        f=number(m.get('fps_sampled'))
        if f is not None and .1<=f<=10000:
            samples.append((row.get('timestamp',''),f,m))
    if len(samples)<2:
        raise ValueError('Poucas amostras de FPS. Ative o sensor Framerate no Afterburner.')
    falls=[]
    for (before_t,before_f,_),(after_t,after_f,metrics) in zip(samples,samples[1:]):
        if after_f<=.6*before_f:
            falls.append({'timestamp':after_t,'from_fps':round(before_f,1),
                          'to_fps':round(after_f,1),'drop_pct':round(100*(1-after_f/before_f),1),
                          'cpu_temp_c':metrics.get('cpu_temp_c'),
                          'gpu_temp_c':metrics.get('gpu_temp_c'),
                          'cpu_usage_pct':metrics.get('cpu_usage_pct'),
                          'gpu_usage_pct':metrics.get('gpu_usage_pct')})
    return {'samples':len(samples),'drops':falls,'observed_min':min(x[1] for x in samples),
            'observed_max':max(x[1] for x in samples),'scenario':session.get('scenario',''),
            'caution':'Amostras espaçadas não dão FPS médio real, 1% low, duração das travadas nem causa. '
                      'Transições de tela/carregamento também reduzem FPS.'}
