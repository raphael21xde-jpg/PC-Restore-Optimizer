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

    def test_unquoted_with_spaces_until_exe(self):
        cmd = r'C:\Program Files (x86)\Outro App\run.exe -background SEGREDO'
        self.assertEqual(sc.executable_from_command(cmd), r'C:\Program Files (x86)\Outro App\run.exe')

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
        self.assertEqual(items[2]['reason'], sc.REASON_SHORTCUT)
        self.assertEqual(items[3]['reason'], sc.REASON_SCRIPT)

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


def _fake_ps(run=None, startup=None, procs=None, fail=()):
    calls = []

    def ps(code, timeout=22):
        calls.append(code)
        if 'Win32_Process' in code:
            kind = 'processes'
        elif 'GetFolderPath' in code:
            kind = 'startup'
        else:
            kind = 'run'
        if kind in fail:
            raise RuntimeError(r'Acesso negado: C:\Users\Fulano Silva\NTUSER.DAT')
        return {'run': run, 'startup': startup, 'processes': procs}[kind]
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
        self.assertEqual(len(ps.calls), 3)
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
        self.assertIn(sc.ALL_CLEAR, clean)
        self.assertNotIn(sc.RECOMMENDATION, clean)
        procs_unchecked = procs + [{'Name': 'System', 'ExecutablePath': None}]
        partial = self._text(sc.read_checkup(_fake_ps(run, None, procs_unchecked), ENV))
        self.assertNotIn(sc.ALL_CLEAR, partial)
        self.assertIn('não puderam ser conferidos', partial)

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
        self.assertEqual(ps.call_count, 3)


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


if __name__ == '__main__':
    unittest.main()
