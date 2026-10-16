"""Evidence scope and partial selections for any user/path; no automatic choices."""
from copy import deepcopy
from collections import Counter
import json
import ntpath
import os
from pathlib import Path
import subprocess
import sys

from audit_v068 import collect_disk_evidence_068, classify_boot_068, enhance_report_068
from completeness_audit_v067 import _within


def enhance_report_069(report, *, proof=None):
    report = enhance_report_068(deepcopy(report), proof=proof)
    report['schema'] = 'pcro-completeness-audit-v069'
    selected = report.get('selected_c_paths', [])
    sources = set(proof.get('verified_source_files', [])) if proof and proof.get('backup_verified') is True else set()
    for row in report.get('candidate_locations', []):
        path = row['path']
        children = [p for p in selected if _within(p, path) and
                    ntpath.normcase(ntpath.normpath(p)) != ntpath.normcase(ntpath.normpath(path))]
        row['selected_descendants'] = children
        row['selection_state'] = 'selected' if row.get('covered_by') else 'partial' if children else 'unselected'
        if children and not row.get('covered_by') and row['status'] == 'REVISAR — NÃO SELECIONADO':
            row['status'] = 'SELEÇÃO PARCIAL — REVISAR RESTANTE'
            row['detail'] += f' {len(children)} caminho(s) interno(s) selecionado(s); restante não incluído.'
    for row in report.get('recovery_map', []):
        count = sum(_within(s, row['source_path']) for s in sources)
        row.update(selection_state='selected', verified_manifest_files=count,
                   backup_state='manifest_files_verified' if count else 'not_proven',
                   coverage_state='not_proven', restore_state='not_proven')
        row['status'] = (f'{count} ARQUIVO(S) VERIFICADO(S) — COBERTURA A CONFERIR' if count
                         else 'SELECIONADO — SEM PROVA DE BACKUP')
        row['note'] = 'Restauração não comprovada nesta auditoria. ' + row.get('note', '')
    report['backup_evidence']['manifest_verified'] = bool(proof and proof.get('backup_verified') is True)
    report['backup_evidence']['scope'] = 'listed_manifest_files_only'
    scan = report.get('scan_c', {})
    report['scan_summary'] = {
        'error_reasons': dict(Counter(x.get('reason', '').split(':')[0] for x in scan.get('errors', []))),
        'skipped_reasons': dict(Counter(x.get('reason', '') for x in scan.get('skipped', []))),
        'selected_path_overlaps': [x for k in ('errors', 'skipped') for x in scan.get(k, [])
                                   if any(_within(x.get('path', ''), p) or _within(p, x.get('path', '')) for p in selected)],
        'notice': 'Itens ignorados não foram apagados. Ausência de sobreposição não certifica cobertura.'}
    report['manual_tasks'] = [
        t.replace('Manter cópia adicional independente e confiável; G: Storage Spaces simples não tem redundância.',
                  'Manter cópia adicional independente; conferir a redundância do destino escolhido.')
        for t in report.get('manual_tasks', [])]
    return report


def apply_volume_mappings(data, mappings):
    data = deepcopy(data)
    by_id = {str(m.get('device_id', '')).lower().rstrip('\\'): m for m in mappings if isinstance(m, dict)}
    data['volume_extent_evidence'] = mappings
    for vol in data.get('legacy_volumes', []):
        match = by_id.get(str(vol.get('device_id', '')).lower().rstrip('\\'), {})
        extents = match.get('extents', []) if match.get('status') == 'mapped' else []
        numbers = sorted({x['disk_number'] for x in extents if isinstance(x.get('disk_number'), int)
                          and not isinstance(x['disk_number'], bool) and x['disk_number'] >= 0})
        vol['disk_numbers'] = numbers
        vol['mapping_source'] = match.get('source', '') if numbers else ''
        vol['mapping_error'] = match.get('error', '')
        # Keep all disks for spanned volumes; never pick the first.
        if len(numbers) == 1 and vol.get('boot_volume') is True and data.get('windows_disk_number') is None:
            data['windows_disk_number'] = numbers[0]
    return data


def collect_disk_evidence_069():
    evidence = collect_disk_evidence_068()
    if not evidence.get('available'):
        return evidence
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('volume_extents.py'))],
                                input=json.dumps(evidence['data'].get('legacy_volumes', [])),
                                capture_output=True, text=True, encoding='utf-8', timeout=25,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('Consulta de volumes não concluída: ' + result.stderr[:200])
        mappings = json.loads(result.stdout)
        if not isinstance(mappings, list):
            raise ValueError('Resposta de volumes inválida.')
        evidence['data'] = apply_volume_mappings(evidence['data'], mappings)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        evidence['data'].setdefault('warnings', []).append('Associação direta indisponível: ' + str(exc)[:250])
    return evidence


def classify_boot_069(evidence):
    result = classify_boot_068(evidence)
    data = evidence.get('data', {})
    system = [v for v in data.get('legacy_volumes', []) if v.get('system_volume') is True]
    mapped = sorted({n for v in system for n in v.get('disk_numbers', [])})
    result['system_volume_disk_numbers'] = mapped
    win = data.get('windows_disk_number')
    # System-volume evidence is deliberately separate from GPT EFI evidence.
    # FAT32 alone is never sufficient to claim an EFI partition or working boot.
    if mapped and win is not None and all(v.get('disk_numbers') for v in system):
        if len(mapped) > 1:
            result.update(status='REVISAR — SISTEMA EM VÁRIOS DISCOS',
                          note='Volumes de sistema associados a vários discos; não presumir boot independente.')
        elif mapped[0] != win:
            result.update(status='SISTEMA EM OUTRO DISCO',
                          note=f'Volume marcado como Sistema associado ao disco {mapped[0]}; Windows no disco {win}. '
                               'Associação de metadados confirmada; boot independente não testado.')
        else:
            result.update(status='TESTE MANUAL NECESSÁRIO',
                          note='Volume de sistema associado ao disco do Windows; boot independente não testado.')
    elif mapped:
        result.update(status='MAPEAMENTO INCOMPLETO',
                      note='Parte dos volumes foi associada; faltam associações do sistema ou do Windows.')
    result['note'] = result['note'].replace('SSD Kingston', 'disco correspondente')
    result['manual_boot_test_needed'] = True
    return result
