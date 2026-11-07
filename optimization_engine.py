"""HONEST-inspired Windows optimizer: inspect first, reversible power scheme only.

This module NEVER modifies BIOS/UEFI, drivers, registry, startup, service state,
security controls or disks. A change to the active power plan requires a separate,
explicit user confirmation by the GUI and is journaled for reversal.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

from hardware_profile import build_profile
from bios_guidance import build_bios_guidance
from elevation_guard import is_process_elevated

GUID_PATTERN = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
BALANCED_GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'


# P3-06 fatia 2: só leitura e sem administrador. Para cada placa de vídeo, só o
# TAMANHO de cada intervalo de memória (fim - início + 1, em bytes). Endereços,
# PNPDeviceID e nomes não saem do PowerShell.
_GPU_BAR_QUERY = ('ConvertTo-Json -Depth 3 -InputObject @(Get-CimInstance Win32_VideoController | '
                  'ForEach-Object { [pscustomobject]@{ Sizes = @(Get-CimAssociatedInstance -InputObject $_ '
                  '-ResultClassName Win32_DeviceMemoryAddress | ForEach-Object { '
                  '[decimal]$_.EndingAddress - [decimal]$_.StartingAddress + 1 }) } })')
# FIX-P3-06-13: nome para leigos nas mensagens de erro do inventário (o resto usa a chave).
_INVENTORY_LABELS = {'gpu_bar': 'Resizable BAR (placa de vídeo)'}


class OptimizationError(RuntimeError):
    pass


def _is_windows() -> bool:
    """Único ponto que confere o sistema; os testes trocam esta função, não o global."""
    return os.name == 'nt'


def _run(command: list[str], timeout: int = 18) -> str:
    if not _is_windows():
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
    if not _is_windows():
        raise OptimizationError('Este recurso só funciona em computadores Windows.')
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


# FIX-M3-T4: só os 4 planos padrão do Windows (GUIDs fixos). Usada só quando o
# nome lido do Windows vem vazio ou ilegível ('\ufffd', ex.: powercfg em cp850).
STANDARD_POWER_PLANS = {
    BALANCED_GUID: 'Equilibrado',
    '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c': 'Alto desempenho',
    'a1841308-3541-4fab-bc81-f71556f20b4a': 'Economia de energia',
    'e9a42b02-d5df-448d-aa00-03f14749eb61': 'Desempenho máximo',
}
_UNREADABLE = '\ufffd'
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')


def _plan_tail(text: str, found) -> str:
    """Nome entre parênteses depois do GUID ('  (Equilibrado) *' -> 'Equilibrado')."""
    tail = text[found.end():].strip().rstrip('*').strip()
    return tail.strip('() ')


def parse_power_list(text) -> list:
    """Função pura: saída de ``powercfg /list`` -> lista de planos (pode ser vazia).

    Independe do idioma (pt-BR, en-US...): procura o GUID em cada linha.
    """
    plans = []
    for line in str(text or '').splitlines():
        found = GUID_PATTERN.search(line)
        if not found:
            continue
        guid = found.group().lower()
        plans.append({'guid': guid, 'name': _plan_tail(line, found) or guid,
                      'active': '*' in line[found.end():]})
    return plans


def parse_active_scheme(text):
    """Função pura: saída de ``powercfg /getactivescheme`` -> (guid, nome) ou (None, None)."""
    for line in str(text or '').splitlines():
        found = GUID_PATTERN.search(line)
        if found:
            return found.group().lower(), (_plan_tail(line, found) or None)
    return None, None


def _readable_name(name, guid):
    """Nome legível para o usuário, ou None (vazio, ilegível, igual ao GUID ou com controle)."""
    if not isinstance(name, str):
        return None
    name = name.strip()
    if (not name or _UNREADABLE in name or _CONTROL_CHARS.search(name)
            or name.lower() == guid or GUID_PATTERN.fullmatch(name)):
        return None
    return name


def power_plan_name(guid, plans):
    """Nome do plano ``guid``: o da lista do Windows; se ilegível, o da tabela fixa
    (só os 4 planos padrão); senão None. Nunca devolve texto com '\ufffd'."""
    if not isinstance(guid, str) or not GUID_PATTERN.fullmatch(guid.strip()):
        return None
    guid = guid.strip().lower()
    for plan in plans if isinstance(plans, list) else []:
        if isinstance(plan, dict) and str(plan.get('guid') or '').lower() == guid:
            name = _readable_name(plan.get('name'), guid)
            if name:
                return name
    return STANDARD_POWER_PLANS.get(guid)


def available_power_plans():
    """Parse GUIDs independently of OS localization (pt-BR, en-US, etc.)."""
    plans = parse_power_list(_run(['powercfg', '/list']))
    if not plans:
        raise OptimizationError('O Windows não informou nenhum plano de energia.')
    return plans


def active_power_guid():
    guid, _name = parse_active_scheme(_run(['powercfg', '/getactivescheme']))
    if not guid:
        raise OptimizationError('Não foi possível identificar o plano ativo.')
    return guid


def active_power_plan_name():
    """FIX-M3-T4: nome do plano ativo, só leitura (``/getactivescheme`` e ``/list``).

    Erro em ``/getactivescheme`` sobe como OptimizationError; erro em ``/list``
    só faz usar o nome da outra consulta. Nome ilegível = None.
    """
    guid, name = parse_active_scheme(_run(['powercfg', '/getactivescheme']))
    if not guid:
        raise OptimizationError('Não foi possível identificar o plano ativo.')
    try:
        plans = parse_power_list(_run(['powercfg', '/list']))
    except OptimizationError:
        plans = []
    return power_plan_name(guid, plans + [{'guid': guid, 'name': name}])


def power_plan_text(power) -> str:
    """Texto do diagnóstico: 'Nome (GUID)'; sem nome, só o GUID; sem nada, 'indisponível'."""
    power = power if isinstance(power, dict) else {}
    guid = power.get('active_guid')
    if not isinstance(guid, str) or not GUID_PATTERN.fullmatch(guid.strip()):
        return 'indisponível'
    guid = guid.strip().lower()
    name = _readable_name(power.get('active_name'), guid)
    if name is None and 'active_name' not in power:
        name = power_plan_name(guid, power.get('plans'))
    return f'{name} ({guid})' if name else guid


def inspect_pc():
    """Read-only inventory; leaves unsupported values explicitly unknown."""
    result = {'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'leitura',
              'windows': _is_windows(), 'hardware': {}, 'power': {}, 'checks': [], 'errors': []}
    if not _is_windows():
        result['errors'].append('Faça o diagnóstico no Windows em que pretende otimizar.')
        result['profile'] = build_profile(result['hardware'])
        result['bios_guidance'] = build_bios_guidance(result['hardware'], result['profile'])
        return result
    queries = {
        'cpu': 'Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Depth 3',
        'gpu': 'Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Depth 3',
        'ram': 'Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,Manufacturer,DeviceLocator,BankLabel | ConvertTo-Json -Depth 3',
        'board': 'Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product | ConvertTo-Json -Depth 3',
        'bios': 'Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate | ConvertTo-Json -Depth 3',
        'os': 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Depth 3',
        # FIX-P3-06-01: sem Model (nada usa e pode trazer o nome do PC).
        'pc': 'Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,PCSystemType | ConvertTo-Json -Depth 3',
        # P3-01 fatia 2: só leitura; nada de número de série nem nome do disco.
        'chassis': 'Get-CimInstance Win32_SystemEnclosure | Select-Object ChassisTypes | ConvertTo-Json -Depth 3',
        'battery': 'Get-CimInstance Win32_Battery | Select-Object BatteryStatus | ConvertTo-Json -Depth 3',
        'disks': 'Get-PhysicalDisk | Select-Object MediaType,BusType,Size | ConvertTo-Json -Depth 3',
        # P3-06 fatia 2: fica só na memória (fora de _EXPORT_COLUMNS); o arquivo leva só o estado.
        'gpu_bar': _GPU_BAR_QUERY,
    }
    for key, code in queries.items():
        try:
            result['hardware'][key] = _ps(code)
        except OptimizationError:
            # R-07: o texto do PowerShell pode trazer caminho com nome do usuário.
            result['errors'].append(f'Inventário {_INVENTORY_LABELS.get(key, key)}: não foi possível ler.')
    try:
        plans = available_power_plans()
        active = active_power_guid()
        # FIX-M3-T4: active_name fica só na memória (fora de _EXPORT_COLUMNS).
        result['power'] = {'plans': plans, 'active_guid': active,
                           'active_name': power_plan_name(active, plans)}
        result['checks'].append({'type': 'power', 'state': 'observado',
                                 'message': 'Plano de energia detectado. Alterar pode aumentar consumo e calor, sem ganho garantido.'})
    except OptimizationError:
        result['errors'].append('Energia: não foi possível ler os planos de energia.')

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
    # P3-06: só orientação; usa o que já foi lido (fatia 2: mais o gpu_bar).
    result['bios_guidance'] = build_bios_guidance(result['hardware'], result['profile'])
    return result


def _atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # FIX-P3-06-06: temporário de nome único na mesma pasta do destino (o
    # os.replace fica no mesmo volume). Se algo falhar, apaga só o temporário
    # desta chamada; nunca mexe em .tmp de outras gravações.
    stream = tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '.', suffix='.tmp',
                                         delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


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


# ---------- P3-03 fatia 2a: plano de energia pelo diário de alterações ----------

POWER_KIND = 'power_plan'
POWER_KEY = 'active_scheme'
# Texto FIXO: nada vindo do usuário entra no comando do PowerShell.
RESTORE_POINT_DESCRIPTION = 'PC Restore Optimizer - antes de ajustes'
_GUID_FULL = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class PowerPlanAdapter:
    """Adaptador do diário (``change_journal``) para o plano de energia ativo.

    ``read`` só lê; ``apply``/``revert`` só rodam ``powercfg /setactive`` com um
    GUID que esteja na lista atual do Windows. Tudo é injetável para os testes:
    ``run(comando)``, ``active()`` e ``plans()``. Sem injeção, as funções do
    módulo são procuradas na hora da chamada.
    """

    kind = POWER_KIND
    label = 'Plano de energia'

    def __init__(self, run=None, active=None, plans=None):
        self._run_fn = run
        self._active_fn = active
        self._plans_fn = plans

    def _check_key(self, key):
        if key != POWER_KEY:
            raise OptimizationError('Ajuste de energia desconhecido; nada alterado.')

    def available(self):
        return (self._plans_fn or available_power_plans)()

    def read(self, key):
        self._check_key(key)
        return str((self._active_fn or active_power_guid)()).lower()

    def _set(self, key, value):
        self._check_key(key)
        guid = value.lower() if isinstance(value, str) else ''
        if not _GUID_FULL.match(guid):
            raise OptimizationError('Plano de energia inválido; nada alterado.')
        if guid not in {str(p.get('guid', '')).lower() for p in self.available()}:
            raise OptimizationError('Plano não consta da lista atual do Windows; nada alterado.')
        (self._run_fn or _run)(['powercfg', '/setactive', guid])

    def apply(self, key, value):
        self._set(key, value)

    def revert(self, key, value):
        self._set(key, value)


_SEQUENCE_QUERY = ('$p = @(Get-ComputerRestorePoint); '
                   'if ($p.Count -gt 0) { ($p | Measure-Object -Property SequenceNumber -Maximum).Maximum '
                   '| ConvertTo-Json } else { 0 | ConvertTo-Json }')
_CHECKPOINT = (f"Checkpoint-Computer -Description '{RESTORE_POINT_DESCRIPTION}' "
               "-RestorePointType 'MODIFY_SETTINGS'")


def _sequence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))
                                     or not value.is_integer()):
        return None
    return int(value)


def create_app_restore_point(_description=None, *, run=None, elevated=None):
    """Cria um ponto de restauração e devolve ``{'sequence': n}`` só se ele foi CONFIRMADO.

    Lê o maior número de sequência, roda ``Checkpoint-Computer`` com a descrição
    fixa e lê de novo: só confirma se o número aumentou (senão, ``None``). Sem
    administrador devolve ``None`` sem rodar nada. Nunca liga a Proteção do
    sistema e nunca muda a frequência de pontos do Windows. Atenção: o Windows não
    cria um ponto novo se já criou um nas últimas 24 horas; nesse caso o número não
    sobe e a resposta é ``None``. A descrição recebida do diário é ignorada de
    propósito.
    """
    try:
        if not (elevated or is_process_elevated)():
            return None
        runner = run or _ps
        before = _sequence(runner(_SEQUENCE_QUERY, timeout=60))
        if before is None:
            return None
        runner(_CHECKPOINT, timeout=300)
        after = _sequence(runner(_SEQUENCE_QUERY, timeout=60))
        if after is None or after <= before:
            return None
        return {'sequence': after}
    except Exception:  # comando, PowerShell ou permissão: não confirmado
        return None


def create_restore_point(_description=None, *, run=None, elevated=None):
    """Como ``create_app_restore_point``, mas só devolve True ou False (uso antigo)."""
    return bool(create_app_restore_point(_description, run=run, elevated=elevated))


# ---------- FIX-M3-T3: reaproveitar o ponto que o próprio app criou ----------
RESTORE_POINT_REUSE_LIMIT = timedelta(hours=24)
RESTORE_POINT_CLOCK_TOLERANCE = timedelta(minutes=15)
RESTORE_POINT_MAX_SEQUENCE = 2 ** 31


def valid_restore_point_sequence(value) -> bool:
    """Número inteiro de verdade (``True`` não vale) entre 1 e 2**31."""
    return (isinstance(value, int) and not isinstance(value, bool)
            and 1 <= value <= RESTORE_POINT_MAX_SEQUENCE)


def parse_utc(text):
    """Data ISO com fuso -> datetime em UTC; sem fuso ou estranha -> None."""
    if not isinstance(text, str):
        return None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _restore_point_query(sequence: int) -> str:
    """Consulta FIXA, só leitura; o número entra formatado por int() (R-07)."""
    number = int(sequence)
    return ('$p=@(Get-ComputerRestorePoint | Where-Object { $_.SequenceNumber -eq %d }); '
            'if ($p.Count -eq 1) { [pscustomobject]@{Sequence=$p[0].SequenceNumber; '
            'Description=$p[0].Description; Created=([Management.ManagementDateTimeConverter]'
            "::ToDateTime($p[0].CreationTime)).ToUniversalTime().ToString('o')} | ConvertTo-Json }"
            % number)


def confirm_app_restore_point(record, *, run=None, elevated=None, now=None):
    """Só leitura: confere no Windows o ponto que o app anotou no diário.

    Devolve a data de criação no Windows (datetime em UTC) ou ``None``. Só confirma
    se: é Windows e o app está como administrador; o registro tem ``sequence``
    válida e ``created`` com fuso; o Windows devolve exatamente um ponto com a
    mesma sequência e a descrição fixa do app; o ponto tem menos de 24 horas (data
    no futuro recusa); e a hora do Windows bate com a anotada (até 15 minutos).
    Qualquer dúvida ou erro dá ``None``. Nunca cria nem muda nada.
    """
    try:
        if not _is_windows():
            return None
        if not (elevated or is_process_elevated)():
            return None
        if not isinstance(record, dict):
            return None
        sequence = record.get('sequence')
        if not valid_restore_point_sequence(sequence):
            return None
        noted = parse_utc(record.get('created'))
        if noted is None:
            return None
        current = datetime.now(timezone.utc) if now is None else now
        if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
            return None
        answer = (run or _ps)(_restore_point_query(sequence), timeout=60)
        if not isinstance(answer, dict):
            return None
        found = answer.get('Sequence')
        if isinstance(found, bool) or not isinstance(found, int) or found != sequence:
            return None
        if answer.get('Description') != RESTORE_POINT_DESCRIPTION:
            return None
        created = parse_utc(answer.get('Created'))
        if created is None:
            return None
        age = current.astimezone(timezone.utc) - created
        if age < timedelta(0) or age >= RESTORE_POINT_REUSE_LIMIT:
            return None
        if abs(created - noted) > RESTORE_POINT_CLOCK_TOLERANCE:
            return None
        return created
    except Exception:  # PowerShell, permissão ou dado estranho: não confirmado
        return None


def legacy_power_pending(journal_path) -> str:
    """Lê (sem gravar) o registro antigo ``pcro-power-1``.

    Devolve ``'none'`` (não existe ou já foi desfeito), ``'applied'`` (troca antiga
    ainda aplicada), ``'pending'`` (interrompida ou com falha) ou ``'unreadable'``
    (ilegível, outro formato, atalho ou pasta).
    """
    path = Path(journal_path)
    if os.path.islink(path):
        return 'unreadable'
    if not path.exists():
        return 'none'
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        return 'unreadable'
    if not isinstance(record, dict) or record.get('schema') != 'pcro-power-1':
        return 'unreadable'
    status = record.get('status')
    if status == 'reverted':
        return 'none'
    if status == 'applied':
        return 'applied'
    if status in ('prepared', 'failed'):
        return 'pending'
    return 'unreadable'


# FIX-P3-06-01: colunas de hardware que podem sair no JSON exportado (allowlist).
# São só as que o perfil (hardware_profile) e a orientação de BIOS (bios_guidance)
# usam. O modelo da placa (Product) fica só na tela, para ajudar a achar o manual.
_EXPORT_COLUMNS = {
    'cpu': ('Name', 'NumberOfCores', 'NumberOfLogicalProcessors'),
    'gpu': ('Name', 'DriverVersion'),
    'ram': ('Capacity', 'Speed', 'ConfiguredClockSpeed', 'Manufacturer', 'DeviceLocator', 'BankLabel'),
    'board': ('Manufacturer',),
    'bios': ('Manufacturer', 'SMBIOSBIOSVersion', 'ReleaseDate'),
    'os': ('Caption', 'Version', 'BuildNumber'),
    'pc': ('Manufacturer', 'PCSystemType'),
    'chassis': ('ChassisTypes',),
    'battery': ('BatteryStatus',),
    'disks': ('MediaType', 'BusType', 'Size'),
}


_DROP = object()


def _export_columns(key, value, columns):
    """Dict ou lista de dicts só com as colunas permitidas; outro valor vira _DROP.

    Bateria: None ou [] quer dizer "o Windows não listou bateria" e é mantido; lista
    com item que não é dict quer dizer "não sei" e sai (o perfil lê o mesmo nos dois).
    """
    def keep(item):
        return {name: copy.deepcopy(item[name]) for name in columns if name in item}
    if key == 'battery' and (value is None or value == []):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return keep(value)
    if isinstance(value, list):
        if key == 'battery' and not all(isinstance(item, dict) for item in value):
            return _DROP
        items = [keep(item) for item in value if isinstance(item, dict)]
        return items if items else _DROP
    return _DROP


def exportable_report(report: dict) -> dict:
    """Cópia do relatório para salvar em arquivo, sem modelo da placa/PC nem colunas extras.

    O relatório original não é alterado (a tela continua mostrando a placa-mãe).
    """
    if not isinstance(report, dict):
        return {}
    result = {key: copy.deepcopy(value) for key, value in report.items() if key != 'hardware'}
    if 'hardware' not in report or not isinstance(report['hardware'], dict):
        return result
    hardware = {}
    for key, columns in _EXPORT_COLUMNS.items():
        if key not in report['hardware']:
            continue
        filtered = _export_columns(key, report['hardware'][key], columns)
        if filtered is not _DROP:
            hardware[key] = filtered
    result['hardware'] = hardware
    return result


def export_snapshot(report: dict, filename: Path):
    filename = Path(filename)
    if filename.suffix.lower() != '.json':
        raise OptimizationError('O relatório deve ser salvo como .json.')
    _atomic_json(filename, exportable_report(report))
    return filename
