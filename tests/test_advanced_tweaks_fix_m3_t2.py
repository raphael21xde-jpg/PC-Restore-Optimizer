"""FIX-M3-T2: agendamento de GPU com o valor ``HwSchMode`` ausente (Windows 11).

Com a versão do Windows conferida (19041 ou mais) e a chave GraphicsDrivers
existente, o valor ausente quer dizer que o Windows usa o padrão do programa
da placa de vídeo (driver), que o app não lê. O estado é ``windows_default``: nunca "já
aplicado" (R-65), o app não cria o valor e o texto diz onde conferir.

Só registro falso em memória (``tests/fake_winreg.py``), ponto de restauração
falso e arquivos em TemporaryDirectory. Nenhum registro, PowerShell ou
subprocess de verdade. Sem Tk (ou sem tela) os testes de janela pulam.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402
import optimization_engine as oe  # noqa: E402
import safe_tweaks as st  # noqa: E402
import session_owner as so  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

try:
    import tkinter as tk
    import optimization_ui as ou
    from tk_helpers import track_tk_root
except ImportError:  # Python sem Tk: os testes de tela pulam.
    tk = ou = track_tk_root = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))

GRAPHICS = r'SYSTEM\CurrentControlSet\Control\GraphicsDrivers'
VERSION = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
HKLM = FakeWinreg.HKEY_LOCAL_MACHINE
DWORD = FakeWinreg.REG_DWORD
SZ = FakeWinreg.REG_SZ
KEY = 'gpu_hw_scheduling'
GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'
WRITES = ('SetValueEx', 'DeleteValue', 'CreateKeyEx', 'DeleteKey', 'DeleteKeyEx')


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.reg = FakeWinreg(hives=('HKLM',))
        self.machine = at.MachineDwordAdapter(registry=self.reg)
        self.user = at.AdvancedRegistryAdapter(registry=FakeWinreg())
        self.restore_calls = []

    def windows11_without_value(self):
        """Build 26300, chave GraphicsDrivers existe (com outro valor), sem HwSchMode."""
        self.reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.reg.put(GRAPHICS, 'OutroValor', 5, DWORD, hive=HKLM)

    def current(self):
        return self.reg.get(GRAPHICS, 'HwSchMode', hive=HKLM)

    def writes(self):
        return [c for c in self.reg.calls if c[0] in WRITES]

    def snapshot(self):
        return {path: dict(values) for path, values in self.reg.machine_keys.items()}

    def gpu_state(self):
        return at.state_for(at.read_states(self.user, self.machine), KEY)

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True


class AbsentValueTests(Base):
    def test_absent_value_is_windows_default_and_nothing_is_written(self):
        self.windows11_without_value()
        before = self.snapshot()
        self.assertEqual(self.gpu_state(), {'id': KEY, 'state': 'windows_default', 'changes': []})
        with self.assertRaises(at.WindowsDefaultError) as raised:
            self.machine.read(KEY)
        self.assertEqual(str(raised.exception), at.MSG_WINDOWS_DEFAULT)
        # Continua sendo um "o app não mexe" (subclasse da recusa neutra).
        self.assertTrue(issubclass(at.WindowsDefaultError, at.NotSupportedError))
        for call in (lambda: self.machine.apply(KEY, 2), lambda: self.machine.revert(KEY, 1)):
            with self.assertRaises(at.WindowsDefaultError):
                call()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.current())   # o app não cria o valor

    def test_state_line_uses_the_windows_default_text(self):
        self.windows11_without_value()
        text = '\n'.join(at.state_lines([self.gpu_state()]))
        self.assertIn('• Agendamento de GPU acelerado por hardware ligado: '
                      + at.STATE_TEXT['windows_default'], text)
        self.assertNotIn(at.STATE_TEXT['unsupported'], text)
        self.assertNotIn('já aplicado', text)


class TextTests(unittest.TestCase):
    def test_texts_say_where_to_check_and_never_say_turn_on(self):
        body = at.STATE_TEXT['windows_default']
        for text in (at.MSG_WINDOWS_DEFAULT, body):
            self.assertIn('"Configurações gráficas avançadas"', text)
            self.assertIn('(em versões anteriores, "Alterar configurações gráficas padrão")', text)
            self.assertIn('Configurações > Sistema > Tela > Elementos gráficos', text)
            self.assertIn('padrão do programa da placa de vídeo (driver)', text)
            self.assertIn('o app não consegue ler', text)
            self.assertIn('não mexe', text)
            lower = text.lower()
            for forbidden in ('ligue', 'ative', 'já aplicado', 'ligado.', 'não oferece',
                              'não reconheceu', '\\', 'hk', 'hwsch'):
                self.assertNotIn(forbidden, lower)
        self.assertTrue(at.MSG_WINDOWS_DEFAULT.endswith(' Nada foi alterado.'))
        self.assertNotIn('Nada foi alterado', body)
        self.assertTrue(body[0].islower())
        self.assertEqual(at.MSG_WINDOWS_DEFAULT, body[0].upper() + body[1:] + ' Nada foi alterado.')
        # O "o que muda" do ajuste usa o nome atual com o antigo entre parênteses.
        self.assertIn('"Configurações gráficas avançadas" (em versões anteriores, "Alterar '
                      'configurações gráficas padrão")', at.TWEAKS_BY_ID[KEY].what)

    def test_ui_message_for_windows_default(self):
        if ou is None:
            self.skipTest('sem Tk')
        self.assertEqual(ou.ADVANCED_WINDOWS_DEFAULT_TEXT, at.MSG_WINDOWS_DEFAULT)
        message = ou.OptimizationPanel._advanced_state_message
        self.assertEqual(message('windows_default'), ou.ADVANCED_WINDOWS_DEFAULT_TEXT)
        self.assertEqual(message('unsupported'), ou.ADVANCED_UNSUPPORTED_TEXT)

    def test_undo_all_confirm_text_mentions_the_skip(self):
        """FIX-M3-T2-02: a confirmação do "Desfazer tudo" cita a exceção do pulo."""
        if ou is None:
            self.skipTest('sem Tk')
        self.assertEqual(ou.CHANGES_CONFIRM_TEXT,
                         'Desfazer {n} alteração(ões) feitas pelo app?\n\n'
                         'O app desfaz da mais nova para a mais antiga; não cria ponto de '
                         'restauração; se uma não puder ser desfeita, o app para ali; só pula '
                         'um ajuste cujo valor foi apagado fora do app, que continua na lista. '
                         # FIX-P4-01-08 (R-72): a recusa por conta também aparece na pergunta.
                         'Se o app estiver aberto com outra conta do Windows, ou se não der para '
                         'confirmar a conta, o app não desfaz nada.')


class StillUnsupportedTests(Base):
    def test_key_absent_zero_three_or_text_stay_neutral(self):
        cases = {'chave ausente': None, 'zero': (0, DWORD), 'tres': (3, DWORD), 'texto': ('1', SZ)}
        for name, case in cases.items():
            with self.subTest(case=name):
                self.reg = FakeWinreg(hives=('HKLM',))
                self.machine = at.MachineDwordAdapter(registry=self.reg)
                self.reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
                if case is not None:
                    self.reg.put(GRAPHICS, 'HwSchMode', case[0], case[1], hive=HKLM)
                self.assertEqual(self.gpu_state(), {'id': KEY, 'state': 'unsupported', 'changes': []})
                with self.assertRaises(at.NotSupportedError) as raised:
                    self.machine.read(KEY)
                self.assertNotIsInstance(raised.exception, at.WindowsDefaultError)
                self.assertEqual(str(raised.exception), at.MSG_NOT_SUPPORTED)
                self.assertEqual(self.writes(), [])
                if case is None:
                    self.assertNotIn(GRAPHICS.lower(), self.reg.machine_keys)

    def test_old_build_without_value_stays_neutral(self):
        # A versão é conferida antes: sem ela, o valor ausente não vira "padrão do Windows".
        self.reg.put(VERSION, 'CurrentBuildNumber', '18363', SZ, hive=HKLM)
        self.reg.put(GRAPHICS, 'OutroValor', 5, DWORD, hive=HKLM)
        self.assertEqual(self.gpu_state()['state'], 'unsupported')
        with self.assertRaises(at.NotSupportedError) as raised:
            self.machine.read(KEY)
        self.assertNotIsInstance(raised.exception, at.WindowsDefaultError)


class JournalTests(Base):
    def test_undo_all_refuses_when_the_value_disappears_outside(self):
        self.reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.reg.put(GRAPHICS, 'HwSchMode', 1, DWORD, hive=HKLM)
        journal = cj.ChangeJournal(self.tmp / 'diario.json',
                                   {at.ADVANCED_KIND: self.user, at.MACHINE_KIND: self.machine},
                                   self.restore_point)
        journal.apply_batch(self.gpu_state()['changes'])
        self.assertEqual(self.current(), (2, DWORD))
        del self.reg.machine_keys[GRAPHICS.lower()]['HwSchMode']   # apagado por fora
        before = self.snapshot()
        self.reg.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual(done, [])
        self.assertTrue(pending)
        self.assertEqual(reason, at.MSG_UNDO_WINDOWS_DEFAULT)
        self.assertEqual(reason, 'Não foi possível desfazer: o valor desta opção foi apagado fora '
                                 'do app, e o Windows passou a usar o padrão do programa da placa '
                                 'de vídeo (driver). Este ajuste não foi alterado e continua na '
                                 'lista de alterações.')
        # Desfazer um item só dá o mesmo motivo.
        ok, single = journal.undo(journal.entries()[0]['id'])
        self.assertEqual((ok, single), (False, at.MSG_UNDO_WINDOWS_DEFAULT))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.current())   # não recriado
        self.assertEqual(journal.entries()[0]['status'], 'applied')


class JournalSkipGpuTests(unittest.TestCase):
    """FIX-M3-T2-02: GPU apagado por fora é pulado; o mouse, mais antigo, é desfeito."""

    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_older_mouse_is_undone_and_only_it_is_written(self):
        reg = FakeWinreg(hives=('HKLM', 'HKCU'))
        mouse = r'Control Panel\Mouse'
        for name, value in (('MouseSpeed', '1'), ('MouseThreshold1', '6'),
                            ('MouseThreshold2', '10')):
            reg.put(mouse, name, value, SZ)
        reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        reg.put(GRAPHICS, 'HwSchMode', 1, DWORD, hive=HKLM)
        user = at.AdvancedRegistryAdapter(registry=reg)
        machine = at.MachineDwordAdapter(registry=reg)
        journal = cj.ChangeJournal(self.tmp / 'diario.json',
                                   {at.ADVANCED_KIND: user, at.MACHINE_KIND: machine},
                                   lambda description: True)
        journal.apply_batch(at.state_for(at.read_states(user, machine), 'mouse_precision')['changes'])
        journal.apply_batch(at.state_for(at.read_states(user, machine), KEY)['changes'])
        mouse_id, gpu_id = [e['id'] for e in journal.entries()]
        self.assertEqual(reg.get(mouse, 'MouseSpeed'), ('0', SZ))
        del reg.machine_keys[GRAPHICS.lower()]['HwSchMode']   # apagado por fora
        machine_before = {p: dict(v) for p, v in reg.machine_keys.items()}
        gpu_entry = dict(journal.entries()[1])
        reg.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual((done, pending, reason), ([mouse_id], [gpu_id], at.MSG_UNDO_WINDOWS_DEFAULT))
        written = [c for c in reg.calls if c[0] in WRITES]
        self.assertTrue(written)
        self.assertEqual({c[1].lower() for c in written}, {mouse.lower()})   # só o mouse foi gravado
        self.assertEqual(reg.get(mouse, 'MouseSpeed'), ('1', SZ))
        self.assertEqual(reg.get(mouse, 'MouseThreshold1'), ('6', SZ))
        self.assertEqual({p: dict(v) for p, v in reg.machine_keys.items()}, machine_before)
        self.assertIsNone(reg.get(GRAPHICS, 'HwSchMode', hive=HKLM))   # não recriado
        self.assertEqual(journal.entries()[1], gpu_entry)              # nem regravado
        self.assertEqual(journal.entries()[0]['status'], 'reverted')


class JournalGenericReasonTests(Base):
    def test_other_read_failure_keeps_the_general_text(self):
        self.reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.reg.put(GRAPHICS, 'HwSchMode', 1, DWORD, hive=HKLM)
        journal = cj.ChangeJournal(self.tmp / 'diario.json',
                                   {at.ADVANCED_KIND: self.user, at.MACHINE_KIND: self.machine},
                                   self.restore_point)
        journal.apply_batch(self.gpu_state()['changes'])
        self.reg.fail_read.add('HwSchMode')   # permissão negada
        self.reg.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual((done, reason), ([], cj.MSG_UNDO_NOT_READ))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.current(), (2, DWORD))


class FakePower:
    kind = oe.POWER_KIND
    label = 'Plano de energia'

    def available(self):
        return [{'guid': GUID, 'name': 'Equilibrado', 'active': True}]

    def read(self, key):
        return GUID

    def apply(self, key, value):
        raise AssertionError('plano de energia não faz parte deste teste')

    revert = apply


@unittest.skipIf(NO_DISPLAY, 'sem Tk ou sem tela')
class GuiTests(unittest.TestCase):
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
        self.reg = FakeWinreg()
        self.machine_reg = FakeWinreg(hives=('HKLM',))
        self.restore_calls = []
        self.asked = []
        self.shown = []
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.panel = ou.OptimizationPanel(
            self.root, app_dir=self.tmp, state_dir=self.tmp, power_adapter=FakePower(),
            tweak_adapter=st.RegistryTweakAdapter(registry=self.reg),
            advanced_adapter=at.AdvancedRegistryAdapter(registry=self.reg),
            machine_adapter=at.MachineDwordAdapter(registry=self.machine_reg),
            restore_point=self._restore_point, elevated_probe=lambda: True,
            session_owner_probe=lambda: so.SAME, ask=self._ask,
            show=lambda *a: self.shown.append(a))
        self.panel.pack()
        self.settle()
        self.addCleanup(self._join)  # R-29: roda antes da limpeza da pasta.

    def _restore_point(self, description):
        self.restore_calls.append(description)
        return True

    def _ask(self, title, text):
        self.asked.append((title, text))
        return True

    def _join(self):
        for name in ('_power_job', '_measure_job', '_checkup_job', '_idle_job', '_history_job'):
            job = getattr(self.panel, name, None)
            if job is not None:
                job.thread.join(timeout=5)

    def settle(self):
        panel = self.panel
        deadline = time.monotonic() + 5
        while (panel.power_busy or panel._history_job is not None) and time.monotonic() < deadline:
            job = panel._power_job
            if job is not None:
                job.thread.join(timeout=0.05)
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(panel.power_busy)

    def test_apply_shows_warning_without_question_or_restore_point(self):
        self.machine_reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.machine_reg.put(GRAPHICS, 'OutroValor', 5, DWORD, hive=HKLM)
        self.panel.apply_advanced(KEY)
        self.settle()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.restore_calls, [])
        self.assertEqual([c for c in self.machine_reg.calls + self.reg.calls if c[0] in WRITES], [])
        self.assertIsNone(self.machine_reg.get(GRAPHICS, 'HwSchMode', hive=HKLM))
        self.assertEqual(self.shown[-1], ('warning', ou.ADVANCED_TITLE, ou.ADVANCED_WINDOWS_DEFAULT_TEXT))
        self.assertEqual(self.panel.advanced_status.get(), ou.ADVANCED_WINDOWS_DEFAULT_TEXT)
        self.assertIn('• Agendamento de GPU acelerado por hardware ligado: '
                      + at.STATE_TEXT['windows_default'], self.panel.advanced_text.get('1.0', 'end'))
        self.assertFalse(self.panel.journal.entries())

    def test_undo_all_skips_deleted_gpu_and_undoes_older_mouse(self):
        """FIX-M3-T2-02: a tela confirma com o texto novo e mostra o motivo do GPU."""
        mouse = r'Control Panel\Mouse'
        for name, value in (('MouseSpeed', '1'), ('MouseThreshold1', '6'),
                            ('MouseThreshold2', '10')):
            self.reg.put(mouse, name, value, SZ)
        self.machine_reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.machine_reg.put(GRAPHICS, 'HwSchMode', 1, DWORD, hive=HKLM)
        user = at.AdvancedRegistryAdapter(registry=self.reg)
        machine = at.MachineDwordAdapter(registry=self.machine_reg)
        journal = self.panel.journal
        journal.apply_batch(at.state_for(at.read_states(user, machine), 'mouse_precision')['changes'])
        journal.apply_batch(at.state_for(at.read_states(user, machine), KEY)['changes'])
        del self.machine_reg.machine_keys[GRAPHICS.lower()]['HwSchMode']   # apagado por fora
        self.panel.undo_all_changes()
        self.settle()
        self.assertEqual(self.asked[-1], ('Desfazer tudo', ou.CHANGES_CONFIRM_TEXT.format(n=2)))
        self.assertIn('o app para ali; só pula um ajuste cujo valor foi apagado fora do app, '
                      'que continua na lista.', self.asked[-1][1])
        message = ou.CHANGES_STOPPED_TEXT.format(done=1, pending=1,
                                                 reason=at.MSG_UNDO_WINDOWS_DEFAULT)
        self.assertEqual(self.shown[-1], ('warning', 'Desfazer tudo', message))
        self.assertEqual(self.panel.changes_status.get(), message)
        self.assertEqual(self.reg.get(mouse, 'MouseSpeed'), ('1', SZ))
        self.assertIsNone(self.machine_reg.get(GRAPHICS, 'HwSchMode', hive=HKLM))
        status = [e['status'] for e in self.panel.journal.entries()]
        self.assertEqual(status, ['reverted', 'applied'])
        self.assertTrue(self.panel.btn_undo_all.instate(['!disabled']))   # continua ligado


if __name__ == '__main__':
    unittest.main()
