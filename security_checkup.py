"""P3-07: check-up de segurança, somente leitura.

Olha os programas que abrem com o Windows (chaves Run/RunOnce e pastas de
Inicialização), as tarefas agendadas (fatia 2), os processos em execução, a
situação do Microsoft Defender e as conexões de rede para portas comuns de
mineração (fatia 3), e marca cada item como OK, atenção ou suspeito, com o
motivo em português simples. A fatia 4 mede, num botão à parte, o uso de CPU e
GPU com o PC parado por 2 minutos (só "OK" ou "atenção", nunca "suspeito").

Regras desta fatia:
- só lê: nada é mudado, encerrado ou tirado do lugar, e não pede administrador;
- da linha de comando de um programa só fica o executável (argumentos podem
  ter senhas ou tokens); dos processos só o nome e o caminho do executável;
  das tarefas agendadas só a pasta, o nome e o executável (os argumentos nem
  são pedidos ao Windows);
- a pasta do usuário vira %USERPROFILE%, a de outros usuários vira
  "<outro usuário>" e o nome do usuário (mesmo colado em letras) vira
  %USERNAME%, só no texto mostrado: a classificação usa o caminho original;
  um SID (como S-1-5-21-...) vira <SID> e um e-mail vira <e-mail>;
- na dúvida o item fica "atenção", nunca "OK";
- o Defender só é lido (situação e exclusões), nunca mudado; das conexões de
  rede só ficam a porta remota e o programa dono (o endereço remoto nem é pedido);
- programa da pasta do Windows só dá OK (ou some, nas tarefas da Microsoft)
  se estiver na lista fechada ``KNOWN_QUIET_PROGRAMS`` (R-46);
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
    'agendadas e dos programas abertos agora (processos), com o lugar de onde cada um roda. '
    'Vai ler também a situação do Microsoft Defender (proteção ligada e exclusões) e as '
    'conexões de rede abertas agora (só a porta e o programa, sem o endereço).\n\n'
    'Nada é mudado, encerrado ou tirado do lugar (nem no Defender), e não precisa de administrador. '
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
TASKS_EMPTY = ('Nenhuma tarefa agendada para mostrar. Só ficam de fora as tarefas da Microsoft '
               'que usam um programa da pasta do Windows de uma lista curta de programas conhecidos '
               '(como o desfragmentador de disco), que não rodam scripts, comandos nem bibliotecas.')
DEFENDER_NO_EXCLUSIONS = ('O Windows não mostrou nenhuma exclusão do Defender (sem administrador, '
                          'ele pode esconder as exclusões).')
DEFENDER_EMPTY = 'Não foi possível conferir o Microsoft Defender.'
NETWORK_EMPTY = 'Nenhuma conexão para portas comuns de mineração no momento do check-up.'
NETWORK_NOTE = 'Só as conexões abertas na hora do check-up são vistas; o endereço de destino não é lido.'
# P3-07 fatia 4: uso de CPU e GPU com o PC parado (medição à parte, 2 minutos).
IDLE_CONFIRMATION = (
    'O app vai medir por 2 minutos o uso do processador (CPU) e da placa de vídeo (GPU), só lendo. '
    'Vai ver também o nome dos 3 programas que mais usaram o processador nesse tempo.\n\n'
    'Nada é mudado nem encerrado, e não precisa de administrador.\n\n'
    'Feche os programas que estiver usando e não use o PC nesse tempo (nem o mouse e o teclado); '
    'senão a medição não vale.\n\nContinuar?')
IDLE_NOTE = 'A medição só vale se você não usou o PC durante os 2 minutos.'
IDLE_NOT_MEASURED = 'Não medido. Para medir, use o botão "Medir uso parado (2 min)".'
IDLE_ONLY_NOTE = ('Esta medição não substitui o check-up de segurança completo '
                  '(botão "Check-up de segurança").')
IDLE_ADVICE = ('Feche os programas abertos e meça de novo sem usar o PC. Se o uso continuar alto, '
               'faça a verificação recomendada no fim desta lista.')
IDLE_TOP_TEXT = 'Programas que mais usaram o processador: '
IDLE_KIND_TEXTS = {'cpu': 'Processador (CPU)', 'gpu': 'Placa de vídeo (GPU)'}
IDLE_SECONDS = 120
IDLE_INTERVAL = 5
IDLE_SAMPLES = 24
IDLE_TIMEOUT = 300
IDLE_LIMIT = 25
# Só as linhas de total e ocioso do Windows saem pelo nome. O processo da própria
# medição sai pelo PID ($PID), nunca pelo nome: um powershell, pwsh ou WmiPrvSE de
# outro PID aparece normalmente entre os 3 citados (R-45, R-53).
IDLE_SELF_PROCESSES = ('_total', 'idle')
IDLE_COST_NOTE = ('A própria medição usa um pouco do processador (o PowerShell e o serviço WMI do '
                  'Windows, WmiPrvSE), mas o PowerShell dela não entra na lista de programas.')
NOT_ALL_CHECKED = ('Nenhum item conferido ficou como atenção ou suspeito, mas o check-up '
                   'não conseguiu conferir tudo (veja acima).')

# Nomes de programas do Windows que só deveriam rodar de System32/SysWOW64.
SYSTEM_NAMES = ('svchost.exe', 'csrss.exe', 'lsass.exe', 'winlogon.exe', 'services.exe',
                'smss.exe', 'dllhost.exe', 'conhost.exe', 'taskhostw.exe', 'rundll32.exe')
# O explorer.exe fica direto na pasta do Windows (ou em SysWOW64).
EXPLORER = 'explorer.exe'
SCRIPT_EXTENSIONS = ('.vbs', '.ps1', '.js', '.bat', '.cmd')
SHORTCUT_EXTENSIONS = ('.lnk', '.url')
# Programas do Windows que rodam o código que vem nos argumentos (um script, um
# comando ou uma biblioteca). Como os argumentos não são lidos, nunca dão OK (R-45).
SCRIPT_HOSTS = ('wscript.exe', 'cscript.exe', 'mshta.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe',
                'rundll32.exe', 'regsvr32.exe')
# R-46: lista FECHADA de programas do Windows que não rodam código vindo dos
# argumentos. Só eles podem dar OK por estarem na pasta do Windows (e só em
# System32 ou SysWOW64, sem subpasta); qualquer outro programa da pasta do
# Windows (conhost, forfiles, msiexec, explorer, svchost...) fica "atenção" nas
# entradas de inicialização e nas tarefas. Na dúvida, um programa fica fora da lista.
KNOWN_QUIET_PROGRAMS = ('defrag.exe', 'cleanmgr.exe', 'wermgr.exe', 'ctfmon.exe',
                        'securityhealthsystray.exe', 'sihclient.exe', 'usoclient.exe',
                        'musnotification.exe', 'musnotificationux.exe', 'dstokenclean.exe',
                        'devicecensus.exe', 'tzsync.exe', 'srtasks.exe', 'bthudtask.exe',
                        'lpremove.exe', 'wsqmcons.exe', 'disksnapshot.exe')
# R-47: lista FECHADA de interpretadores (programas que rodam código escrito depois
# deles). Em tarefas e entradas de inicialização nunca dão OK nem somem, em
# qualquer pasta (inclusive Arquivos de Programas). Na dúvida, o programa entra.
INTERPRETERS = ('python.exe', 'pythonw.exe', 'python3.exe', 'py.exe', 'pyw.exe', 'pypy.exe', 'pypy3.exe',
                'node.exe', 'deno.exe', 'bun.exe', 'dotnet.exe', 'java.exe', 'javaw.exe', 'jshell.exe',
                'jrunscript.exe', 'bash.exe', 'sh.exe', 'zsh.exe', 'dash.exe', 'fish.exe', 'busybox.exe',
                'git-bash.exe', 'wsl.exe', 'perl.exe', 'wperl.exe', 'ruby.exe', 'rubyw.exe', 'php.exe',
                'php-win.exe', 'php-cgi.exe', 'lua.exe', 'wlua.exe', 'luajit.exe', 'tclsh.exe', 'wish.exe',
                'rscript.exe', 'r.exe', 'rterm.exe', 'julia.exe', 'autohotkey.exe', 'autohotkey32.exe',
                'autohotkey64.exe', 'autohotkeyu32.exe', 'autohotkeyu64.exe', 'autohotkeya32.exe',
                'autoit3.exe', 'autoit3_x64.exe', 'autohotkeyux.exe', 'autohotkey64_uia.exe',
                'autohotkey32_uia.exe', 'javaws.exe', 'jjs.exe', 'mintty.exe', 'msbuild.exe',
                # FIX-P3-07-03: lançadores que rodam o código ou o programa dos argumentos.
                'env.exe', 'awk.exe', 'gawk.exe', 'mawk.exe', 'nawk.exe', 'go.exe', 'groovy.exe',
                'scala.exe', 'kotlin.exe', 'kotlinc.exe')
# R-48: nome curto 8.3 (ex.: AUTOHO~1.EXE); não dá para saber qual programa é.
_SHORT_NAME = re.compile(r'~\d')
# R-49: qualquer nome da lista com versão (ex.: python3.13.exe, node18.exe, java8.exe,
# javaw17.exe, wish86.exe, php-8.exe). Do lado seguro: "-" ou "_" antes do número também conta.


def _versioned_names(names):
    """Padrão de nome com versão para uma lista que tira o OK (R-49, R-50)."""
    return re.compile(
        r'^(' + '|'.join(sorted((re.escape(n[:-4]) for n in names), key=len, reverse=True))
        + r')[-_]?\d+(\.\d+)*t?w?\.exe$')


_VERSIONED_INTERPRETER = _versioned_names(INTERPRETERS)
# R-50: o mesmo padrão vale para SCRIPT_HOSTS (ex.: pwsh7.exe, cmd2.exe, wscript5.exe).
_VERSIONED_SCRIPT_HOST = _versioned_names(SCRIPT_HOSTS)

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
REASON_WINDOWS_PROGRAM = 'windows_program'
REASON_MS_WINDOWS_PROGRAM = 'ms_windows_program'
REASON_MS_COM_HANDLER = 'ms_com_handler'
REASON_INTERPRETER = 'interpreter'
REASON_UNCERTAIN_NAME = 'uncertain_name'
# P3-07 fatia 3: Microsoft Defender e conexões de rede.
REASON_RT_ON = 'rt_on'
REASON_RT_OFF = 'rt_off'
REASON_DEFENDER_UNKNOWN = 'defender_unknown'
REASON_EXCL_HIDDEN = 'excl_hidden'
REASON_EXCL_UNKNOWN = 'excl_unknown'
REASON_EXCL_USER = 'excl_user_folder'
REASON_EXCL_TEMP = 'excl_temp'
REASON_EXCL_APPDATA = 'excl_appdata'
REASON_EXCL_PROGRAMDATA = 'excl_programdata'
REASON_EXCL_DRIVE_ROOT = 'excl_drive_root'
REASON_EXCL_WINDOWS = 'excl_windows'
REASON_EXCL_EXTENSION = 'excl_extension'
REASON_EXCL_SCRIPT_PROCESS = 'excl_script_process'
REASON_EXCL_OTHER = 'excl_other'
REASON_MINING_PORT = 'mining_port'
REASON_IDLE_OK = 'idle_ok'
REASON_IDLE_HIGH = 'idle_high'
REASON_IDLE_UNKNOWN = 'idle_unknown'

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
    REASON_SCRIPT_HOST: ('Usa um programa do Windows que roda o que vier escrito depois dele (um script, '
                         'um comando ou uma biblioteca); o app não confere o que ele roda.'),
    REASON_SHORTCUT: 'É um atalho na pasta Inicialização; o app não confere para onde ele aponta.',
    REASON_STARTUP_FILE: 'É um arquivo colocado direto na pasta Inicialização.',
    REASON_UNREADABLE: 'O caminho veio vazio ou não pôde ser lido.',
    REASON_NOT_FULL_PATH: 'O caminho completo não está escrito; o app não confere de onde ele abre.',
    REASON_OTHER_PLACE: 'Fica fora das pastas de programas do Windows (Windows ou Arquivos de Programas).',
    REASON_COM_HANDLER: ('A tarefa abre um componente do Windows em vez de um arquivo de programa; '
                         'o app não confere o que esse componente faz.'),
    REASON_MS_FOLDER_OUTSIDE: ('Está na pasta de tarefas da Microsoft, mas roda de fora da pasta do '
                               'Windows.'),
    REASON_WINDOWS_PROGRAM: ('Usa um programa da pasta do Windows que pode rodar o que vier escrito '
                             'depois dele (outro programa, um script ou um comando); o app não confere '
                             'o que ele roda.'),
    REASON_MS_WINDOWS_PROGRAM: ('É uma tarefa da Microsoft que usa um programa do Windows que pode rodar '
                                'o que vier escrito depois dele (como o rundll32). Isso é comum nas '
                                'tarefas da Microsoft, mas o app não confere o que ele roda.'),
    REASON_MS_COM_HANDLER: ('É uma tarefa da Microsoft que abre um componente do Windows em vez de um '
                            'arquivo de programa. Isso é comum nas tarefas da Microsoft, mas o app não '
                            'confere o que esse componente faz.'),
    REASON_INTERPRETER: ('É um programa que roda scripts ou comandos que recebe (como Python, Node ou Java). '
                         'O app não lê esses comandos, então não confere o que ele roda.'),
    REASON_UNCERTAIN_NAME: ('O nome do arquivo não termina em .exe, termina com ponto ou espaço, ou está '
                            'abreviado (como ARQUIV~1.EXE); o app não confere qual programa ele abre.'),
    REASON_RT_ON: 'A proteção em tempo real do Microsoft Defender está ligada.',
    REASON_RT_OFF: ('O Microsoft Defender ou a proteção em tempo real dele está desligado. Isso pode ser '
                    'normal se outro programa de segurança estiver instalado; confira em Segurança do Windows.'),
    REASON_DEFENDER_UNKNOWN: ('Não foi possível conferir se a proteção em tempo real do Microsoft Defender '
                              'está ligada (isso acontece, por exemplo, com outro programa de segurança '
                              'instalado). Confira em Segurança do Windows.'),
    REASON_EXCL_HIDDEN: ('Sem administrador, o Windows não mostra as exclusões do Defender; '
                         'não foi possível conferir.'),
    REASON_EXCL_UNKNOWN: 'Não foi possível conferir as exclusões do Defender.',
    REASON_EXCL_USER: ('O Defender foi configurado para não olhar uma pasta de usuário. Programas '
                       'indesejados costumam se esconder assim.'),
    REASON_EXCL_TEMP: ('O Defender foi configurado para não olhar uma pasta temporária. Programas '
                       'indesejados costumam se esconder assim.'),
    REASON_EXCL_APPDATA: ('O Defender foi configurado para não olhar a pasta AppData (ou algo dentro dela). '
                          'Programas indesejados costumam se esconder assim.'),
    REASON_EXCL_PROGRAMDATA: ('O Defender foi configurado para não olhar a pasta ProgramData (ou algo dentro '
                              'dela). Programas indesejados costumam se esconder assim.'),
    REASON_EXCL_DRIVE_ROOT: 'O Defender foi configurado para não olhar uma unidade inteira (como C:\\).',
    REASON_EXCL_WINDOWS: 'O Defender foi configurado para não olhar a pasta do Windows (ou System32) inteira.',
    REASON_EXCL_EXTENSION: ('O Defender foi configurado para não olhar arquivos de programa ou de script '
                            '(como .exe, .dll ou .ps1). Programas indesejados costumam fazer isso.'),
    REASON_EXCL_SCRIPT_PROCESS: ('O Defender foi configurado para não olhar um programa que roda scripts ou '
                                 'comandos (como PowerShell, cmd ou Python). Programas indesejados costumam '
                                 'fazer isso.'),
    REASON_EXCL_OTHER: ('O Defender foi configurado para não olhar este item. Alguns programas pedem isso '
                        '(como jogos ou ferramentas), mas confira se foi você que colocou.'),
    REASON_MINING_PORT: ('Tem uma conexão para uma porta comum de mineração de criptomoedas. Pode ser outro '
                         'programa usando a mesma porta, mas vale conferir.'),
    REASON_IDLE_OK: 'O uso ficou baixo com o PC parado.',
    REASON_IDLE_HIGH: ('Uso alto com o PC parado; pode ser um programa em segundo plano, uma atualização '
                       'do Windows ou, às vezes, um minerador.'),
    REASON_IDLE_UNKNOWN: 'Não foi possível medir.',
}
ADVICE_TEXTS = {
    STATE_SUSPECT: ('Não mexa no arquivo por conta própria. Faça a verificação recomendada '
                    'no fim desta lista.'),
    STATE_ATTENTION: ('Confira se você reconhece este programa. Se não reconhecer, faça a '
                      'verificação recomendada no fim desta lista.'),
}

# P3-07 fatia 3: conselhos do Defender (uma configuração, não um arquivo) e da rede.
DEFENDER_ADVICE_TEXTS = {
    STATE_SUSPECT: ('Não mude nada por conta própria. Faça a verificação recomendada no fim desta lista.'),
    STATE_ATTENTION: ('Confira em Segurança do Windows se você reconhece esta configuração. Se não '
                      'reconhecer, faça a verificação recomendada no fim desta lista.'),
}
NETWORK_ADVICE = ('Não encerre o programa nem mexa no arquivo por conta própria. Faça a verificação '
                  'recomendada no fim desta lista.')

SOURCE_TEXTS = {
    'run_user': 'registro, só este usuário',
    'runonce_user': 'registro, só este usuário, abre uma vez',
    'run_all': 'registro, todos os usuários',
    'runonce_all': 'registro, todos os usuários, abre uma vez',
    'startup_user': 'pasta Inicialização deste usuário',
    'startup_all': 'pasta Inicialização de todos os usuários',
    'task': 'tarefa agendada',
}
DEFENDER_KIND_TEXTS = {
    'path': 'Exclusão de pasta ou arquivo',
    'process': 'Exclusão de programa',
    'extension': 'Exclusão de tipo de arquivo',
}
_STARTUP_SOURCES = ('startup_user', 'startup_all')

ERROR_TEXTS = {
    'run': 'Programas que abrem com o Windows (registro): não foi possível ler.',
    'run_part': 'Não foi possível ler parte das chaves do registro de inicialização.',
    'startup': 'Pastas de Inicialização: não foi possível ler.',
    'startup_part': 'Não foi possível ler parte das pastas de Inicialização.',
    'processes': 'Processos em execução: não foi possível ler.',
    'tasks': 'Tarefas agendadas: não foi possível ler.',
    'defender': 'Microsoft Defender: não foi possível ler.',
    'network': 'Conexões de rede: não foi possível ler.',
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

# P3-07 fatia 3. Só leitura: o Defender só é consultado (situação e exclusões).
# Cada parte tem seu try: uma parte negada vira null e não derruba a outra.
DEFENDER_QUERY = (
    '$s=$null; $p=$null; '
    'try{ $s=Get-MpComputerStatus -ErrorAction Stop | '
    'Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled }catch{}; '
    'try{ $p=Get-MpPreference -ErrorAction Stop | '
    'Select-Object ExclusionPath,ExclusionProcess,ExclusionExtension }catch{}; '
    'ConvertTo-Json -InputObject ([pscustomobject]@{Status=$s;Preference=$p}) -Depth 3 -Compress')
# Portas comuns de mineração (stratum). Só a porta remota e o programa dono:
# o endereço de destino nem é pedido ao Windows (dado pessoal).
MINING_PORTS = (3333, 4444, 5555, 7777, 14444, 14433, 45700)
NETWORK_QUERY = (
    '$ports=@(' + ','.join(str(p) for p in MINING_PORTS) + '); $e=$null; '
    # Sem nenhuma conexão estabelecida o Windows dá "ObjectNotFound": isso é "nenhuma
    # conexão", não erro. Qualquer outro erro continua derrubando a consulta ('network').
    '$conns=@(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue -ErrorVariable e | '
    'Select-Object RemotePort,OwningProcess); '
    "foreach($x in @($e)){ if($x -and $x.CategoryInfo.Category -ne 'ObjectNotFound'){ throw 'network' } }; "
    '$out=foreach($c in $conns){ if($ports -contains [int]$c.RemotePort){ '
    '$n=$null; $x=$null; '
    'try{ $g=Get-Process -Id $c.OwningProcess -ErrorAction Stop; $n=[string]$g.Name; $x=[string]$g.Path }catch{}; '
    '[pscustomobject]@{RemotePort=[int]$c.RemotePort;Name=$n;Path=$x} } }; '
    'ConvertTo-Json -InputObject @($out) -Compress')
# Extensões de programa, script ou atalho: exclusão de qualquer uma delas é "suspeito".
EXECUTABLE_EXTENSIONS = ('exe', 'dll', 'ps1', 'bat', 'cmd', 'vbs', 'js', 'scr', 'com', 'hta', 'msi', 'jar',
                         'wsf', 'vbe', 'jse', 'psm1', 'cpl', 'pif', 'lnk', 'sys', 'msc', 'reg')

# P3-07 fatia 4. Só leitura, sem administrador. Classes CIM de desempenho, cujos nomes
# não mudam com o idioma do Windows (o Get-Counter usa nomes traduzidos). Uma leitura
# de aquecimento (o primeiro valor costuma vir zerado) e depois 24 amostras com 5 s
# entre elas (2 minutos): CPU total (_Total), soma dos motores da GPU por amostra
# (classe ausente ou sem motor = sem dado) e, dos processos, só o nome e o uso de CPU,
# somados no intervalo para achar os 3 que mais usaram (sem _Total e Idle).
IDLE_CPU_CLASS = 'Win32_PerfFormattedData_PerfOS_Processor'
IDLE_GPU_CLASS = 'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine'
IDLE_PROCESS_CLASS = 'Win32_PerfFormattedData_PerfProc_Process'
IDLE_QUERY = (
    '$skip=@(' + ','.join("'" + n + "'" for n in IDLE_SELF_PROCESSES) + '); '
    "$q=\"Name='_Total'\"; $cpu=@(); $gpu=@(); $hasGpu=$true; $acc=@{}; $n=0; "
    'try{ $null=Get-CimInstance ' + IDLE_CPU_CLASS + ' -Filter $q -ErrorAction Stop }catch{}; '
    'try{ $null=Get-CimInstance ' + IDLE_GPU_CLASS + ' -ErrorAction Stop }catch{}; '
    'try{ $null=Get-CimInstance ' + IDLE_PROCESS_CLASS + ' -Property Name,PercentProcessorTime -ErrorAction Stop }catch{}; '
    'for($i=0; $i -lt ' + str(IDLE_SAMPLES) + '; $i++){ Start-Sleep ' + str(IDLE_INTERVAL) + '; '
    'try{ $c=Get-CimInstance ' + IDLE_CPU_CLASS + ' -Filter $q -Property PercentProcessorTime -ErrorAction Stop; '
    'if($c){ $cpu+=[double]$c.PercentProcessorTime } }catch{}; '
    # GPU como no Gerenciador de Tarefas: soma por tipo de motor (engtype_3D, VideoDecode,
    # Copy...) e vale o tipo mais usado, não a soma de todos.
    'if($hasGpu){ try{ $e=@(Get-CimInstance ' + IDLE_GPU_CLASS + ' -Property Name,UtilizationPercentage -ErrorAction Stop); '
    'if($e.Count -eq 0){ $hasGpu=$false; $gpu=@() }else{ $h=@{}; '
    "foreach($x in $e){ $k=if([string]$x.Name -match 'engtype_(.+)$'){ $matches[1] }else{ '?' }; "
    '$h[$k]=[double]$h[$k]+[double]$x.UtilizationPercentage }; '
    '$gpu+=($h.Values | Measure-Object -Maximum).Maximum } }catch{ $hasGpu=$false; $gpu=@() } }; '
    'try{ foreach($p in @(Get-CimInstance ' + IDLE_PROCESS_CLASS + ' -Property Name,IDProcess,PercentProcessorTime '
    '-ErrorAction Stop)){ '
    "$nm=([string]$p.Name) -replace '#\\d+$',''; "
    "if($nm -and [int]$p.IDProcess -ne $PID -and $skip -notcontains $nm.ToLower()){ $acc[$nm]=[double]$acc[$nm]+[double]$p.PercentProcessorTime } }; "
    '$n++ }catch{} }; '
    '$top=@(if($n){ $acc.GetEnumerator() | Where-Object { $_.Value -gt 0 } | Sort-Object Value -Descending | '
    'Select-Object -First 3 | ForEach-Object { [string]$_.Key } }); '
    'ConvertTo-Json -InputObject ([pscustomobject]@{Cpu=$(if($cpu.Count){$cpu}else{$null});'
    'Gpu=$(if($gpu.Count){$gpu}else{$null});Top=$top}) -Depth 3 -Compress')

_DRIVE_PATH = re.compile(r'^[a-z]:\\')
_DRIVE_ROOT_FILE = re.compile(r'^[a-z]:\\[^\\]+$')
_ENV_VAR = re.compile(r'%([^%]+)%')
# C:\Users\<nome>, C:\Documents and Settings\<nome> e \\servidor\users\<nome>.
_OTHER_USER = re.compile(r'((?:[A-Za-z]:|\\\\[^\\/"]+)[\\/](?:Users|Documents and Settings)[\\/])([^\\/"]+)',
                         re.IGNORECASE)
# Marcadores que a troca do nome do usuário não pode estragar.
# <SID> e <e-mail> entram para um usuário chamado "SID" ou "mail" (FIX-P3-07-03).
_PLACEHOLDERS = ('%USERPROFILE%', '%USERNAME%', '<outro usuário>', '<SID>', '<e-mail>')
_KEEP_USERS = ('public', 'default', 'default user', 'all users', '<outro usuário>')
# A extensão termina quando não vem letra, número ou "_" colado (app.exe--token=X vira app.exe).
_COMMAND_EXE = re.compile(r'^(.*?\.(?:exe|bat|cmd|vbs|ps1|js))(?![A-Za-z0-9_])', re.IGNORECASE)
_NT_PREFIX = re.compile(r'^(?:\\\\\?\\|\\\?\?\\)(UNC\\)?', re.IGNORECASE)
# SID de usuário (S-1-5-21-...) e qualquer S-1-... com pelo menos 3 sub-autoridades,
# mesmo colado em letras (ex.: GoogleUpdateTaskUserS-1-5-21-...Core). "S-1-5-18" fica.
_SID = re.compile(r'S-1-5-21-\d+-\d+-\d+(?:-\d+)?|S-1-\d+(?:-\d+){3,}', re.IGNORECASE)
# O "%" entra para pegar também "%USERNAME%@exemplo.com" e "a@%USERNAME%.com" (o nome já trocado).
_EMAIL = re.compile(r'[\w.+%-]+@[\w%-]+(?:\.[\w%-]+)+')
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
    # O SID é trocado antes do nome do usuário (um nome como "S-1" estragaria o SID)
    # e de novo depois; os marcadores já colocados ficam protegidos (FIX-P3-07-03).
    text = _hide_user_name(_SID.sub('<SID>', text), env)
    return _EMAIL.sub('<e-mail>', _SID.sub('<SID>', text))


def _hide_user_name(text, env):
    """Troca o USERNAME (sem diferenciar maiúsculas) por %USERNAME%, mesmo colado em letras.

    Ex.: ``TaskxFulano Silvay`` vira ``Taskx%USERNAME%y`` (R-45). Do lado seguro:
    um nome curto também é trocado dentro de outras palavras ("Ana" em "Banana").
    Só muda o texto mostrado. Nome de uma letra só não é trocado (não identifica
    ninguém e estragaria "C:"). Os marcadores já colocados ficam como estão.
    """
    user = _env_get(env, 'USERNAME')
    user = user.strip() if user else ''
    if len(user) < 2:
        return text
    protected = '|'.join(re.escape(p) for p in _PLACEHOLDERS)
    pattern = re.compile('(' + protected + ')|' + re.escape(user), re.IGNORECASE)
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


def _quoted_trailing_space(cmd) -> bool:
    """O nome entre aspas termina com espaço (ex.: ``"C:\\a\\b.exe "``); R-48."""
    if not isinstance(cmd, str):
        return False
    text = cmd.strip()
    end = text.find('"', 1) if text.startswith('"') else -1
    if end <= 0:
        return False
    inner = text[1:end]
    return inner != inner.rstrip()


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


def _system_root(env):
    return _env_get(env, 'SystemRoot') or _env_get(env, 'windir') or 'C:\\Windows'


def _norm_exe(path, env):
    # R-48: o Windows ignora pontos e espaços no fim do nome ("node.exe." abre node.exe).
    return _key(_expand(_strip_nt_prefix(path.strip()), env)).rstrip(' .')


def _exe_names(path, env):
    """Nomes com que o programa pode ser comparado às listas (R-48).

    Sem ".exe" no fim, o Windows pode acrescentar ".exe" (``node`` abre ``node.exe``),
    então os dois nomes contam.
    """
    base = ntpath.basename(_norm_exe(path, env))
    return (base,) if base.endswith('.exe') else (base, base + '.exe')


def _uncertain_name(path, env) -> bool:
    """Nome sem ".exe", com ponto ou espaço no fim, ou curto (8.3): nunca dá OK (R-48)."""
    raw = ntpath.basename(_key(_expand(_strip_nt_prefix(path.strip()), env)))
    return raw != raw.rstrip(' .') or not raw.endswith('.exe') or bool(_SHORT_NAME.search(raw))


def _known_quiet(path, env) -> bool:
    """Programa da lista fechada, direto em System32 ou SysWOW64 (R-46)."""
    if not isinstance(path, str) or not path.strip():
        return False
    if _uncertain_name(path, env):
        # R-48: "defrag", "defrag.exe." ou "DEFRAG~1.EXE" não somem nem dão OK.
        return False
    norm = _norm_exe(path, env)
    root_key = _key(_system_root(env)).rstrip('\\')
    return (ntpath.basename(norm) in KNOWN_QUIET_PROGRAMS
            and ntpath.dirname(norm) in (root_key + '\\system32', root_key + '\\syswow64'))


def _is_interpreter(path, env) -> bool:
    """Interpretador da lista fechada ``INTERPRETERS`` (ou nome com versão), em qualquer pasta (R-47)."""
    if not isinstance(path, str) or not path.strip():
        return False
    return any(base in INTERPRETERS or _VERSIONED_INTERPRETER.match(base) for base in _exe_names(path, env))


def _is_script_host(path, env) -> bool:
    """Programa da lista ``SCRIPT_HOSTS`` (ou nome com versão, R-50), em qualquer pasta (R-45)."""
    if not isinstance(path, str) or not path.strip():
        return False
    return any(base in SCRIPT_HOSTS or _VERSIONED_SCRIPT_HOST.match(base) for base in _exe_names(path, env))


def _code_runner_reason(path, env, allow_known):
    """Motivo de "atenção" para um programa que pode rodar o que vem nos argumentos, ou None.

    Os programas que rodam scripts, comandos ou bibliotecas (``SCRIPT_HOSTS``)
    nunca dão OK, estejam onde estiverem (R-45); os interpretadores (``INTERPRETERS``)
    também não (R-47). Qualquer outro programa da pasta do Windows só dá OK se
    ``allow_known`` e se for da lista fechada (R-46). Nome sem ".exe", com ponto ou
    espaço no fim, ou curto (8.3) nunca dá OK, em qualquer pasta (R-48).
    """
    if not isinstance(path, str) or not path.strip():
        return None
    norm = _norm_exe(path, env)
    if _is_script_host(path, env):
        return REASON_SCRIPT_HOST
    if _is_interpreter(path, env):
        return REASON_INTERPRETER
    if _uncertain_name(path, env):
        return REASON_UNCERTAIN_NAME
    if not _under(norm, _system_root(env)):
        return None
    if allow_known and _known_quiet(path, env):
        return None
    return REASON_WINDOWS_PROGRAM


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
        if state == STATE_OK:
            # R-45/R-46: sem os argumentos, só a lista fechada da pasta do Windows dá OK.
            runner = _code_runner_reason(exe, env, allow_known=True)
            if runner:
                state, reason = STATE_ATTENTION, runner
        if state == STATE_OK and _quoted_trailing_space(command):
            # R-48: '"...\\ctfmon.exe "' nunca dá OK (espaço no fim do nome).
            state, reason = STATE_ATTENTION, REASON_UNCERTAIN_NAME
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
    return not _under(norm, _system_root(env))


def _classify_task(row, env):
    """(estado, motivo, executável mostrado) de uma ação; None quando a tarefa não aparece."""
    execute = row.get('Execute')
    in_ms = _in_ms_folder(row.get('TaskPath'))
    if row.get('Com') is True and not (isinstance(execute, str) and execute.strip()):
        # Ação COM não tem arquivo nem é conferida: sempre "atenção", nunca some nem dá OK.
        return STATE_ATTENTION, (REASON_MS_COM_HANDLER if in_ms else REASON_COM_HANDLER), ''
    exe = _task_executable(execute)
    quoted_space = False
    if not exe and _quoted_trailing_space(execute):
        # FIX-P3-07-04: "C:\...\defrag.exe " (só espaço no fim, dentro das aspas, e nada
        # depois) tem caminho completo, mas o nome é incerto (R-48): nunca some nem dá OK.
        text = execute.strip()
        inner = text[1:-1] if text.endswith('"') and text.count('"') == 2 else ''
        if inner and inner == inner.lstrip():
            exe = _task_executable('"' + inner.rstrip() + '"')
            quoted_space = bool(exe)
    if not exe:
        empty = not (isinstance(execute, str) and execute.strip())
        state, reason = STATE_ATTENTION, (REASON_UNREADABLE if empty else REASON_NOT_FULL_PATH)
        guess = _command_guess(execute)
        if guess and classify_path(None, guess, env)[0] == STATE_SUSPECT:
            state, reason = STATE_SUSPECT, REASON_SYSTEM_NAME
        return state, reason, ''
    state, reason = classify_path(None, exe, env)
    runs_code = _is_script_host(exe, env)
    if (state == STATE_OK and (execute != execute.rstrip() or quoted_space) and not runs_code
            and not _is_interpreter(exe, env)):
        # R-48: espaço no fim do caminho: nunca some nem dá OK, nem em \Microsoft\.
        return STATE_ATTENTION, REASON_UNCERTAIN_NAME, exe
    if in_ms:
        if state == STATE_OK:
            if _known_quiet(exe, env):
                # R-46: só some o que é da lista fechada (programas que não rodam código).
                return None
            runner = _code_runner_reason(exe, env, allow_known=False)
            if runner in (REASON_INTERPRETER, REASON_UNCERTAIN_NAME):
                # R-47/R-48: interpretador ou nome incerto nunca some nem dá OK, nem em \Microsoft\.
                return STATE_ATTENTION, runner, exe
            if runner == REASON_SCRIPT_HOST and not any(b in SCRIPT_HOSTS for b in _exe_names(exe, env)):
                # Ressalva da PR #195: "cmd2.exe" não é programa do Windows; o texto de
                # "comum nas tarefas da Microsoft" seria falso (R-50).
                return STATE_ATTENTION, REASON_SCRIPT_HOST, exe
            if runner:
                return STATE_ATTENTION, REASON_MS_WINDOWS_PROGRAM, exe
            # Ex.: Office em Arquivos de Programas: aparece como OK, não some.
            return state, reason, exe
        if _outside_windows_folder(exe, env):
            base = ntpath.basename(_key(exe.strip()))
            system = base in SYSTEM_NAMES or base == EXPLORER
            state = STATE_SUSPECT if system else STATE_ATTENTION
            reason = REASON_MS_FOLDER_OUTSIDE
        return state, reason, exe
    if state != STATE_SUSPECT and runs_code:
        state, reason = STATE_ATTENTION, REASON_SCRIPT_HOST
    elif state == STATE_OK:
        # Fora de \Microsoft\, todo programa da pasta do Windows fica "atenção" (R-46),
        # e todo interpretador também, em qualquer pasta (R-47).
        runner = _code_runner_reason(exe, env, allow_known=False)
        if runner:
            state, reason = STATE_ATTENTION, runner
    return state, reason, exe


def classify_tasks(rows, env=None):
    """Classifica as ações das tarefas agendadas (dados já lidos).

    O nome da tarefa não conta como nome de programa. Fora de ``\\Microsoft\\``,
    todo programa da pasta do Windows fica "atenção". Em ``\\Microsoft\\`` só some
    a tarefa cujo programa é da lista fechada ``KNOWN_QUIET_PROGRAMS`` (em System32
    ou SysWOW64); as outras aparecem, e ação COM fica "atenção" (R-46). Interpretador
    fica "atenção" em qualquer pasta e nunca some (R-47). Tarefas
    iguais (mesmo nome e mesmo executável) aparecem uma vez.
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


# --- P3-07 fatia 3: Microsoft Defender -------------------------------------------------

# "N/A: ...", "N/D: ..." etc.: o Windows mandou um aviso no lugar das exclusões.
_HIDDEN_EXCLUSION = re.compile(r'^\s*N/[AD]\b', re.IGNORECASE)
_ADMIN_WORDS = ('administrator', 'administrador')
_EXTENSION_VALUE = re.compile(r'^\*?\.?[^\s\\/:*?"<>|.]+[ .]*$')
_LOOKS_LIKE_PATH = re.compile(r'^(?:[a-z]:|\\\\|%[^%\s]+%|\*)', re.IGNORECASE)
_WILDCARD = re.compile(r'[*?]')
_EXCL_SUSPECT = (REASON_EXCL_USER, REASON_EXCL_TEMP, REASON_EXCL_APPDATA, REASON_EXCL_PROGRAMDATA,
                 REASON_EXCL_DRIVE_ROOT, REASON_EXCL_WINDOWS, REASON_EXCL_EXTENSION, REASON_EXCL_SCRIPT_PROCESS)
_EXCL_REASONS = _EXCL_SUSPECT + (REASON_EXCL_OTHER,)
_DEFENDER_REASONS = {REASON_RT_ON: STATE_OK, REASON_RT_OFF: STATE_ATTENTION,
                     REASON_DEFENDER_UNKNOWN: STATE_ATTENTION, REASON_EXCL_HIDDEN: STATE_ATTENTION,
                     REASON_EXCL_UNKNOWN: STATE_ATTENTION, REASON_EXCL_OTHER: STATE_ATTENTION}
_DEFENDER_REASONS.update({reason: STATE_SUSPECT for reason in _EXCL_SUSPECT})
_EXCL_FIELDS = (('ExclusionPath', 'path'), ('ExclusionProcess', 'process'), ('ExclusionExtension', 'extension'))


def _clean_path(value, env) -> str:
    return _CONTROL.sub(' ', sanitize_path(value, env)).strip()


def _exclusion_values(value):
    """Valores de um campo de exclusão: None, um texto ou uma lista de textos."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _looks_like_path_or_program(text) -> bool:
    """Tem cara de caminho (unidade, \\\\, %VAR%, barra invertida) ou de arquivo com extensão."""
    return bool(_LOOKS_LIKE_PATH.match(text) or '\\' in text or re.search(r'\.[a-z0-9]{1,5}[ .]*$', text, re.I))


def _exclusion_hidden(text) -> bool:
    """Aviso do Windows no lugar da exclusão ("N/A: Must be an administrator..." e parecidos).

    R-52: a palavra "administrador" só conta fora de um caminho ou programa (a pasta
    ``C:\\Users\\Administrador`` é comum e a exclusão dela continua "suspeito").
    """
    # R-52/R-53: nada que pareça caminho ou programa vira o aviso, nem com "N/A" na frente.
    if _looks_like_path_or_program(text):
        return False
    return bool(_HIDDEN_EXCLUSION.match(text)) or any(word in text.lower() for word in _ADMIN_WORDS)


def _exclusion_readable(kind, value) -> bool:
    """O valor parece mesmo um caminho, um programa ou uma extensão? Se não, o texto não aparece (R-07)."""
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    if _exclusion_hidden(text):
        return False
    if kind == 'extension':
        return bool(_EXTENSION_VALUE.match(text))
    if _LOOKS_LIKE_PATH.match(text) or '\\' in text:
        return True
    if kind == 'process' and _extension_reason(ntpath.splitext(text.rstrip(' .'))[1] or '-'):
        return True  # nome de programa com espaço, como "Meu Jogo.exe"
    return not re.search(r'\s', text)


def _extension_reason(text):
    # R-51: o Windows ignora ponto e espaço no fim ("exe." vale "exe").
    ext = text.strip().lstrip('*').lstrip('.').rstrip(' .').strip().lower()
    return REASON_EXCL_EXTENSION if ext in EXECUTABLE_EXTENSIONS else None


def _windows_form(value, env) -> str:
    """R-51: o caminho como o Windows o entende, para comparar (sem diferenciar maiúsculas).

    Tira os prefixos \\\\?\\ e \\??\\, expande as variáveis e tira ponto e espaço do fim
    de cada pedaço (``C:\\Windows.`` e ``C:\\Users \\x`` são ``C:\\Windows`` e ``C:\\Users\\x``).
    """
    text = _expand(_strip_nt_prefix(value.strip()), env).replace('/', '\\')
    parts = [part if part in ('.', '..') else part.rstrip(' .') for part in text.split('\\')]
    text = '\\'.join(parts)
    return _key(text).rstrip('\\') if text.strip('\\') else ''


def _folder_reason(value, env):
    """Motivo "suspeito" de uma pasta ou arquivo excluído, ou None (outros lugares: "atenção").

    R-51: compara na forma do Windows (sem ponto e espaço no fim de cada pedaço). Um
    curinga (``*`` ou ``?``) pode pegar qualquer coisa da pasta onde está: vale a pasta
    de cima (``C:\\*.*`` e ``C:\\Win*`` = a unidade inteira; ``*`` sozinho = tudo).
    """
    norm = _windows_form(value, env)
    base = ntpath.basename(norm)
    if _WILDCARD.search(base) and _extension_reason(ntpath.splitext(base)[1] or base):
        return REASON_EXCL_EXTENSION
    pieces = norm.split('\\')
    for index, piece in enumerate(pieces):
        if _WILDCARD.search(piece):
            norm = '\\'.join(pieces[:index]).rstrip('\\')
            break
    bare = norm.rstrip('\\*').rstrip('\\')
    if re.match(r'^[a-z]:$', bare) or norm in ('*', '', '.'):
        return REASON_EXCL_DRIVE_ROOT
    root = _key(_system_root(env)).rstrip('\\')
    windows = (root, root + '\\system32', root + '\\syswow64')
    if bare in windows:
        return REASON_EXCL_WINDOWS
    folder = norm + '\\'

    def inside(name):
        base_dir = _env_get(env, name)
        if not base_dir:
            return False
        key = _key(base_dir).rstrip('\\')
        return bool(key) and (norm == key or norm.startswith(key + '\\'))
    if '\\temp\\' in folder or '\\tmp\\' in folder or inside('TEMP') or inside('TMP'):
        return REASON_EXCL_TEMP
    if '\\appdata\\' in folder or inside('LOCALAPPDATA') or inside('APPDATA'):
        return REASON_EXCL_APPDATA
    if re.match(r'^[a-z]:\\programdata\\', folder) or inside('ProgramData'):
        return REASON_EXCL_PROGRAMDATA
    if re.match(r'^[a-z]:\\(users|documents and settings)\\', folder) or inside('USERPROFILE'):
        return REASON_EXCL_USER
    return None


def classify_exclusion(kind, value, env=None):
    """(estado, motivo) de uma exclusão do Defender. Nunca dá OK (toda exclusão vale conferir)."""
    env = _env(env)
    if not isinstance(value, str) or not value.strip():
        return STATE_ATTENTION, REASON_EXCL_OTHER
    # R-53: a classificação não depende de o texto parecer "normal"; o filtro de texto
    # estranho (em classify_defender e na tela) só esconde o texto, nunca rebaixa.
    if kind == 'extension':
        reason = _extension_reason(value)
    elif kind == 'process':
        reason = (REASON_EXCL_SCRIPT_PROCESS
                  if _is_script_host(value, env) or _is_interpreter(value, env) else _folder_reason(value, env))
    else:
        reason = _folder_reason(value, env)
    return (STATE_SUSPECT, reason) if reason else (STATE_ATTENTION, REASON_EXCL_OTHER)


def _defender_item(reason, env, kind=None, value=None):
    state = _DEFENDER_REASONS[reason]
    name = DEFENDER_KIND_TEXTS.get(kind, 'Microsoft Defender')
    return {'source': 'defender', 'name': name, 'kind': kind, 'path': _clean_path(value, env) if value else '',
            'state': state, 'reason': reason, 'count': 1}


def classify_defender(data, env=None):
    """Classifica a situação do Defender (dados já lidos). Só lê; nunca pede administrador.

    Proteção em tempo real ligada (com o serviço e o antivírus do Defender ligados) dá
    OK; desligada fica "atenção" (pode ser outro programa de segurança); sem dado
    legível, "atenção" ("não foi possível conferir"). Cada exclusão é um item: nunca
    OK; pasta de usuário, temporária, AppData, ProgramData, raiz de unidade, pasta do
    Windows (ou System32/SysWOW64) inteira, extensão de programa ou script, e programa
    que roda scripts ou comandos ficam "suspeito". Sem administrador o Windows esconde
    as exclusões ("N/A: ..."): vira um item "atenção", sem pedir elevação.
    """
    env = _env(env)
    rows = _as_list(data)
    data = rows[0] if rows and isinstance(rows[0], dict) else {}
    status = data.get('Status')
    status = status if isinstance(status, dict) else {}
    flags = [status.get(k) for k in ('RealTimeProtectionEnabled', 'AntivirusEnabled', 'AMServiceEnabled')]
    if any(flag is False for flag in flags):
        items = [_defender_item(REASON_RT_OFF, env)]
    elif all(flag is True for flag in flags):
        items = [_defender_item(REASON_RT_ON, env)]
    else:
        items = [_defender_item(REASON_DEFENDER_UNKNOWN, env)]
    pref = data.get('Preference')
    if not isinstance(pref, dict):
        items.append(_defender_item(REASON_EXCL_UNKNOWN, env))
        return items
    hidden = unreadable = False
    seen = set()
    for field, kind in _EXCL_FIELDS:
        for value in _exclusion_values(pref.get(field)):
            state, reason = classify_exclusion(kind, value, env)
            readable = _exclusion_readable(kind, value)
            if state != STATE_SUSPECT:
                # R-53: só o que não dá "suspeito" pode virar aviso ou "não foi possível conferir".
                if _exclusion_hidden(value.strip()):
                    hidden = True
                    continue
                if not readable:
                    # R-07: um texto que não parece exclusão não aparece na tela.
                    unreadable = True
                    continue
            key = (kind, _windows_form(value, env) if readable else value.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            # Texto estranho que dá "suspeito": continua "suspeito", só sem o texto (R-07).
            items.append(_defender_item(reason, env, kind, value if readable else None))
    if hidden:
        items.append(_defender_item(REASON_EXCL_HIDDEN, env))
    if unreadable:
        items.append(_defender_item(REASON_EXCL_UNKNOWN, env))
    return items


# --- P3-07 fatia 3: conexões de rede ---------------------------------------------------

def _port(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def classify_connections(rows, env=None):
    """Conexões para portas comuns de mineração (dados já lidos): cada uma é "suspeito".

    Só a porta remota e o programa dono são usados (o endereço remoto nunca é lido
    nem guardado). Conexões iguais (porta, programa e caminho) aparecem uma vez.
    """
    env = _env(env)
    grouped = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        port = _port(row.get('RemotePort'))
        if port not in MINING_PORTS:
            continue
        name = row.get('Name') if isinstance(row.get('Name'), str) else ''
        path = row.get('Path') if isinstance(row.get('Path'), str) else ''
        key = (port, name.strip().lower(), _key(_strip_nt_prefix(path.strip())) if path.strip() else '')
        if key in grouped:
            grouped[key]['count'] += 1
            continue
        grouped[key] = {'source': 'network', 'name': _clean_name(name, env), 'path': _clean_path(path, env),
                        'port': port, 'state': STATE_SUSPECT, 'reason': REASON_MINING_PORT, 'count': 1}
    return list(grouped.values())


# --- P3-07 fatia 4: uso de CPU e GPU com o PC parado ----------------------------------

def _percent(value):
    """Um número de porcentagem válido (0 a 100), ou None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float('inf'), float('-inf')) or value < 0:  # NaN e infinito
        return None
    return min(float(value), 100.0)


def _samples(value):
    """Amostras legíveis: um número, uma lista de números ou, por amostra, uma lista a somar."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list):
        return []
    found = []
    for sample in value:
        if isinstance(sample, list):
            parts = [_percent(v) for v in sample]
            parts = [v for v in parts if v is not None]
            sample = sum(parts) if parts else None
        sample = _percent(sample)
        if sample is not None:
            found.append(sample)
    return found


def _rounded(value):
    """Arredonda como é mostrado (meio para cima), ou None."""
    value = _percent(value)
    return None if value is None else int(value + 0.5)


def _idle_state(value):
    """(estado, motivo) de uma média: o número arredondado decide; nunca "suspeito"."""
    shown = _rounded(value)
    if shown is None:
        return STATE_ATTENTION, REASON_IDLE_UNKNOWN
    if shown >= IDLE_LIMIT:
        return STATE_ATTENTION, REASON_IDLE_HIGH
    return STATE_OK, REASON_IDLE_OK


def _idle_self_process(name) -> bool:
    """Processo da própria medição (ou o total/ocioso do Windows): não é citado."""
    base = name.strip().lower()
    base = base[:-4] if base.endswith('.exe') else base
    return base in IDLE_SELF_PROCESSES


def classify_idle(data, env=None):
    """Uso de CPU e GPU com o PC parado (dados já lidos). Só "OK" ou "atenção".

    Média (arredondada) de 25% ou mais na CPU ou na GPU = "atenção" (pode ser um
    programa em segundo plano, uma atualização do Windows ou, às vezes, um minerador);
    abaixo = OK; sem dado ou ilegível = "atenção" ("não foi possível medir"). Só o
    nome dos 3 programas que mais usaram a CPU fica guardado, limpo por ``_clean_name``.
    """
    env = _env(env)
    rows = _as_list(data)
    data = rows[0] if rows and isinstance(rows[0], dict) else {}
    items = []
    for kind, field in (('cpu', 'Cpu'), ('gpu', 'Gpu')):
        found = _samples(data.get(field))
        if kind == 'cpu' and not any(found):
            # Revisão 2 da PR #197: CPU em 0 nas amostras todas é leitura que falhou, não OK.
            found = []
        value = _rounded(sum(found) / len(found)) if found else None
        state, reason = _idle_state(value)
        items.append({'source': 'idle', 'kind': kind, 'name': IDLE_KIND_TEXTS[kind], 'value': value,
                      'state': state, 'reason': reason})
    top = []
    raw_top = data.get('Top')
    for name in ([raw_top] if isinstance(raw_top, str) else raw_top if isinstance(raw_top, list) else []):
        name = _clean_name(name, env)
        if name and name not in top and not _idle_self_process(name):
            top.append(name)
        if len(top) == 3:
            break
    return {'items': items, 'top': top}


def read_idle(ps=None, env=None):
    """Mede por 2 minutos (só leitura) e classifica. Nunca levanta erro: falha = "não foi possível medir"."""
    if ps is None:
        from optimization_engine import _ps  # noqa: PLC0415 - preguiçoso de propósito

        def ps(code):
            return _ps(code, timeout=IDLE_TIMEOUT)
    try:
        data = ps(IDLE_QUERY)
    except Exception:  # noqa: BLE001 - R-07: a mensagem original não é guardada
        data = None
    return classify_idle(data, env)


def _idle_effective(item):
    """Estado e motivo de um item do uso parado, a partir do número guardado (R-32).

    Vale o mais grave entre o guardado e o recalculado; nunca "suspeito" só pelo número.
    """
    state, reason = _idle_state(item.get('value'))
    if item.get('state') in (STATE_ATTENTION, STATE_SUSPECT):
        # R-32: vale o mais grave entre o guardado e o recalculado (nunca "suspeito" aqui).
        return STATE_ATTENTION, reason
    if state == STATE_OK and item.get('reason') != REASON_IDLE_OK:
        # O estado fica o mais grave, mas o texto vem do número (revisão da PR #197):
        # "uso alto" nunca aparece ao lado de uma média baixa.
        return STATE_ATTENTION, reason
    return state, reason


def _idle_section(idle, env, counts):
    """Linhas da seção "USO COM O PC PARADO" (soma os estados em ``counts``)."""
    lines = ['USO COM O PC PARADO']
    if not isinstance(idle, dict):
        lines += ['  ' + IDLE_NOT_MEASURED, '']
        return lines
    measured = idle.get('measured_at')
    if isinstance(measured, str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', measured):
        # Revisão da PR #197: uma medição reaproveitada diz de quando ela é.
        lines.append(f'  Medido às {measured}.')
    items = [i for i in _as_list(idle.get('items')) if isinstance(i, dict)]
    if not items:
        items = classify_idle(None, env)['items']
    high = False
    for item in items:
        state, reason = _idle_effective(item)
        counts[state] += 1
        high = high or reason == REASON_IDLE_HIGH
        label = IDLE_KIND_TEXTS.get(item.get('kind'), 'Medição')
        shown = _rounded(item.get('value')) if reason != REASON_IDLE_UNKNOWN else None
        lines.append(f'  [{state}] {label}: ' + (f'média de {shown}%' if shown is not None else 'sem dado'))
        lines.append('      Motivo: ' + REASON_TEXTS[reason])
        if state != STATE_OK:
            lines.append('      O que fazer: ' + IDLE_ADVICE)
    top = []
    for name in _as_list(idle.get('top')) if isinstance(idle.get('top'), list) else []:
        name = _clean_name(name, env)
        if name and name not in top and not _idle_self_process(name):
            top.append(name)
    if high and top:
        lines.append('  ' + IDLE_TOP_TEXT + ', '.join(top[:3]) + '.')
    lines += ['  ' + IDLE_NOTE, '  ' + IDLE_COST_NOTE, '']
    return lines


_CHECKUP_KEYS = ('autostart', 'tasks', 'processes', 'unchecked', 'defender', 'network', 'errors')


def _idle_only_lines(result, env):
    """Janela só com a medição do uso parado (o check-up completo não rodou)."""
    counts = {STATE_OK: 0, STATE_ATTENTION: 0, STATE_SUSPECT: 0}
    lines = ['USO COM O PC PARADO — SÓ LEITURA', NEVER_CHANGES, '']
    lines += _idle_section(result.get('idle'), env, counts)
    lines.append(f'RESUMO: OK {counts[STATE_OK]} · atenção {counts[STATE_ATTENTION]} · '
                 f'suspeito {counts[STATE_SUSPECT]}')
    lines.append(IDLE_ONLY_NOTE)
    if counts[STATE_ATTENTION] + counts[STATE_SUSPECT]:
        lines += ['', NOT_CERTAIN, RECOMMENDATION]
    return lines


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
    """Faz as seis consultas (só leitura) e classifica. Erro vira código, nunca texto do sistema."""
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
    defender = []
    try:
        defender = classify_defender(ps(DEFENDER_QUERY), env)
    except Exception:  # noqa: BLE001
        errors.append('defender')
    network = []
    try:
        network = classify_connections(ps(NETWORK_QUERY), env)
    except Exception:  # noqa: BLE001
        errors.append('network')
    return {'autostart': classify_autostart(entries, env), 'tasks': tasks, 'processes': processes['items'],
            'unchecked': processes['unchecked'], 'defender': defender, 'network': network, 'errors': errors}


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
    if new_state == STATE_OK and item.get('source') != 'process':
        # R-45/R-46/R-47: inicialização e tarefas não têm os argumentos lidos. Tarefa
        # mostrada nunca dá OK com programa da pasta do Windows (as da lista fechada
        # em \Microsoft\ nem aparecem); inicialização, só os da lista fechada.
        # Interpretador (R-47) e nome incerto (R-48) ficam "atenção" em qualquer
        # pasta, inclusive com nome da lista fechada.
        runner = _code_runner_reason(path, env, allow_known=item.get('source') != 'task')
        if runner:
            new_state, new_reason = STATE_ATTENTION, runner
    if _ORDER[new_state] < _ORDER[state]:
        return new_state, new_reason
    return state, reason


def _defender_effective(item, env):
    """Estado e motivo de um item do Defender, sempre a partir dos códigos (R-32).

    Só o motivo "proteção ligada" pode dar OK; uma exclusão é classificada de novo
    pelo valor guardado e vale o mais grave (nunca promove a OK).
    """
    reason = item.get('reason')
    kind = item.get('kind')
    if kind in DEFENDER_KIND_TEXTS or reason in _EXCL_REASONS:
        # Uma exclusão nunca dá OK: o valor guardado é classificado de novo.
        new_state, new_reason = classify_exclusion(kind, item.get('path'), env)
        if (new_state != STATE_SUSPECT and kind in DEFENDER_KIND_TEXTS
                and not _exclusion_readable(kind, item.get('path'))):
            # Valor que não parece exclusão (e não dá "suspeito"): não aparece (R-07);
            # vale o mais grave entre o guardado e "não foi possível conferir" (R-53).
            if _DEFENDER_REASONS.get(reason) == STATE_SUSPECT:
                return STATE_SUSPECT, reason
            return STATE_ATTENTION, REASON_EXCL_UNKNOWN
        if reason in _EXCL_REASONS and _ORDER[_DEFENDER_REASONS[reason]] <= _ORDER[new_state]:
            return _DEFENDER_REASONS[reason], reason
        return new_state, new_reason
    if reason not in _DEFENDER_REASONS:
        return STATE_ATTENTION, REASON_DEFENDER_UNKNOWN
    # O estado vem do motivo (o "state" do dict é ignorado): só "proteção ligada" é OK.
    return _DEFENDER_REASONS[reason], reason


def _special_effective(item, env):
    if item.get('source') == 'network':
        # Toda conexão mostrada é para uma porta comum de mineração: sempre "suspeito".
        return STATE_SUSPECT, REASON_MINING_PORT
    return _defender_effective(item, env)


def _special_lines(item, env, with_count=False):
    """Linhas de um item do Defender ou de uma conexão de rede."""
    state, reason = _special_effective(item, env)
    if item.get('source') == 'network':
        name = _clean_name(item.get('name'), env) or 'programa sem nome'
        count = item.get('count')
        if isinstance(count, int) and not isinstance(count, bool) and count > 1:
            name += f' ({count} conexões)'
        port = _port(item.get('port'))
        lines = [f'  [{state}] {name}' + (f' — porta {port}' if port in MINING_PORTS else '')]
    else:
        kind = item.get('kind')
        lines = [f'  [{state}] ' + DEFENDER_KIND_TEXTS.get(kind, 'Microsoft Defender')]
    path = _clean_path(item.get('path'), env)
    network = item.get('source') == 'network'
    if not network and item.get('kind') in DEFENDER_KIND_TEXTS and not _exclusion_readable(item.get('kind'), path):
        path = ''
    if path and not network and item.get('kind') == 'extension' and not path.startswith(('.', '*')):
        path = '.' + path
    if path:
        lines.append(('      Onde: ' if network else '      Item: ') + path)
    lines.append('      Motivo: ' + REASON_TEXTS[reason])
    advice = NETWORK_ADVICE if network else DEFENDER_ADVICE_TEXTS.get(state)
    if advice:
        lines.append('      O que fazer: ' + advice)
    return lines, state


_SPECIAL_SOURCES = ('defender', 'network')


def _item_lines(item, env, with_count=False):
    if item.get('source') in _SPECIAL_SOURCES:
        return _special_lines(item, env, with_count)
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
    if 'idle' in result and not any(key in result for key in _CHECKUP_KEYS):
        return _idle_only_lines(result, env)
    errors = [e for e in _as_list(result.get('errors'))]
    counts = {STATE_OK: 0, STATE_ATTENTION: 0, STATE_SUSPECT: 0}
    lines = ['CHECK-UP DE SEGURANÇA — SÓ LEITURA', NEVER_CHANGES]
    checked = result.get('checked_at')
    if isinstance(checked, str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', checked):
        # Revisão 2 da PR #197: o check-up mostrado de novo diz de quando ele é.
        lines.append(f'Check-up feito às {checked}.')
    lines.append('')

    def section(title, items, with_count, empty_text, special=None):
        lines.append(title)
        valid = [i for i in _as_list(items) if isinstance(i, dict)]
        # A seção decide como o item é mostrado, não o "source" guardado no dict.
        valid = [dict(i, source=special) if special or i.get('source') in _SPECIAL_SOURCES else i
                 for i in valid]
        valid.sort(key=lambda i: _ORDER[(_special_effective if special else _effective)(i, env)[0]])
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
    # Sem administrador o Windows pode esconder tarefas: com essa nota, nunca a frase de "tudo limpo".
    # Por isso a frase de "tudo limpo" não existe mais: sem alerta, a frase do fim é a neutra.
    lines.insert(len(lines) - 1, '  ' + TASKS_NOTE)
    section('PROCESSOS EM EXECUÇÃO', result.get('processes'), True,
                              None if 'processes' in errors else 'Nenhum processo foi informado.')
    unchecked = result.get('unchecked')
    unchecked = unchecked if isinstance(unchecked, int) and not isinstance(unchecked, bool) and unchecked > 0 else 0
    if unchecked == 1:
        lines.insert(len(lines) - 1, '  1 processo não pôde ser conferido (o Windows não informou de onde '
                                     'ele roda). Isso é comum em processos do próprio Windows.')
    elif unchecked:
        lines.insert(len(lines) - 1, f'  {unchecked} processos não puderam ser conferidos (o Windows não '
                                     'informou de onde eles rodam). Isso é comum em processos do próprio Windows.')
    defender_items = [i for i in _as_list(result.get('defender')) if isinstance(i, dict)]
    section('MICROSOFT DEFENDER', defender_items, False,
            None if 'defender' in errors else DEFENDER_EMPTY, special='defender')
    if defender_items and not any(i.get('kind') in DEFENDER_KIND_TEXTS
                                  or i.get('reason') in (REASON_EXCL_HIDDEN, REASON_EXCL_UNKNOWN)
                                  for i in defender_items):
        lines.insert(len(lines) - 1, '  ' + DEFENDER_NO_EXCLUSIONS)
    section('CONEXÕES DE REDE', result.get('network'), True,
            None if 'network' in errors else NETWORK_EMPTY, special='network')
    if 'network' not in errors:
        lines.insert(len(lines) - 1, '  ' + NETWORK_NOTE)
    # P3-07 fatia 4: a medição do uso parado é à parte; sem ela, a seção diz como medir.
    lines.extend(_idle_section(result.get('idle'), env, counts))
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
    else:
        lines.append(NOT_ALL_CHECKED)
    return lines
