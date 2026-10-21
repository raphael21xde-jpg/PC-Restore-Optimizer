"""P2-04 (fatia 2): instala os programas marcados e confere um por um.

Este é o ÚNICO módulo do aplicativo que roda `winget import`. Regras:
- só instala o que a pessoa marcou e confirmou (a tela pede a confirmação);
- só pacotes da fonte `winget` (fonte fixa no código), sem versões e nunca o
  `ppy.osu` (o winget instalaria o osu!lazer, que é outro jogo);
- recusa se o aplicativo estiver como administrador, fora do Windows ou sem
  winget; nunca pede elevação e nunca aceita termos pela pessoa;
- antes e depois do `import`, confere pacote a pacote com `winget list`;
- grava o arquivo de importação e o relatório numa pasta NOVA em
  %LOCALAPPDATA%\\PC-Restore-Optimizer\\instalacoes-winget\\; nada vai para
  dentro do backup e nada é apagado.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from app_recovery import command as recovery_command, package_id
from elevation_guard import is_process_elevated

APP_FOLDER = 'PC-Restore-Optimizer'
RUNS_FOLDER = 'instalacoes-winget'
IMPORT_NAME = 'importar.json'
OUTPUT_NAME = 'saida-winget.txt'
REPORT_JSON = 'relatorio.json'
REPORT_TXT = 'relatorio.txt'
IMPORT_TIMEOUT_SEC = 2 * 60 * 60   # 2 h; ao acabar, o app só para de esperar
LIST_TIMEOUT_SEC = 90

# Fonte fixa: o arquivo de importação nunca copia a fonte do backup.
WINGET_SOURCE = {
    'Argument': 'https://cdn.winget.microsoft.com/cache',
    'Identifier': 'Microsoft.Winget.Source_8wekyb3d8bbwe',
    'Name': 'winget',
    'Type': 'Microsoft.PreIndexed.Package',
}

STATUS_INSTALLED = 'instalado'
STATUS_ALREADY = 'já instalado'
STATUS_FAILED = 'não instalado'

ELEVATED_TEXT = ('O aplicativo está aberto como administrador. Para instalar os programas, '
                 'feche o aplicativo e abra de novo pelo atalho normal, sem usar "Executar como '
                 'administrador". Nada foi instalado.')
NOT_WINDOWS_TEXT = 'A instalação de programas só funciona no Windows. Nada foi instalado.'
NO_WINGET_TEXT = ('O winget não foi encontrado neste computador. Atualize o "Instalador de '
                  'Aplicativo" pela Microsoft Store e tente de novo. Nada foi instalado.')
NOTHING_SELECTED_TEXT = 'Nenhum programa que o winget possa instalar foi marcado. Nada foi instalado.'
FOLDER_ERROR_TEXT = ('Não foi possível criar a pasta de trabalho da instalação (sem permissão '
                     'ou disco cheio). Nada foi instalado.')
RUN_ERROR_TEXT = ('Não foi possível iniciar o winget. A conferência abaixo mostra o que está '
                  'instalado agora.')
UNEXPECTED_TEXT = 'Não foi possível concluir a instalação por um erro inesperado.'
REPORT_ERROR_TEXT = 'Não foi possível gravar o relatório (sem permissão ou disco cheio).'

EXPLAIN_HASH = ('O arquivo baixado não bateu com o esperado (hash diferente). Por segurança, '
                'instale pelo site oficial do programa.')
EXPLAIN_NOT_FOUND = ('Programa não encontrado no winget (pode ter mudado de nome ou saído da '
                     'lista). Procure no site oficial do programa.')
EXPLAIN_ADMIN = ('Este programa precisa de administrador: instale sozinho pelo site oficial e '
                 'aceite o aviso do Windows.')
EXPLAIN_ALREADY = 'Já instalado, segundo o winget (confira no menu Iniciar).'
EXPLAIN_AGREEMENT = ('O winget pediu para aceitar os termos de uso. Instale este programa '
                     'sozinho pelo site oficial (ou pelo winget, aceitando os termos você mesmo).')
EXPLAIN_UNKNOWN = 'Não deu para confirmar a instalação. Instale pelo site oficial do programa.'

# Ordem importa: a primeira regra que combinar decide.
_EXPLANATIONS = (
    (EXPLAIN_HASH, ('hash',)),
    (EXPLAIN_NOT_FOUND, ('not found', 'no package found', 'não encontrado', 'nao encontrado',
                         'nenhum pacote encontrado', '0x8a150014')),
    (EXPLAIN_ADMIN, ('administrator', 'administrador', 'access denied', 'access is denied',
                     'acesso negado', '0x80070005')),
    (EXPLAIN_ALREADY, ('already installed', 'já instalado', 'já está instalado',
                       'ja instalado', 'ja esta instalado')),
    (EXPLAIN_AGREEMENT, ('agreement', 'contrato', 'termos')),
)

_ID_CHARS = r'A-Za-z0-9._+-'


def _platform_is_windows():
    return os.name == 'nt'


def _find_winget():
    return shutil.which('winget')


def _timestamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def _no_window():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


def default_state_dir():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        return None
    return Path(base) / APP_FOLDER / RUNS_FOLDER


def _id_pattern(pid):
    return re.compile(rf'(?<![{_ID_CHARS}]){re.escape(pid)}(?![{_ID_CHARS}])', re.IGNORECASE)


# ---------------------------------------------------------------- documento

def _installable(package):
    if not isinstance(package, dict) or package.get('selectable') is not True:
        return None
    if str(package.get('source') or '').casefold() != 'winget':
        return None
    try:
        pid = package_id(str(package.get('id') or ''))
    except ValueError:
        return None
    if pid.casefold() == 'ppy.osu':
        return None
    return pid


def installable_ids(packages, selected_ids):
    """IDs marcados que o winget pode instalar, na ordem da lista, sem repetição."""
    wanted = {str(i).strip().casefold() for i in (selected_ids or ()) if isinstance(i, str)}
    chosen, seen = [], set()
    for package in packages or ():
        pid = _installable(package)
        if pid is None or pid.casefold() not in wanted or pid.casefold() in seen:
            continue
        seen.add(pid.casefold())
        chosen.append(pid)
    return chosen


def _document(ids):
    return {
        '$schema': 'https://aka.ms/winget-packages.schema.2.0.json',
        'CreationDate': datetime.now().isoformat(timespec='seconds'),
        'Sources': [{'Packages': [{'PackageIdentifier': pid} for pid in ids],
                     'SourceDetails': dict(WINGET_SOURCE)}],
        'WinGetVersion': '1.0',
    }


def build_import_document(packages, selected_ids):
    """Arquivo de importação só com os marcados válidos. Lista vazia → ValueError."""
    ids = installable_ids(packages, selected_ids)
    if not ids:
        raise ValueError(NOTHING_SELECTED_TEXT)
    return _document(ids)


def _atomic_text(path, text):
    """Grava em arquivo temporário e troca de uma vez. Em falha o temporário fica."""
    path = Path(path)
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with open(temp, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    os.replace(temp, path)


def _new_run_dir(state_dir):
    state_dir = Path(state_dir)
    os.makedirs(state_dir, exist_ok=True)
    stamp = _timestamp()
    for attempt in range(1, 21):
        candidate = state_dir / (stamp if attempt == 1 else f'{stamp}-{attempt}')
        try:
            os.mkdir(candidate)  # falha se já existir: nunca reaproveita uma pasta
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError('pasta de instalação já existe')


def prepare_run(state_dir, document):
    """Cria a pasta nova da instalação e grava importar.json. Devolve (pasta, arquivo)."""
    run_dir = _new_run_dir(state_dir)
    import_path = run_dir / IMPORT_NAME
    _atomic_text(import_path, json.dumps(document, indent=2, ensure_ascii=False))
    return run_dir, import_path


def import_command(path, executable='winget'):
    return [str(executable), 'import', '--import-file', str(path), '--ignore-unavailable',
            '--no-upgrade', '--disable-interactivity']


# ---------------------------------------------------------------- winget

def _default_runner(cmd):
    """Roda o winget sem shell e sem entrada. Devolve (código, saída).

    No `import`, a saída vai para um arquivo na pasta da instalação e o app
    espera até 2 h; se o tempo acabar, devolve código None e NÃO encerra o
    winget nem os instaladores (interromper um instalador pode estragá-lo).
    """
    cmd = [str(part) for part in cmd]
    if len(cmd) > 1 and cmd[1] == 'import':
        folder = Path(cmd[cmd.index('--import-file') + 1]).parent
        log_path = folder / OUTPUT_NAME
        with open(log_path, 'wb') as log:
            proc = subprocess.Popen(cmd, shell=False, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=_no_window())
            try:
                code = proc.wait(timeout=IMPORT_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                code = None
        try:
            with open(log_path, 'rb') as log:
                output = log.read(2 * 1024 * 1024).decode('utf-8', errors='replace')
        except OSError:
            output = ''
        return code, output
    result = subprocess.run(cmd, shell=False, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=LIST_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
                            creationflags=_no_window())
    return result.returncode, ((result.stdout or '') + '\n' + (result.stderr or '')).strip()


def check_installed(pid, runner, executable='winget'):
    """True só com código 0 e o ID exato na saída do `winget list`."""
    try:
        code, output = runner(recovery_command('list', pid, executable))
    except Exception:
        return False
    return code == 0 and bool(_id_pattern(pid).search(str(output or '')))


def _segment(pid, output, all_ids):
    output = str(output or '')
    found = _id_pattern(pid).search(output)
    if not found:
        return ''
    start = found.end()
    end = len(output)
    for other in all_ids or ():
        if not isinstance(other, str) or other.casefold() == pid.casefold():
            continue
        try:
            nxt = _id_pattern(other).search(output, start)
        except re.error:
            continue
        if nxt:
            end = min(end, nxt.start())
    return output[start:end]


def explain_failure(pid, output, all_ids=()):
    """Explicação simples para um pacote que não ficou instalado.

    Só olha o trecho da saída entre este ID e o próximo ID selecionado.
    """
    text = _segment(pid, output, all_ids).casefold()
    if text:
        for explanation, terms in _EXPLANATIONS:
            if any(term in text for term in terms):
                return explanation
    return EXPLAIN_UNKNOWN


# ---------------------------------------------------------------- execução

def _result(status, message, results=(), report_dir=None, timed_out=False):
    return {'status': status, 'message': message, 'results': list(results),
            'report_dir': str(report_dir) if report_dir else None, 'timed_out': timed_out}


def _write_report(run_dir, results, *, timed_out, winget_code):
    data = {
        'formato': 1,
        'data': datetime.now().isoformat(timespec='seconds'),
        'tempo_esgotado': bool(timed_out),
        'codigo_winget': winget_code,
        'pacotes': [{'id': r['id'], 'status': r['status'], 'explicacao': r['explanation']}
                    for r in results],
    }
    _atomic_text(Path(run_dir) / REPORT_JSON, json.dumps(data, indent=2, ensure_ascii=False))
    lines = ['Programas do backup: resultado da instalação',
             f'Data: {data["data"]}', '']
    lines += [f'{r["id"]}: {r["status"]}' + (f' — {r["explanation"]}' if r['explanation'] else '')
              for r in results]
    if timed_out:
        lines += ['', 'O tempo de espera acabou; a conferência foi feita mesmo assim.']
    _atomic_text(Path(run_dir) / REPORT_TXT, '\n'.join(lines) + '\n')


def run_install(packages, selected_ids, *, runner=None, state_dir=None, elevated_probe=None,
                executable=None):
    """Instala os marcados e confere um por um. Nunca levanta exceção."""
    try:
        return _run_install(packages, selected_ids, runner or _default_runner, state_dir,
                            elevated_probe, executable)
    except Exception:
        return _result('falhou', UNEXPECTED_TEXT)


def _run_install(packages, selected_ids, runner, state_dir, elevated_probe, executable):
    if is_process_elevated(elevated_probe):
        return _result('recusado', ELEVATED_TEXT)
    if not _platform_is_windows():
        return _result('indisponivel', NOT_WINDOWS_TEXT)
    if executable is None:
        executable = _find_winget()
        if not executable:
            return _result('indisponivel', NO_WINGET_TEXT)
    ids = installable_ids(packages, selected_ids)
    if not ids:
        return _result('recusado', NOTHING_SELECTED_TEXT)
    if state_dir is None:
        state_dir = default_state_dir()
        if state_dir is None:
            return _result('falhou', FOLDER_ERROR_TEXT)

    # 1) confere antes: quem já está instalado fica fora do arquivo
    already = {pid for pid in ids if check_installed(pid, runner, executable)}
    pending = [pid for pid in ids if pid not in already]

    try:
        if pending:
            run_dir, import_path = prepare_run(state_dir, _document(pending))
        else:
            run_dir, import_path = _new_run_dir(state_dir), None
    except OSError:
        return _result('falhou', FOLDER_ERROR_TEXT)

    # 2) roda o import (só se sobrou algo)
    output, code, timed_out, run_failed = '', None, False, False
    if import_path is not None:
        try:
            code, output = runner(import_command(import_path, executable))
            timed_out = code is None
        except subprocess.TimeoutExpired:
            timed_out = True
        except Exception:
            run_failed = True

    # 3) confere de novo, pacote a pacote
    results = []
    for pid in ids:
        if pid in already:
            results.append({'id': pid, 'status': STATUS_ALREADY, 'explanation': ''})
        elif not run_failed and check_installed(pid, runner, executable):
            results.append({'id': pid, 'status': STATUS_INSTALLED, 'explanation': ''})
        else:
            results.append({'id': pid, 'status': STATUS_FAILED,
                            'explanation': explain_failure(pid, output, ids)})

    ok = sum(1 for r in results if r['status'] != STATUS_FAILED)
    parts = [f'{ok} de {len(results)} programa(s) instalados ou já presentes.']
    if timed_out:
        parts.append('O tempo de espera (2 horas) acabou; algum instalador pode ainda estar '
                     'aberto. A conferência foi feita mesmo assim.')
    if run_failed:
        parts.append(RUN_ERROR_TEXT)
    try:
        _write_report(run_dir, results, timed_out=timed_out, winget_code=code)
        parts.append(f'Relatório salvo em: {run_dir}')
    except OSError:
        parts.append(REPORT_ERROR_TEXT)
    return _result('falhou' if run_failed else 'concluido', ' '.join(parts), results, run_dir,
                   timed_out)
