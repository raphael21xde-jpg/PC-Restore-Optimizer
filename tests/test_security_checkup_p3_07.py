"""P3-07 fatia 1: check-up de segurança (inicialização e processos), só leitura.

Só dados sintéticos: o PowerShell é sempre um ``ps`` falso; nenhum comando real,
nenhum registro, WMI ou subprocess.
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import security_checkup as sc  # noqa: E402

ENV = {
    'USERPROFILE': r'C:\Users\Fulano Silva',
    'USERNAME': 'Fulano Silva',
    'SystemRoot': r'C:\Windows',
    'ProgramFiles': r'C:\Program Files',
    'ProgramFiles(x86)': r'C:\Program Files (x86)',
    'ProgramData': r'C:\ProgramData',
    'LOCALAPPDATA': r'C:\Users\Fulano Silva\AppData\Local',
    'APPDATA': r'C:\Users\Fulano Silva\AppData\Roaming',
    'TEMP': r'C:\Users\Fulano Silva\AppData\Local\Temp',
}
FORBIDDEN_WORDS = ('vírus', 'remover', 'apagar', 'quarentena')
# A frase de "tudo limpo" saiu na fatia 2 (a nota das tarefas sempre aparece).
ALL_CLEAR_TEXT = 'não apareceu nenhum sinal de alerta'


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


def _state(path, name=None):
    return sc.classify_path(name or Path(path.replace('\\', '/')).name, path, ENV)[0]


class SanitizeTests(unittest.TestCase):
    def test_user_folder_becomes_userprofile_keeping_spelling(self):
        out = sc.sanitize_path(r'c:\users\fulano silva\AppData\Local\MeuApp\App.exe', ENV)
        self.assertEqual(out, r'%USERPROFILE%\AppData\Local\MeuApp\App.exe')

    def test_other_user_is_hidden(self):
        out = sc.sanitize_path(r'D:\Users\Beltrano\Downloads\x.exe', ENV)
        self.assertEqual(out, r'D:\Users\<outro usuário>\Downloads\x.exe')
        self.assertNotIn('Beltrano', out)

    def test_prefix_of_user_name_is_not_userprofile(self):
        out = sc.sanitize_path(r'C:\Users\Fulano Silvana\x.exe', ENV)
        self.assertNotIn('Silvana', out)
        self.assertNotIn('%USERPROFILE%', out)

    def test_non_text_is_empty(self):
        for value in (None, 42, ['x'], {'a': 1}):
            self.assertEqual(sc.sanitize_path(value, ENV), '')


class CommandTests(unittest.TestCase):
    def test_quoted_executable_drops_arguments(self):
        cmd = r'"C:\Program Files\App\app.exe" --token=SEGREDO /min'
        self.assertEqual(sc.executable_from_command(cmd), r'C:\Program Files\App\app.exe')

    def test_unquoted_with_spaces_until_exe_is_empty(self):
        # FIX-P3-07-01 (R-40): sem aspas fechadas, espaço no executável = vazio (pode ser argumento).
        cmd = r'C:\Program Files (x86)\Outro App\run.exe -background SEGREDO'
        self.assertEqual(sc.executable_from_command(cmd), '')
        self.assertEqual(sc.executable_from_command(r'C:\x\run.exe -background SEGREDO'), r'C:\x\run.exe')

    def test_script_and_first_token(self):
        self.assertEqual(sc.executable_from_command(r'C:\x\a.vbs arg'), r'C:\x\a.vbs')
        self.assertEqual(sc.executable_from_command('ctfmon arg2'), 'ctfmon')

    def test_empty_and_strange(self):
        for value in (None, '', '   ', 3, '""'):
            self.assertEqual(sc.executable_from_command(value), '')


class ClassifyPathTests(unittest.TestCase):
    def test_system_name_outside_system32_is_suspect(self):
        path = r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe'
        self.assertEqual(_state(path), sc.STATE_SUSPECT)

    def test_each_system_name(self):
        for name in sc.SYSTEM_NAMES:
            with self.subTest(name=name):
                self.assertEqual(_state(r'C:\Windows\System32\\' + name), sc.STATE_OK)
                self.assertEqual(_state(r'C:\Windows\SysWOW64\\' + name), sc.STATE_OK)
                self.assertEqual(_state(r'C:\Program Files\X\\' + name), sc.STATE_SUSPECT)
                self.assertEqual(_state(r'C:\Windows\System32\Tasks\\' + name), sc.STATE_SUSPECT)

    def test_explorer_only_in_systemroot(self):
        self.assertEqual(_state(r'C:\Windows\explorer.exe'), sc.STATE_OK)
        self.assertEqual(_state(r'C:\Windows\Temp\explorer.exe'), sc.STATE_SUSPECT)
        self.assertEqual(_state(r'C:\explorer.exe'), sc.STATE_SUSPECT)

    def test_name_alone_marks_system_name(self):
        state = sc.classify_path('lsass.exe', r'C:\Program Files\App\outro.exe', ENV)[0]
        self.assertEqual(state, sc.STATE_SUSPECT)

    def test_attention_places(self):
        for path in (r'C:\Users\Fulano Silva\AppData\Local\Temp\a.exe',
                     r'C:\Windows\Temp\a.exe',
                     r'C:\Users\Fulano Silva\AppData\Local\Prog\a.exe',
                     r'D:\Users\Beltrano\AppData\Roaming\a.exe',
                     r'C:\ProgramData\Coisa\a.exe',
                     r'C:\a.exe', r'E:\a.exe',
                     r'D:\Jogos\a.exe', r'\\servidor\pasta\a.exe', 'a.exe'):
            with self.subTest(path=path):
                self.assertEqual(_state(path), sc.STATE_ATTENTION)

    def test_scripts_are_attention_even_in_program_files(self):
        for ext in ('.vbs', '.ps1', '.js', '.bat', '.cmd'):
            with self.subTest(ext=ext):
                self.assertEqual(_state(r'C:\Program Files\App\run' + ext), sc.STATE_ATTENTION)

    def test_empty_or_unreadable_is_attention(self):
        for value in (None, '', '   ', 42):
            self.assertEqual(sc.classify_path('x.exe', value, ENV)[0], sc.STATE_ATTENTION)

    def test_ok_places(self):
        for path in (r'C:\Windows\System32\notepad.exe', r'C:\Program Files\App\app.exe',
                     r'C:\Program Files (x86)\App\app.exe', r'c:\program files\app\APP.EXE'):
            with self.subTest(path=path):
                self.assertEqual(_state(path), sc.STATE_OK)

    def test_environment_variables_are_expanded(self):
        self.assertEqual(_state(r'%ProgramFiles%\App\app.exe'), sc.STATE_OK)
        self.assertEqual(_state(r'%APPDATA%\svchost.exe'), sc.STATE_SUSPECT)
        self.assertEqual(_state(r'%NAOEXISTE%\app.exe'), sc.STATE_ATTENTION)

    def test_unknown_place_never_ok(self):
        self.assertEqual(_state(r'C:\WindowsX\app.exe'), sc.STATE_ATTENTION)
        self.assertEqual(_state(r'C:\Program Files Fake\app.exe'), sc.STATE_ATTENTION)


class AutostartTests(unittest.TestCase):
    def test_run_entries_and_startup_folder(self):
        entries = [
            {'source': 'run_user', 'name': 'Bom', 'command': r'"C:\Program Files\Bom\bom.exe" /min'},
            {'source': 'run_all', 'name': 'Falso', 'command': r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe -k x'},
            {'source': 'startup_user', 'name': 'Atalho.lnk', 'extension': '.lnk'},
            {'source': 'startup_all', 'name': 'abre.vbs', 'extension': '.vbs'},
            {'source': 'startup_user', 'name': 'direto.exe', 'extension': '.exe'},
        ]
        items = sc.classify_autostart(entries, ENV)
        states = [i['state'] for i in items]
        self.assertEqual(states, [sc.STATE_OK, sc.STATE_SUSPECT, sc.STATE_ATTENTION,
                                  sc.STATE_ATTENTION, sc.STATE_ATTENTION])
        self.assertEqual(items[1]['path'], '')  # sem aspas e com espaço: nada é mostrado (R-40)
        self.assertEqual(items[2]['reason'], sc.REASON_SHORTCUT)
        self.assertEqual(items[3]['reason'], sc.REASON_SCRIPT)

    def test_code_runners_in_system32_are_attention(self):
        # R-45 (revisão da PR #189): rundll32 e regsvr32 rodam o que vem nos argumentos.
        for exe in ('rundll32.exe', 'regsvr32.exe', 'mshta.exe', 'cscript.exe', 'pwsh.exe'):
            with self.subTest(exe=exe):
                entries = [{'source': 'run_all', 'name': 'X',
                            'command': 'C:\\Windows\\System32\\' + exe + ' C:\\a\\b.dll,Entrada'}]
                item = sc.classify_autostart(entries, ENV)[0]
                self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST))
                text = '\n'.join(sc.checkup_lines({'autostart': [item], 'errors': []}, ENV))
                self.assertIn('[atenção] X', text)
        forged = {'autostart': [{'source': 'run_all', 'name': 'F', 'path': r'C:\Windows\System32\rundll32.exe',
                                 'state': sc.STATE_OK, 'reason': sc.REASON_OK}], 'errors': []}
        self.assertIn('[atenção] F', '\n'.join(sc.checkup_lines(forged, ENV)))
        # Processos não mudam: o caminho do executável é o que o Windows informa.
        procs = [{'Name': 'rundll32.exe', 'ExecutablePath': r'C:\Windows\System32\rundll32.exe'}]
        self.assertEqual(sc.classify_processes(procs, ENV)['items'][0]['state'], sc.STATE_OK)

    def test_script_host_is_attention(self):
        entries = [{'source': 'run_user', 'name': 'Script',
                    'command': r'C:\Windows\System32\wscript.exe "C:\Users\Fulano Silva\a.vbs"'}]
        self.assertEqual(sc.classify_autostart(entries, ENV)[0]['state'], sc.STATE_ATTENTION)

    def test_strange_entries_do_not_break(self):
        for value in (None, [], 'x', 42, [None, 'x', 3, {}], {'value': []}):
            items = sc.classify_autostart(value, ENV)
            self.assertIsInstance(items, list)
            for item in items:
                self.assertNotEqual(item['state'], sc.STATE_OK)


class ProcessTests(unittest.TestCase):
    def test_without_path_is_unchecked(self):
        procs = [{'Name': 'System', 'ExecutablePath': None},
                 {'Name': 'svchost.exe', 'ExecutablePath': r'C:\Windows\System32\svchost.exe'},
                 {'Name': 'svchost.exe', 'ExecutablePath': r'C:\Windows\System32\svchost.exe'},
                 {'Name': 'csrss.exe'}]
        out = sc.classify_processes(procs, ENV)
        self.assertEqual(out['unchecked'], 2)
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(out['items'][0]['count'], 2)
        self.assertEqual(out['items'][0]['state'], sc.STATE_OK)

    def test_fake_svchost_in_appdata_is_suspect(self):
        procs = [{'Name': 'svchost.exe',
                  'ExecutablePath': r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe'}]
        item = sc.classify_processes(procs, ENV)['items'][0]
        self.assertEqual(item['state'], sc.STATE_SUSPECT)
        self.assertEqual(item['path'], r'%USERPROFILE%\AppData\Roaming\svchost.exe')

    def test_ps51_value_wrapper_and_none(self):
        wrapped = {'value': [{'Name': 'a.exe', 'ExecutablePath': r'C:\Program Files\a.exe'}], 'Count': 1}
        self.assertEqual(len(sc.classify_processes(wrapped, ENV)['items']), 1)
        single = {'Name': 'a.exe', 'ExecutablePath': r'C:\Program Files\a.exe'}
        self.assertEqual(len(sc.classify_processes(single, ENV)['items']), 1)
        for value in (None, [], 'x', 5, [None, 7]):
            out = sc.classify_processes(value, ENV)
            self.assertEqual(out['items'], [])


# P3-07 fatia 3: por padrão, o Defender ligado e sem exclusões mostradas, e nenhuma conexão.
DEFENDER_ON = {'Status': {'AMServiceEnabled': True, 'AntivirusEnabled': True,
                          'RealTimeProtectionEnabled': True},
               'Preference': {'ExclusionPath': None, 'ExclusionProcess': None, 'ExclusionExtension': None}}
_DEFAULT = object()


def _fake_ps(run=None, startup=None, procs=None, fail=(), tasks=None, defender=_DEFAULT, network=None):
    calls = []
    defender = DEFENDER_ON if defender is _DEFAULT else defender

    def ps(code, timeout=22):
        calls.append(code)
        if 'Get-MpComputerStatus' in code:
            kind = 'defender'
        elif 'Get-NetTCPConnection' in code:
            kind = 'network'
        elif 'Win32_Process' in code:
            kind = 'processes'
        elif 'Get-ScheduledTask' in code:
            kind = 'tasks'
        elif 'GetFolderPath' in code:
            kind = 'startup'
        else:
            kind = 'run'
        if kind in fail:
            raise RuntimeError(r'Acesso negado: C:\Users\Fulano Silva\NTUSER.DAT')
        return {'run': run, 'startup': startup, 'processes': procs, 'tasks': tasks,
                'defender': defender, 'network': network}[kind]
    ps.calls = calls
    return ps


class ReadCheckupTests(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_queries_are_read_only(self):
        ps = _fake_ps()
        sc.read_checkup(ps, ENV)
        self.assertEqual(len(ps.calls), 6)  # P3-07 fatia 3: + Defender e rede
        code = '\n'.join(ps.calls)
        for key in (r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
                    r'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
                    r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
                    r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
                    r'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
                    r'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce'):
            self.assertIn(key, code)
        self.assertIn('Get-ItemProperty', code)
        self.assertIn('Get-ChildItem', code)
        self.assertIn('Get-CimInstance Win32_Process', code)
        self.assertIn('Select-Object Name,ExecutablePath', code)
        for forbidden in ('CommandLine', 'Stop-Process', 'Remove-', 'Set-MpPreference',
                          'Add-MpPreference', 'RunAs', 'Set-Item', 'New-Item'):
            self.assertNotIn(forbidden, code)

    def test_full_result_without_user_names_or_arguments(self):
        run = [{'Key': r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'Name': 'Falso',
                'Command': r'"C:\Users\Fulano Silva\AppData\Roaming\svchost.exe" --senha=SEGREDO'},
               {'Key': r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 'Name': 'Outro',
                'Command': r'D:\Users\Beltrano\x\y.exe /token ABC123'},
               {'Key': r'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce', 'Error': True}]
        startup = {'value': [{'Scope': 0, 'Name': 'Atalho.lnk', 'Extension': '.lnk'},
                             {'Scope': 1, 'Name': 'desktop.ini', 'Extension': '.ini'}]}
        procs = [{'Name': 'app.exe', 'ExecutablePath': r'C:\Users\Fulano Silva\Desktop\app.exe'},
                 {'Name': 'b.exe', 'ExecutablePath': r'E:\Users\Ciclano\b.exe'}]
        result = sc.read_checkup(_fake_ps(run, startup, procs), ENV)
        text = self._text(result)
        for secret in ('Fulano', 'Silva', 'Beltrano', 'Ciclano', 'SEGREDO', 'ABC123', '--senha', '/token'):
            self.assertNotIn(secret, text)
        self.assertIn(r'%USERPROFILE%\AppData\Roaming\svchost.exe', text)
        self.assertIn('<outro usuário>', text)
        self.assertNotIn('desktop.ini', text)
        self.assertIn(sc.STATE_SUSPECT, text)
        self.assertIn(sc.RECOMMENDATION, text)
        self.assertIn('Não foi possível ler parte', text)

    def test_recommendation_text_is_exact(self):
        self.assertIn('Verificação offline do Microsoft Defender', sc.RECOMMENDATION)
        self.assertIn('Malwarebytes', sc.RECOMMENDATION)
        self.assertIn('só do site oficial', sc.RECOMMENDATION)

    def test_query_failure_says_could_not_read_without_system_text(self):
        result = sc.read_checkup(_fake_ps(fail=('run', 'startup', 'processes')), ENV)
        text = self._text(result)
        self.assertIn('não foi possível ler', text)
        self.assertNotIn('Acesso negado', text)
        self.assertNotIn('NTUSER', text)
        self.assertNotIn('Fulano', text)
        self.assertNotIn(ALL_CLEAR_TEXT, text)
        self.assertEqual(len(result['errors']), 3)

    def test_ps_raising_on_non_windows_does_not_break(self):
        def ps(code, timeout=22):
            raise OSError('sem PowerShell')
        result = sc.read_checkup(ps, ENV)
        self.assertEqual(result['autostart'], [])
        self.assertNotIn(ALL_CLEAR_TEXT, self._text(result))

    def test_empty_none_and_wrapped_outputs(self):
        for run, startup, procs in ((None, None, None), ([], [], []),
                                    ({'value': []}, {'value': []}, {'value': []})):
            result = sc.read_checkup(_fake_ps(run, startup, procs), ENV)
            self.assertEqual(result['errors'], [])
            self.assertIsInstance(self._text(result), str)

    def test_all_clear_only_when_everything_checked(self):
        run = [{'Key': r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'Name': 'Bom',
                'Command': r'"C:\Program Files\Bom\bom.exe"'}]
        procs = [{'Name': 'bom.exe', 'ExecutablePath': r'C:\Program Files\Bom\bom.exe'}]
        clean = self._text(sc.read_checkup(_fake_ps(run, None, procs), ENV))
        # P3-07 fatia 2: a nota das tarefas (sem administrador) deixa a frase neutra.
        self.assertIn(sc.TASKS_NOTE, clean)
        self.assertNotIn(ALL_CLEAR_TEXT, clean)
        self.assertIn(sc.NOT_ALL_CHECKED, clean)
        self.assertNotIn(sc.RECOMMENDATION, clean)
        old = {'autostart': [], 'processes': [], 'unchecked': 0, 'errors': []}
        self.assertNotIn(ALL_CLEAR_TEXT, self._text(old))
        procs_unchecked = procs + [{'Name': 'System', 'ExecutablePath': None}]
        partial = self._text(sc.read_checkup(_fake_ps(run, None, procs_unchecked), ENV))
        self.assertNotIn(ALL_CLEAR_TEXT, partial)
        self.assertIn('1 processo não pôde ser conferido', partial)

    def test_no_forbidden_words_in_any_line(self):
        run = [{'Key': r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'Name': 'X',
                'Command': r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe'}]
        startup = [{'Scope': 0, 'Name': 'a.vbs', 'Extension': '.vbs'}]
        procs = [{'Name': 'lsass.exe', 'ExecutablePath': r'C:\Temp\lsass.exe'}, {'Name': 'System'}]
        for result in (sc.read_checkup(_fake_ps(run, startup, procs), ENV),
                       sc.read_checkup(_fake_ps(fail=('run', 'startup', 'processes')), ENV),
                       sc.read_checkup(_fake_ps(), ENV)):
            for line in sc.checkup_lines(result, ENV):
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word, line.lower())
        self.assertNotIn('vírus', sc.CHECKUP_CONFIRMATION.lower())

    def test_lines_ignore_free_text_from_dict(self):
        result = {'autostart': [{'source': 'run_user', 'name': 'X', 'path': r'C:\a.exe',
                                 'state': 'inventado', 'reason': 'texto livre do dict'}],
                  'processes': [], 'unchecked': 0, 'errors': ['texto livre']}
        text = self._text(result)
        self.assertNotIn('texto livre', text)
        self.assertNotIn('inventado', text)
        self.assertIn(sc.STATE_ATTENTION, text)

    def test_default_ps_is_lazy_optimization_engine(self):
        import optimization_engine as oe
        with mock.patch.object(oe, '_ps', return_value=None) as ps:
            sc.read_checkup(env=ENV)
        self.assertEqual(ps.call_count, 6)  # P3-07 fatia 3: + Defender e rede


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'security_checkup.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.source)

    def test_no_tk_no_subprocess_no_project_imports_at_top(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        for name in ('tkinter', 'subprocess', 'ctypes', 'winreg'):
            self.assertNotIn(name, imported)
        self.assertLessEqual(imported, {'ntpath', 'os', 're', 'optimization_engine', '__future__'})
        top = {(n.module or '') for n in self.tree.body if isinstance(n, ast.ImportFrom)}
        top |= {a.name for n in self.tree.body if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn('optimization_engine', top)

    def test_no_dangerous_commands(self):
        for forbidden in ('Stop-Process', 'Remove-', 'Set-MpPreference', 'Add-MpPreference',
                          'RunAs', 'CommandLine', 'subprocess', 'os.system', 'Popen'):
            self.assertNotIn(forbidden, self.source)


SECRET_COMMANDS = (
    r'"C:\Program Files\App\a.exe --token=SEGREDO123',        # aspa sem fechar
    r'C:\Program Files\App\app.exe--token=SEGREDO123',        # sem espaço antes do argumento
    r'C:\Program Files\App\app.exe/token SEGREDO123',         # barra colada
    r'ferramenta --token=SEGREDO123',                         # sem extensão, com "="
    r'"C:\Program Files\App\app.exe" --token=SEGREDO123',     # aspas normais
    # PR #183 (R-40): segredo antes de um segundo caminho com extensão, ou com vírgula
    r'"sem extensao --token=SEGREDO123 C:\a.exe',
    r'powershell -WindowStyle Hidden -token=SEGREDO123 -File C:\x\a.ps1',
    r'C:\Tools\app --token=SEGREDO123 C:\a.exe',
    r'C:\Tools\app,SEGREDO123',
    # PR #183, segunda revisão (R-40): segredo posicional, sem -, / ou =
    r'"C:\Tools\app SEGREDO123 C:\a.exe',
    r'C:\Tools\app SEGREDO123 C:\a.exe',
    r'C:\Program Files\App\run SEGREDO123 C:\Program Files\App\a.exe',
    r'C:\Tools\app "SEGREDO123" C:\a.exe',
    r'C:\Tools\app user:SEGREDO123 C:\a.js',
    r'node SEGREDO123 C:\x\a.js',
)


class FixRessalvas181Tests(unittest.TestCase):
    """FIX-P3-07-01: ressalvas da revisão da PR #181 (issue #182)."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    # Ressalva 1 / R-40
    def test_secret_argument_never_in_executable(self):
        for cmd in SECRET_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertNotIn('SEGREDO123', sc.executable_from_command(cmd))
                self.assertNotIn('token', sc.executable_from_command(cmd))

    def test_secret_argument_never_in_lines(self):
        run = [{'Key': r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'Name': f'X{i}',
                'Command': cmd} for i, cmd in enumerate(SECRET_COMMANDS)]
        text = '\n'.join(sc.checkup_lines(sc.read_checkup(_fake_ps(run=run), ENV), ENV))
        self.assertNotIn('SEGREDO123', text)
        self.assertNotIn('token', text)

    def test_malformed_commands_give_only_the_executable(self):
        # Sem aspas fechadas e com espaço até a extensão: vazio (R-40).
        self.assertEqual(sc.executable_from_command(SECRET_COMMANDS[0]), '')
        self.assertEqual(sc.executable_from_command(SECRET_COMMANDS[1]), '')
        self.assertEqual(sc.executable_from_command(SECRET_COMMANDS[2]), '')
        self.assertEqual(sc.executable_from_command(r'"C:\App\a.exe --token=SEGREDO123'), r'C:\App\a.exe')
        self.assertEqual(sc.executable_from_command(r'C:\App\app.exe--token=SEGREDO123'), r'C:\App\app.exe')
        self.assertEqual(sc.executable_from_command(r'C:\App\app.exe/token SEGREDO123'), r'C:\App\app.exe')
        self.assertEqual(sc.executable_from_command(SECRET_COMMANDS[3]), 'ferramenta')
        self.assertEqual(sc.executable_from_command('a=b'), '')
        self.assertEqual(sc.executable_from_command('"sem extensao --token=SEGREDO123'), '')
        self.assertEqual(sc.executable_from_command(SECRET_COMMANDS[4]), r'C:\Program Files\App\app.exe')

    def test_secret_before_second_path_gives_empty(self):
        for cmd in SECRET_COMMANDS[5:]:
            with self.subTest(cmd=cmd):
                self.assertEqual(sc.executable_from_command(cmd), '')
        entries = [{'source': 'run_user', 'name': 'X', 'command': cmd} for cmd in SECRET_COMMANDS[5:]]
        for item in sc.classify_autostart(entries, ENV):
            self.assertEqual(item['state'], sc.STATE_ATTENTION)
            self.assertEqual(item['path'], '')
        text = '\n'.join(sc.checkup_lines({'autostart': sc.classify_autostart(entries, ENV),
                                           'processes': [], 'unchecked': 0, 'errors': []}, ENV))
        self.assertNotIn('SEGREDO', text)

    def test_normal_paths_with_spaces_still_work(self):
        self.assertEqual(sc.executable_from_command(r'"C:\Program Files (x86)\A B\a.exe" -x'),
                         r'C:\Program Files (x86)\A B\a.exe')
        # Sem aspas, caminho com espaço passa a vazio ("atenção", sem "Onde:"): escolha mais segura.
        self.assertEqual(sc.executable_from_command(r'C:\Program Files\A B\a.exe /min'), '')
        self.assertEqual(sc.executable_from_command(r'C:\Program Files\x\a.exe'), '')

    def test_positional_secret_not_ok_and_not_on_screen(self):
        cmd = r'C:\Program Files\App\run SEGREDO123 C:\Program Files\App\a.exe'
        item = sc.classify_autostart([{'source': 'run_user', 'name': 'X', 'command': cmd}], ENV)[0]
        self.assertEqual(item['state'], sc.STATE_ATTENTION)
        lines = sc.checkup_lines({'autostart': [item], 'processes': [], 'unchecked': 0, 'errors': []}, ENV)
        self.assertFalse(any('Onde:' in line for line in lines))
        self.assertNotIn('SEGREDO', '\n'.join(lines))

    def test_processes_with_spaces_unchanged(self):
        procs = [{'Name': 'a.exe', 'ExecutablePath': r'C:\Program Files\A B\a.exe'}]
        item = sc.classify_processes(procs, ENV)['items'][0]
        self.assertEqual((item['state'], item['path']), (sc.STATE_OK, r'C:\Program Files\A B\a.exe'))

    def test_malformed_command_in_program_files_is_never_ok(self):
        entries = [{'source': 'run_user', 'name': 'X', 'command': cmd} for cmd in SECRET_COMMANDS[:3]]
        for item in sc.classify_autostart(entries, ENV):
            self.assertEqual(item['state'], sc.STATE_ATTENTION)
        ok = sc.classify_autostart([{'source': 'run_user', 'name': 'X', 'command': SECRET_COMMANDS[4]}], ENV)
        self.assertEqual(ok[0]['state'], sc.STATE_OK)

    def test_dot_dot_after_glued_extension_is_not_ok(self):
        cmd = r'C:\Windows\a.exe-\..\..\Users\Fulano Silva\AppData\Roaming\b.exe'
        item = sc.classify_autostart([{'source': 'run_user', 'name': 'X', 'command': cmd}], ENV)[0]
        self.assertNotEqual(item['state'], sc.STATE_OK)

    # Ressalva 2
    def test_user_name_hidden_everywhere(self):
        startup = [{'Scope': 0, 'Name': 'Fulano Silva - atalho.lnk', 'Extension': '.lnk'}]
        procs = [{'Name': 'a.exe', 'ExecutablePath': r'C:\Documents and Settings\Fulano Silva\a.exe'},
                 {'Name': 'b.exe', 'ExecutablePath': r'\\srv\users\Fulano Silva\b.exe'},
                 {'Name': 'x.exe', 'ExecutablePath': r'D:\Fulano Silva\x.exe'},
                 {'Name': 'c.exe', 'ExecutablePath': r'C:\Documents and Settings\Beltrano\c.exe'},
                 {'Name': 'd.exe', 'ExecutablePath': r'\\srv\Users\Beltrano\d.exe'}]
        lines = sc.checkup_lines(sc.read_checkup(_fake_ps(startup=startup, procs=procs), ENV), ENV)
        for line in lines:
            self.assertNotIn('Fulano', line)
            self.assertNotIn('Beltrano', line)
        text = '\n'.join(lines)
        self.assertIn(r'D:\%USERNAME%\x.exe', text)
        self.assertIn('%USERNAME% - atalho.lnk', text)
        self.assertIn(r'\\srv\users\<outro usuário>\b.exe', text)

    def test_user_name_also_glued_to_letters(self):
        # R-45 (revisão 2 da PR #189): colado em letras também é trocado (do lado seguro).
        env = dict(ENV, USERNAME='Ana')
        self.assertEqual(sc.sanitize_path(r'D:\Ana\Banana\Anais_x.exe', env),
                         r'D:\%USERNAME%\B%USERNAME%na\%USERNAME%is_x.exe')
        self.assertEqual(sc.sanitize_path(r'D:\ana\x.exe', env), r'D:\%USERNAME%\x.exe')

    def test_user_name_does_not_break_placeholders(self):
        env = dict(ENV, USERNAME='USERPROFILE')
        out = sc.sanitize_path(r'C:\Users\Fulano Silva\x.exe', env)
        self.assertEqual(out, r'%USERPROFILE%\x.exe')
        env = dict(ENV, USERNAME='outro')
        out = sc.sanitize_path(r'C:\Users\Beltrano\x.exe', env)
        self.assertEqual(out, r'C:\Users\<outro usuário>\x.exe')

    def test_user_name_changes_only_text_not_state(self):
        for user in ('Windows', 'System32', 'svchost', 'Program Files'):
            env = dict(ENV, USERNAME=user)
            procs = [{'Name': 'svchost.exe', 'ExecutablePath': r'C:\Windows\System32\svchost.exe'},
                     {'Name': 'app.exe', 'ExecutablePath': r'C:\Program Files\App\app.exe'},
                     {'Name': 'svchost.exe', 'ExecutablePath': r'C:\Temp\svchost.exe'}]
            with self.subTest(user=user):
                result = sc.read_checkup(_fake_ps(procs=procs), env)
                states = [i['state'] for i in result['processes']]
                self.assertEqual(states, [sc.STATE_OK, sc.STATE_OK, sc.STATE_SUSPECT])
                text = '\n'.join(sc.checkup_lines(result, env))
                # +1 OK: Defender ligado (P3-07 fatia 3)
                self.assertIn('RESUMO: OK 3 · atenção 0 · suspeito 1', text)

    # Ressalva 3
    def test_nt_prefix_in_system32_is_ok(self):
        for path in (r'\\?\C:\Windows\System32\svchost.exe', r'\??\C:\Windows\System32\svchost.exe'):
            with self.subTest(path=path):
                self.assertEqual(sc.classify_path('svchost.exe', path, ENV), (sc.STATE_OK, sc.REASON_OK))

    def test_nt_prefix_outside_system32_stays_suspect(self):
        self.assertEqual(sc.classify_path('svchost.exe', r'\\?\C:\Temp\svchost.exe', ENV)[0], sc.STATE_SUSPECT)
        self.assertEqual(sc.classify_path('a.exe', r'\??\C:\Temp\a.exe', ENV)[0], sc.STATE_ATTENTION)
        self.assertNotEqual(sc.classify_path('a.exe', r'\\?\UNC\srv\share\a.exe', ENV)[0], sc.STATE_OK)

    def test_nt_prefix_with_trailing_space_or_dot_is_never_ok(self):
        for path in (r'\\?\C:\Windows\System32\svchost.exe ', r'\??\C:\Windows\System32\svchost.exe.',
                     r'\\?\C:\Windows\System32\svchost.exe . '):
            with self.subTest(path=path):
                self.assertEqual(sc.classify_path('svchost.exe', path, ENV)[0], sc.STATE_SUSPECT)
        self.assertEqual(sc.classify_path('a.exe', r'\\?\C:\Program Files\A\a.exe ', ENV)[0],
                         sc.STATE_ATTENTION)
        self.assertEqual(sc.classify_path('a.exe', r'\\?\C:\Program Files\A\a.exe', ENV)[0], sc.STATE_OK)

    def test_trailing_space_prefixed_process_not_grouped_with_ok(self):
        procs = [{'Name': 'svchost.exe', 'ExecutablePath': r'C:\Windows\System32\svchost.exe'},
                 {'Name': 'svchost.exe', 'ExecutablePath': '\\\\?\\C:\\Windows\\System32\\svchost.exe '}]
        out = sc.classify_processes(procs, ENV)
        self.assertEqual(sorted(i['state'] for i in out['items']), [sc.STATE_OK, sc.STATE_SUSPECT])
        text = '\n'.join(sc.checkup_lines({'autostart': [], 'processes': out['items'],
                                           'unchecked': 0, 'errors': []}, ENV))
        self.assertIn('suspeito 1', text)

    def test_nt_prefix_with_dot_components_or_unicode_space_is_never_ok(self):
        for path in (r'\\?\C:\Temp\..\Windows\System32\svchost.exe',
                     r'\\?\C:\Windows\System32\.\svchost.exe',
                     r'\??\C:\Windows\System32\..\System32\svchost.exe',
                     '\\\\?\\C:\\Windows\\System32\\svchost.exe\u3000'):
            with self.subTest(path=path):
                self.assertEqual(sc.classify_path('svchost.exe', path, ENV)[0], sc.STATE_SUSPECT)
        self.assertEqual(sc.classify_path('a.exe', r'\\?\C:\Program Files\A\..\A\a.exe', ENV)[0],
                         sc.STATE_ATTENTION)
        self.assertEqual(sc.classify_path('a.exe', 'C:\\Program Files\\A\\a.exe\u3000', ENV)[0], sc.STATE_OK)

    def test_strip_nt_prefix(self):
        self.assertEqual(sc._strip_nt_prefix(r'\\?\C:\a.exe'), r'C:\a.exe')
        self.assertEqual(sc._strip_nt_prefix(r'\??\C:\a.exe'), r'C:\a.exe')
        self.assertEqual(sc._strip_nt_prefix(r'\\?\UNC\srv\s\a.exe'), r'\\srv\s\a.exe')
        self.assertEqual(sc._strip_nt_prefix(r'\\?\unc\srv\s\a.exe'), r'\\srv\s\a.exe')
        self.assertEqual(sc._strip_nt_prefix(r'C:\a.exe'), r'C:\a.exe')

    def test_nt_prefix_groups_with_plain_path(self):
        procs = [{'Name': 'svchost.exe', 'ExecutablePath': r'C:\Windows\System32\svchost.exe'},
                 {'Name': 'svchost.exe', 'ExecutablePath': r'\\?\C:\Windows\System32\svchost.exe'}]
        out = sc.classify_processes(procs, ENV)
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(out['items'][0]['count'], 2)

    # Ressalva 4
    def test_unchecked_singular_and_plural(self):
        procs = [{'Name': 'System'}]
        one = '\n'.join(sc.checkup_lines(sc.read_checkup(_fake_ps(procs=procs), ENV), ENV))
        self.assertIn('1 processo não pôde ser conferido (o Windows não informou de onde ele roda).', one)
        self.assertNotIn('1 processos', one)
        two = '\n'.join(sc.checkup_lines(sc.read_checkup(_fake_ps(procs=procs * 2), ENV), ENV))
        self.assertIn('2 processos não puderam ser conferidos (o Windows não informou de onde eles rodam).',
                      two)

    # Ressalva 5
    def test_process_query_only_asks_name_and_path(self):
        self.assertIn('-Property Name,ExecutablePath', sc.PROCESS_QUERY)
        self.assertNotIn('CommandLine', sc.PROCESS_QUERY)

    # Ressalva 6
    def test_lines_reclassify_and_never_promote(self):
        result = {'autostart': [], 'processes': [
            {'source': 'process', 'name': 'app.exe', 'path': r'%USERPROFILE%\AppData\Roaming\app.exe',
             'state': sc.STATE_OK, 'reason': sc.REASON_OK},
            {'source': 'process', 'name': 'svchost.exe', 'path': r'C:\Temp\svchost.exe',
             'state': sc.STATE_ATTENTION, 'reason': sc.REASON_TEMP},
            {'source': 'process', 'name': 'b.exe', 'path': r'C:\Program Files\B\b.exe',
             'state': sc.STATE_SUSPECT, 'reason': sc.REASON_SYSTEM_NAME}],
            'unchecked': 0, 'errors': []}
        text = '\n'.join(sc.checkup_lines(result, ENV))
        self.assertIn('[atenção] app.exe', text)
        self.assertIn('[suspeito] svchost.exe', text)
        self.assertIn('[suspeito] b.exe', text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 2', text)

    def test_autostart_name_is_not_used_as_program_name(self):
        result = {'autostart': [{'source': 'run_user', 'name': 'svchost.exe',
                                 'path': r'C:\Program Files\B\b.exe',
                                 'state': sc.STATE_OK, 'reason': sc.REASON_OK}],
                  'processes': [], 'unchecked': 0, 'errors': []}
        self.assertIn('[OK] svchost.exe', '\n'.join(sc.checkup_lines(result, ENV)))


def _task(path, name, execute='', com=False):
    return {'TaskPath': path, 'TaskName': name, 'Execute': execute, 'Com': com}


class ScheduledTaskTests(unittest.TestCase):
    """P3-07 fatia 2: tarefas agendadas, só com dados simulados e ``ps`` falso."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _one(self, row):
        items = sc.classify_tasks([row], ENV)
        self.assertEqual(len(items), 1, items)
        return items[0]

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_program_files_is_ok(self):
        for execute in (r'"C:\Program Files\App\app.exe"', r'"C:\Program Files (x86)\App\app.exe"',
                        r'%ProgramFiles%\App\app.exe', r'"%ProgramFiles(x86)%\App\app.exe"'):
            with self.subTest(execute=execute):
                item = self._one(_task('\\', 'Atualizador', execute))
                self.assertEqual(item['state'], sc.STATE_OK)
        item = self._one(_task('\\', 'Atualizador', r'"C:\Program Files\App\app.exe"'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_OK, sc.REASON_OK))
        self.assertEqual(item['source'], 'task')
        self.assertEqual(item['path'], r'C:\Program Files\App\app.exe')

    def test_unquoted_path_with_space_shows_nothing(self):
        # R-40: sem aspas fechadas, um espaço pode separar argumentos; nada é mostrado.
        item = self._one(_task('\\', 'Atualizador', r'C:\Program Files\App\app.exe'))
        self.assertEqual((item['state'], item['reason'], item['path']),
                         (sc.STATE_ATTENTION, sc.REASON_NOT_FULL_PATH, ''))

    def test_appdata_and_temp_are_attention(self):
        cases = ((r'%LOCALAPPDATA%\Coisa\coisa.exe', sc.REASON_APPDATA),
                 (r'C:\Users\Fulano\AppData\Local\Coisa\coisa.exe', sc.REASON_APPDATA),
                 (r'C:\Windows\Temp\x.exe', sc.REASON_TEMP),
                 (r'%TEMP%\x.exe', sc.REASON_TEMP))
        for execute, reason in cases:
            with self.subTest(execute=execute):
                item = self._one(_task('\\', 'Coisa', execute))
                self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, reason))

    def test_svchost_outside_system32_is_suspect(self):
        item = self._one(_task('\\', 'Servico', r'%APPDATA%\svchost.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_SUSPECT, sc.REASON_SYSTEM_NAME))

    def test_task_name_is_not_program_name(self):
        item = self._one(_task('\\', 'svchost.exe', r'"C:\Program Files\App\app.exe"'))
        self.assertEqual(item['state'], sc.STATE_OK)
        text = self._text({'tasks': [item], 'processes': [], 'errors': []})
        self.assertIn('[OK] \\svchost.exe — tarefa agendada', text)

    def test_microsoft_folder_hides_only_known_quiet_programs(self):
        # R-46: em \Microsoft\ só some a lista fechada, direto em System32 ou SysWOW64.
        rows = [_task('\\Microsoft\\Windows\\Defrag\\', 'ScheduledDefrag', r'%windir%\system32\defrag.exe'),
                _task('\\Microsoft\\Windows\\WER\\', 'Q', r'C:\Windows\SysWOW64\wermgr.exe')]
        self.assertEqual(sc.classify_tasks(rows, ENV), [])
        result = sc.read_checkup(_fake_ps(tasks=rows), ENV)
        self.assertEqual(result['tasks'], [])
        text = self._text(result)
        self.assertNotIn('Defrag', text)
        self.assertIn(sc.TASKS_EMPTY, text)
        self.assertIn('RESUMO: OK 1 · atenção 0 · suspeito 0', text) # +1 OK: Defender ligado (P3-07 fatia 3)

    def test_microsoft_folder_outside_windows_is_shown(self):
        item = self._one(_task('\\Microsoft\\Windows\\Defrag\\', 'ScheduledDefrag', r'%APPDATA%\defrag.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_MS_FOLDER_OUTSIDE))
        item = self._one(_task('\\microsoft\\Windows\\X\\', 'Y', r'"C:\Users\Fulano Silva\AppData\svchost.exe"'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_SUSPECT, sc.REASON_MS_FOLDER_OUTSIDE))
        text = self._text({'tasks': [item], 'processes': [], 'errors': []})
        self.assertIn(sc.REASON_TEXTS[sc.REASON_MS_FOLDER_OUTSIDE], text)
        self.assertIn('[suspeito] \\microsoft\\Windows\\X\\Y — tarefa agendada', text)
        self.assertNotIn('Fulano', text)

    def test_microsoft_folder_other_programs_are_shown(self):
        # R-46: fora da lista fechada, nada some: svchost e explorer ficam "atenção";
        # um programa em Arquivos de Programas aparece como OK (não some).
        item = self._one(_task('\\Microsoft\\Windows\\X\\', 'Y', r'C:\Windows\System32\svchost.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_MS_WINDOWS_PROGRAM))
        item = self._one(_task('\\Microsoft\\Office\\', 'Z', r'"C:\Program Files\Microsoft Office\root\a.exe"'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_OK, sc.REASON_OK))
        # Da lista, mas numa subpasta: não some.
        item = self._one(_task('\\Microsoft\\A\\', 'B', r'C:\Windows\System32\Tasks\defrag.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_MS_WINDOWS_PROGRAM))

    def test_microsoft_folder_inside_windows_keeps_own_reason(self):
        item = self._one(_task('\\Microsoft\\Windows\\X\\', 'Y', r'C:\Windows\Temp\a.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_TEMP))

    def test_com_handler_is_attention_without_where(self):
        item = self._one(_task('\\', 'ComTarefa', '', com=True))
        self.assertEqual((item['state'], item['reason'], item['path']),
                         (sc.STATE_ATTENTION, sc.REASON_COM_HANDLER, ''))
        text = self._text({'tasks': [item], 'processes': [], 'errors': []})
        self.assertIn('[atenção] \\ComTarefa — tarefa agendada', text)
        self.assertNotIn('Onde:', text)
        self.assertIn(sc.REASON_TEXTS[sc.REASON_COM_HANDLER], text)
        # COM na pasta da Microsoft também aparece como "atenção" (revisão 2 da PR #189).
        item = self._one(_task('\\Microsoft\\Windows\\A\\', 'B', '', com=True))
        self.assertEqual((item['state'], item['reason'], item['path']),
                         (sc.STATE_ATTENTION, sc.REASON_MS_COM_HANDLER, ''))
        text = self._text({'tasks': [item], 'processes': [], 'errors': []})
        self.assertIn('[atenção] \\Microsoft\\Windows\\A\\B — tarefa agendada', text)
        self.assertIn('comum nas tarefas da Microsoft', text)
        self.assertNotIn('Onde:', text)

    def test_secret_after_or_glued_to_execute_never_shown(self):
        commands = (r'C:\Program Files\App\a.exe --token=SEGREDO123',
                    r'"C:\Program Files\App\a.exe" --token=SEGREDO123',
                    r'"C:\Program Files\App\a.exe --token=SEGREDO123',
                    r'C:\Tools\a.exe--token=SEGREDO123',
                    r'C:\Tools\a.exeSEGREDO123',
                    r'C:\Tools\a"SEGREDO123".exe',
                    r'C:\Tools\a.exe,SEGREDO123',
                    r'C:\Tools\app SEGREDO123 C:\a.exe',
                    r'"C:\Tools\--token=SEGREDO123.exe"',
                    r'C:\Tools\ferramentaSEGREDO123')
        for execute in commands:
            with self.subTest(execute=execute):
                rows = [_task('\\', 'Tarefa', execute), _task('\\Microsoft\\Windows\\A\\', 'B', execute)]
                items = sc.classify_tasks(rows, ENV)
                self.assertNotIn('SEGREDO123', repr(items))
                for item in items:
                    self.assertEqual((item['state'], item['reason'], item['path']),
                                     (sc.STATE_ATTENTION, sc.REASON_NOT_FULL_PATH, ''))
                result = sc.read_checkup(_fake_ps(tasks=rows), ENV)
                self.assertNotIn('SEGREDO123', repr(result))
                self.assertNotIn('SEGREDO123', self._text(result))

    def test_malformed_system_name_outside_windows_is_suspect(self):
        item = self._one(_task('\\', 'T', r'C:\Users\Fulano Silva\svchost.exe --token=SEGREDO123'))
        self.assertEqual((item['state'], item['reason'], item['path']),
                         (sc.STATE_SUSPECT, sc.REASON_SYSTEM_NAME, ''))

    def test_script_host_is_attention(self):
        for execute in (r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                        r'%windir%\System32\wscript.exe', 'cmd.exe'):
            with self.subTest(execute=execute):
                item = self._one(_task('\\', 'Script', execute))
                self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST))

    def test_sid_user_profile_and_user_name_hidden(self):
        sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
        rows = [_task('\\Fulano Silva\\', 'Sync-' + sid, '"C:\\Users\\Fulano Silva\\AppData\\Local\\' + sid + '\\a.exe"'),
                _task('\\', 'OneDrive ' + sid, r'"D:\Fulano Silva\x.exe"')]
        items = sc.classify_tasks(rows, ENV)
        self.assertEqual(len(items), 2)
        text = self._text(sc.read_checkup(_fake_ps(tasks=rows), ENV))
        for leak in (sid, '1111111111', 'Fulano', 'Silva'):
            self.assertNotIn(leak, repr(items))
            self.assertNotIn(leak, text)
        self.assertIn(r'\%USERNAME%\Sync-<SID>', text)
        self.assertIn(r'%USERPROFILE%\AppData\Local\<SID>\a.exe', text)
        self.assertIn(r'D:\%USERNAME%\x.exe', text)
        # A troca só muda o texto: a classificação continua a mesma.
        self.assertEqual(items[0]['state'], sc.STATE_ATTENTION)

    def test_same_task_shown_once(self):
        row = _task('\\', 'Repetida', r'%LOCALAPPDATA%\r\r.exe')
        other = _task('\\', 'Repetida', r'%LOCALAPPDATA%\r\outro.exe')
        items = sc.classify_tasks([row, dict(row), other], ENV)
        self.assertEqual(len(items), 2)
        text = self._text({'tasks': items, 'processes': [], 'errors': []})
        self.assertEqual(text.count('Onde: %LOCALAPPDATA%\\r\\r.exe\n'), 1)

    def test_fake_ok_in_dict_is_reclassified(self):
        result = {'tasks': [{'source': 'task', 'name': '\\T', 'path': r'C:\Users\Fulano Silva\AppData\svchost.exe',
                             'state': sc.STATE_OK, 'reason': sc.REASON_OK},
                            {'source': 'task', 'name': '\\Com', 'path': '', 'state': sc.STATE_OK,
                             'reason': sc.REASON_OK}],
                  'processes': [], 'errors': []}
        text = self._text(result)
        self.assertNotIn('[OK]', text)
        self.assertIn('[suspeito] \\T', text)
        self.assertIn('[atenção] \\Com', text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 1', text)

    def test_query_does_not_ask_arguments(self):
        self.assertIn('Get-ScheduledTask', sc.TASK_QUERY)
        self.assertIn('ConvertTo-Json -InputObject @($out) -Compress', sc.TASK_QUERY)
        self.assertIn('MSFT_TaskComHandlerAction', sc.TASK_QUERY)
        for forbidden in ('Arguments', 'WorkingDirectory', 'Disable-ScheduledTask', 'Unregister',
                          'Set-ScheduledTask', 'Stop-ScheduledTask', 'Start-ScheduledTask', 'RunAs'):
            self.assertNotIn(forbidden, sc.TASK_QUERY)
        ps = _fake_ps()
        sc.read_checkup(ps, ENV)
        self.assertEqual(sum('Get-ScheduledTask' in code for code in ps.calls), 1)

    def test_task_entries_keep_only_asked_fields(self):
        raw = {'value': [{'TaskPath': '\\', 'TaskName': 'A', 'Execute': r'C:\a.exe', 'Com': False,
                          'Arguments': '--token=SEGREDO123'}, None, 'x']}
        self.assertEqual(sc._task_entries(raw), [_task('\\', 'A', r'C:\a.exe')])
        self.assertNotIn('SEGREDO123', repr(sc._task_entries(raw)))
        self.assertEqual(sc._task_entries(None), [])
        self.assertEqual(sc._task_entries(_task('\\', 'B', '', 'sim')), [_task('\\', 'B', '')])

    def test_query_failure_keeps_other_sections(self):
        run = [{'Key': r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'Name': 'Bom',
                'Command': r'"C:\Program Files\Bom\bom.exe"'}]
        procs = [{'Name': 'bom.exe', 'ExecutablePath': r'C:\Program Files\Bom\bom.exe'}]
        result = sc.read_checkup(_fake_ps(run, None, procs, fail=('tasks',)), ENV)
        self.assertEqual(result['errors'], ['tasks'])
        self.assertEqual(result['tasks'], [])
        self.assertEqual(len(result['autostart']), 1)
        self.assertEqual(len(result['processes']), 1)
        text = self._text(result)
        self.assertIn(sc.ERROR_TEXTS['tasks'], text)
        self.assertIn('não foi possível ler', text)
        self.assertNotIn('Acesso negado', text)
        self.assertNotIn('NTUSER', text)
        self.assertNotIn(sc.TASKS_EMPTY, text)
        self.assertIn(sc.RECOMMENDATION, text)
        self.assertNotIn(ALL_CLEAR_TEXT, text)
        for title in ('PROGRAMAS QUE ABREM COM O WINDOWS', 'TAREFAS AGENDADAS', 'PROCESSOS EM EXECUÇÃO'):
            self.assertIn(title, text)
        self.assertIn('[OK] Bom', text)
        self.assertIn('[OK] bom.exe', text)

    def test_section_order_note_and_summary(self):
        tasks = [_task('\\', 'Boa', r'"C:\Program Files\Boa\boa.exe"'),
                 _task('\\', 'Ruim', r'%TEMP%\ruim.exe')]
        procs = [{'Name': 'bom.exe', 'ExecutablePath': r'C:\Program Files\Bom\bom.exe'}]
        lines = sc.checkup_lines(sc.read_checkup(_fake_ps(procs=procs, tasks=tasks), ENV), ENV)
        a = lines.index('PROGRAMAS QUE ABREM COM O WINDOWS')
        t = lines.index('TAREFAS AGENDADAS')
        p = lines.index('PROCESSOS EM EXECUÇÃO')
        self.assertLess(a, t)
        self.assertLess(t, p)
        section = lines[t:p]
        self.assertIn('  ' + sc.TASKS_NOTE, section)
        self.assertEqual(sc.TASKS_NOTE, 'Sem administrador, o Windows pode não mostrar algumas tarefas.')
        self.assertTrue(any('[atenção] \\Ruim — tarefa agendada' in line for line in section))
        self.assertTrue(any('[OK] \\Boa — tarefa agendada' in line for line in section))
        self.assertIn('RESUMO: OK 3 · atenção 1 · suspeito 0 · não conferidos 0', lines)
        self.assertIn(sc.RECOMMENDATION, lines)

    def test_ok_tasks_with_admin_note_use_neutral_phrase(self):
        tasks = [_task('\\', 'Boa', r'"C:\Program Files\Boa\boa.exe"')]
        procs = [{'Name': 'bom.exe', 'ExecutablePath': r'C:\Program Files\Bom\bom.exe'}]
        text = self._text(sc.read_checkup(_fake_ps(procs=procs, tasks=tasks), ENV))
        self.assertIn(sc.TASKS_NOTE, text)
        self.assertNotIn(ALL_CLEAR_TEXT, text)
        self.assertIn(sc.NOT_ALL_CHECKED, text)
        self.assertNotIn(sc.RECOMMENDATION, text)

    def test_confirmation_mentions_tasks_and_no_forbidden_words(self):
        self.assertIn('tarefas agendadas', sc.CHECKUP_CONFIRMATION)
        self.assertIn('não precisa de administrador', sc.CHECKUP_CONFIRMATION)
        texts = [sc.TASKS_NOTE, sc.TASKS_EMPTY, sc.ERROR_TEXTS['tasks'], sc.SOURCE_TEXTS['task'],
                 sc.REASON_TEXTS[sc.REASON_COM_HANDLER], sc.REASON_TEXTS[sc.REASON_MS_FOLDER_OUTSIDE]]
        for text in texts:
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, text.lower())

    def test_microsoft_folder_code_runners_in_system32_are_shown(self):
        # R-45: em \Microsoft\ esses programas não somem; ficam "atenção".
        for exe in ('powershell.exe', 'pwsh.exe', 'cmd.exe', 'wscript.exe', 'cscript.exe', 'mshta.exe',
                    'rundll32.exe', 'regsvr32.exe'):
            with self.subTest(exe=exe):
                item = self._one(_task('\\Microsoft\\Windows\\A\\', 'B', '%windir%\\System32\\' + exe))
                self.assertEqual((item['state'], item['reason']),
                                 (sc.STATE_ATTENTION, sc.REASON_MS_WINDOWS_PROGRAM))
                text = self._text({'tasks': [item], 'errors': []})
                self.assertIn('[atenção] \\Microsoft\\Windows\\A\\B — tarefa agendada', text)
                self.assertIn('RESUMO: OK 0 · atenção 1', text)
        self.assertEqual(sc.classify_tasks([_task('\\Microsoft\\Windows\\A\\', 'B',
                                                  r'C:\Windows\System32\defrag.exe')], ENV), [])

    def test_code_runners_outside_microsoft_are_attention(self):
        for exe in ('rundll32.exe', 'regsvr32.exe', 'mshta.exe'):
            with self.subTest(exe=exe):
                item = self._one(_task('\\', 'T', 'C:\\Windows\\SysWOW64\\' + exe))
                self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST))
        forged = {'tasks': [{'source': 'task', 'name': '\\F', 'path': r'C:\Windows\System32\regsvr32.exe',
                             'state': sc.STATE_OK, 'reason': sc.REASON_OK}], 'errors': []}
        self.assertIn('[atenção] \\F', self._text(forged))

    def test_sid_glued_to_letters_is_hidden(self):
        sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
        rows = [_task('\\', 'GoogleUpdateTaskUser' + sid + 'Core', r'"C:\Program Files\Google\u.exe"'),
                _task('\\', 'MicrosoftEdgeUpdateTaskUser' + sid + 'UA', r'"C:\Program Files\Edge\e.exe"'),
                _task('\\', 'Sem' + 'S-1-5-21-44444-55555-66666' + 'Fim', r'"C:\Program Files\x.exe"'),
                _task('\\', 'Outro' + 's-1-5-80-111-222-333-444' + 'x', r'"C:\Program Files\y.exe"'),
                _task('\\', 'Comum S-1-5-18 e S-1', r'"C:\Program Files\z.exe"')]
        text = self._text(sc.read_checkup(_fake_ps(tasks=rows), ENV))
        for leak in ('1111111111', '2222222222', '3333333333', '1001', '44444', '66666', '444'):
            self.assertNotIn(leak, text)
        self.assertIn('GoogleUpdateTaskUser<SID>Core', text)
        self.assertIn('MicrosoftEdgeUpdateTaskUser<SID>UA', text)
        self.assertIn('Sem<SID>Fim', text)
        self.assertIn('Outro<SID>x', text)
        self.assertIn('Comum S-1-5-18 e S-1', text)

    def test_email_in_task_name_is_hidden(self):
        rows = [_task('\\', 'OneDrive fulano.silva+x@exemplo.com.br', r'"C:\Program Files\o.exe"'),
                _task('\\Pasta\\', 'Sync-ciclano@empresa.org-Diario', r'"C:\Program Files\s.exe"')]
        text = self._text(sc.read_checkup(_fake_ps(tasks=rows), ENV))
        for leak in ('fulano', 'exemplo', 'ciclano', 'empresa', '@'):
            self.assertNotIn(leak, text)
        self.assertIn('\\OneDrive <e-mail>', text)
        # Do lado seguro: o que vem colado com "-" ao e-mail some junto.
        self.assertIn('\\Pasta\\<e-mail> — tarefa agendada', text)

    def test_empty_tasks_text_says_what_is_left_out(self):
        # Ressalva da revisão 2: só a lista fechada fica de fora (COM e bibliotecas aparecem).
        for words in ('Microsoft', 'pasta do Windows', 'lista curta', 'scripts', 'comandos', 'bibliotecas'):
            self.assertIn(words, sc.TASKS_EMPTY)
        self.assertNotIn('programas instalados', sc.TASKS_EMPTY)
        self.assertFalse(hasattr(sc, 'ALL_CLEAR'))

    def test_strange_rows_do_not_break(self):
        rows = [None, 5, 'x', {}, {'TaskPath': 7, 'TaskName': None, 'Execute': ['a'], 'Com': 'True'}]
        items = sc.classify_tasks(rows, ENV)
        for item in items:
            self.assertNotEqual(item['state'], sc.STATE_OK)
        self.assertEqual(sc.classify_tasks(None, ENV), [])
        self.assertEqual(sc.classify_tasks({'value': []}, ENV), [])
        self.assertIsInstance(self._text({'tasks': items, 'errors': []}), str)


# Programas do Windows que rodam o que vem nos argumentos e não são os da R-45
# (revisão 2 da PR #189). Nenhum deles é da lista fechada.
WINDOWS_RUNNERS = (r'C:\Windows\System32\conhost.exe', r'C:\Windows\System32\forfiles.exe',
                   r'C:\Windows\System32\msiexec.exe', r'C:\Windows\explorer.exe',
                   r'C:\Windows\System32\wbem\WMIC.exe',
                   r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe',
                   r'C:\Windows\System32\wsl.exe', r'C:\Windows\System32\schtasks.exe',
                   r'C:\Windows\hh.exe', r'C:\Windows\System32\control.exe',
                   r'C:\Windows\System32\certutil.exe', r'C:\Windows\SysWOW64\bitsadmin.exe')


def _expected_runner(path, default):
    # R-47: wsl.exe e MSBuild.exe são interpretadores; continuam "atenção", com o motivo próprio.
    return sc.REASON_INTERPRETER if path.lower().endswith(('\\wsl.exe', '\\msbuild.exe')) else default


class ClosedListRevision2Tests(unittest.TestCase):
    """R-46: só uma lista fechada de programas do Windows dá OK ou some."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_known_quiet_list_is_closed_and_has_no_code_runner(self):
        self.assertIsInstance(sc.KNOWN_QUIET_PROGRAMS, tuple)
        for exe in sc.SCRIPT_HOSTS + sc.SYSTEM_NAMES + (sc.EXPLORER,):
            self.assertNotIn(exe, sc.KNOWN_QUIET_PROGRAMS)
        for path in WINDOWS_RUNNERS:
            self.assertNotIn(Path(path.replace('\\', '/')).name.lower(), sc.KNOWN_QUIET_PROGRAMS)

    def test_task_outside_microsoft_with_windows_program_is_attention(self):
        for path in WINDOWS_RUNNERS + (r'C:\Windows\System32\defrag.exe',):
            with self.subTest(path=path):
                items = sc.classify_tasks([_task('\\', 'T', path)], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_ATTENTION, _expected_runner(path, sc.REASON_WINDOWS_PROGRAM))])
                self.assertIn('[atenção] \\T — tarefa agendada', self._text({'tasks': items, 'errors': []}))

    def test_task_in_microsoft_with_windows_program_is_shown(self):
        for path in WINDOWS_RUNNERS:
            with self.subTest(path=path):
                rows = [_task('\\Microsoft\\Windows\\A\\', 'B', path)]
                items = sc.classify_tasks(rows, ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_ATTENTION, _expected_runner(path, sc.REASON_MS_WINDOWS_PROGRAM))])
                text = self._text(sc.read_checkup(_fake_ps(tasks=rows), ENV))
                self.assertIn('[atenção] \\Microsoft\\Windows\\A\\B — tarefa agendada', text)
                self.assertIn('RESUMO: OK 1 · atenção 1', text) # +1 OK: Defender ligado (P3-07 fatia 3)
                self.assertNotIn(sc.TASKS_EMPTY, text)

    def test_microsoft_reason_says_rundll32_is_common(self):
        text = sc.REASON_TEXTS[sc.REASON_MS_WINDOWS_PROGRAM]
        self.assertIn('rundll32', text)
        self.assertIn('comum nas tarefas da Microsoft', text)
        for reason in (sc.REASON_WINDOWS_PROGRAM, sc.REASON_MS_WINDOWS_PROGRAM, sc.REASON_MS_COM_HANDLER):
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, sc.REASON_TEXTS[reason].lower())

    def test_autostart_windows_program_is_attention_except_closed_list(self):
        for path in WINDOWS_RUNNERS:
            with self.subTest(path=path):
                item = sc.classify_autostart([{'source': 'run_all', 'name': 'X', 'command': path + ' /a'}], ENV)[0]
                self.assertEqual((item['state'], item['reason']),
                                 (sc.STATE_ATTENTION, _expected_runner(path, sc.REASON_WINDOWS_PROGRAM)))
        for path in (r'C:\Windows\System32\SecurityHealthSystray.exe', r'%windir%\system32\ctfmon.exe'):
            with self.subTest(path=path):
                item = sc.classify_autostart([{'source': 'run_all', 'name': 'Y', 'command': path}], ENV)[0]
                self.assertEqual((item['state'], item['reason']), (sc.STATE_OK, sc.REASON_OK))
                self.assertIn('[OK] Y', self._text({'autostart': [item], 'errors': []}))
        # Da lista, mas fora de System32/SysWOW64: atenção.
        item = sc.classify_autostart([{'source': 'run_all', 'name': 'Z',
                                       'command': r'C:\Windows\Tasks\ctfmon.exe'}], ENV)[0]
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_WINDOWS_PROGRAM))

    def test_forged_ok_is_reclassified_on_screen(self):
        forged = {'autostart': [{'source': 'run_all', 'name': 'F', 'path': r'C:\Windows\System32\conhost.exe',
                                 'state': sc.STATE_OK, 'reason': sc.REASON_OK},
                                {'source': 'run_all', 'name': 'G', 'path': r'C:\Windows\System32\ctfmon.exe',
                                 'state': sc.STATE_OK, 'reason': sc.REASON_OK}],
                  'tasks': [{'source': 'task', 'name': '\\T', 'path': r'C:\Windows\System32\defrag.exe',
                             'state': sc.STATE_OK, 'reason': sc.REASON_OK}], 'errors': []}
        text = self._text(forged)
        self.assertIn('[atenção] F', text)
        self.assertIn('[OK] G', text)
        self.assertIn('[atenção] \\T', text)
        self.assertIn('RESUMO: OK 1 · atenção 2', text)

    def test_processes_do_not_change(self):
        procs = [{'Name': 'conhost.exe', 'ExecutablePath': r'C:\Windows\System32\conhost.exe'},
                 {'Name': 'explorer.exe', 'ExecutablePath': r'C:\Windows\explorer.exe'}]
        states = [i['state'] for i in sc.classify_processes(procs, ENV)['items']]
        self.assertEqual(states, [sc.STATE_OK, sc.STATE_OK])


class UserNameAndEmailRevision2Tests(unittest.TestCase):
    """R-45, 2ª parte: identificador separado e colado em letras dos dois lados."""

    def test_user_name_separated_and_glued(self):
        rows = [_task('\\', 'Task Fulano Silva', r'"C:\Program Files\a.exe"'),
                _task('\\', 'TaskxFulano Silvay', r'"C:\Program Files\b.exe"'),
                _task('\\', 'xFULANO SILVA', r'"C:\Program Files\c.exe"')]
        procs = [{'Name': 'd.exe', 'ExecutablePath': r'D:\xFulano Silvay\d.exe'},
                 {'Name': 'e.exe', 'ExecutablePath': r'D:\Fulano Silva\e.exe'}]
        result = sc.read_checkup(_fake_ps(procs=procs, tasks=rows), ENV)
        text = '\n'.join(sc.checkup_lines(result, ENV))
        for leak in ('Fulano', 'FULANO', 'Silva', 'SILVA'):
            self.assertNotIn(leak, repr(result))
            self.assertNotIn(leak, text)
        self.assertIn('\\Task %USERNAME% — tarefa agendada', text)
        self.assertIn('\\Taskx%USERNAME%y — tarefa agendada', text)
        self.assertIn('\\x%USERNAME% — tarefa agendada', text)
        self.assertIn(r'D:\x%USERNAME%y\d.exe', text)
        self.assertIn(r'D:\%USERNAME%\e.exe', text)
        # Só muda o texto: os estados continuam os mesmos.
        self.assertEqual([i['state'] for i in result['tasks']], [sc.STATE_OK] * 3)

    def test_email_in_path_is_hidden(self):
        env = dict(ENV, USERNAME='fulano')
        procs = [{'Name': 'a.exe', 'ExecutablePath': r'D:\Dados\ciclano.souza@exemplo.com.br\a.exe'},
                 {'Name': 'b.exe', 'ExecutablePath': r'D:\Dados\fulano@empresa.org\b.exe'}]
        result = sc.read_checkup(_fake_ps(procs=procs), env)
        text = '\n'.join(sc.checkup_lines(result, env))
        for leak in ('ciclano', 'exemplo', 'empresa', '@'):
            self.assertNotIn(leak, repr(result))
            self.assertNotIn(leak, text)
        self.assertIn(r'D:\Dados\<e-mail>\a.exe', text)
        self.assertIn(r'D:\Dados\<e-mail>\b.exe', text)
        self.assertEqual(sc.sanitize_path(r'C:\x\fulano.silva+t@exemplo.com\y.exe', ENV), r'C:\x\<e-mail>\y.exe')


class InterpreterRevision3Tests(unittest.TestCase):
    """R-47: interpretador em tarefa ou inicialização nunca dá OK nem some, em qualquer pasta."""

    NODE = r'C:\Program Files\nodejs\node.exe'
    PYTHON = r'C:\Program Files\Python313\python.exe'

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_interpreter_list_is_closed_lowercase_and_has_no_known_quiet(self):
        self.assertIsInstance(sc.INTERPRETERS, tuple)
        for exe in sc.INTERPRETERS:
            self.assertEqual(exe, exe.lower())
            self.assertTrue(exe.endswith('.exe'))
        self.assertEqual(set(sc.INTERPRETERS) & set(sc.KNOWN_QUIET_PROGRAMS), set())
        for exe in ('node.exe', 'python.exe', 'java.exe', 'bash.exe', 'autohotkey.exe', 'wsl.exe'):
            self.assertIn(exe, sc.INTERPRETERS)

    def test_reason_text_is_plain_and_has_no_forbidden_words(self):
        text = sc.REASON_TEXTS[sc.REASON_INTERPRETER]
        self.assertIn('Python', text)
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, text.lower())

    def test_versioned_names_by_regex(self):
        for path in (r'C:\Program Files\Python\python3.13.exe', r'D:\x\python3.13t.exe',
                     r'C:\Program Files\Lua\lua5.4.exe', r'C:\Program Files\Tcl\wish86.exe',
                     r'C:\Program Files\Python\pythonw3.12.exe', r'C:\Program Files\PHP\php8.exe'):
            with self.subTest(path=path):
                self.assertTrue(sc._is_interpreter(path, ENV))
        for path in (r'C:\Windows\System32\notepad.exe', r'C:\Program Files\App\app.exe',
                     r'C:\Program Files\App\python.dll', r'C:\Program Files\App\mypython.exe', '', None):
            with self.subTest(path=path):
                self.assertFalse(sc._is_interpreter(path, ENV))

    def test_task_outside_microsoft_is_attention(self):
        for path in (self.NODE, self.PYTHON):
            with self.subTest(path=path):
                items = sc.classify_tasks([_task('\\', 'T', '"' + path + '"')], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])

    def test_task_inside_microsoft_is_attention_and_never_hidden(self):
        for path in (self.NODE, self.PYTHON, r'C:\Windows\System32\bash.exe'):
            with self.subTest(path=path):
                items = sc.classify_tasks([_task('\\Microsoft\\Windows\\X\\', 'T', '"' + path + '"')], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])

    def test_every_interpreter_in_program_files_is_attention(self):
        for exe in sc.INTERPRETERS:
            path = 'C:\\Program Files\\Tool\\' + exe
            with self.subTest(exe=exe):
                for folder in ('\\', '\\Microsoft\\Windows\\'):
                    items = sc.classify_tasks([_task(folder, 'T', '"' + path + '"')], ENV)
                    self.assertEqual([(i['state'], i['reason']) for i in items],
                                     [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
                auto = sc.classify_autostart([{'source': 'run_all', 'name': 'A', 'command': '"' + path + '"'}], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in auto],
                                 [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])

    def test_run_entry_with_arguments_hides_argument(self):
        command = '"' + self.NODE + '" C:\\x\\segredo.js'
        items = sc.classify_autostart([{'source': 'run_user', 'name': 'N', 'command': command}], ENV)
        self.assertEqual([(i['state'], i['reason']) for i in items],
                         [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
        self.assertEqual(items[0]['path'], self.NODE)
        text = self._text({'autostart': items, 'errors': []})
        self.assertNotIn('segredo', text)
        self.assertNotIn('segredo', repr(items))
        self.assertIn('[atenção] N', text)
        self.assertIn('Motivo: ' + sc.REASON_TEXTS[sc.REASON_INTERPRETER], text)

    def test_forged_ok_is_downgraded_on_screen(self):
        forged = {'autostart': [{'source': 'run_all', 'name': 'F', 'path': self.NODE,
                                 'state': sc.STATE_OK, 'reason': sc.REASON_OK}],
                  'tasks': [{'source': 'task', 'name': '\\T', 'path': self.PYTHON,
                             'state': sc.STATE_OK, 'reason': sc.REASON_OK},
                            {'source': 'task', 'name': '\\Microsoft\\U', 'path': self.NODE,
                             'state': sc.STATE_OK, 'reason': sc.REASON_OK}], 'errors': []}
        text = self._text(forged)
        self.assertIn('[atenção] F', text)
        self.assertIn('[atenção] \\T', text)
        self.assertIn('[atenção] \\Microsoft\\U', text)
        self.assertEqual(text.count('Motivo: ' + sc.REASON_TEXTS[sc.REASON_INTERPRETER]), 3)
        self.assertIn('RESUMO: OK 0 · atenção 3', text)

    def test_screen_never_promotes_to_ok(self):
        stored = {'tasks': [{'source': 'task', 'name': '\\T', 'path': self.NODE,
                             'state': sc.STATE_SUSPECT, 'reason': sc.REASON_SYSTEM_NAME}], 'errors': []}
        self.assertIn('[suspeito] \\T', self._text(stored))

    def test_processes_do_not_change(self):
        procs = [{'Name': 'node.exe', 'ExecutablePath': self.NODE},
                 {'Name': 'python.exe', 'ExecutablePath': self.PYTHON}]
        items = sc.classify_processes(procs, ENV)['items']
        self.assertEqual([(i['state'], i['reason']) for i in items], [(sc.STATE_OK, sc.REASON_OK)] * 2)
        text = self._text({'processes': items, 'errors': []})
        self.assertIn('RESUMO: OK 2 · atenção 0', text)

    def test_common_program_in_program_files_still_ok(self):
        path = r'C:\Program Files\App\app.exe'
        self.assertEqual([(i['state'], i['reason']) for i in sc.classify_tasks([_task('\\', 'T', '"' + path + '"')], ENV)],
                         [(sc.STATE_OK, sc.REASON_OK)])
        auto = sc.classify_autostart([{'source': 'run_all', 'name': 'A', 'command': '"' + path + '" --x'}], ENV)
        self.assertEqual([(i['state'], i['reason']) for i in auto], [(sc.STATE_OK, sc.REASON_OK)])

    def test_interpreter_in_appdata_stays_appdata(self):
        path = r'C:\Users\Fulano Silva\AppData\Local\Programs\Python\python.exe'
        auto = sc.classify_autostart([{'source': 'run_user', 'name': 'A', 'command': '"' + path + '"'}], ENV)
        self.assertEqual([(i['state'], i['reason']) for i in auto], [(sc.STATE_ATTENTION, sc.REASON_APPDATA)])
        tasks = sc.classify_tasks([_task('\\', 'T', '"' + path + '"')], ENV)
        self.assertEqual([(i['state'], i['reason']) for i in tasks], [(sc.STATE_ATTENTION, sc.REASON_APPDATA)])


class UncertainNameRevisionPR191Tests(unittest.TestCase):
    """R-48: nome sem extensão, com ponto ou espaço no fim, ou curto (8.3) nunca dá OK."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def _auto(self, command):
        items = sc.classify_autostart([{'source': 'run_user', 'name': 'A', 'command': command}], ENV)
        return [(i['state'], i['reason']) for i in items], items

    def test_interpreter_without_extension_or_trailing_dot_in_autostart(self):
        for command in (r'"C:\Program Files\nodejs\node" x.js', r'"C:\Program Files\Python313\python"',
                        r'"C:\Program Files\nodejs\node.exe." x.js', r'"C:\Program Files\nodejs\node.exe "',
                        r'"C:\Program Files\Python313\python3.13" a.py'):
            with self.subTest(command=command):
                found, items = self._auto(command)
                self.assertEqual(found, [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
                self.assertIn('[atenção] A', self._text({'autostart': items, 'errors': []}))

    def test_script_host_without_extension_or_trailing_dot(self):
        for command in (r'"C:\Program Files\x\powershell" -c y', r'"C:\Program Files\x\cmd.exe." /c y',
                        r'"C:\Program Files\x\POWERS~1.EXE"'):
            with self.subTest(command=command):
                found, _ = self._auto(command)
                self.assertEqual(found[0][0], sc.STATE_ATTENTION)
                self.assertIn(found[0][1], (sc.REASON_SCRIPT_HOST, sc.REASON_UNCERTAIN_NAME))
        self.assertEqual(self._auto(r'"C:\Program Files\x\powershell"')[0],
                         [(sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST)])

    def test_any_extensionless_program_is_never_ok(self):
        for command in (r'"C:\Program Files\App\app"', r'"C:\Program Files\App\app.exe."',
                        r'"C:\Program Files\App\app.com"', r'"C:\Program Files\App\app.exe.."'):
            with self.subTest(command=command):
                found, _ = self._auto(command)
                self.assertEqual(found, [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])

    def test_short_83_name_is_attention_in_autostart_and_task(self):
        path = r'C:\Program Files\AutoHotkey\AUTOHO~1.EXE'
        self.assertEqual(self._auto('"' + path + '" a.ahk')[0], [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])
        for folder in ('\\', '\\Microsoft\\Windows\\'):
            with self.subTest(folder=folder):
                items = sc.classify_tasks([_task(folder, 'T', '"' + path + '"')], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])

    def test_known_quiet_with_odd_name_is_shown_not_hidden(self):
        for path in (r'C:\Windows\System32\DEFRAG~1.EXE', r'C:\Windows\System32\defrag.exe.'):
            with self.subTest(path=path):
                items = sc.classify_tasks([_task('\\Microsoft\\Windows\\A\\', 'B', path)], ENV)
                self.assertEqual([i['state'] for i in items], [sc.STATE_ATTENTION])
        self.assertFalse(sc._known_quiet(r'C:\Windows\System32\defrag', ENV))
        self.assertFalse(sc._known_quiet(r'C:\Windows\System32\defrag.exe.', ENV))
        self.assertTrue(sc._known_quiet(r'C:\Windows\System32\defrag.exe', ENV))
        found, _ = self._auto(r'C:\Windows\System32\ctfmon.exe.')
        self.assertEqual(found[0][0], sc.STATE_ATTENTION)

    def test_screen_downgrades_forged_ok(self):
        paths = (r'C:\Program Files\nodejs\node', r'C:\Program Files\Python313\python',
                 r'C:\Program Files\nodejs\node.exe.', r'C:\Program Files\AutoHotkey\AUTOHO~1.EXE',
                 r'C:\Program Files\x\powershell', r'C:\Program Files\x\cmd.exe.')
        forged = {'autostart': [{'source': 'run_all', 'name': 'F%d' % n, 'path': p, 'state': sc.STATE_OK,
                                 'reason': sc.REASON_OK} for n, p in enumerate(paths)],
                  'tasks': [{'source': 'task', 'name': '\\T%d' % n, 'path': p, 'state': sc.STATE_OK,
                             'reason': sc.REASON_OK} for n, p in enumerate(paths)], 'errors': []}
        text = self._text(forged)
        self.assertIn('RESUMO: OK 0 · atenção %d' % (2 * len(paths)), text)
        self.assertIn('Motivo: ' + sc.REASON_TEXTS[sc.REASON_INTERPRETER], text)
        self.assertIn('Motivo: ' + sc.REASON_TEXTS[sc.REASON_UNCERTAIN_NAME], text)

    def test_new_interpreters_and_texts(self):
        for exe in ('autohotkeyux.exe', 'autohotkey64_uia.exe', 'autohotkey32_uia.exe', 'javaws.exe',
                    'jjs.exe', 'mintty.exe', 'msbuild.exe'):
            self.assertIn(exe, sc.INTERPRETERS)
        self.assertEqual(set(sc.INTERPRETERS) & set(sc.KNOWN_QUIET_PROGRAMS), set())
        self.assertEqual(sc.REASON_TEXTS[sc.REASON_INTERPRETER],
                         'É um programa que roda scripts ou comandos que recebe (como Python, Node ou Java). '
                         'O app não lê esses comandos, então não confere o que ele roda.')
        for reason in (sc.REASON_INTERPRETER, sc.REASON_UNCERTAIN_NAME):
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, sc.REASON_TEXTS[reason].lower())

    def test_processes_still_unchanged(self):
        procs = [{'Name': 'node.exe', 'ExecutablePath': r'C:\Program Files\nodejs\node.exe'}]
        self.assertEqual([i['state'] for i in sc.classify_processes(procs, ENV)['items']], [sc.STATE_OK])


class LaunchersAndVersionsFix0703Tests(unittest.TestCase):
    """FIX-P3-07-03 (issue #192): lançadores, nomes com versão, espaço no fim e marcadores."""

    LAUNCHERS = ('env.exe', 'awk.exe', 'gawk.exe', 'mawk.exe', 'nawk.exe', 'go.exe', 'groovy.exe',
                 'scala.exe', 'kotlin.exe', 'kotlinc.exe')
    VERSIONED = ('node18.exe', 'java8.exe', 'javaw17.exe', 'bash5.exe', 'python3.12.exe', 'lua5.4.exe',
                 'env2.exe', 'go1.22.exe', 'deno2.exe')

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result, env=ENV):
        return '\n'.join(sc.checkup_lines(result, env))

    def _auto(self, command):
        items = sc.classify_autostart([{'source': 'run_user', 'name': 'A', 'command': command}], ENV)
        return [(i['state'], i['reason']) for i in items], items

    def _tasks(self, folder, execute):
        items = sc.classify_tasks([_task(folder, 'T', execute)], ENV)
        return [(i['state'], i['reason']) for i in items]

    def test_launchers_are_in_closed_list(self):
        for exe in self.LAUNCHERS:
            self.assertIn(exe, sc.INTERPRETERS)
        self.assertEqual(set(sc.INTERPRETERS) & set(sc.KNOWN_QUIET_PROGRAMS), set())

    def test_launchers_and_versioned_names_in_program_files_are_attention(self):
        for exe in self.LAUNCHERS + self.VERSIONED:
            path = 'C:\\Program Files\\Lang\\' + exe
            with self.subTest(exe=exe):
                self.assertTrue(sc._is_interpreter(path, ENV))
                found, items = self._auto('"' + path + '" x')
                self.assertEqual(found, [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
                for folder in ('\\', '\\Microsoft\\Windows\\'):
                    self.assertEqual(self._tasks(folder, '"' + path + '"'),
                                     [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
                forged = {'autostart': [dict(items[0], state=sc.STATE_OK, reason=sc.REASON_OK)],
                          'tasks': [{'source': 'task', 'name': '\\T', 'path': path, 'state': sc.STATE_OK,
                                     'reason': sc.REASON_OK}], 'errors': []}
                self.assertIn('RESUMO: OK 0 · atenção 2', self._text(forged))

    def test_versioned_without_extension_is_attention(self):
        for command in (r'"C:\Program Files\nodejs\node18"', r'"C:\Program Files\Java\bin\java8" -jar a.jar'):
            with self.subTest(command=command):
                self.assertEqual(self._auto(command)[0], [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])

    def test_common_programs_with_numbers_stay_ok(self):
        for path in (r'C:\Program Files\App\app2.exe', r'C:\Program Files\Steam\steam.exe',
                     r'C:\Program Files\Envoy\envoy.exe', r'C:\Program Files\Golf\golf.exe'):
            with self.subTest(path=path):
                self.assertFalse(sc._is_interpreter(path, ENV))
                self.assertEqual(self._auto('"' + path + '"')[0], [(sc.STATE_OK, sc.REASON_OK)])

    def test_trailing_space_inside_quotes_is_never_ok(self):
        for command in ('"C:\\Windows\\System32\\ctfmon.exe "', '"C:\\Windows\\System32\\ctfmon.exe\t" x',
                        '"C:\\Program Files\\App\\app.exe "'):
            with self.subTest(command=command):
                self.assertEqual(self._auto(command)[0], [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])
        # Sem o espaço, continua como antes.
        self.assertEqual(self._auto(r'"C:\Windows\System32\ctfmon.exe"')[0], [(sc.STATE_OK, sc.REASON_OK)])
        # Interpretador continua com o motivo de interpretador.
        self.assertEqual(self._auto(r'"C:\Program Files\nodejs\node.exe "')[0],
                         [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])

    def test_task_with_trailing_space_is_shown_not_hidden(self):
        for execute in ('C:\\Windows\\System32\\ctfmon.exe ', 'C:\\Windows\\System32\\defrag.exe\t'):
            with self.subTest(execute=execute):
                self.assertEqual(self._tasks('\\Microsoft\\Windows\\A\\', execute),
                                 [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])
        # Fora de \\Microsoft\\ também não dá OK.
        self.assertEqual([r[0] for r in self._tasks('\\', 'C:\\Program Files\\App\\app.exe ')],
                         [sc.STATE_ATTENTION])
        self.assertEqual(self._tasks('\\', 'C:\\Windows\\System32\\ctfmon.exe '),
                         [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])
        self.assertEqual(self._tasks('\\Microsoft\\Windows\\A\\', r'C:\Windows\System32\defrag.exe'), [])

    def test_uncertain_name_text(self):
        self.assertEqual(sc.REASON_TEXTS[sc.REASON_UNCERTAIN_NAME],
                         'O nome do arquivo não termina em .exe, termina com ponto ou espaço, ou está '
                         'abreviado (como ARQUIV~1.EXE); o app não confere qual programa ele abre.')

    def test_placeholders_survive_user_named_sid_or_mail(self):
        sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
        for user in ('SID', 'mail', 'e-mail', 'Sid', 'MAIL'):
            env = dict(ENV, USERNAME=user)
            with self.subTest(user=user):
                path = 'D:\\Sync-' + sid + '\\fulano@empresa.com\\a.exe'
                once = sc.sanitize_path(path, env)
                self.assertEqual(once, 'D:\\Sync-<SID>\\<e-mail>\\a.exe')
                self.assertEqual(sc.sanitize_path(once, env), once)
                procs = [{'Name': 'a.exe', 'ExecutablePath': path}]
                rows = [_task('\\', 'Task' + sid, '"C:\\Program Files\\x\\' + 'ciclano@mail.com\\b.exe"')]
                result = sc.read_checkup(_fake_ps(procs=procs, tasks=rows), env)
                text = self._text(result, env)
                for leak in ('1001', '3333333333', 'fulano', 'ciclano', 'empresa', '@'):
                    self.assertNotIn(leak, repr(result))
                    self.assertNotIn(leak, text)
                self.assertIn('D:\\Sync-<SID>\\<e-mail>\\a.exe', text)
                self.assertIn('\\Task<SID>', text)
                self.assertIn('\\x\\<e-mail>\\b.exe', text)
                self.assertNotIn('<%USERNAME%>', text)
                self.assertNotIn('<e-%USERNAME%>', text)

    def test_user_name_inside_email_domain_still_hides_email(self):
        env = dict(ENV, USERNAME='mail')
        self.assertEqual(sc.sanitize_path(r'D:\x\fulano@mail.com\a.exe', env), r'D:\x\<e-mail>\a.exe')
        env = dict(ENV, USERNAME='com')
        self.assertEqual(sc.sanitize_path(r'D:\x\fulano@mail.com\a.exe', env), r'D:\x\<e-mail>\a.exe')


class QuotedSpaceAndScriptHostVersionsFix0704Tests(unittest.TestCase):
    """FIX-P3-07-04 (issue #194): ação entre aspas com espaço e versões de SCRIPT_HOSTS (R-50)."""

    VERSIONED_HOSTS = ('pwsh7.exe', 'powershell7.exe', 'cmd2.exe', 'wscript5.exe', 'cscript5.exe',
                       'mshta2.exe', 'pwsh-7.exe', 'pwsh7.4.exe')

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result, env=ENV):
        return '\n'.join(sc.checkup_lines(result, env))

    def _auto(self, command):
        items = sc.classify_autostart([{'source': 'run_user', 'name': 'A', 'command': command}], ENV)
        return [(i['state'], i['reason']) for i in items], items

    def _tasks(self, folder, execute):
        items = sc.classify_tasks([_task(folder, 'T', execute)], ENV)
        return [(i['state'], i['reason']) for i in items]

    def test_quoted_task_with_space_inside_is_uncertain_name(self):
        for execute in ('"C:\\Windows\\System32\\defrag.exe "', '"C:\\Windows\\System32\\ctfmon.exe\t"',
                        '"C:\\Program Files\\App\\app.exe "'):
            for folder in ('\\', '\\Microsoft\\Windows\\A\\'):
                with self.subTest(execute=execute, folder=folder):
                    self.assertEqual(self._tasks(folder, execute),
                                     [(sc.STATE_ATTENTION, sc.REASON_UNCERTAIN_NAME)])
        # Sem o espaço, a tarefa da lista fechada em \Microsoft\ continua sumindo.
        self.assertEqual(self._tasks('\\Microsoft\\Windows\\A\\', '"C:\\Windows\\System32\\defrag.exe"'), [])

    def test_quoted_task_with_space_keeps_stronger_reasons(self):
        self.assertEqual(self._tasks('\\', '"C:\\Program Files\\nodejs\\node.exe "'),
                         [(sc.STATE_ATTENTION, sc.REASON_INTERPRETER)])
        self.assertEqual(self._tasks('\\', '"C:\\Windows\\System32\\cmd.exe "'),
                         [(sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST)])
        self.assertEqual(self._tasks('\\', '"C:\\Temp\\svchost.exe "'),
                         [(sc.STATE_SUSPECT, sc.REASON_SYSTEM_NAME)])
        # Espaço no começo, aspas a mais ou algo depois continua sem caminho completo.
        for execute in ('" C:\\Windows\\System32\\defrag.exe"', '"C:\\a b\\x.exe " --token=1'):
            with self.subTest(execute=execute):
                self.assertEqual(self._tasks('\\', execute),
                                 [(sc.STATE_ATTENTION, sc.REASON_NOT_FULL_PATH)])

    def test_versioned_script_hosts_in_program_files_are_attention(self):
        for exe in self.VERSIONED_HOSTS:
            path = 'C:\\Program Files\\Tools\\' + exe
            with self.subTest(exe=exe):
                found, items = self._auto('"' + path + '" x')
                self.assertEqual(found, [(sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST)])
                self.assertEqual(self._tasks('\\', '"' + path + '"'),
                                 [(sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST)])
                self.assertEqual([r[0] for r in self._tasks('\\Microsoft\\Windows\\', '"' + path + '"')],
                                 [sc.STATE_ATTENTION])
                forged = {'autostart': [dict(items[0], state=sc.STATE_OK, reason=sc.REASON_OK)],
                          'tasks': [{'source': 'task', 'name': '\\T', 'path': path, 'state': sc.STATE_OK,
                                     'reason': sc.REASON_OK}], 'errors': []}
                self.assertIn('RESUMO: OK 0 · atenção 2', self._text(forged))

    def test_common_names_stay_ok(self):
        for path in (r'C:\Program Files\App\app2.exe', r'C:\Program Files\Steam\steam.exe',
                     r'C:\Program Files\Cmder\cmder.exe', r'C:\Program Files\Cmd\cmdr.exe',
                     r'C:\Program Files\Pwsh\pwshell.exe'):
            with self.subTest(path=path):
                self.assertEqual(self._auto('"' + path + '"')[0], [(sc.STATE_OK, sc.REASON_OK)])
                self.assertEqual(self._tasks('\\', '"' + path + '"'), [(sc.STATE_OK, sc.REASON_OK)])



ADMIN_HIDDEN = 'N/A: Must be and administrator to view exclusions'


def _defender(rt=True, av=True, am=True, paths=None, procs=None, exts=None, preference=True):
    return {'Status': {'AMServiceEnabled': am, 'AntivirusEnabled': av, 'RealTimeProtectionEnabled': rt},
            'Preference': ({'ExclusionPath': paths, 'ExclusionProcess': procs, 'ExclusionExtension': exts}
                           if preference else None)}


class DefenderAndNetworkSlice3Tests(unittest.TestCase):
    """P3-07 fatia 3: Defender e conexões de rede, só com dados simulados e ``ps`` falso."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result, env=ENV):
        return '\n'.join(sc.checkup_lines(result, env))

    def _reasons(self, data):
        return [(i['state'], i['reason']) for i in sc.classify_defender(data, ENV)]

    def _exclusion(self, kind, value):
        data = _defender(**{kind: [value]})
        found = [(i['state'], i['reason']) for i in sc.classify_defender(data, ENV)
                 if i['reason'] != sc.REASON_RT_ON]
        self.assertEqual(len(found), 1, found)
        return found[0]

    # --- Defender: proteção em tempo real ---
    def test_real_time_on_is_ok(self):
        self.assertEqual(self._reasons(_defender()), [(sc.STATE_OK, sc.REASON_RT_ON)])

    def test_real_time_off_is_attention_and_mentions_security_app(self):
        for kwargs in ({'rt': False}, {'av': False}, {'am': False}):
            with self.subTest(**kwargs):
                self.assertEqual(self._reasons(_defender(**kwargs)), [(sc.STATE_ATTENTION, sc.REASON_RT_OFF)])
        self.assertIn('Segurança do Windows', sc.REASON_TEXTS[sc.REASON_RT_OFF])
        self.assertIn('outro programa de segurança', sc.REASON_TEXTS[sc.REASON_RT_OFF])

    def test_missing_or_unreadable_status_is_attention_not_checked(self):
        cases = (None, 'x', 7, [], {}, {'Status': None, 'Preference': None},
                 {'Status': {'RealTimeProtectionEnabled': 'True', 'AntivirusEnabled': True,
                             'AMServiceEnabled': True}},
                 {'Status': {'RealTimeProtectionEnabled': True}})
        for data in cases:
            with self.subTest(data=data):
                found = self._reasons(data)
                self.assertIn((sc.STATE_ATTENTION, sc.REASON_DEFENDER_UNKNOWN), found)
                self.assertNotIn(sc.STATE_OK, [f[0] for f in found])
        self.assertIn('não foi possível conferir', sc.REASON_TEXTS[sc.REASON_DEFENDER_UNKNOWN].lower())

    def test_wrapped_list_output_is_read(self):
        self.assertEqual(self._reasons([_defender()]), [(sc.STATE_OK, sc.REASON_RT_ON)])

    # --- Defender: exclusões ---
    def test_suspect_path_exclusions(self):
        cases = {
            r'C:\Users\Fulano Silva': sc.REASON_EXCL_USER,
            r'C:\Users\Fulano Silva\Downloads': sc.REASON_EXCL_USER,
            r'%USERPROFILE%\Documents': sc.REASON_EXCL_USER,
            r'D:\Users\Beltrano': sc.REASON_EXCL_USER,
            r'C:\Users': sc.REASON_EXCL_USER,
            r'C:\Users\Fulano Silva\AppData\Local\Temp': sc.REASON_EXCL_TEMP,
            r'C:\Windows\Temp\x': sc.REASON_EXCL_TEMP,
            r'%TEMP%': sc.REASON_EXCL_TEMP,
            r'C:\Users\Fulano Silva\AppData\Roaming\Minerador': sc.REASON_EXCL_APPDATA,
            r'%APPDATA%': sc.REASON_EXCL_APPDATA,
            r'C:\ProgramData': sc.REASON_EXCL_PROGRAMDATA,
            r'C:\ProgramData\Coisa\x.exe': sc.REASON_EXCL_PROGRAMDATA,
            'C:\\': sc.REASON_EXCL_DRIVE_ROOT,
            'D:': sc.REASON_EXCL_DRIVE_ROOT,
            'E:\\*': sc.REASON_EXCL_DRIVE_ROOT,
            r'\\?\C:\\': sc.REASON_EXCL_DRIVE_ROOT,
            r'C:\Windows': sc.REASON_EXCL_WINDOWS,
            'c:\\windows\\': sc.REASON_EXCL_WINDOWS,
            r'%SystemRoot%\System32': sc.REASON_EXCL_WINDOWS,
            r'C:\Windows\SysWOW64\*': sc.REASON_EXCL_WINDOWS,
            '*.exe': sc.REASON_EXCL_EXTENSION,
            r'C:\Jogos\*.ps1': sc.REASON_EXCL_EXTENSION,
        }
        for value, reason in cases.items():
            with self.subTest(value=value):
                self.assertEqual(self._exclusion('paths', value), (sc.STATE_SUSPECT, reason))

    def test_other_exclusions_are_attention_never_ok(self):
        for kind, value in (('paths', r'C:\Program Files\Jogo'), ('paths', r'D:\Jogos\Steam'),
                            ('paths', r'C:\Windows\Logs\CBS'), ('paths', 'pasta_solta'),
                            ('procs', r'C:\Program Files\Jogo\jogo.exe'), ('procs', 'steam.exe'),
                            ('exts', 'iso'), ('exts', '.mp4'), ('exts', '*.vhdx')):
            with self.subTest(kind=kind, value=value):
                self.assertEqual(self._exclusion(kind, value), (sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER))

    def test_executable_extensions_are_suspect(self):
        for ext in ('exe', '.dll', '*.ps1', 'BAT', '.cmd', 'vbs', 'js', 'scr'):
            with self.subTest(ext=ext):
                self.assertEqual(self._exclusion('exts', ext), (sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION))

    def test_script_host_and_interpreter_processes_are_suspect(self):
        for value in ('powershell.exe', 'pwsh7.exe', 'cmd.exe', r'C:\Windows\System32\wscript.exe',
                      'python.exe', 'python3.12.exe', r'C:\Program Files\nodejs\node.exe', 'node18.exe',
                      'mshta', 'java8.exe'):
            with self.subTest(value=value):
                self.assertEqual(self._exclusion('procs', value),
                                 (sc.STATE_SUSPECT, sc.REASON_EXCL_SCRIPT_PROCESS))

    def test_process_in_suspect_folder_is_suspect(self):
        self.assertEqual(self._exclusion('procs', r'C:\Users\Fulano Silva\AppData\Roaming\x\app.exe'),
                         (sc.STATE_SUSPECT, sc.REASON_EXCL_APPDATA))
        self.assertEqual(self._exclusion('procs', r'C:\Temp\x.exe'), (sc.STATE_SUSPECT, sc.REASON_EXCL_TEMP))

    def test_hidden_exclusions_without_admin(self):
        for value in (ADMIN_HIDDEN, [ADMIN_HIDDEN], 'n/a: algo'):
            data = _defender(paths=value, procs=value, exts=value)
            with self.subTest(value=value):
                self.assertEqual(self._reasons(data), [(sc.STATE_OK, sc.REASON_RT_ON),
                                                       (sc.STATE_ATTENTION, sc.REASON_EXCL_HIDDEN)])
        self.assertEqual(sc.REASON_TEXTS[sc.REASON_EXCL_HIDDEN],
                         'Sem administrador, o Windows não mostra as exclusões do Defender; '
                         'não foi possível conferir.')
        text = self._text({'defender': sc.classify_defender(_defender(paths=[ADMIN_HIDDEN]), ENV), 'errors': []})
        self.assertNotIn('Must be', text)
        for word in ('elevar', 'como administrador', 'executar como'):
            self.assertNotIn(word, text.lower())

    def test_missing_preference_is_attention_not_checked(self):
        for data in (_defender(preference=False), {'Status': _defender()['Status'], 'Preference': 'x'}):
            with self.subTest(data=data):
                self.assertIn((sc.STATE_ATTENTION, sc.REASON_EXCL_UNKNOWN), self._reasons(data))

    def test_no_exclusions_is_a_neutral_line_not_ok(self):
        text = self._text({'defender': sc.classify_defender(_defender(paths=[], procs=None, exts=None), ENV),
                           'errors': []})
        self.assertIn(sc.DEFENDER_NO_EXCLUSIONS, text)
        self.assertIn('RESUMO: OK 1 · atenção 0 · suspeito 0', text)
        self.assertNotIn('nenhuma exclusão', sc.REASON_TEXTS[sc.REASON_RT_ON].lower())

    def test_exclusion_paths_are_cleaned_and_listed_once(self):
        paths = [r'C:\Users\Fulano Silva\AppData\Roaming\Mina', r'c:\users\fulano silva\appdata\roaming\mina',
                 r'D:\Users\Beltrano\x', r'D:\S-1-5-21-111-222-333-1001\fulano@exemplo.com\Fulano Silva',
                 'D:\\Jogos\x07ruim']
        items = sc.classify_defender(_defender(paths=paths), ENV)
        excl = [i for i in items if i['reason'] != sc.REASON_RT_ON]
        self.assertEqual(len(excl), 4)
        text = self._text({'defender': items, 'errors': []})
        for secret in ('Fulano', 'Silva', 'Beltrano', 'S-1-5-21', 'exemplo.com', '\x07'):
            self.assertNotIn(secret, text)
        self.assertIn(r'%USERPROFILE%\AppData\Roaming\Mina', text)
        self.assertIn('<outro usuário>', text)
        self.assertIn('<SID>', text)

    def test_forged_ok_exclusion_is_never_ok_on_screen(self):
        forged = {'defender': [{'source': 'defender', 'name': 'Exclusão de pasta', 'kind': 'path',
                                'path': r'%USERPROFILE%\AppData\Roaming\x', 'state': sc.STATE_OK,
                                'reason': sc.REASON_OK},
                               {'source': 'defender', 'name': 'Exclusão de pasta', 'kind': 'path',
                                'path': r'D:\Jogos', 'state': sc.STATE_OK, 'reason': sc.REASON_EXCL_OTHER},
                               {'source': 'defender', 'name': 'x', 'state': sc.STATE_OK, 'reason': 'texto livre'}],
                  'network': [{'source': 'network', 'name': 'a.exe', 'port': 3333, 'state': sc.STATE_OK,
                               'reason': sc.REASON_OK}],
                  'errors': []}
        text = self._text(forged)
        self.assertIn('RESUMO: OK 0 · atenção 2 · suspeito 2', text)
        self.assertNotIn('texto livre', text)
        self.assertIn(sc.RECOMMENDATION, text)

    # --- Rede ---
    def _conn(self, port, name='app', path=r'C:\Program Files\App\app.exe'):
        return {'RemotePort': port, 'Name': name, 'Path': path}

    def test_mining_ports_are_suspect(self):
        for port in sc.MINING_PORTS:
            with self.subTest(port=port):
                items = sc.classify_connections([self._conn(port)], ENV)
                self.assertEqual([(i['state'], i['reason']) for i in items],
                                 [(sc.STATE_SUSPECT, sc.REASON_MINING_PORT)])
        self.assertEqual(sc.MINING_PORTS, (3333, 4444, 5555, 7777, 14444, 14433, 45700))
        self.assertIn('conexão para uma porta comum de mineração', sc.REASON_TEXTS[sc.REASON_MINING_PORT])

    def test_other_ports_and_garbage_are_ignored(self):
        rows = [self._conn(443), self._conn(80), self._conn('3333x'), self._conn(True), self._conn(None),
                {'Name': 'x'}, None, 7, 'texto']
        self.assertEqual(sc.classify_connections(rows, ENV), [])
        self.assertEqual(sc.classify_connections(None, ENV), [])
        self.assertEqual(len(sc.classify_connections({'value': [self._conn('4444')]}, ENV)), 1)

    def test_same_connection_once_with_count_and_clean_names(self):
        path = r'C:\Users\Fulano Silva\AppData\Roaming\Fulano Silva\x.exe'
        rows = [self._conn(3333, 'Fulano Silva-miner', path)] * 3 + [self._conn(3333, None, None),
                                                                    self._conn(4444, 'b', path)]
        items = sc.classify_connections(rows, ENV)
        self.assertEqual(len(items), 3)
        text = self._text({'network': items, 'errors': []})
        self.assertIn('(3 conexões)', text)
        self.assertIn('porta 3333', text)
        self.assertIn('porta 4444', text)
        self.assertNotIn('Fulano', text)
        self.assertNotIn('Silva', text)
        self.assertIn(r'%USERPROFILE%\AppData\Roaming\%USERNAME%\x.exe', text)
        self.assertIn('RESUMO: OK 0 · atenção 0 · suspeito 3', text)

    def test_no_connection_is_neutral_line(self):
        text = self._text({'network': [], 'errors': []})
        self.assertIn('Nenhuma conexão para portas comuns de mineração no momento do check-up.', text)
        self.assertIn(sc.NOT_ALL_CHECKED, text)

    def test_network_query_never_asks_remote_address(self):
        source = (ROOT / 'security_checkup.py').read_text(encoding='utf-8')
        self.assertNotIn('RemoteAddress', source)
        self.assertNotIn('RemoteAddress', sc.NETWORK_QUERY)
        self.assertIn('Get-NetTCPConnection -State Established', sc.NETWORK_QUERY)
        self.assertIn('Get-Process -Id', sc.NETWORK_QUERY)
        self.assertIn('RemotePort', sc.NETWORK_QUERY)
        self.assertIn('OwningProcess', sc.NETWORK_QUERY)
        rows = [{'RemotePort': 3333, 'Name': 'a', 'Path': None, 'RemoteAddress': '203.0.113.9',
                 'LocalAddress': '192.168.0.10'}]
        result = sc.read_checkup(_fake_ps(network=rows), ENV)
        self.assertNotIn('203.0.113.9', repr(result))
        self.assertNotIn('192.168.0.10', repr(result))

    # --- Consultas, read_checkup e tela ---
    def test_defender_query_is_read_only(self):
        self.assertIn('Get-MpComputerStatus', sc.DEFENDER_QUERY)
        self.assertIn('Get-MpPreference', sc.DEFENDER_QUERY)
        for field in ('AMServiceEnabled', 'AntivirusEnabled', 'RealTimeProtectionEnabled',
                      'ExclusionPath', 'ExclusionProcess', 'ExclusionExtension'):
            self.assertIn(field, sc.DEFENDER_QUERY)
        self.assertIn('-Compress', sc.DEFENDER_QUERY)
        source = (ROOT / 'security_checkup.py').read_text(encoding='utf-8')
        for code in (sc.DEFENDER_QUERY, sc.NETWORK_QUERY, source):
            for word in ('Set-Mp', 'Add-Mp', 'Remove-Mp', 'Start-Mp', 'Update-Mp', 'Stop-Process', 'RunAs',
                         'Disable', 'Set-NetFirewall'):
                self.assertNotIn(word, code)

    def test_read_checkup_returns_defender_and_network(self):
        rows = [{'RemotePort': 3333, 'Name': 'mina', 'Path': r'C:\Temp\mina.exe'}]
        result = sc.read_checkup(_fake_ps(defender=_defender(rt=False, exts=['exe']), network=rows), ENV)
        self.assertEqual(result['errors'], [])
        self.assertEqual([i['reason'] for i in result['defender']], [sc.REASON_RT_OFF, sc.REASON_EXCL_EXTENSION])
        self.assertEqual([i['reason'] for i in result['network']], [sc.REASON_MINING_PORT])
        text = self._text(result)
        self.assertIn('MICROSOFT DEFENDER', text)
        self.assertIn('CONEXÕES DE REDE', text)
        self.assertLess(text.index('PROCESSOS EM EXECUÇÃO'), text.index('MICROSOFT DEFENDER'))
        self.assertLess(text.index('MICROSOFT DEFENDER'), text.index('CONEXÕES DE REDE'))
        self.assertLess(text.index('CONEXÕES DE REDE'), text.index('RESUMO'))
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 2', text)
        self.assertIn(sc.RECOMMENDATION, text)

    def test_recommendation_when_only_defender_or_network_flagged(self):
        for kwargs in ({'defender': _defender(rt=False)}, {'defender': _defender(paths=[ADMIN_HIDDEN])},
                       {'defender': None},
                       {'network': [{'RemotePort': 14444, 'Name': 'x', 'Path': None}]}):
            with self.subTest(kwargs=kwargs):
                text = self._text(sc.read_checkup(_fake_ps(**kwargs), ENV))
                self.assertIn(sc.RECOMMENDATION, text)
                self.assertIn(sc.NOT_CERTAIN, text)
        clean = self._text(sc.read_checkup(_fake_ps(), ENV))
        self.assertNotIn(sc.RECOMMENDATION, clean)
        self.assertIn(sc.NOT_ALL_CHECKED, clean)

    def test_failed_queries_become_codes_without_system_text(self):
        result = sc.read_checkup(_fake_ps(fail=('defender', 'network')), ENV)
        self.assertEqual(result['errors'], ['defender', 'network'])
        self.assertEqual(result['defender'], [])
        self.assertEqual(result['network'], [])
        text = self._text(result)
        self.assertIn(sc.ERROR_TEXTS['defender'], text)
        self.assertIn(sc.ERROR_TEXTS['network'], text)
        self.assertNotIn('Acesso negado', text)
        self.assertNotIn('NTUSER', text)
        self.assertNotIn(sc.NETWORK_EMPTY, text)
        self.assertIn(sc.RECOMMENDATION, text)
        # As outras seções continuam.
        procs = [{'Name': 'a.exe', 'ExecutablePath': r'C:\Temp\a.exe'}]
        other = sc.read_checkup(_fake_ps(procs=procs, fail=('defender',)), ENV)
        self.assertEqual(len(other['processes']), 1)
        self.assertEqual(other['errors'], ['defender'])

    def test_confirmation_mentions_defender_and_network(self):
        self.assertIn('Microsoft Defender', sc.CHECKUP_CONFIRMATION)
        self.assertIn('conexões de rede', sc.CHECKUP_CONFIRMATION)
        self.assertIn('tarefas agendadas', sc.CHECKUP_CONFIRMATION)
        self.assertNotIn('vírus', sc.CHECKUP_CONFIRMATION.lower())

    def test_no_forbidden_words_in_new_lines(self):
        result = sc.read_checkup(_fake_ps(defender=_defender(rt=False, paths=['C:\\', ADMIN_HIDDEN],
                                                             procs=['cmd.exe'], exts=['iso']),
                                          network=[{'RemotePort': 3333, 'Name': 'x', 'Path': None}]), ENV)
        for line in sc.checkup_lines(result, ENV):
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, line.lower())

    # --- Ressalvas da revisão da PR #195 ---
    def test_quoted_trailing_space_task_shows_path_without_space(self):
        for folder in ('\\', '\\Microsoft\\Windows\\Defrag\\'):
            with self.subTest(folder=folder):
                items = sc.classify_tasks([_task(folder, 'T', '"C:\\Windows\\System32\\defrag.exe "')], ENV)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]['path'], r'C:\Windows\System32\defrag.exe')

    def test_versioned_script_host_in_microsoft_task_is_script_host(self):
        items = sc.classify_tasks([_task('\\Microsoft\\Windows\\A\\', 'T', r'C:\Windows\System32\cmd2.exe')], ENV)
        self.assertEqual([(i['state'], i['reason']) for i in items], [(sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST)])
        # O rundll32 de verdade continua com o motivo das tarefas da Microsoft.
        items = sc.classify_tasks([_task('\\Microsoft\\Windows\\A\\', 'T', r'C:\Windows\System32\rundll32.exe')],
                                  ENV)
        self.assertEqual([i['reason'] for i in items], [sc.REASON_MS_WINDOWS_PROGRAM])


class Revisions196Slice4Tests(unittest.TestCase):
    """P3-07 fatia 4: ressalvas da revisão da PR #196 (R-51), só dados simulados e ``ps`` falso."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _exclusions(self, kind, value):
        data = _defender(**{kind: [value]})
        return [(i['state'], i['reason']) for i in sc.classify_defender(data, ENV)
                if i['reason'] != sc.REASON_RT_ON]

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    # 1. Normalização do Windows antes de comparar (R-51)
    def test_trailing_dot_space_and_wildcards_are_suspect(self):
        cases = {
            'C:\\Windows.': sc.REASON_EXCL_WINDOWS,
            'C:\\Windows. \\': sc.REASON_EXCL_WINDOWS,
            'C:\\Windows\\System32.': sc.REASON_EXCL_WINDOWS,
            'C:\\ProgramData.': sc.REASON_EXCL_PROGRAMDATA,
            'C:\\ProgramData.\\x': sc.REASON_EXCL_PROGRAMDATA,
            'C:\\Users \\x': sc.REASON_EXCL_USER,
            'C:\\Users.': sc.REASON_EXCL_USER,
            'C:\\*.*': sc.REASON_EXCL_DRIVE_ROOT,
            'C:\\*': sc.REASON_EXCL_DRIVE_ROOT,
            '*': sc.REASON_EXCL_DRIVE_ROOT,
            '*.*': sc.REASON_EXCL_DRIVE_ROOT,
            'C:\\Win*': sc.REASON_EXCL_DRIVE_ROOT,
            'C:\\Windo?s': sc.REASON_EXCL_DRIVE_ROOT,
            'C:\\Windows\\*.*': sc.REASON_EXCL_WINDOWS,
            '\\\\?\\C:\\Windows.': sc.REASON_EXCL_WINDOWS,
            '\\??\\C:\\ProgramData': sc.REASON_EXCL_PROGRAMDATA,
            'C:\\Jogos\\*.exe.': sc.REASON_EXCL_EXTENSION,
            'C:\\Users\\*\\AppData': sc.REASON_EXCL_USER,
        }
        for value, reason in cases.items():
            with self.subTest(value=value):
                self.assertEqual(self._exclusions('paths', value), [(sc.STATE_SUSPECT, reason)])

    def test_normalized_others_stay_attention(self):
        for value in ('D:\\Jogos\\*', 'D:\\Jogos.\\Steam ', 'D:\\Jogos\\*.iso'):
            with self.subTest(value=value):
                self.assertEqual(self._exclusions('paths', value), [(sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER)])

    def test_screen_reclassifies_normalized_value(self):
        forged = {'defender': [{'source': 'defender', 'kind': 'path', 'path': 'C:\\Windows.',
                                'state': sc.STATE_ATTENTION, 'reason': sc.REASON_EXCL_OTHER}], 'errors': []}
        text = self._text(forged)
        self.assertIn('[suspeito] Exclusão de pasta ou arquivo', text)

    # 2. Mais extensões de programa ou de script
    def test_more_executable_extensions_are_suspect(self):
        for ext in ('com', 'hta', 'msi', 'jar', 'wsf', 'vbe', 'jse', 'psm1', 'cpl', 'pif', 'lnk', 'sys',
                    'msc', 'reg', 'exe.', '.EXE.', '*.msi', '*.lnk.', 'exe ', 'exe. .'):
            with self.subTest(ext=ext):
                self.assertEqual(self._exclusions('exts', ext), [(sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION)])
        for value in ('C:\\Jogos\\*.hta', 'D:\\x\\*.jar'):
            with self.subTest(value=value):
                self.assertEqual(self._exclusions('paths', value), [(sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION)])
        self.assertEqual(self._exclusions('exts', 'iso'), [(sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER)])

    # 3. Nenhuma conexão estabelecida não é erro
    def test_network_query_tolerates_no_connection(self):
        query = sc.NETWORK_QUERY
        self.assertIn('Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue', query)
        self.assertNotIn('Get-NetTCPConnection -State Established -ErrorAction Stop', query)
        self.assertIn('-ErrorVariable', query)
        self.assertIn('ObjectNotFound', query)
        self.assertIn('throw', query)
        for empty in (None, [], '', {'value': []}):
            with self.subTest(empty=empty):
                result = sc.read_checkup(_fake_ps(network=empty), ENV)
                self.assertEqual(result['network'], [])
                self.assertNotIn('network', result['errors'])
                text = self._text(result)
                self.assertIn(sc.NETWORK_EMPTY, text)
                self.assertNotIn(sc.ERROR_TEXTS['network'], text)
                self.assertNotIn(sc.RECOMMENDATION, text)
        # Um erro de verdade continua virando o código 'network'.
        result = sc.read_checkup(_fake_ps(fail=('network',)), ENV)
        self.assertEqual(result['errors'], ['network'])

    # 4. Valor das exclusões que não parece caminho, extensão ou programa
    def test_unreadable_exclusion_values_hide_system_text(self):
        odd = ('N/D: É preciso ser administrador para ver as exclusões', 'Must be an administrator',
               'Precisa ser Administrador', 'pasta solta', 'Erro ao ler')
        # 'n/d: x\\y' tem barra invertida: parece caminho e não vira aviso (R-52/R-53).
        for kind in ('paths', 'procs', 'exts'):
            for value in odd:
                with self.subTest(kind=kind, value=value):
                    data = _defender(**{kind: [value]})
                    items = sc.classify_defender(data, ENV)
                    found = [(i['state'], i['reason']) for i in items if i['reason'] != sc.REASON_RT_ON]
                    self.assertEqual(len(found), 1, found)
                    self.assertEqual(found[0][0], sc.STATE_ATTENTION)
                    self.assertIn(found[0][1], (sc.REASON_EXCL_HIDDEN, sc.REASON_EXCL_UNKNOWN))
                    text = self._text({'defender': items, 'errors': []})
                    self.assertNotIn(value, text)
                    for word in ('N/D', 'preciso', 'Must', 'Precisa', 'solta', 'Erro'):
                        self.assertNotIn(word, text)
        self.assertEqual(self._exclusions('exts', 'exe exe'), [(sc.STATE_ATTENTION, sc.REASON_EXCL_UNKNOWN)])
        self.assertEqual(self._exclusions('paths', 'N/D: algo'), [(sc.STATE_ATTENTION, sc.REASON_EXCL_HIDDEN)])

    def test_unreadable_value_on_screen_is_hidden(self):
        forged = {'defender': [{'source': 'defender', 'kind': 'path', 'path': 'Texto do Windows aqui',
                                'state': sc.STATE_OK, 'reason': sc.REASON_EXCL_OTHER},
                               {'source': 'defender', 'kind': 'process', 'path': 'Must be administrator',
                                'state': sc.STATE_SUSPECT, 'reason': sc.REASON_EXCL_USER}], 'errors': []}
        text = self._text(forged)
        self.assertNotIn('Texto do Windows', text)
        self.assertNotIn('Must be', text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 1', text)

    def test_administrator_profile_paths_stay_suspect(self):
        # Revisão da PR #197 (R-52): a palavra "administrador" num caminho não é o aviso do Windows.
        env = dict(ENV, USERPROFILE='C:\\Users\\Administrador', USERNAME='Administrador',
                   LOCALAPPDATA='C:\\Users\\Administrador\\AppData\\Local',
                   APPDATA='C:\\Users\\Administrador\\AppData\\Roaming',
                   TEMP='C:\\Users\\Administrador\\AppData\\Local\\Temp')
        for profile in ('Administrador', 'Administrator'):
            paths = [f'C:\\Users\\{profile}\\Downloads', f'C:\\Users\\{profile}\\AppData\\Roaming\\x',
                     f'C:\\Users\\{profile}\\AppData\\Local\\Temp\\miner.exe']
            procs = [f'C:\\Users\\{profile}\\AppData\\Local\\Temp\\miner.exe', 'Administrador.exe']
            with self.subTest(profile=profile):
                items = sc.classify_defender(_defender(paths=paths, procs=procs), env)
                found = [(i['state'], i['reason']) for i in items if i['reason'] != sc.REASON_RT_ON]
                self.assertEqual([f[0] for f in found[:4]], [sc.STATE_SUSPECT] * 4)
                self.assertEqual(found[4], (sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER))
                self.assertNotIn(sc.REASON_EXCL_HIDDEN, [f[1] for f in found])
                text = '\n'.join(sc.checkup_lines({'defender': items, 'errors': []}, env))
                self.assertIn('RESUMO: OK 1 · atenção 1 · suspeito 4', text)
                self.assertNotIn(sc.REASON_TEXTS[sc.REASON_EXCL_HIDDEN], text)
        # Na tela (_defender_effective), um dict guardado também continua "suspeito".
        forged = {'defender': [{'source': 'defender', 'kind': 'path',
                                'path': 'C:\\Users\\Administrador\\Downloads', 'state': sc.STATE_OK,
                                'reason': sc.REASON_EXCL_OTHER}], 'errors': []}
        self.assertIn('RESUMO: OK 0 · atenção 0 · suspeito 1', '\n'.join(sc.checkup_lines(forged, ENV)))

    def test_filter_only_hides_never_downgrades(self):
        # Revisão 2 da PR #197 (R-53): mesma classificação de antes do filtro (main).
        cases = (('procs', 'bin/cmd.exe', sc.STATE_SUSPECT, sc.REASON_EXCL_SCRIPT_PROCESS),
                 ('procs', 'a/cmd.exe', sc.STATE_SUSPECT, sc.REASON_EXCL_SCRIPT_PROCESS),
                 ('procs', 'ab/cd\\miner.exe', sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER),
                 ('procs', 'usr/bin', sc.STATE_ATTENTION, sc.REASON_EXCL_OTHER),
                 ('exts', '**.exe', sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION),
                 ('exts', '*. exe', sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION),
                 ('exts', '. exe', sc.STATE_SUSPECT, sc.REASON_EXCL_EXTENSION),
                 ('paths', 'C:\\Users\\x administrator\\AppData\\Roaming', sc.STATE_SUSPECT,
                  sc.REASON_EXCL_APPDATA))
        for kind, value, state, reason in cases:
            with self.subTest(kind=kind, value=value):
                items = sc.classify_defender(_defender(**{kind: [value]}), ENV)
                found = [(i['state'], i['reason']) for i in items if i['reason'] != sc.REASON_RT_ON]
                self.assertEqual(found, [(state, reason)])
                text = self._text({'defender': items, 'errors': []})
                expected = {sc.STATE_SUSPECT: 'suspeito 1', sc.STATE_ATTENTION: 'atenção 1'}[state]
                self.assertIn(expected, text)
                self.assertNotIn(sc.REASON_TEXTS[sc.REASON_EXCL_HIDDEN], text)
        # Texto estranho que dá "suspeito" continua "suspeito", só sem aparecer.
        items = sc.classify_defender(_defender(exts=['**.exe']), ENV)
        self.assertNotIn('**.exe', self._text({'defender': items, 'errors': []}))
        forged = {'defender': [{'source': 'defender', 'kind': 'extension', 'path': '**.exe',
                                'state': sc.STATE_OK, 'reason': sc.REASON_EXCL_OTHER}], 'errors': []}
        text = self._text(forged)
        self.assertIn('RESUMO: OK 0 · atenção 0 · suspeito 1', text)
        self.assertNotIn('**.exe', text)

    def test_valid_values_still_shown(self):
        for kind, value in (('paths', 'D:\\Jogos'), ('paths', 'D:'), ('paths', '%APPDATA%'),
                            ('procs', 'steam.exe'), ('procs', 'C:\\Program Files\\Jogo\\jogo.exe'),
                            ('exts', 'iso'), ('exts', '*.vhdx')):
            with self.subTest(kind=kind, value=value):
                found = self._exclusions(kind, value)
                self.assertNotIn(found[0][1], (sc.REASON_EXCL_HIDDEN, sc.REASON_EXCL_UNKNOWN))


def _idle(cpu=(3, 4, 5), gpu=(1, 2), top=('chrome', 'explorer', 'svchost')):
    return {'Cpu': list(cpu) if cpu is not None else None, 'Gpu': list(gpu) if gpu is not None else None,
            'Top': list(top) if top is not None else None}


class IdleUsageSlice4Tests(unittest.TestCase):
    """P3-07 fatia 4: uso de CPU e GPU com o PC parado, só dados simulados e ``ps`` falso."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _states(self, data):
        idle = sc.classify_idle(data, ENV)
        return [(i['kind'], i['state'], i['reason']) for i in idle['items']]

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_query_is_read_only_two_minutes_and_names_only(self):
        query = sc.IDLE_QUERY
        # Classes CIM: os nomes não mudam com o idioma do Windows (o Get-Counter muda).
        self.assertNotIn('Get-Counter', query)
        self.assertIn("Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter $q", query)
        self.assertIn("$q=\"Name='_Total'\"", query)
        self.assertIn('PercentProcessorTime', query)
        self.assertIn('Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine', query)
        self.assertIn('UtilizationPercentage', query)
        self.assertIn('Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Property Name,PercentProcessorTime',
                      query)
        self.assertIn('$id -gt 0 -and $id -ne $PID', query)
        self.assertIn('$i -lt 24', query)
        self.assertIn('Start-Sleep 5', query)
        self.assertEqual(sc.IDLE_SAMPLES * sc.IDLE_INTERVAL, sc.IDLE_SECONDS)
        self.assertIn('-Compress', query)
        self.assertNotIn('Get-Process', query)
        for word in ('CommandLine', 'ExecutablePath', 'Stop-Process', 'Remove-', 'Set-', 'RunAs', 'Path',
                     'Win32_Process', 'Disable', 'Start-Process', 'Invoke-'):
            self.assertNotIn(word, query)
        self.assertEqual(sc.IDLE_SECONDS, 120)
        self.assertGreater(sc.IDLE_TIMEOUT, 120)

    def test_low_usage_is_ok(self):
        self.assertEqual(self._states(_idle()), [('cpu', sc.STATE_OK, sc.REASON_IDLE_OK),
                                                 ('gpu', sc.STATE_OK, sc.REASON_IDLE_OK)])

    def test_high_cpu_or_gpu_is_attention_never_suspect(self):
        for data, expected in ((_idle(cpu=(30, 20, 25)), ('cpu', 'gpu')),
                               (_idle(cpu=(25,)), ('cpu',)),
                               (_idle(gpu=(24.6, 25.4)), ('gpu',)),
                               (_idle(cpu=(99, 100), gpu=(80,)), ('cpu', 'gpu'))):
            with self.subTest(data=data):
                states = self._states(data)
                for kind, state, reason in states:
                    self.assertNotEqual(state, sc.STATE_SUSPECT)
                    if kind in expected and reason == sc.REASON_IDLE_HIGH:
                        self.assertEqual(state, sc.STATE_ATTENTION)
                high = [k for k, s, r in states if r == sc.REASON_IDLE_HIGH]
                self.assertTrue(high)
                self.assertTrue(set(high) <= set(expected))
        self.assertEqual(self._states(_idle(cpu=(24.4,)))[0], ('cpu', sc.STATE_OK, sc.REASON_IDLE_OK))
        # Arredondado como é mostrado: 24,6% aparece como 25% e já é "atenção" (o mais grave).
        self.assertEqual(self._states(_idle(cpu=(24.6,)))[0], ('cpu', sc.STATE_ATTENTION, sc.REASON_IDLE_HIGH))
        text = sc.REASON_TEXTS[sc.REASON_IDLE_HIGH]
        self.assertIn('uso alto com o pc parado', text.lower())
        self.assertIn('atualização do Windows', text)
        self.assertIn('minerador', text)

    def test_gpu_samples_are_summed(self):
        data = _idle(cpu=(1,), gpu=([10, 10, 6], [10, 10, 6]))
        idle = sc.classify_idle(data, ENV)
        gpu = [i for i in idle['items'] if i['kind'] == 'gpu'][0]
        self.assertEqual(gpu['value'], 26)
        self.assertEqual(gpu['state'], sc.STATE_ATTENTION)

    def test_missing_or_unreadable_is_attention_cannot_measure(self):
        for data in (None, 'x', 7, [], {}, _idle(cpu=None, gpu=None), _idle(cpu=[], gpu=[]),
                     _idle(cpu=('a', True, None, float('nan'), -5)), {'Cpu': 'texto', 'Gpu': {'a': 1}}):
            with self.subTest(data=data):
                states = self._states(data)
                cpu = [s for s in states if s[0] == 'cpu'][0]
                self.assertEqual(cpu[1:], (sc.STATE_ATTENTION, sc.REASON_IDLE_UNKNOWN))
                self.assertNotIn(sc.STATE_OK, [s[1] for s in states if s[0] == 'cpu'])
        gpu = self._states(_idle(gpu=None))
        self.assertEqual(gpu[1], ('gpu', sc.STATE_ATTENTION, sc.REASON_IDLE_UNKNOWN))
        self.assertEqual(gpu[0], ('cpu', sc.STATE_OK, sc.REASON_IDLE_OK))
        self.assertIn('não foi possível medir', sc.REASON_TEXTS[sc.REASON_IDLE_UNKNOWN].lower())

    def test_top_processes_cited_only_when_high_and_cleaned(self):
        top = ('Fulano Silva-miner', 'chrome\x07', '', None, 'a', 'b')
        idle = sc.classify_idle(_idle(cpu=(80,), top=top), ENV)
        self.assertLessEqual(len(idle['top']), 3)
        text = self._text({'idle': idle})
        self.assertIn('%USERNAME%-miner', text)
        self.assertNotIn('Fulano', text)
        self.assertNotIn('\x07', text)
        self.assertIn('Programas que mais usaram o processador:', text)
        calm = self._text({'idle': sc.classify_idle(_idle(), ENV)})
        self.assertNotIn('Programas que mais usaram o processador:', calm)

    def test_values_shown_rounded_percent(self):
        idle = sc.classify_idle(_idle(cpu=(10.2, 10.4), gpu=(30.55, 30.61)), ENV)
        text = self._text({'idle': idle})
        self.assertIn('[OK] Processador (CPU): média de 10%', text)
        self.assertIn('[atenção] Placa de vídeo (GPU): média de 31%', text)
        unknown = self._text({'idle': sc.classify_idle(_idle(gpu=None), ENV)})
        self.assertIn('[atenção] Placa de vídeo (GPU): sem dado', unknown)

    def test_idle_only_window_text(self):
        text = self._text({'idle': sc.classify_idle(_idle(), ENV)})
        self.assertIn('USO COM O PC PARADO', text)
        self.assertIn(sc.IDLE_NOTE, text)
        self.assertEqual(sc.IDLE_NOTE, 'A medição só vale se você não usou o PC durante os 2 minutos.')
        self.assertIn(sc.NEVER_CHANGES, text)
        self.assertNotIn('PROCESSOS EM EXECUÇÃO', text)
        self.assertNotIn('MICROSOFT DEFENDER', text)
        self.assertIn('RESUMO: OK 2 · atenção 0 · suspeito 0', text)
        self.assertNotIn(sc.RECOMMENDATION, text)
        self.assertIn(sc.IDLE_ONLY_NOTE, text)
        self.assertNotIn(sc.NOT_ALL_CHECKED, text)

    def test_recommendation_when_idle_attention(self):
        for data in (_idle(cpu=(50,)), None):
            with self.subTest(data=data):
                text = self._text({'idle': sc.classify_idle(data, ENV)})
                self.assertIn(sc.RECOMMENDATION, text)
                self.assertIn(sc.NOT_CERTAIN, text)
                self.assertNotIn('[suspeito]', text)

    def test_idle_section_inside_full_checkup(self):
        full = sc.read_checkup(_fake_ps(), ENV)
        full['idle'] = sc.classify_idle(_idle(cpu=(40,)), ENV)
        text = self._text(full)
        self.assertLess(text.index('CONEXÕES DE REDE'), text.index('USO COM O PC PARADO'))
        self.assertLess(text.index('USO COM O PC PARADO'), text.index('RESUMO'))
        self.assertIn(sc.RECOMMENDATION, text)
        # Sem a medição, a seção diz como medir e não conta no RESUMO.
        plain = self._text(sc.read_checkup(_fake_ps(), ENV))
        self.assertIn(sc.IDLE_NOT_MEASURED, plain)

    def test_forged_items_reclassified_on_screen(self):
        forged = {'idle': {'items': [{'kind': 'cpu', 'value': 90, 'state': sc.STATE_OK, 'reason': sc.REASON_IDLE_OK},
                                     {'kind': 'gpu', 'value': 'x', 'state': sc.STATE_OK, 'reason': 'texto livre'},
                                     {'kind': 'cpu', 'value': 3, 'state': sc.STATE_SUSPECT,
                                      'reason': sc.REASON_IDLE_HIGH}],
                           'top': ['a']}}
        text = self._text(forged)
        self.assertNotIn('texto livre', text)
        self.assertNotIn('[OK]', text)
        self.assertNotIn('[suspeito]', text)
        self.assertIn('RESUMO: OK 0 · atenção 3 · suspeito 0', text)

    def test_stored_high_with_low_value_does_not_say_high(self):
        # Revisão da PR #197: o texto vem do número; o estado continua o mais grave.
        forged = {'idle': {'items': [{'kind': 'cpu', 'value': 5, 'state': sc.STATE_ATTENTION,
                                      'reason': sc.REASON_IDLE_HIGH}], 'top': ['a']}}
        text = self._text(forged)
        self.assertIn('[atenção] Processador (CPU): média de 5%', text)
        self.assertNotIn(sc.REASON_TEXTS[sc.REASON_IDLE_HIGH], text)
        self.assertNotIn(sc.IDLE_TOP_TEXT, text)

    def test_gpu_uses_busiest_engine_type_and_own_process_by_pid(self):
        query = sc.IDLE_QUERY
        self.assertIn('engtype_', query)
        self.assertIn('-Property Name,UtilizationPercentage', query)
        # Revisão 2 da PR #197 (R-45, R-53): só o processo da própria medição sai, pelo PID.
        self.assertIn('-Property Name,IDProcess,PercentProcessorTime', query)
        # FIX-P3-07-05: o "Ocioso" (PID 0) e a linha _Total (sem PID) também saem pelo PID.
        self.assertIn('$id -ne $PID', query)
        for name in ('wmiprvse', 'powershell', 'pwsh', 'idle'):
            self.assertNotIn("'" + name + "'", query.lower())
        top = ('powershell', 'WmiPrvSE', 'pwsh.exe', '_Total', 'Idle', 'mina')
        idle = sc.classify_idle(_idle(cpu=(80,), top=top), ENV)
        self.assertEqual(idle['top'], ['powershell', 'WmiPrvSE', 'pwsh.exe'])
        text = self._text({'idle': idle})
        self.assertIn(sc.IDLE_TOP_TEXT + 'powershell, WmiPrvSE, pwsh.exe.', text)
        self.assertIn(sc.IDLE_COST_NOTE, text)

    def test_all_zero_cpu_cannot_measure(self):
        for cpu in ((0,) * 24, (0.0, 0), ()):
            with self.subTest(cpu=cpu):
                self.assertEqual(self._states(_idle(cpu=cpu))[0],
                                 ('cpu', sc.STATE_ATTENTION, sc.REASON_IDLE_UNKNOWN))
        self.assertEqual(self._states(_idle(cpu=(0, 0, 1)))[0], ('cpu', sc.STATE_OK, sc.REASON_IDLE_OK))

    def test_stored_state_more_severe_is_kept(self):
        forged = {'idle': {'items': [{'kind': 'cpu', 'value': 5, 'state': sc.STATE_ATTENTION,
                                      'reason': sc.REASON_IDLE_OK},
                                     {'kind': 'gpu', 'value': 5, 'state': sc.STATE_SUSPECT,
                                      'reason': sc.REASON_IDLE_OK}], 'top': []}}
        text = self._text(forged)
        self.assertNotIn('[OK]', text)
        self.assertNotIn('[suspeito]', text)
        self.assertIn('RESUMO: OK 0 · atenção 2 · suspeito 0', text)

    def test_checkup_time_is_shown(self):
        full = dict(sc.read_checkup(_fake_ps(), ENV), checked_at='09:41')
        self.assertIn('Check-up feito às 09:41.', self._text(full))
        for bad in ('9:41', 'C:\\Users\\Fulano Silva', None, 941):
            with self.subTest(bad=bad):
                text = self._text(dict(full, checked_at=bad))
                self.assertNotIn('Check-up feito às', text)
                self.assertNotIn('Fulano', text)

    def test_measured_time_is_shown(self):
        idle = dict(sc.classify_idle(_idle(), ENV), measured_at='14:05')
        self.assertIn('Medido às 14:05.', self._text({'idle': idle}))
        full = sc.read_checkup(_fake_ps(), ENV)
        full['idle'] = idle
        self.assertIn('Medido às 14:05.', self._text(full))
        for bad in ('25:99x', 'C:\\Users\\Fulano Silva', 7, None):
            with self.subTest(bad=bad):
                text = self._text({'idle': dict(idle, measured_at=bad)})
                self.assertNotIn('Medido às', text)
                self.assertNotIn('Fulano', text)

    def test_read_idle_uses_fake_ps_and_never_raises(self):
        calls = []

        def ps(code):
            calls.append(code)
            return _idle(cpu=(12, 14))
        idle = sc.read_idle(ps, ENV)
        self.assertEqual(calls, [sc.IDLE_QUERY])
        self.assertEqual(idle['items'][0]['value'], 13)

        def broken(code):
            raise RuntimeError('Acesso negado: C:\\Users\\Fulano Silva\\x')
        idle = sc.read_idle(broken, ENV)
        self.assertEqual([i['reason'] for i in idle['items']], [sc.REASON_IDLE_UNKNOWN, sc.REASON_IDLE_UNKNOWN])
        self.assertNotIn('Fulano', repr(idle))

    def test_confirmation_text(self):
        text = sc.IDLE_CONFIRMATION
        self.assertIn('2 minutos', text)
        self.assertIn('só', text)
        self.assertIn('não use o PC', text)
        self.assertNotIn('vírus', text.lower())

    def test_no_forbidden_words(self):
        for data in (_idle(cpu=(90,)), None, _idle()):
            for line in sc.checkup_lines({'idle': sc.classify_idle(data, ENV)}, ENV):
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word, line.lower())



class IdleRevisions197Fix0705Tests(unittest.TestCase):
    """FIX-P3-07-05: "Ocioso" pelo PID, item que falta = "sem dado", nota em linguagem simples."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _text(self, result):
        return '\n'.join(sc.checkup_lines(result, ENV))

    def test_query_skips_idle_and_total_by_pid_not_by_name(self):
        query = sc.IDLE_QUERY
        # O "Ocioso" do Windows tem PID 0 e a linha _Total não tem PID de processo:
        # só passa um IDProcess numérico maior que 0 e diferente do PID da medição.
        self.assertIn('[long]::TryParse([string]$p.IDProcess,[ref]$id)', query)
        self.assertIn('$id -gt 0', query)
        self.assertIn('$id -ne $PID', query)
        self.assertNotIn('$skip', query)
        self.assertNotIn("'idle'", query.lower())
        self.assertNotIn("'_total')", query.lower())
        self.assertFalse(hasattr(sc, 'IDLE_SELF_PROCESSES'))

    def test_program_named_idle_is_listed(self):
        for top in (('Idle', 'chrome'), ('Idle.exe', 'chrome'), ('_Total', 'idle')):
            with self.subTest(top=top):
                idle = sc.classify_idle(_idle(cpu=(80,), top=top), ENV)
                self.assertEqual(idle['top'], list(top))
                text = self._text({'idle': idle})
                self.assertIn(sc.IDLE_TOP_TEXT + ', '.join(top) + '.', text)

    def test_stored_result_missing_gpu_shows_no_data(self):
        stored = {'idle': {'items': [{'kind': 'cpu', 'value': 3, 'state': sc.STATE_OK,
                                      'reason': sc.REASON_IDLE_OK}], 'top': []}}
        text = self._text(stored)
        self.assertIn('[OK] Processador (CPU): média de 3%', text)
        self.assertIn('[atenção] Placa de vídeo (GPU): sem dado', text)
        self.assertIn(sc.REASON_TEXTS[sc.REASON_IDLE_UNKNOWN], text)
        self.assertIn('RESUMO: OK 1 · atenção 1 · suspeito 0', text)
        self.assertIn(sc.RECOMMENDATION, text)

    def test_stored_result_missing_cpu_shows_no_data(self):
        stored = {'idle': {'items': [{'kind': 'gpu', 'value': 2, 'state': sc.STATE_OK,
                                      'reason': sc.REASON_IDLE_OK}], 'top': []}}
        text = self._text(stored)
        self.assertIn('[atenção] Processador (CPU): sem dado', text)
        self.assertIn('[OK] Placa de vídeo (GPU): média de 2%', text)
        self.assertIn('RESUMO: OK 1 · atenção 1 · suspeito 0', text)

    def test_missing_item_inside_full_checkup(self):
        full = sc.read_checkup(_fake_ps(), ENV)
        full['idle'] = {'items': [{'kind': 'cpu', 'value': 3, 'state': sc.STATE_OK,
                                   'reason': sc.REASON_IDLE_OK}], 'top': []}
        text = self._text(full)
        self.assertIn('[atenção] Placa de vídeo (GPU): sem dado', text)

    def test_cost_note_is_plain_language(self):
        note = sc.IDLE_COST_NOTE
        self.assertEqual(note, 'A própria medição usa um pouco do processador; por isso o uso pode '
                               'aparecer um pouco acima do normal.')
        for word in ('WMI', 'WmiPrvSE', 'PowerShell', 'serviço'):
            self.assertNotIn(word, note)
        self.assertIn(note, self._text({'idle': sc.classify_idle(_idle(), ENV)}))


class IdleUnhashableKindPr199Tests(unittest.TestCase):
    """Revisão da PR #199 (R-32): 'kind' que não serve de chave num resultado guardado não quebra."""

    def setUp(self):
        for name in ('run', 'Popen', 'check_output', 'call'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_list_or_dict_kind_shows_as_measure(self):
        for kind in (['cpu'], {'cpu': 1}, {'x'}):
            with self.subTest(kind=kind):
                stored = {'idle': {'items': [{'kind': kind, 'value': 3, 'state': sc.STATE_OK,
                                              'reason': sc.REASON_IDLE_OK}], 'top': []}}
                text = '\n'.join(sc.checkup_lines(stored, ENV))
                self.assertIn('[OK] Medição: média de 3%', text)
                # CPU e GPU continuam aparecendo como "sem dado" (nunca somem).
                self.assertIn('[atenção] Processador (CPU): sem dado', text)
                self.assertIn('[atenção] Placa de vídeo (GPU): sem dado', text)


if __name__ == '__main__':
    unittest.main()
