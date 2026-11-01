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


def _fake_ps(run=None, startup=None, procs=None, fail=(), tasks=None):
    calls = []

    def ps(code, timeout=22):
        calls.append(code)
        if 'Win32_Process' in code:
            kind = 'processes'
        elif 'Get-ScheduledTask' in code:
            kind = 'tasks'
        elif 'GetFolderPath' in code:
            kind = 'startup'
        else:
            kind = 'run'
        if kind in fail:
            raise RuntimeError(r'Acesso negado: C:\Users\Fulano Silva\NTUSER.DAT')
        return {'run': run, 'startup': startup, 'processes': procs, 'tasks': tasks}[kind]
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
        self.assertEqual(len(ps.calls), 4)
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
        self.assertNotIn(sc.ALL_CLEAR, text)
        self.assertEqual(len(result['errors']), 3)

    def test_ps_raising_on_non_windows_does_not_break(self):
        def ps(code, timeout=22):
            raise OSError('sem PowerShell')
        result = sc.read_checkup(ps, ENV)
        self.assertEqual(result['autostart'], [])
        self.assertNotIn(sc.ALL_CLEAR, self._text(result))

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
        self.assertNotIn(sc.ALL_CLEAR, clean)
        self.assertIn(sc.NOT_ALL_CHECKED, clean)
        self.assertNotIn(sc.RECOMMENDATION, clean)
        old = {'autostart': [], 'processes': [], 'unchecked': 0, 'errors': []}
        self.assertNotIn(sc.ALL_CLEAR, self._text(old))
        procs_unchecked = procs + [{'Name': 'System', 'ExecutablePath': None}]
        partial = self._text(sc.read_checkup(_fake_ps(run, None, procs_unchecked), ENV))
        self.assertNotIn(sc.ALL_CLEAR, partial)
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
        self.assertEqual(ps.call_count, 4)


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

    def test_user_name_only_whole_word(self):
        env = dict(ENV, USERNAME='Ana')
        self.assertEqual(sc.sanitize_path(r'D:\Ana\Banana\Anais_x.exe', env), r'D:\%USERNAME%\Banana\Anais_x.exe')
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
                self.assertIn('RESUMO: OK 2 · atenção 0 · suspeito 1', text)

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

    def test_microsoft_folder_in_system32_is_hidden(self):
        rows = [_task('\\Microsoft\\Windows\\Defrag\\', 'ScheduledDefrag', r'%windir%\system32\defrag.exe'),
                _task('\\Microsoft\\Windows\\X\\', 'Y', r'C:\Windows\System32\svchost.exe'),
                _task('\\Microsoft\\Office\\', 'Z', r'"C:\Program Files\Microsoft Office\root\a.exe"')]
        self.assertEqual(sc.classify_tasks(rows, ENV), [])
        result = sc.read_checkup(_fake_ps(tasks=rows), ENV)
        self.assertEqual(result['tasks'], [])
        text = self._text(result)
        self.assertNotIn('Defrag', text)
        self.assertIn(sc.TASKS_EMPTY, text)
        self.assertIn('RESUMO: OK 0 · atenção 0 · suspeito 0', text)

    def test_microsoft_folder_outside_windows_is_shown(self):
        item = self._one(_task('\\Microsoft\\Windows\\Defrag\\', 'ScheduledDefrag', r'%APPDATA%\defrag.exe'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_MS_FOLDER_OUTSIDE))
        item = self._one(_task('\\microsoft\\Windows\\X\\', 'Y', r'"C:\Users\Fulano Silva\AppData\svchost.exe"'))
        self.assertEqual((item['state'], item['reason']), (sc.STATE_SUSPECT, sc.REASON_MS_FOLDER_OUTSIDE))
        text = self._text({'tasks': [item], 'processes': [], 'errors': []})
        self.assertIn(sc.REASON_TEXTS[sc.REASON_MS_FOLDER_OUTSIDE], text)
        self.assertIn('[suspeito] \\microsoft\\Windows\\X\\Y — tarefa agendada', text)
        self.assertNotIn('Fulano', text)

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
        # COM na pasta da Microsoft não aparece.
        self.assertEqual(sc.classify_tasks([_task('\\Microsoft\\Windows\\A\\', 'B', '', com=True)], ENV), [])

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
        self.assertNotIn(sc.ALL_CLEAR, text)
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
        self.assertIn('RESUMO: OK 2 · atenção 1 · suspeito 0 · não conferidos 0', lines)
        self.assertIn(sc.RECOMMENDATION, lines)

    def test_ok_tasks_with_admin_note_use_neutral_phrase(self):
        tasks = [_task('\\', 'Boa', r'"C:\Program Files\Boa\boa.exe"')]
        procs = [{'Name': 'bom.exe', 'ExecutablePath': r'C:\Program Files\Bom\bom.exe'}]
        text = self._text(sc.read_checkup(_fake_ps(procs=procs, tasks=tasks), ENV))
        self.assertIn(sc.TASKS_NOTE, text)
        self.assertNotIn(sc.ALL_CLEAR, text)
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
                self.assertEqual((item['state'], item['reason']), (sc.STATE_ATTENTION, sc.REASON_SCRIPT_HOST))
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
        for words in ('Microsoft', 'pasta do Windows', 'programas instalados', 'scripts'):
            self.assertIn(words, sc.TASKS_EMPTY)

    def test_strange_rows_do_not_break(self):
        rows = [None, 5, 'x', {}, {'TaskPath': 7, 'TaskName': None, 'Execute': ['a'], 'Com': 'True'}]
        items = sc.classify_tasks(rows, ENV)
        for item in items:
            self.assertNotEqual(item['state'], sc.STATE_OK)
        self.assertEqual(sc.classify_tasks(None, ENV), [])
        self.assertEqual(sc.classify_tasks({'value': []}, ENV), [])
        self.assertIsInstance(self._text({'tasks': items, 'errors': []}), str)


if __name__ == '__main__':
    unittest.main()
