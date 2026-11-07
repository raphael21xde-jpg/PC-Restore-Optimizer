"""FIX-M3-T6: tarefas de rotina da Microsoft resumidas numa linha no check-up.

Só dados sintéticos: nenhuma tarefa, registro, PowerShell ou WMI de verdade.
Os testes de tela com Tk real pulam sem Tk (ou sem tela); os de ``show_checkup``
e ``save_checkup_full`` com Tk e diálogo falsos (lidos com ``ast``) rodam sempre,
e o arquivo salvo fica numa ``TemporaryDirectory``.
"""
import ast
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import atomic_write  # noqa: E402
import security_checkup as sc  # noqa: E402

try:
    import tkinter as tk
    import optimization_engine as oe
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de Tk real pulam.
    tk = ou = oe = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

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
BUTTON = 'Salvar check-up completo (.txt)'


def _task(path, name, execute='', com=False):
    return {'TaskPath': path, 'TaskName': name, 'Execute': execute, 'Com': com}


def _routine_rows(count):
    """Tarefas sintéticas comuns do Windows: metade rundll32, metade componente (COM)."""
    rows = []
    for n in range(count):
        if n % 2:
            rows.append(_task(f'\\Microsoft\\Windows\\Pasta{n}\\', f'Rotina{n}', '', com=True))
        else:
            rows.append(_task(f'\\Microsoft\\Windows\\Pasta{n}\\', f'Rotina{n}',
                              '%windir%\\system32\\rundll32.exe'))
    return rows


def _result(rows):
    return {'tasks': sc.classify_tasks(rows, ENV), 'processes': [], 'errors': []}


def _lines(result, full=False):
    return sc.checkup_lines(result, ENV, full=full)


def _tasks_section(lines):
    start = lines.index('TAREFAS AGENDADAS')
    end = lines.index('', start)
    return lines[start + 1:end]


class SummaryTests(unittest.TestCase):
    def test_150_routine_tasks_become_one_line(self):
        result = _result(_routine_rows(150))
        self.assertEqual(len(result['tasks']), 150)
        lines = _lines(result)
        section = _tasks_section(lines)
        flagged = [line for line in section if line.startswith('  [')]
        self.assertEqual(flagged, [f'  [atenção] {sc.MS_TASKS_SUMMARY.format(count=150)} — tarefa agendada'])
        self.assertIn('150', flagged[0])
        self.assertIn('      Motivo: ' + sc.MS_TASKS_REASON, section)
        self.assertIn('      O que fazer: ' + sc.MS_TASKS_FULL_HINT, section)
        text = '\n'.join(lines)
        self.assertNotIn('Rotina', text)
        self.assertNotIn('Pasta', text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 0', text)
        self.assertIn(sc.MS_TASKS_RESUMO.format(count=150), lines)
        self.assertNotIn(sc.TASKS_EMPTY, text)
        self.assertIn(sc.TASKS_NOTE.join(('  ', '')), section)

    def test_singular(self):
        lines = _lines(_result(_routine_rows(1)))
        self.assertIn(f'  [atenção] {sc.MS_TASKS_SUMMARY_ONE} — tarefa agendada', lines)
        self.assertIn(sc.MS_TASKS_RESUMO_ONE, lines)
        self.assertTrue(sc.MS_TASKS_SUMMARY_ONE.startswith('1 tarefa da Microsoft'))
        self.assertTrue(sc.MS_TASKS_RESUMO_ONE.startswith('1 tarefa da Microsoft resumida numa linha'))
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 0', '\n'.join(lines))

    def test_resumo_line_text(self):
        self.assertTrue(sc.MS_TASKS_RESUMO.format(count=3).startswith(
            '3 tarefas da Microsoft resumidas numa linha'))

    def test_folder_is_case_insensitive(self):
        rows = [_task('\\MICROSOFT\\WINDOWS\\A\\', 'B', r'C:\WINDOWS\System32\RUNDLL32.EXE'),
                _task('\\microsoft\\windows\\c\\', 'D', '', com=True)]
        lines = _lines(_result(rows))
        self.assertIn(f'  [atenção] {sc.MS_TASKS_SUMMARY.format(count=2)} — tarefa agendada', lines)

    def test_summary_after_flagged_and_before_ok(self):
        rows = _routine_rows(3) + [
            _task('\\Microsoft\\Windows\\X\\', 'Falso', r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe'),
            _task('\\', 'Outra', r'C:\Windows\System32\rundll32.exe'),
            _task('\\Microsoft\\Office\\', 'Office', '"C:\\Program Files\\Microsoft Office\\office.exe"')]
        flagged = [line for line in _tasks_section(_lines(_result(rows))) if line.startswith('  [')]
        self.assertEqual(len(flagged), 4)
        self.assertTrue(flagged[0].startswith('  [suspeito] \\Microsoft\\Windows\\X\\Falso'))
        self.assertTrue(flagged[1].startswith('  [atenção] \\Outra'))
        self.assertIn(sc.MS_TASKS_SUMMARY.format(count=3), flagged[2])
        self.assertTrue(flagged[3].startswith('  [OK] \\Microsoft\\Office\\Office'))
        self.assertIn('RESUMO: OK 1 · atenção 2 · suspeito 1', '\n'.join(_lines(_result(rows))))

    def test_hint_cites_exact_button_label_and_window(self):
        self.assertEqual(sc.CHECKUP_SAVE_FULL_BUTTON, BUTTON)
        self.assertIn(f'"{BUTTON}"', sc.MS_TASKS_FULL_HINT)
        self.assertIn('janela do check-up', sc.MS_TASKS_FULL_HINT)

    def test_texts_are_simple_and_never_say_remove(self):
        for text in (sc.MS_TASKS_SUMMARY, sc.MS_TASKS_SUMMARY_ONE, sc.MS_TASKS_REASON, sc.MS_TASKS_FULL_HINT,
                     sc.MS_TASKS_RESUMO, sc.MS_TASKS_RESUMO_ONE, sc.CHECKUP_FULL_HEADER):
            for word in ('vírus', 'remover', 'apagar', 'quarentena', 'ms_', 'routine'):
                self.assertNotIn(word, text.lower())

    def test_user_name_never_appears(self):
        rows = [_task('\\Microsoft\\Windows\\Fulano Silva\\', 'Tarefa', r'C:\Windows\System32\rundll32.exe'),
                _task('\\Microsoft\\Windows\\B\\', 'Fulano Silva', '', com=True)]
        for full in (False, True):
            with self.subTest(full=full):
                self.assertNotIn('Fulano', '\n'.join(_lines(_result(rows), full=full)))

    def test_decision_is_not_stored_in_result(self):
        result = _result(_routine_rows(4))
        before = repr(result)
        _lines(result)
        _lines(result, full=True)
        self.assertEqual(repr(result), before)
        for item in result['tasks']:
            self.assertEqual(set(item), {'source', 'name', 'path', 'state', 'reason', 'count'})


class NeverSummarizedTests(unittest.TestCase):
    """R-77: o que não é rotina reconferida aparece numa linha por item, como antes."""

    CASES = {
        'suspeito (nome do Windows fora da pasta)':
            _task('\\Microsoft\\Windows\\A\\', 'Caso', r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe'),
        'interpretador': _task('\\Microsoft\\Windows\\A\\', 'Caso', r'C:\Windows\System32\wsl.exe'),
        'nome incerto (8.3)': _task('\\Microsoft\\Windows\\A\\', 'Caso', r'C:\Windows\System32\RUNDLL~1.EXE'),
        'nome incerto (espaço no fim)': _task('\\Microsoft\\Windows\\A\\', 'Caso',
                                              '"C:\\Windows\\System32\\conhost.exe "'),
        'script host que não é do Windows': _task('\\Microsoft\\Windows\\A\\', 'Caso',
                                                  r'C:\Windows\System32\cmd2.exe'),
        'fora da pasta do Windows': _task('\\Microsoft\\Windows\\A\\', 'Caso', r'D:\Ferramentas\a.exe'),
        'caminho incompleto': _task('\\Microsoft\\Windows\\A\\', 'Caso', 'rundll32.exe'),
        'caminho ilegível': _task('\\Microsoft\\Windows\\A\\', 'Caso', ''),
        'OK (Arquivos de Programas)': _task('\\Microsoft\\Windows\\A\\', 'Caso',
                                            '"C:\\Program Files\\Microsoft\\a.exe"'),
        'pasta \\Microsoft\\Office\\': _task('\\Microsoft\\Office\\', 'Caso', r'C:\Windows\System32\rundll32.exe'),
        'COM em \\Microsoft\\Office\\': _task('\\Microsoft\\Office\\', 'Caso', '', com=True),
        'pasta \\Microsoft\\WindowsX\\': _task('\\Microsoft\\WindowsX\\', 'Caso',
                                              r'C:\Windows\System32\rundll32.exe'),
        'fora de \\Microsoft\\': _task('\\', 'Caso', r'C:\Windows\System32\rundll32.exe'),
        'COM fora de \\Microsoft\\': _task('\\', 'Caso', '', com=True),
    }

    def test_each_case_keeps_its_own_line(self):
        for label, row in self.CASES.items():
            with self.subTest(caso=label):
                result = _result([row])
                self.assertEqual(len(result['tasks']), 1)
                self.assertFalse(sc._ms_windows_routine(result['tasks'][0], ENV))
                window = _lines(result)
                text = '\n'.join(window)
                self.assertNotIn('resumid', text)
                own = [line for line in _tasks_section(window) if line.startswith('  [')]
                self.assertEqual(len(own), 1)
                self.assertIn('Caso — tarefa agendada', own[0])
                # Sem resumo, a janela é igual à versão completa (fora o cabeçalho).
                full = _lines(result, full=True)
                self.assertEqual(full[1], sc.CHECKUP_FULL_HEADER)
                self.assertEqual(full[:1] + full[2:], window)

    def test_forged_items_are_not_summarized(self):
        base = {'source': 'task', 'name': '\\Microsoft\\Windows\\A\\B', 'state': sc.STATE_ATTENTION,
                'reason': sc.REASON_MS_WINDOWS_PROGRAM, 'count': 1}
        forged = {
            'Temp do usuário': dict(base, path=r'%USERPROFILE%\AppData\Local\Temp\rundll32.exe'),
            'AppData': dict(base, path=r'C:\Users\Fulano Silva\AppData\Roaming\rundll32.exe'),
            'Temp do Windows': dict(base, path=r'C:\Windows\Temp\rundll32.exe'),
            'Arquivos de Programas': dict(base, path=r'C:\Program Files\App\rundll32.exe'),
            'interpretador na pasta do Windows': dict(base, path=r'C:\Windows\System32\wsl.exe'),
            'script com nome de versão': dict(base, path=r'C:\Windows\System32\cmd2.exe'),
            'nome incerto': dict(base, path=r'C:\Windows\System32\rundll32'),
            'caminho vazio': dict(base, path=''),
            'caminho incompleto': dict(base, path='rundll32.exe'),
            'caminho que não é texto': dict(base, path=None),
            'COM com caminho': dict(base, reason=sc.REASON_MS_COM_HANDLER,
                                    path=r'C:\Windows\System32\rundll32.exe'),
            'suspeito guardado': dict(base, state=sc.STATE_SUSPECT, reason=sc.REASON_SYSTEM_NAME,
                                      path=r'C:\Windows\System32\rundll32.exe'),
            'outro motivo': dict(base, reason=sc.REASON_SCRIPT_HOST, path=r'C:\Windows\System32\rundll32.exe'),
            'outra origem': dict(base, source='run_user', path=r'C:\Windows\System32\rundll32.exe'),
            'nome fora da pasta': dict(base, name='\\Microsoft\\WindowsX\\B',
                                       path=r'C:\Windows\System32\rundll32.exe'),
            'nome só da pasta': dict(base, name='\\Microsoft\\Windows\\', path=r'C:\Windows\System32\rundll32.exe'),
            'nome sem a barra do começo': dict(base, name='Microsoft\\Windows\\A\\B',
                                               path=r'C:\Windows\System32\rundll32.exe'),
        }
        for label, item in forged.items():
            with self.subTest(caso=label):
                self.assertFalse(sc._ms_windows_routine(item, ENV))
                text = '\n'.join(_lines({'tasks': [item], 'errors': []}))
                self.assertNotIn('resumid', text)
                self.assertRegex(text, r'\[(atenção|suspeito)\] ')

    def test_genuine_stored_items_are_summarized(self):
        base = {'source': 'task', 'name': '\\Microsoft\\Windows\\A\\B', 'state': sc.STATE_ATTENTION, 'count': 1}
        self.assertTrue(sc._ms_windows_routine(dict(base, reason=sc.REASON_MS_WINDOWS_PROGRAM,
                                                    path=r'%windir%\system32\rundll32.exe'), ENV))
        self.assertTrue(sc._ms_windows_routine(dict(base, reason=sc.REASON_MS_WINDOWS_PROGRAM,
                                                    path=r'C:\Windows\SysWOW64\RUNDLL32.EXE'), ENV))
        self.assertEqual(sc.MS_SUMMARY_PROGRAMS, ('rundll32.exe',))
        self.assertTrue(sc._ms_windows_routine(dict(base, reason=sc.REASON_MS_COM_HANDLER, path=''), ENV))

    def test_only_exact_rundll32_in_system32_or_syswow64(self):
        """R-45/R-46/R-78: programa da pasta do Windows que não é o rundll32 direto em
        System32/SysWOW64 continua numa linha própria (tarefa lida e item guardado)."""
        paths = ['C:\\Windows\\System32\\' + exe for exe in (
            'powershell.exe', 'pwsh.exe', 'cmd.exe', 'mshta.exe', 'wscript.exe', 'cscript.exe', 'regsvr32.exe',
            'forfiles.exe', 'msiexec.exe', 'certutil.exe', 'schtasks.exe', 'svchost.exe', 'conhost.exe',
            'zzupdater.exe')] + [
            r'C:\Windows\SysWOW64\bitsadmin.exe', r'C:\Windows\SysWOW64\regsvr32.exe',
            r'C:\Windows\rundll32.exe', r'C:\Windows\evil.exe', r'C:\Windows\Tasks\x.exe',
            r'C:\Windows\Tasks\rundll32.exe', r'C:\Windows\Tracing\rundll32.exe',
            r'C:\Windows\System32\spool\drivers\color\x.exe',
            r'C:\Windows\System32\spool\drivers\color\rundll32.exe',
            r'C:\Windows\System32\Tasks\x.exe', r'C:\Windows\System32\Tasks\rundll32.exe',
            r'C:\Windows\System32\sub\rundll32.exe', r'C:\Windows\SysWOW64\sub\rundll32.exe',
            r'C:\Windows\System32\rundll32x.exe', r'C:\Windows\System32\rundll32.exe.exe',
            r'C:\Windows\System32\rundll64.exe']
        for path in paths:
            with self.subTest(path=path):
                row = _task('\\Microsoft\\Windows\\A\\', 'Caso', path)
                result = _result([row])
                for item in result['tasks']:
                    self.assertFalse(sc._ms_windows_routine(item, ENV))
                text = '\n'.join(_lines(result))
                self.assertNotIn('resumid', text)
                self.assertIn('Caso — tarefa agendada', text)
                forged = {'source': 'task', 'name': '\\Microsoft\\Windows\\A\\B', 'state': sc.STATE_ATTENTION,
                          'reason': sc.REASON_MS_WINDOWS_PROGRAM, 'path': path, 'count': 1}
                self.assertFalse(sc._ms_windows_routine(forged, ENV))
                self.assertNotIn('resumid', '\n'.join(_lines({'tasks': [forged], 'errors': []})))

    def test_reason_only_says_what_is_checked(self):
        # R-37: o texto cita só o que o código confere (rundll32 em System32/SysWOW64 ou componente).
        self.assertIn('rundll32', sc.MS_TASKS_REASON)
        self.assertIn('System32 ou SysWOW64', sc.MS_TASKS_REASON)
        self.assertIn('componente do Windows', sc.MS_TASKS_REASON)
        self.assertNotIn('como o rundll32', sc.MS_TASKS_REASON)

    def test_suspect_rules_unchanged_next_to_summary(self):
        rows = _routine_rows(10) + [
            _task('\\Microsoft\\Windows\\X\\', 'Falso', r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe')]
        text = '\n'.join(_lines(_result(rows)))
        self.assertIn('[suspeito] \\Microsoft\\Windows\\X\\Falso — tarefa agendada', text)
        self.assertIn(sc.REASON_TEXTS[sc.REASON_SYSTEM_NAME], text)
        self.assertIn('RESUMO: OK 0 · atenção 1 · suspeito 1', text)


class FullVersionTests(unittest.TestCase):
    def test_full_shows_every_task_like_before(self):
        rows = _routine_rows(150)
        result = _result(rows)
        full = _lines(result, full=True)
        self.assertEqual(full[0], 'CHECK-UP DE SEGURANÇA — SÓ LEITURA')
        self.assertEqual(full[1], sc.CHECKUP_FULL_HEADER)
        text = '\n'.join(full)
        for n in range(150):
            self.assertIn(f'  [atenção] \\Microsoft\\Windows\\Pasta{n}\\Rotina{n} — tarefa agendada', full)
        self.assertEqual(text.count(sc.REASON_TEXTS[sc.REASON_MS_COM_HANDLER]), 75)
        self.assertEqual(text.count(sc.REASON_TEXTS[sc.REASON_MS_WINDOWS_PROGRAM]), 75)
        self.assertIn('RESUMO: OK 0 · atenção 150 · suspeito 0', text)
        self.assertNotIn('resumid', text)
        self.assertNotIn(sc.MS_TASKS_FULL_HINT, text)

    def test_full_header_also_in_idle_only(self):
        idle = sc.classify_idle({'Cpu': [5], 'Gpu': [1], 'Top': []}, ENV)
        window = sc.checkup_lines({'idle': idle}, ENV)
        full = sc.checkup_lines({'idle': idle}, ENV, full=True)
        self.assertEqual(full[1], sc.CHECKUP_FULL_HEADER)
        self.assertEqual(full[:1] + full[2:], window)


# --- Tela -------------------------------------------------------------------------------

def _source_tree():
    return ast.parse((ROOT / 'optimization_ui.py').read_text(encoding='utf-8'))


def _function(name):
    return next(n for n in ast.walk(_source_tree()) if isinstance(n, ast.FunctionDef) and n.name == name)


def _constants(prefix):
    nodes = [n for n in _source_tree().body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id.startswith(prefix) for t in n.targets)]
    namespace = {'checkup_engine': sc}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'optimization_ui.py', 'exec'), namespace)
    return {k: v for k, v in namespace.items() if k.startswith(prefix)}


def _imported_from_engine(name):
    """O valor que optimization_ui importa de security_checkup (R-74: um texto só para o botão e a dica)."""
    for node in _source_tree().body:
        if isinstance(node, ast.ImportFrom) and node.module == 'security_checkup':
            if any(alias.name == name and alias.asname is None for alias in node.names):
                return getattr(sc, name)
    raise AssertionError(f'optimization_ui não importa {name} de security_checkup')


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def pack(self, *args, **kwargs):
        return None

    def configure(self, *args, **kwargs):
        return None

    def yview(self, *args):
        return None

    def set(self, *args):
        return None


class _FakeToplevel(_FakeWidget):
    def title(self, *args):
        return None

    def winfo_exists(self):
        return True

    def destroy(self):
        return None


class _FakeButton(_FakeWidget):
    created = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeButton.created.append(self)


class SaveWithoutTkTests(unittest.TestCase):
    """Executa ``show_checkup`` e ``save_checkup_full`` (lidos com ast) com Tk e diálogo falsos."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.texts = _constants('CHECKUP_SAVE')
        self.assertNotIn('CHECKUP_SAVE_FULL_BUTTON', self.texts)  # vem de security_checkup, não repetido
        self.texts['CHECKUP_SAVE_FULL_BUTTON'] = _imported_from_engine('CHECKUP_SAVE_FULL_BUTTON')
        self.answer = str(self.tmp / 'checkup.txt')
        self.dialog = []
        self.shown = []
        self.notes = []
        dialog = types.SimpleNamespace(asksaveasfilename=self._dialog)
        _FakeButton.created = []
        namespace = dict(self.texts, tk=types.SimpleNamespace(Toplevel=_FakeToplevel, Frame=_FakeWidget,
                                                              Text=_FakeWidget),
                         ttk=types.SimpleNamespace(Scrollbar=_FakeWidget, Button=_FakeButton),
                         BG='#000', PANEL='#111', TEXT='#fff', checkup_engine=sc, filedialog=dialog,
                         time=time, Path=Path, atomic_write_text=atomic_write.atomic_write_text)
        module = ast.Module(body=[_function('show_checkup'), _function('save_checkup_full')], type_ignores=[])
        exec(compile(module, 'optimization_ui.py', 'exec'), namespace)
        self.namespace = namespace
        self.panel = types.SimpleNamespace(
            _write=lambda widget, text: None, _show=lambda *a: self.shown.append(a),
            note=types.SimpleNamespace(set=self.notes.append))
        self.panel.save_checkup_full = lambda result: namespace['save_checkup_full'](self.panel, result)
        self.result = _result(_routine_rows(6) + [
            _task('\\Microsoft\\Windows\\X\\', 'Falso', r'C:\Users\Fulano Silva\AppData\Roaming\svchost.exe')])

    def _dialog(self, **kwargs):
        self.dialog.append(kwargs)
        return self.answer

    def test_button_label_is_exact_and_saves_full_version(self):
        self.assertEqual(self.texts['CHECKUP_SAVE_FULL_BUTTON'], BUTTON)
        self.namespace['show_checkup'](self.panel, self.result)
        buttons = [b for b in _FakeButton.created if b.kwargs.get('text') == BUTTON]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(len([b for b in _FakeButton.created if b.kwargs.get('text') == 'Fechar']), 1)
        buttons[0].kwargs['command']()
        saved = (self.tmp / 'checkup.txt').read_text(encoding='utf-8')
        self.assertEqual(saved, '\n'.join(sc.checkup_lines(self.result, full=True)) + '\n')
        self.assertIn('Rotina0', saved)
        self.assertIn(sc.CHECKUP_FULL_HEADER, saved)
        self.assertEqual(self.notes[-1], self.texts['CHECKUP_SAVED_TEXT'])
        self.assertEqual(self.shown, [])

    def test_dialog_suggests_name_and_txt(self):
        self.namespace['save_checkup_full'](self.panel, self.result)
        (kwargs,) = self.dialog
        self.assertEqual(kwargs['defaultextension'], '.txt')
        self.assertRegex(kwargs['initialfile'], r'^checkup-seguranca-\d{8}-\d{4}\.txt$')

    def test_cancel_writes_nothing(self):
        for answer in ('', ()):
            with self.subTest(answer=answer):
                self.answer = answer
                self.assertIsNone(self.namespace['save_checkup_full'](self.panel, self.result))
                self.assertEqual(list(self.tmp.iterdir()), [])
                self.assertEqual(self.notes[-1], self.texts['CHECKUP_SAVE_CANCELLED_TEXT'])
                self.assertEqual(self.shown, [])

    def test_error_shows_only_generic_message(self):
        def broken(*args, **kwargs):
            raise OSError(r'C:\Users\Fulano Silva\Documentos\segredo: acesso negado')
        self.namespace['atomic_write_text'] = broken
        self.assertIsNone(self.namespace['save_checkup_full'](self.panel, self.result))
        self.assertEqual(self.shown, [('warning', self.texts['CHECKUP_SAVE_TITLE'],
                                       self.texts['CHECKUP_SAVE_FAILED_TEXT'])])
        for text in (self.texts['CHECKUP_SAVE_FAILED_TEXT'], self.notes[-1]):
            self.assertNotIn('Fulano', text)
            self.assertNotIn('segredo', text)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_save_handler_never_runs_commands(self):
        code = ast.unparse(_function('save_checkup_full'))
        for forbidden in ('subprocess', 'startfile', 'webbrowser', 'Remove-', 'unlink', 'rmtree', 'str(exc'):
            self.assertNotIn(forbidden, code)
        self.assertIn('full=True', code)


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class SaveButtonTkTests(unittest.TestCase):
    def setUp(self):
        for name in ('_run', '_ps'):
            patcher = mock.patch.object(oe, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.shown = []
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.panel = ou.OptimizationPanel(self.root, app_dir=self.tmp, state_dir=self.tmp,
                                          ask=lambda *a: False, show=lambda *a: self.shown.append(a))
        self.panel.pack()
        deadline = time.monotonic() + 5
        while self.panel.power_busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.result = _result(_routine_rows(4))

    def _button(self, window):
        from tkinter import ttk
        found = [w for w in window.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == BUTTON]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_button_saves_full_version(self):
        window = self.panel.show_checkup(self.result)
        target = self.tmp / 'saida' / 'checkup.txt'
        target.parent.mkdir()
        with mock.patch.object(ou.filedialog, 'asksaveasfilename', return_value=str(target)):
            self._button(window).invoke()
        expected = '\n'.join(sc.checkup_lines(dict(self.result), full=True)) + '\n'
        self.assertEqual(target.read_text(encoding='utf-8'), expected)
        self.assertEqual(self.shown, [])
        window.destroy()

    def test_cancel_writes_nothing(self):
        window = self.panel.show_checkup(self.result)
        before = sorted(self.tmp.rglob('*'))
        with mock.patch.object(ou.filedialog, 'asksaveasfilename', return_value=''):
            self._button(window).invoke()
        self.assertEqual(sorted(self.tmp.rglob('*')), before)
        self.assertEqual(self.panel.note.get(), ou.CHECKUP_SAVE_CANCELLED_TEXT)
        window.destroy()

    def test_error_shows_generic_message(self):
        window = self.panel.show_checkup(self.result)
        with mock.patch.object(ou.filedialog, 'asksaveasfilename', return_value=str(self.tmp / 'x.txt')), \
                mock.patch.object(ou, 'atomic_write_text', side_effect=OSError('C:\\Users\\Fulano\\x')):
            self._button(window).invoke()
        self.assertEqual(self.shown, [('warning', ou.CHECKUP_SAVE_TITLE, ou.CHECKUP_SAVE_FAILED_TEXT)])
        window.destroy()


if __name__ == '__main__':
    unittest.main()
