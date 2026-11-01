"""P3-07: check-up de segurança, somente leitura.

Olha os programas que abrem com o Windows (chaves Run/RunOnce e pastas de
Inicialização), as tarefas agendadas (fatia 2) e os processos em execução, e
marca cada item como OK, atenção ou suspeito, com o motivo em português simples.

Regras desta fatia:
- só lê: nada é mudado, encerrado ou tirado do lugar, e não pede administrador;
- da linha de comando de um programa só fica o executável (argumentos podem
  ter senhas ou tokens); dos processos só o nome e o caminho do executável;
  das tarefas agendadas só a pasta, o nome e o executável (os argumentos nem
  são pedidos ao Windows);
- a pasta do usuário vira %USERPROFILE%, a de outros usuários vira
  "<outro usuário>" e o nome do usuário (palavra inteira) vira %USERNAME%,
  só no texto mostrado: a classificação usa o caminho original; um SID
  (como S-1-5-21-...) vira <SID>;
- na dúvida o item fica "atenção", nunca "OK";
- as funções são puras e recebem os dados já lidos; o PowerShell real só é
  usado por ``read_checkup`` quando nenhum ``ps`` é passado (importado na hora,
  de ``optimization_engine``).
"""
from __future__ import annotations

import ntpath
import os
import re

STATE_OK = 'OK'
STATE_ATTENTION = 'atenção'
STATE_SUSPECT = 'suspeito'
_STATES = (STATE_OK, STATE_ATTENTION, STATE_SUSPECT)

CHECKUP_CONFIRMATION = (
    'O check-up vai só ler a lista de programas que abrem com o Windows, das tarefas '
    'agendadas e dos programas abertos agora (processos), com o lugar de onde cada um roda.\n\n'
    'Nada é mudado, encerrado ou tirado do lugar, e não precisa de administrador. '
    'Pode levar alguns segundos.\n\nContinuar?')

NEVER_CHANGES = ('O app só olha: não muda, não encerra e não tira nada do lugar. '
                 'Este check-up não substitui um programa de segurança.')
RECOMMENDATION = (
    'Recomendação: abra a Segurança do Windows, entre em "Opções de verificação" e faça a '
    '"Verificação offline do Microsoft Defender" (o PC reinicia para isso; salve antes o que '
    'estiver aberto). Para uma segunda opinião, use o Malwarebytes, baixado só do site oficial.')
NOT_CERTAIN = ('"Suspeito" não é certeza de problema: é um sinal para conferir. '
               '"Atenção" quer dizer que vale a pena saber o que é.')
TASKS_NOTE = 'Sem administrador, o Windows pode não mostrar algumas tarefas.'
TASKS_EMPTY = ('Nenhuma tarefa agendada para mostrar (as da Microsoft que rodam da pasta do '
               'Windows não aparecem).')
ALL_CLEAR = 'Nos itens conferidos não apareceu nenhum sinal de alerta.'
NOT_ALL_CHECKED = ('Nenhum item conferido ficou como atenção ou suspeito, mas o check-up '
                   'não conseguiu conferir tudo (veja acima).')

# Nomes de programas do Windows que só deveriam rodar de System32/SysWOW64.
SYSTEM_NAMES = ('svchost.exe', 'csrss.exe', 'lsass.exe', 'winlogon.exe', 'services.exe',
                'smss.exe', 'dllhost.exe', 'conhost.exe', 'taskhostw.exe', 'rundll32.exe')
# O explorer.exe fica direto na pasta do Windows (ou em SysWOW64).
EXPLORER = 'explorer.exe'
SCRIPT_EXTENSIONS = ('.vbs', '.ps1', '.js', '.bat', '.cmd')
SHORTCUT_EXTENSIONS = ('.lnk', '.url')
# Programas do Windows que abrem scripts: o script em si não é conferido.
SCRIPT_HOSTS = ('wscript.exe', 'cscript.exe', 'mshta.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe')

REASON_OK = 'ok'
REASON_SYSTEM_NAME = 'system_name'
REASON_TEMP = 'temp'
REASON_APPDATA = 'appdata'
REASON_PROGRAMDATA = 'programdata'
REASON_DRIVE_ROOT = 'drive_root'
REASON_SCRIPT = 'script'
REASON_SCRIPT_HOST = 'script_host'
REASON_SHORTCUT = 'shortcut'
REASON_STARTUP_FILE = 'startup_file'
REASON_UNREADABLE = 'unreadable'
REASON_NOT_FULL_PATH = 'not_full_path'
REASON_OTHER_PLACE = 'other_place'
REASON_COM_HANDLER = 'com_handler'
REASON_MS_FOLDER_OUTSIDE = 'ms_folder_outside'

REASON_TEXTS = {
    REASON_OK: 'Fica numa pasta de programas do Windows (Windows ou Arquivos de Programas).',
    REASON_SYSTEM_NAME: ('Tem o nome de um programa do próprio Windows, mas não está na pasta do '
                         'Windows. Programas indesejados costumam se disfarçar assim.'),
    REASON_TEMP: 'Roda de uma pasta temporária. Programas comuns quase nunca rodam de lá.',
    REASON_APPDATA: ('Roda da pasta AppData. Alguns programas comuns ficam lá (como navegadores '
                     'e apps de conversa), mas é também onde programas indesejados se escondem.'),
    REASON_PROGRAMDATA: ('Roda da pasta ProgramData. Alguns programas comuns usam essa pasta, '
                         'mas ela também é usada por programas indesejados.'),
    REASON_DRIVE_ROOT: 'Fica direto na raiz de uma unidade (como C:\\), lugar incomum para um programa.',
    REASON_SCRIPT: 'É um script (arquivo de comandos) que abre direto, sem um programa instalado por trás.',
    REASON_SCRIPT_HOST: 'Abre um script por meio de um programa do Windows; o app não confere o que o script faz.',
    REASON_SHORTCUT: 'É um atalho na pasta Inicialização; o app não confere para onde ele aponta.',
    REASON_STARTUP_FILE: 'É um arquivo colocado direto na pasta Inicialização.',
    REASON_UNREADABLE: 'O caminho veio vazio ou não pôde ser lido.',
    REASON_NOT_FULL_PATH: 'O caminho completo não está escrito; o app não confere de onde ele abre.',
    REASON_OTHER_PLACE: 'Fica fora das pastas de programas do Windows (Windows ou Arquivos de Programas).',
    REASON_COM_HANDLER: ('A tarefa abre um componente do Windows em vez de um arquivo de programa; '
                         'o app não confere o que esse componente faz.'),
    REASON_MS_FOLDER_OUTSIDE: ('Está na pasta de tarefas da Microsoft, mas roda de fora da pasta do '
                               'Windows.'),
}
ADVICE_TEXTS = {
    STATE_SUSPECT: ('Não mexa no arquivo por conta própria. Faça a verificação recomendada '
                    'no fim desta lista.'),
    STATE_ATTENTION: ('Confira se você reconhece este programa. Se não reconhecer, faça a '
                      'verificação recomendada no fim desta lista.'),
}

SOURCE_TEXTS = {
    'run_user': 'registro, só este usuário',
    'runonce_user': 'registro, só este usuário, abre uma vez',
    'run_all': 'registro, todos os usuários',
    'runonce_all': 'registro, todos os usuários, abre uma vez',
    'startup_user': 'pasta Inicialização deste usuário',
    'startup_all': 'pasta Inicialização de todos os usuários',
    'task': 'tarefa agendada',
}
_STARTUP_SOURCES = ('startup_user', 'startup_all')

ERROR_TEXTS = {
    'run': 'Programas que abrem com o Windows (registro): não foi possível ler.',
    'run_part': 'Não foi possível ler parte das chaves do registro de inicialização.',
    'startup': 'Pastas de Inicialização: não foi possível ler.',
    'startup_part': 'Não foi possível ler parte das pastas de Inicialização.',
    'processes': 'Processos em execução: não foi possível ler.',
    'tasks': 'Tarefas agendadas: não foi possível ler.',
}
ERROR_GENERIC = 'Parte do check-up: não foi possível ler.'

RUN_KEYS = (
    r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    r'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
    r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
    r'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
    r'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce',
)
# Só leitura. Cada chave é lida em separado: uma chave negada vira {Error} e
# não derruba as outras. As propriedades PS* são as que o PowerShell acrescenta.
RUN_QUERY = (
    '$keys=@(' + ','.join("'" + key + "'" for key in RUN_KEYS) + '); '
    "$skip=@('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider'); "
    '$out=foreach($k in $keys){ if(Test-Path -LiteralPath $k){ '
    'try{ $p=Get-ItemProperty -LiteralPath $k; '
    'foreach($prop in $p.PSObject.Properties){ if($skip -notcontains $prop.Name){ '
    '[pscustomobject]@{Key=$k;Name=$prop.Name;Command=[string]$prop.Value} } } } '
    'catch{ [pscustomobject]@{Key=$k;Error=$true} } } }; '
    'ConvertTo-Json -InputObject @($out) -Compress')
# Só nome e extensão dos arquivos: o caminho da pasta (com o nome do usuário) não sai.
STARTUP_QUERY = (
    "$dirs=@([Environment]::GetFolderPath('Startup'),[Environment]::GetFolderPath('CommonStartup')); "
    '$out=foreach($i in 0..1){ $d=$dirs[$i]; if($d -and (Test-Path -LiteralPath $d)){ '
    'try{ Get-ChildItem -LiteralPath $d -File -Force | ForEach-Object { '
    '[pscustomobject]@{Scope=$i;Name=$_.Name;Extension=$_.Extension} } } '
    'catch{ [pscustomobject]@{Scope=$i;Error=$true} } } }; '
    'ConvertTo-Json -InputObject @($out) -Compress')
# -Property: o Windows nem chega a entregar os outros campos (como a linha de comando).
PROCESS_QUERY = ('Get-CimInstance Win32_Process -Property Name,ExecutablePath | '
                 'Select-Object Name,ExecutablePath | ConvertTo-Json -Compress')

# Só a pasta, o nome e o executável de cada ação; Arguments e WorkingDirectory
# nem são pedidos (podem ter senha ou token). Ação COM não tem arquivo: Com=$true.
TASK_QUERY = (
    '$out=foreach($t in @(Get-ScheduledTask)){ foreach($a in @($t.Actions)){ '
    '[pscustomobject]@{TaskPath=[string]$t.TaskPath;TaskName=[string]$t.TaskName;'
    'Execute=[string]$a.Execute;'
    "Com=($a.CimClass.CimClassName -eq 'MSFT_TaskComHandlerAction')} } }; "
    'ConvertTo-Json -InputObject @($out) -Compress')
MS_TASK_FOLDER = '\\microsoft\\'

_DRIVE_PATH = re.compile(r'^[a-z]:\\')
_DRIVE_ROOT_FILE = re.compile(r'^[a-z]:\\[^\\]+$')
_ENV_VAR = re.compile(r'%([^%]+)%')
# C:\Users\<nome>, C:\Documents and Settings\<nome> e \\servidor\users\<nome>.
_OTHER_USER = re.compile(r'((?:[A-Za-z]:|\\\\[^\\/"]+)[\\/](?:Users|Documents and Settings)[\\/])([^\\/"]+)',
                         re.IGNORECASE)
# Marcadores que a troca do nome do usuário não pode estragar.
_PLACEHOLDERS = ('%USERPROFILE%', '%USERNAME%', '<outro usuário>')
_KEEP_USERS = ('public', 'default', 'default user', 'all users', '<outro usuário>')
# A extensão termina quando não vem letra, número ou "_" colado (app.exe--token=X vira app.exe).
_COMMAND_EXE = re.compile(r'^(.*?\.(?:exe|bat|cmd|vbs|ps1|js))(?![A-Za-z0-9_])', re.IGNORECASE)
_NT_PREFIX = re.compile(r'^(?:\\\\\?\\|\\\?\?\\)(UNC\\)?', re.IGNORECASE)
_SID = re.compile(r'(?<![A-Za-z0-9])S-1-\d+(?:-\d+)+(?![0-9])', re.IGNORECASE)
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
MAX_NAME = 80


def _env(env):
    return os.environ if env is None else env


def _env_get(env, name):
    wanted = name.lower()
    for key, value in env.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str) and value.strip():
            return value
    return None


def _as_list(value):
    """Saída do ConvertTo-Json: None, um objeto, uma lista ou {"value": [...]} (PS 5.1)."""
    if value is None:
        return []
    if isinstance(value, dict):
        inner = value.get('value')
        if isinstance(inner, list):
            return inner
        return [value]
    if isinstance(value, list):
        return value
    return []


def sanitize_path(path, env=None) -> str:
    """Esconde nomes de usuário: a pasta do usuário vira %USERPROFILE%; outras, <outro usuário>.

    Compara sem diferenciar maiúsculas (R-01), mas mantém a grafia original do resto.
    """
    if not isinstance(path, str):
        return ''
    env = _env(env)
    text = path
    profile = _env_get(env, 'USERPROFILE')
    if profile:
        base = profile.strip().rstrip('\\/')
        if base:
            pattern = r'[\\/]'.join(re.escape(part) for part in re.split(r'[\\/]', base))
            text = re.sub('(?i)' + pattern + r'(?=[\\/"\s]|$)', lambda m: '%USERPROFILE%', text)

    def other(match):
        if match.group(2).strip().lower() in _KEEP_USERS:
            return match.group(0)
        return match.group(1) + '<outro usuário>'
    text = _OTHER_USER.sub(other, text)
    return _SID.sub('<SID>', _hide_user_name(text, env))


def _hide_user_name(text, env):
    """Troca o USERNAME (palavra inteira, sem diferenciar maiúsculas) por %USERNAME%.

    Só muda o texto mostrado. Nome de uma letra só não é trocado (não identifica
    ninguém e estragaria "C:"). Os marcadores já colocados ficam como estão.
    """
    user = _env_get(env, 'USERNAME')
    user = user.strip() if user else ''
    if len(user) < 2:
        return text
    protected = '|'.join(re.escape(p) for p in _PLACEHOLDERS)
    pattern = re.compile('(' + protected + r')|(?<![\w%])' + re.escape(user) + r'(?![\w%])',
                         re.IGNORECASE)
    return pattern.sub(lambda m: m.group(1) or '%USERNAME%', text)


def _clean_name(value, env) -> str:
    if not isinstance(value, str):
        return ''
    text = _CONTROL.sub(' ', sanitize_path(value, env)).strip()
    return text[:MAX_NAME] + ('...' if len(text) > MAX_NAME else '')


def executable_from_command(cmd) -> str:
    """Só o executável de uma linha de comando; os argumentos são descartados."""
    if not isinstance(cmd, str):
        return ''
    text = cmd.strip()
    if not text:
        return ''
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 0:
            return _only_if_not_argument(text[1:end].strip())
        # Aspa sem fechar: o resto pode ter argumentos; só fica o que termina numa extensão.
        found = _COMMAND_EXE.match(text[1:])
        return _only_if_not_argument(_no_space(found.group(1).strip())) if found else ''
    found = _COMMAND_EXE.match(text)
    if found:
        return _only_if_not_argument(_no_space(found.group(1).strip()))
    # Sem extensão conhecida: só o primeiro pedaço.
    return _only_if_not_argument(text.split()[0])


def _command_guess(cmd) -> str:
    """Trecho até a primeira extensão, sem as travas de argumento: só para classificar, nunca mostrado."""
    if not isinstance(cmd, str):
        return ''
    text = cmd.strip().lstrip('"')
    found = _COMMAND_EXE.match(text)
    return found.group(1).strip() if found else ''


def _no_space(exe) -> str:
    """Sem aspas fechadas, o executável não pode ter espaço (R-40).

    A busca pela extensão pode atravessar argumentos até um segundo caminho
    (ex.: ``app SEGREDO C:\\a.exe``); como não dá para saber onde termina o
    executável, nada é mostrado e o item fica "atenção".
    """
    return '' if any(ch.isspace() for ch in exe) else exe


def _only_if_not_argument(exe) -> str:
    """Devolve '' se algum pedaço (separado por espaço) parece argumento (R-40).

    A busca pela extensão pode atravessar espaços até um segundo caminho
    (ex.: ``prog --token=X C:\\a.exe``); um pedaço que começa com "-" ou "/", ou que
    tem "=" ou ",", pode ser senha ou token, e nunca é mostrado. O item vira "atenção".
    """
    for piece in exe.split():
        if piece[:1] in ('-', '/') or '=' in piece or ',' in piece:
            return ''
    return exe


def _command_is_malformed(cmd, exe) -> bool:
    """Aspa sem fechar, ou algo colado logo depois do executável: na dúvida, nunca OK."""
    if not isinstance(cmd, str) or not exe:
        return False
    text = cmd.strip()
    if text.startswith('"'):
        return text.find('"', 1) < 0
    rest = text[len(exe):] if text.lower().startswith(exe.lower()) else ''
    return bool(rest) and not rest[0].isspace() and rest[0] != ','


def _nt_literal_end(path) -> bool:
    """Caminho com \\\\?\\ ou \\??\\ que o Windows não normaliza: nunca pode dar OK.

    Com esses prefixos o Windows não tira espaço (qualquer um, inclusive Unicode)
    nem ponto do fim e não resolve os pedaços "." e "..": é outro arquivo, e
    comparar o caminho normalizado daria uma pasta que não é a de verdade.
    """
    if not isinstance(path, str) or not path:
        return False
    found = _NT_PREFIX.match(path.lstrip())
    if not found:
        return False
    if path[-1].isspace() or path[-1] == '.':
        return True
    return any(part in ('.', '..') for part in re.split(r'[\\/]', path.lstrip()[found.end():]))


def _strip_nt_prefix(path):
    """Tira os prefixos \\\\?\\ e \\??\\ do Windows; \\\\?\\UNC\\ vira \\\\."""
    if not isinstance(path, str):
        return path
    found = _NT_PREFIX.match(path)
    if not found:
        return path
    rest = path[found.end():]
    return '\\\\' + rest if found.group(1) else rest


def _expand(path, env):
    def repl(match):
        value = _env_get(env, match.group(1))
        if not value and match.group(1).lower() in ('windir', 'systemroot'):
            # As tarefas do Windows usam %windir%; as duas variáveis são a mesma pasta.
            value = _env_get(env, 'SystemRoot') or _env_get(env, 'windir')
        return value if value else match.group(0)
    return _ENV_VAR.sub(repl, path)


def _key(path):
    return ntpath.normcase(ntpath.normpath(path))


def _under(norm, base):
    if not base:
        return False
    root = _key(base).rstrip('\\')
    return bool(root) and norm.startswith(root + '\\')


def classify_path(name, path, env=None):
    """Devolve (estado, motivo) para um executável. Na dúvida, "atenção"; nunca OK."""
    env = _env(env)
    if not isinstance(path, str) or not path.strip():
        return STATE_ATTENTION, REASON_UNREADABLE
    state, reason = _classify_clean(name, _strip_nt_prefix(path.strip()), env)
    if state == STATE_OK and _nt_literal_end(path):
        # Ex.: "\\\\?\\C:\\Windows\\System32\\svchost.exe " não é o svchost do Windows.
        base = ntpath.basename(_key(path.strip()))
        claimed = name.strip().lower() if isinstance(name, str) else ''
        if base in SYSTEM_NAMES or claimed in SYSTEM_NAMES or EXPLORER in (base, claimed):
            return STATE_SUSPECT, REASON_SYSTEM_NAME
        return STATE_ATTENTION, REASON_OTHER_PLACE
    return state, reason


def _classify_clean(name, path, env):
    norm = _key(_expand(path, env))
    base = ntpath.basename(norm)
    claimed = name.strip().lower() if isinstance(name, str) else ''
    if not _DRIVE_PATH.match(norm) and not norm.startswith('\\\\'):
        return STATE_ATTENTION, REASON_NOT_FULL_PATH
    system_root = _env_get(env, 'SystemRoot') or _env_get(env, 'windir') or 'C:\\Windows'
    root_key = _key(system_root).rstrip('\\')
    parent = ntpath.dirname(norm)
    if base in SYSTEM_NAMES or claimed in SYSTEM_NAMES:
        if parent not in (root_key + '\\system32', root_key + '\\syswow64') or base != (claimed or base):
            return STATE_SUSPECT, REASON_SYSTEM_NAME
    if base == EXPLORER or claimed == EXPLORER:
        if parent not in (root_key, root_key + '\\syswow64') or base != (claimed or base):
            return STATE_SUSPECT, REASON_SYSTEM_NAME
    if ntpath.splitext(norm)[1] in SCRIPT_EXTENSIONS:
        return STATE_ATTENTION, REASON_SCRIPT
    if ('\\temp\\' in norm or '\\tmp\\' in norm
            or _under(norm, _env_get(env, 'TEMP')) or _under(norm, _env_get(env, 'TMP'))):
        return STATE_ATTENTION, REASON_TEMP
    if ('\\appdata\\' in norm or _under(norm, _env_get(env, 'LOCALAPPDATA'))
            or _under(norm, _env_get(env, 'APPDATA'))):
        return STATE_ATTENTION, REASON_APPDATA
    if re.match(r'^[a-z]:\\programdata\\', norm) or _under(norm, _env_get(env, 'ProgramData')):
        return STATE_ATTENTION, REASON_PROGRAMDATA
    if _DRIVE_ROOT_FILE.match(norm):
        return STATE_ATTENTION, REASON_DRIVE_ROOT
    program_dirs = (system_root, _env_get(env, 'ProgramFiles') or 'C:\\Program Files',
                    _env_get(env, 'ProgramFiles(x86)') or 'C:\\Program Files (x86)',
                    _env_get(env, 'ProgramW6432'))
    if any(_under(norm, folder) for folder in program_dirs):
        return STATE_OK, REASON_OK
    return STATE_ATTENTION, REASON_OTHER_PLACE


def _item(source, name, path, state, reason, env, count=1):
    return {'source': source, 'name': _clean_name(name, env), 'path': sanitize_path(path, env),
            'state': state, 'reason': reason, 'count': count}


def classify_autostart(entries, env=None):
    """Classifica as entradas de inicialização (chaves Run/RunOnce e pastas de Inicialização)."""
    env = _env(env)
    items = []
    for entry in _as_list(entries):
        if not isinstance(entry, dict):
            continue
        source = entry.get('source')
        name = entry.get('name')
        if source in _STARTUP_SOURCES:
            ext = entry.get('extension')
            ext = ext.lower() if isinstance(ext, str) else ''
            if ext in SHORTCUT_EXTENSIONS:
                reason = REASON_SHORTCUT
            elif ext in SCRIPT_EXTENSIONS:
                reason = REASON_SCRIPT
            else:
                reason = REASON_STARTUP_FILE
            items.append(_item(source, name, '', STATE_ATTENTION, reason, env))
            continue
        command = entry.get('command')
        exe = executable_from_command(command)
        state, reason = classify_path(None, exe, env)
        if not exe:
            # Nada é mostrado, mas um nome de sistema fora da pasta do Windows continua suspeito.
            guess = _command_guess(command)
            if guess and classify_path(None, guess, env)[0] == STATE_SUSPECT:
                state, reason = STATE_SUSPECT, REASON_SYSTEM_NAME
        if state == STATE_OK and _command_is_malformed(command, exe):
            state, reason = STATE_ATTENTION, REASON_NOT_FULL_PATH
        if state == STATE_OK and ntpath.basename(_key(exe)) in SCRIPT_HOSTS:
            state, reason = STATE_ATTENTION, REASON_SCRIPT_HOST
        items.append(_item(source, name, exe, state, reason, env))
    return items


def classify_processes(procs, env=None):
    """Agrupa processos iguais (nome + caminho). Sem caminho = "não conferido"."""
    env = _env(env)
    grouped = {}
    unchecked = 0
    for proc in _as_list(procs):
        if not isinstance(proc, dict):
            continue
        name = proc.get('Name')
        path = proc.get('ExecutablePath')
        if not isinstance(path, str) or not path.strip():
            unchecked += 1
            continue
        key = ((name or '').lower() if isinstance(name, str) else '', _key(_strip_nt_prefix(path.strip())),
               _nt_literal_end(path))
        if key in grouped:
            grouped[key]['count'] += 1
            continue
        state, reason = classify_path(name, path, env)
        grouped[key] = _item('process', name, path, state, reason, env)
    return {'items': list(grouped.values()), 'unchecked': unchecked}


def _task_executable(execute) -> str:
    """O executável de uma ação de tarefa, só quando dá para ter certeza de onde termina (R-40).

    O campo já deveria ser só o caminho. Devolve '' (nada é mostrado) se tiver aspa
    no meio ou sem fechar, espaço sem aspas fechadas, algo depois da extensão
    (ex.: ``a.exe --token=X``), nenhuma extensão conhecida ou pedaço que parece argumento.
    """
    if not isinstance(execute, str):
        return ''
    text = execute.strip()
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"') or text.count('"') != 2:
            return ''
        inner = text[1:-1]
        if inner != inner.strip():
            return ''
    else:
        if '"' in text or any(ch.isspace() for ch in text):
            return ''
        inner = text
    found = _COMMAND_EXE.match(inner)
    if not found or found.group(1) != inner:
        return ''
    return _only_if_not_argument(inner)


def _in_ms_folder(task_path) -> bool:
    if not isinstance(task_path, str):
        return False
    return ('\\' + task_path.strip().lstrip('\\')).lower().startswith(MS_TASK_FOLDER)


def _task_name(task_path, task_name) -> str:
    folder = task_path if isinstance(task_path, str) else ''
    name = task_name if isinstance(task_name, str) else ''
    if folder and name and not folder.endswith('\\'):
        folder += '\\'
    return folder + name


def _outside_windows_folder(exe, env) -> bool:
    norm = _key(_expand(_strip_nt_prefix(exe.strip()), env))
    if not _DRIVE_PATH.match(norm) and not norm.startswith('\\\\'):
        return False
    system_root = _env_get(env, 'SystemRoot') or _env_get(env, 'windir') or 'C:\\Windows'
    return not _under(norm, system_root)


def _classify_task(row, env):
    """(estado, motivo, executável mostrado) de uma ação; None quando a tarefa não aparece."""
    execute = row.get('Execute')
    in_ms = _in_ms_folder(row.get('TaskPath'))
    if row.get('Com') is True and not (isinstance(execute, str) and execute.strip()):
        # Ação COM não tem arquivo: fora da pasta da Microsoft fica "atenção", nunca OK.
        return None if in_ms else (STATE_ATTENTION, REASON_COM_HANDLER, '')
    exe = _task_executable(execute)
    if not exe:
        empty = not (isinstance(execute, str) and execute.strip())
        state, reason = STATE_ATTENTION, (REASON_UNREADABLE if empty else REASON_NOT_FULL_PATH)
        guess = _command_guess(execute)
        if guess and classify_path(None, guess, env)[0] == STATE_SUSPECT:
            state, reason = STATE_SUSPECT, REASON_SYSTEM_NAME
        return state, reason, ''
    state, reason = classify_path(None, exe, env)
    if in_ms:
        if state == STATE_OK:
            return None
        if _outside_windows_folder(exe, env):
            base = ntpath.basename(_key(exe.strip()))
            system = base in SYSTEM_NAMES or base == EXPLORER
            state = STATE_SUSPECT if system else STATE_ATTENTION
            reason = REASON_MS_FOLDER_OUTSIDE
        return state, reason, exe
    if state != STATE_SUSPECT and ntpath.basename(_key(exe.strip())) in SCRIPT_HOSTS:
        state, reason = STATE_ATTENTION, REASON_SCRIPT_HOST
    return state, reason, exe


def classify_tasks(rows, env=None):
    """Classifica as ações das tarefas agendadas (dados já lidos).

    O nome da tarefa não conta como nome de programa. Tarefa da pasta da Microsoft
    só aparece se o executável não der OK. Tarefas iguais (mesmo nome e mesmo
    executável) aparecem uma vez.
    """
    env = _env(env)
    grouped = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        found = _classify_task(row, env)
        if found is None:
            continue
        state, reason, exe = found
        name = _task_name(row.get('TaskPath'), row.get('TaskName'))
        execute = row.get('Execute') if isinstance(row.get('Execute'), str) else ''
        key = (name.lower(), _key(_strip_nt_prefix(execute.strip())) if execute.strip() else '',
               row.get('Com') is True)
        if key in grouped:
            grouped[key]['count'] += 1
            continue
        grouped[key] = _item('task', name, exe, state, reason, env)
    return list(grouped.values())


def _task_entries(raw):
    """Linhas da consulta das tarefas: só os quatro campos pedidos, nada mais."""
    rows = []
    for row in _as_list(raw):
        if not isinstance(row, dict):
            continue
        rows.append({'TaskPath': row.get('TaskPath'), 'TaskName': row.get('TaskName'),
                     'Execute': row.get('Execute'), 'Com': row.get('Com') is True})
    return rows


def _run_entries(raw):
    entries, failed = [], False
    for row in _as_list(raw):
        if not isinstance(row, dict):
            continue
        key = row.get('Key') if isinstance(row.get('Key'), str) else ''
        if row.get('Error'):
            failed = True
            continue
        once = key.lower().endswith('runonce')
        scope = 'user' if key.upper().startswith('HKCU') else 'all'
        entries.append({'source': ('runonce_' if once else 'run_') + scope,
                        'name': row.get('Name'), 'command': row.get('Command')})
    return entries, failed


def _startup_entries(raw):
    entries, failed = [], False
    for row in _as_list(raw):
        if not isinstance(row, dict):
            continue
        if row.get('Error'):
            failed = True
            continue
        name = row.get('Name')
        if isinstance(name, str) and name.strip().lower() == 'desktop.ini':
            continue
        entries.append({'source': 'startup_all' if row.get('Scope') == 1 else 'startup_user',
                        'name': name, 'extension': row.get('Extension')})
    return entries, failed


def read_checkup(ps=None, env=None):
    """Faz as quatro consultas (só leitura) e classifica. Erro vira código, nunca texto do sistema."""
    if ps is None:
        from optimization_engine import _ps as ps  # noqa: PLC0415 - preguiçoso de propósito
    env = _env(env)
    errors = []
    entries = []
    try:
        found, failed = _run_entries(ps(RUN_QUERY))
        entries.extend(found)
        if failed:
            errors.append('run_part')
    except Exception:  # noqa: BLE001 - R-07: a mensagem original não é guardada
        errors.append('run')
    try:
        found, failed = _startup_entries(ps(STARTUP_QUERY))
        entries.extend(found)
        if failed:
            errors.append('startup_part')
    except Exception:  # noqa: BLE001
        errors.append('startup')
    tasks = []
    try:
        tasks = classify_tasks(_task_entries(ps(TASK_QUERY)), env)
    except Exception:  # noqa: BLE001
        errors.append('tasks')
    processes = {'items': [], 'unchecked': 0}
    try:
        processes = classify_processes(ps(PROCESS_QUERY), env)
    except Exception:  # noqa: BLE001
        errors.append('processes')
    return {'autostart': classify_autostart(entries, env), 'tasks': tasks, 'processes': processes['items'],
            'unchecked': processes['unchecked'], 'errors': errors}


_ORDER = {STATE_SUSPECT: 0, STATE_ATTENTION: 1, STATE_OK: 2}


def _safe_state(item):
    state = item.get('state')
    return state if state in _STATES else STATE_ATTENTION


def _safe_reason(item, state):
    reason = item.get('reason')
    if reason not in REASON_TEXTS or (state == STATE_OK) != (reason == REASON_OK):
        return REASON_OTHER_PLACE if state != STATE_OK else REASON_OK
    return reason


def _effective(item, env):
    """Estado e motivo para mostrar: classifica de novo o caminho guardado (R-32).

    Vale o mais grave entre o guardado e o recalculado: só rebaixa, nunca promove a OK.
    Nas entradas de inicialização o nome é o do registro, não o do programa.
    """
    state = _safe_state(item)
    reason = _safe_reason(item, state)
    name = item.get('name') if item.get('source') == 'process' else None
    name = _expand(name, env) if isinstance(name, str) else None
    path = item.get('path')
    path = _expand(path, env) if isinstance(path, str) else path
    if item.get('source') in _STARTUP_SOURCES and not path:
        return state, reason
    new_state, new_reason = classify_path(name, path, env)
    if _ORDER[new_state] < _ORDER[state]:
        return new_state, new_reason
    return state, reason


def _item_lines(item, env, with_count=False):
    state, reason = _effective(item, env)
    name = _clean_name(item.get('name'), env) or 'sem nome'
    count = item.get('count')
    if with_count and isinstance(count, int) and not isinstance(count, bool) and count > 1:
        name += f' ({count} abertos)'
    source = SOURCE_TEXTS.get(item.get('source'))
    lines = [f'  [{state}] {name}' + (f' — {source}' if source else '')]
    path = sanitize_path(item.get('path'), env)
    if path:
        lines.append('      Onde: ' + path)
    lines.append('      Motivo: ' + REASON_TEXTS[reason])
    if state in ADVICE_TEXTS:
        lines.append('      O que fazer: ' + ADVICE_TEXTS[state])
    return lines, state


def checkup_lines(result, env=None):
    """Texto da janela. Só mostra textos gerados aqui (R-32); nome e caminho são limpos de novo."""
    env = _env(env)
    result = result if isinstance(result, dict) else {}
    errors = [e for e in _as_list(result.get('errors'))]
    counts = {STATE_OK: 0, STATE_ATTENTION: 0, STATE_SUSPECT: 0}
    lines = ['CHECK-UP DE SEGURANÇA — SÓ LEITURA', NEVER_CHANGES, '']

    def section(title, items, with_count, empty_text):
        lines.append(title)
        valid = [i for i in _as_list(items) if isinstance(i, dict)]
        valid.sort(key=lambda i: _ORDER[_effective(i, env)[0]])
        for item in valid:
            item_lines, state = _item_lines(item, env, with_count)
            lines.extend(item_lines)
            counts[state] += 1
        if not valid and empty_text:
            lines.append('  ' + empty_text)
        lines.append('')
        return len(valid)

    autostart_failed = 'run' in errors and 'startup' in errors
    section('PROGRAMAS QUE ABREM COM O WINDOWS', result.get('autostart'), False,
            None if autostart_failed else 'Nenhum programa encontrado nas chaves e pastas de inicialização.')
    section('TAREFAS AGENDADAS', result.get('tasks'), False, None if 'tasks' in errors else TASKS_EMPTY)
    lines.insert(len(lines) - 1, '  ' + TASKS_NOTE)
    processes_shown = section('PROCESSOS EM EXECUÇÃO', result.get('processes'), True,
                              None if 'processes' in errors else 'Nenhum processo foi informado.')
    unchecked = result.get('unchecked')
    unchecked = unchecked if isinstance(unchecked, int) and not isinstance(unchecked, bool) and unchecked > 0 else 0
    if unchecked == 1:
        lines.insert(len(lines) - 1, '  1 processo não pôde ser conferido (o Windows não informou de onde '
                                     'ele roda). Isso é comum em processos do próprio Windows.')
    elif unchecked:
        lines.insert(len(lines) - 1, f'  {unchecked} processos não puderam ser conferidos (o Windows não '
                                     'informou de onde eles rodam). Isso é comum em processos do próprio Windows.')
    if errors:
        lines.append('CONSULTAS INCOMPLETAS:')
        texts = []
        for code in errors:
            text = ERROR_TEXTS.get(code, ERROR_GENERIC) if isinstance(code, str) else ERROR_GENERIC
            if text not in texts:
                texts.append(text)
        lines.extend('  • ' + text for text in texts)
        lines.append('')
    lines.append(f'RESUMO: OK {counts[STATE_OK]} · atenção {counts[STATE_ATTENTION]} · '
                 f'suspeito {counts[STATE_SUSPECT]} · não conferidos {unchecked}')
    flagged = counts[STATE_ATTENTION] + counts[STATE_SUSPECT]
    if flagged or errors:
        lines.append('')
        if flagged:
            lines.append(NOT_CERTAIN)
        lines.append(RECOMMENDATION)
    elif not unchecked and processes_shown:
        lines.append(ALL_CLEAR)
    else:
        lines.append(NOT_ALL_CHECKED)
    return lines
