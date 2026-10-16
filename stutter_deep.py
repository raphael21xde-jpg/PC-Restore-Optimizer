"""Reproducible frame pacing study, with no implicit edits to original capture.

Trimming the first seconds is a side-by-side diagnostic only; neither view is
silently substituted for the original result. Sensor fusion remains separate.
"""
from __future__ import annotations
from statistics import median
from stutter_analysis import analyze_frames, parse_frames


def study_frames(frames, start_exclusion_s=5.0, window_s=5.0):
    if not 0 <= start_exclusion_s <= 30:
        raise ValueError('Recorte inicial deve estar entre 0 e 30 segundos.')
    if not 1 <= window_s <= 60:
        raise ValueError('Janela deve ter entre 1 e 60 segundos.')
    if len(frames) < 30:
        raise ValueError('Menos de 30 quadros.')
    original = analyze_frames(frames)
    first = frames[0][0]
    usable = [(t - start_exclusion_s, ms) for t, ms in frames
              if t - first >= start_exclusion_s]
    if len(usable) < 30:
        raise ValueError('O recorte exclui quadros demais.')
    trimmed = analyze_frames(usable)
    baseline = median(v for _, v in usable)
    # A threshold relative to each session baseline highlights pacing variations
    # even when no frame reaches the severe fixed 33.33 ms threshold.
    adaptive = max(8.0, 2.5 * baseline)
    thresholds = (8.0, 12.0, 16.67, 25.0, 33.33, 50.0)
    counts = {f'{th:.2f}': sum(ms >= th for _, ms in usable) for th in thresholds}
    windows = {}
    for t, ms in usable:
        idx = max(0, int(t // window_s))
        windows.setdefault(idx, []).append(ms)
    timeline = []
    for idx in sorted(windows):
        values = windows[idx]
        # Use actual time spent on frames, not artificial count/window normalization.
        fps = len(values) * 1000 / sum(values)
        timeline.append({'start_s': round(start_exclusion_s + idx*window_s, 2),
                         'fps': round(fps, 2), 'slow_frames': sum(v >= adaptive for v in values),
                         'max_ms': round(max(values), 2), 'count': len(values)})
    slowest = sorted(({'t_s': round(t + start_exclusion_s, 3),
                        'ms': round(ms, 3), 'fps_equivalent': round(1000/ms, 1)}
                      for t, ms in usable if ms >= adaptive),
                     key=lambda x: x['ms'], reverse=True)[:25]
    return {'schema': 'pcro-frame-study-1', 'original': original, 'after_exclusion': trimmed,
            'excluded_seconds': start_exclusion_s, 'window_seconds': window_s,
            'slow_frame_threshold_ms': round(adaptive, 2), 'threshold_counts': counts,
            'timeline': timeline, 'slowest_frames': slowest,
            'note': ('Recorte de cinco segundos não prova que eventos foram causados pelo início. '
                     'FPS equivalente por quadro não representa FPS médio daquela cena. '
                     'A captura sem sensores sincronizados não prova causas térmicas ou de CPU.')}


def study_csv(path, process='cs2.exe', start_exclusion_s=5.0):
    frames, metadata = parse_frames(path, process)
    result = study_frames(frames, start_exclusion_s)
    result['metadata'] = metadata
    return result


def study_text(r):
    o, t = r['original'], r['after_exclusion']
    lines = ['ESTUDO DE FLUIDEZ — COMPARAÇÃO EXPLÍCITA', '',
             '                           ORIGINAL      APÓS RECORTE',
             f"FPS médio:                  {o['avg_fps']:>8.2f}      {t['avg_fps']:>8.2f}",
             f"1% low:                    {o['low_1']:>8.2f}      {t['low_1']:>8.2f}",
             f"0,2% low:                  {o['low_02']:>8.2f}      {t['low_02']:>8.2f}",
             f"Pior quadro (ms):          {o['worst_ms']:>8.2f}      {t['worst_ms']:>8.2f}",
             f"Quadros analisados:        {o['count']:>8}      {t['count']:>8}", '',
             f"Recorte: {r['excluded_seconds']} s iniciais; não modifica CSV.",
             f"Limiar adaptativo: {r['slow_frame_threshold_ms']} ms; não significa travada confirmada.", '',
             'QUADROS LENTOS APÓS RECORTE:']
    lines.extend(f'  >= {key} ms: {val}' for key, val in r['threshold_counts'].items())
    lines += ['', 'JANELAS DE DESEMPENHO:']
    lines.extend(f"  {x['start_s']:>6.1f}s: {x['fps']:>7.1f} FPS | pior {x['max_ms']:>6.2f} ms | {x['slow_frames']} quadros lentos"
                 for x in r['timeline'][:40])
    lines += ['', 'PIOR INTERVALO APÓS RECORTE:']
    lines.extend(f"  {x['t_s']:>7.2f}s | {x['ms']:>6.2f} ms | {x['fps_equivalent']:>6.1f} FPS/quadro"
                 for x in r['slowest_frames'][:10])
    lines += ['', 'LIMITAÇÕES:', r['note']]
    return '\n'.join(lines)
