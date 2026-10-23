"""HONEST-inspired Windows optimizer: inspect first, reversible power scheme only.

This module NEVER modifies BIOS/UEFI, drivers, registry, startup, service state,
security controls or disks. A change to the active power plan requires a separate,
explicit user confirmation by the GUI and is journaled for reversal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from hardware_profile import build_profile

GUID_PATTERN = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
BALANCED_GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'


class OptimizationError(RuntimeError):
    pass


def _run(command: list[str], timeout: int = 18) -> str:
    if os.name != 'nt':
        raise OptimizationError('Este recurso só funciona em computadores Windows.')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8-sig',
                                errors='replace', check=False, timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OptimizationError(f'Falha na consulta Windows: {exc}') from exc
    if result.returncode != 0:
        raise OptimizationError((result.stderr or result.stdout or 'Comando não concluído.')[-400:])
    return result.stdout.strip()


def _ps(code: str, timeout=22):
    program = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not program:
        raise OptimizationError('PowerShell não foi encontrado.')
    output = _run([program, '-NoProfile', '-NonInteractive', '-Command',
                   "$ErrorActionPreference='Stop'; " + code], timeout)
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise OptimizationError('PowerShell retornou dados incompletos.') from exc


def _data_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def available_power_plans():
    """Parse GUIDs independently of OS localization (pt-BR, en-US, etc.)."""
    out = _run(['powercfg', '/list'])
    plans = []
    for line in out.splitlines():
        found = GUID_PATTERN.search(line)
        if not found:
            continue
        guid = found.group().lower()
        tail = line[found.end():].strip().rstrip('*').strip()
        label = tail.strip('() ') or guid
        plans.append({'guid': guid, 'name': label, 'active': '*' in line[found.end():]})
    if not plans:
        raise OptimizationError('O Windows não informou nenhum plano de energia.')
    return plans


def active_power_guid():
    out = _run(['powercfg', '/getactivescheme'])
    match = GUID_PATTERN.search(out)
    if not match:
        raise OptimizationError('Não foi possível identificar o plano ativo.')
    return match.group().lower()


def inspect_pc():
    """Read-only inventory; leaves unsupported values explicitly unknown."""
    result = {'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'leitura',
              'windows': os.name == 'nt', 'hardware': {}, 'power': {}, 'checks': [], 'errors': []}
    if os.name != 'nt':
        result['errors'].append('Faça o diagnóstico no Windows em que pretende otimizar.')
        result['profile'] = build_profile(result['hardware'])
        return result
    queries = {
        'cpu': 'Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Depth 3',
        'gpu': 'Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Depth 3',
        'ram': 'Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,Manufacturer | ConvertTo-Json -Depth 3',
        'board': 'Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product | ConvertTo-Json -Depth 3',
        'bios': 'Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate | ConvertTo-Json -Depth 3',
        'os': 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Depth 3',
        'pc': 'Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,PCSystemType | ConvertTo-Json -Depth 3',
    }
    for key, code in queries.items():
        try:
            result['hardware'][key] = _ps(code)
        except OptimizationError as exc:
            result['errors'].append(f'Inventário {key}: {exc}')
    try:
        plans = available_power_plans()
        active = active_power_guid()
        result['power'] = {'plans': plans, 'active_guid': active}
        result['checks'].append({'type': 'power', 'state': 'observado',
                                 'message': 'Plano de energia detectado. Alterar pode aumentar consumo e calor, sem ganho garantido.'})
    except OptimizationError as exc:
        result['errors'].append(f'Energia: {exc}')

    mem = _data_list(result['hardware'].get('ram'))
    for module in mem:
        nominal = module.get('Speed')
        current = module.get('ConfiguredClockSpeed')
        if isinstance(current, int) and current > 0 and isinstance(nominal, int) and nominal > current:
            result['checks'].append({'type': 'ram', 'state': 'verificar',
                                     'message': f'Memória configurada a {current} MT/s; módulo informa {nominal} MT/s. Confirmar fabricante, estabilidade e perfil XMP/EXPO na UEFI.'})
    result['checks'].extend([
        {'type': 'firmware', 'state': 'manual', 'message': 'XMP/EXPO, SMT/Hyper-Threading e boost não serão alterados automaticamente. A leitura do perfil UEFI não é confiável por esta interface.'},
        {'type': 'gpu', 'state': 'manual', 'message': 'Verifique drivers apenas por canais oficiais NVIDIA/AMD/Intel. Sem ajustes automáticos da NVAPI/ADL.'},
        {'type': 'windows', 'state': 'manual', 'message': 'Não desativar serviços em massa, segurança, Windows Update, paginação ou Registry tweaks não documentados.'},
        {'type': 'benchmark', 'state': 'pendente', 'message': 'Meça FPS médio e 1%/0,2% low no mesmo cenário, pelo menos três vezes antes e depois.'},
    ])
    result['unmeasured'] = ['temperatura CPU/GPU (disponível separadamente no monitoramento em tempo real se os sensores responderem)', 'consumo neste relatório estático', 'estabilidade de memória',
                            'versões compatíveis de perfis BIOS', 'FPS de jogo', 'latência DWM']
    result['profile'] = build_profile(result['hardware'])
    return result


def _atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def safe_change_power_plan(target: str, journal_path: Path):
    """Explicit change of a previously enumerated Windows power plan, never arbitrary GUID."""
    target = str(target).lower()
    plans = available_power_plans()
    valid = {p['guid'] for p in plans}
    if target not in valid:
        raise OptimizationError('Plano não consta da lista atual do Windows; nada alterado.')
    old = active_power_guid()
    if old == target:
        return {'changed': False, 'previous': old, 'current': target}
    journal_path = Path(journal_path)
    if journal_path.exists():
        # Preserve the original rollback point rather than silently overwriting it.
        try:
            record = json.loads(journal_path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise OptimizationError('Registro de reversão ilegível: alteração bloqueada.') from exc
        if record.get('status') == 'prepared':
            current = active_power_guid()
            if current == record.get('previous'):
                record['status'] = 'reverted'
                _atomic_json(journal_path, record)
            elif current == record.get('requested'):
                record['status'] = 'applied'
                _atomic_json(journal_path, record)
                raise OptimizationError('Encontrei uma mudança anterior pendente; ela agora está registrada para Desfazer.')
            else:
                raise OptimizationError('Mudança anterior interrompida e plano externo desconhecido. Consulte a aba Energia.')
        if record.get('status') != 'reverted':
            raise OptimizationError('Existe uma alteração não revertida. Reverta antes de escolher outro plano.')
    record = {'schema': 'pcro-power-1', 'status': 'prepared', 'previous': old, 'requested': target,
              'timestamp': datetime.now(timezone.utc).isoformat()}
    _atomic_json(journal_path, record)
    try:
        _run(['powercfg', '/setactive', target])
        confirmed = active_power_guid()
        if confirmed != target:
            raise OptimizationError('Não foi possível confirmar a alteração.')
    except Exception as exc:
        # Attempt immediate rollback; report if it also fails.
        rollback_error = None
        try:
            _run(['powercfg', '/setactive', old])
        except Exception as rollback:
            rollback_error = str(rollback)
        record['status'] = 'failed' if rollback_error else 'reverted'
        record['error'] = str(exc)
        record['rollback_error'] = rollback_error
        _atomic_json(journal_path, record)
        raise OptimizationError('Alteração falhou. ' + ('Reversão também falhou: ' + rollback_error if rollback_error else 'Plano anterior restaurado.')) from exc
    record['status'] = 'applied'
    _atomic_json(journal_path, record)
    return {'changed': True, 'previous': old, 'current': target}


def revert_power_plan(journal_path: Path):
    path = Path(journal_path)
    if not path.exists():
        raise OptimizationError('Nenhuma alteração anterior registrada neste aplicativo.')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise OptimizationError('Registro de reversão está ilegível.') from exc
    if record.get('schema') != 'pcro-power-1' or record.get('status') != 'applied':
        raise OptimizationError('Não há ajuste aplicado para reverter.')
    previous = str(record.get('previous', '')).lower()
    if previous not in {p['guid'] for p in available_power_plans()}:
        raise OptimizationError('Plano original não existe mais. Nenhuma alteração feita.')
    current = active_power_guid()
    if current != record.get('requested'):
        raise OptimizationError('O plano foi alterado por outro programa. Não sobrescrevi a escolha atual.')
    _run(['powercfg', '/setactive', previous])
    if active_power_guid() != previous:
        raise OptimizationError('Windows não confirmou a reversão. Verifique o plano ativo.')
    record['status'] = 'reverted'
    record['reverted_at'] = datetime.now(timezone.utc).isoformat()
    _atomic_json(path, record)
    return previous


def export_snapshot(report: dict, filename: Path):
    filename = Path(filename)
    if filename.suffix.lower() != '.json':
        raise OptimizationError('O relatório deve ser salvo como .json.')
    _atomic_json(filename, report)
    return filename
