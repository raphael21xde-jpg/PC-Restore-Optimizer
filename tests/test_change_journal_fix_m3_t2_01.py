"""FIX-M3-T2-01: motivo de recusa de um item dentro do "Desfazer tudo" (R-68).

No lote, a tela mostra "N desfeita(s); M continuam como estavam. Motivo: ...".
Se um item é recusado depois de outros já desfeitos, o motivo fala só daquele
item ("este ajuste não foi alterado/desfeito"), nunca "Nada foi alterado" geral.
O "driver" vem explicado: "programa da placa de vídeo (driver)".

Só registro falso em memória (``tests/fake_winreg.py``), adaptadores falsos,
ponto de restauração falso e arquivos em TemporaryDirectory. Nenhum registro,
PowerShell ou subprocess de verdade.
"""
import ast
import inspect
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / 'tests'):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import advanced_tweaks as at  # noqa: E402
import change_journal as cj  # noqa: E402
from fake_winreg import FakeWinreg  # noqa: E402

try:
    import optimization_ui as ou
except ImportError:  # Python sem Tk: a parte do texto da tela usa o modelo copiado.
    ou = None

GRAPHICS = r'SYSTEM\CurrentControlSet\Control\GraphicsDrivers'
VERSION = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
HKLM = FakeWinreg.HKEY_LOCAL_MACHINE
DWORD = FakeWinreg.REG_DWORD
SZ = FakeWinreg.REG_SZ
GPU_KEY = 'gpu_hw_scheduling'
WRITES = ('SetValueEx', 'DeleteValue', 'CreateKeyEx', 'DeleteKey', 'DeleteKeyEx')
FAKE_KIND = 'fake_newer'
OLD_KIND = 'fake_older'
# Mesmo modelo de optimization_ui.CHANGES_STOPPED_TEXT (conferido quando há Tk).
STOPPED_TEXT = '{done} desfeita(s); {pending} continuam como estavam. Motivo: {reason}'


def _forbidden(*args, **kwargs):
    raise AssertionError('comando real executado em teste')


class FakeAdapter:
    """Adaptador falso em memória: guarda valores num dicionário."""

    def __init__(self, start):
        self.values = dict(start)
        self.fail_read = False
        self.calls = []

    def read(self, key):
        if self.fail_read:
            raise OSError('leitura negada (simulada)')   # sem ``undo_reason``
        return self.values[key]

    def apply(self, key, value):
        self.calls.append(('apply', key, value))
        self.values[key] = value

    def revert(self, key, value):
        self.calls.append(('revert', key, value))
        self.values[key] = value


def _stopped_text():
    return ou.CHANGES_STOPPED_TEXT if ou is not None else STOPPED_TEXT


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('run', 'Popen'):
            patcher = mock.patch.object(subprocess, name, side_effect=_forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.restore_calls = []

    def restore_point(self, description):
        self.restore_calls.append(description)
        return True


class GpuRefusedAfterOtherUndoneTests(Base):
    """A1: o mais antigo é o do GPU (HKLM falso); o mais novo é de outro tipo."""

    def setUp(self):
        super().setUp()
        self.reg = FakeWinreg(hives=('HKLM',))
        self.reg.put(VERSION, 'CurrentBuildNumber', '26300', SZ, hive=HKLM)
        self.reg.put(GRAPHICS, 'HwSchMode', 1, DWORD, hive=HKLM)
        self.machine = at.MachineDwordAdapter(registry=self.reg)
        self.newer = FakeAdapter({'outro_ajuste': 0})
        self.journal = cj.ChangeJournal(self.tmp / 'diario.json',
                                        {at.MACHINE_KIND: self.machine, FAKE_KIND: self.newer},
                                        self.restore_point)
        self.journal.apply_batch([{'kind': at.MACHINE_KIND, 'key': GPU_KEY, 'after': 2}])
        self.journal.apply_batch([{'kind': FAKE_KIND, 'key': 'outro_ajuste', 'after': 1}])
        self.gpu_id, self.newer_id = [e['id'] for e in self.journal.entries()]

    def test_reason_speaks_only_of_the_refused_item(self):
        del self.reg.machine_keys[GRAPHICS.lower()]['HwSchMode']   # apagado por fora
        before = {p: dict(v) for p, v in self.reg.machine_keys.items()}
        self.reg.calls.clear()
        done, pending, reason = self.journal.undo_all()
        self.assertEqual(done, [self.newer_id])
        self.assertEqual(pending, [self.gpu_id])
        self.assertEqual(reason, at.MSG_UNDO_WINDOWS_DEFAULT)
        self.assertNotIn('nada foi', reason.casefold())
        message = _stopped_text().format(done=len(done), pending=len(pending), reason=reason)
        self.assertTrue(message.startswith('1 desfeita(s)'))
        self.assertIn('Este ajuste não foi alterado', message)
        self.assertNotIn('nada foi', message.casefold())
        # O GPU não foi gravado nem recriado; o outro voltou ao valor anterior.
        self.assertEqual([c for c in self.reg.calls if c[0] in WRITES], [])
        self.assertEqual({p: dict(v) for p, v in self.reg.machine_keys.items()}, before)
        self.assertIsNone(self.reg.get(GRAPHICS, 'HwSchMode', hive=HKLM))
        self.assertEqual(self.newer.values['outro_ajuste'], 0)
        status = {e['id']: e['status'] for e in self.journal.entries()}
        self.assertEqual(status, {self.gpu_id: 'applied', self.newer_id: 'reverted'})

    @unittest.skipIf(ou is None, 'sem Tk: o modelo da tela não pode ser importado')
    def test_screen_template_is_the_same(self):
        self.assertEqual(ou.CHANGES_STOPPED_TEXT, STOPPED_TEXT)


class GeneralReadFailureAfterOtherUndoneTests(Base):
    """A2: o adaptador do mais antigo lança erro sem ``undo_reason``."""

    def test_general_reason_speaks_only_of_the_item(self):
        older = FakeAdapter({'antigo': 0})
        newer = FakeAdapter({'novo': 0})
        journal = cj.ChangeJournal(self.tmp / 'diario.json',
                                   {OLD_KIND: older, FAKE_KIND: newer}, self.restore_point)
        journal.apply_batch([{'kind': OLD_KIND, 'key': 'antigo', 'after': 1}])
        journal.apply_batch([{'kind': FAKE_KIND, 'key': 'novo', 'after': 1}])
        old_id, new_id = [e['id'] for e in journal.entries()]
        older.fail_read = True
        older.calls.clear()
        done, pending, reason = journal.undo_all()
        self.assertEqual((done, pending), ([new_id], [old_id]))
        self.assertEqual(reason, cj.MSG_UNDO_NOT_READ)
        self.assertIn('este ajuste não foi desfeito', reason)
        self.assertNotIn('nada foi', reason.casefold())
        message = _stopped_text().format(done=len(done), pending=len(pending), reason=reason)
        self.assertTrue(message.startswith('1 desfeita(s)'))
        self.assertNotIn('nada foi', message.casefold())
        self.assertEqual(older.calls, [])   # nada gravado no item recusado
        self.assertEqual(older.values['antigo'], 1)


def _undo_reasons():
    """Todos os motivos que ``ChangeJournal.undo`` devolve (constantes e textos literais)."""
    source = textwrap.dedent(inspect.getsource(cj.ChangeJournal.undo))
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
            continue
        for part in ast.walk(node.value.elts[1]):
            if isinstance(part, ast.Constant) and isinstance(part.value, str) and part.value:
                found.append(part.value)
            elif isinstance(part, ast.Name) and isinstance(getattr(cj, part.id, None), str):
                found.append(getattr(cj, part.id))
    return found


class ReasonTextTests(unittest.TestCase):
    def test_no_undo_reason_says_nothing_was_changed(self):
        """A3: nenhum motivo que pode ir para o lote diz "nada foi"."""
        reasons = _undo_reasons()
        # Confere que a busca achou as constantes e os textos literais.
        self.assertIn(cj.MSG_UNDO_NOT_READ, reasons)
        self.assertIn(cj.MSG_CHANGED_OUTSIDE, reasons)
        self.assertGreaterEqual(len(reasons), 7)
        for reason in reasons + [at.MSG_UNDO_WINDOWS_DEFAULT, at.WindowsDefaultError.undo_reason]:
            with self.subTest(reason=reason):
                self.assertNotIn('nada foi', reason.casefold())

    def test_driver_is_explained(self):
        """A4: "driver" vem explicado em todos os textos do padrão do Windows."""
        texts = [at.MSG_WINDOWS_DEFAULT, at.MSG_UNDO_WINDOWS_DEFAULT,
                 at.STATE_TEXT['windows_default']]
        if ou is not None:
            texts.append(ou.ADVANCED_WINDOWS_DEFAULT_TEXT)
        for text in texts:
            with self.subTest(text=text):
                self.assertIn('programa da placa de vídeo (driver)', text)
                self.assertNotIn('padrão do driver', text)
                self.assertNotIn('placa de vídeo e do driver', text)

    def test_texts_are_the_planned_ones(self):
        self.assertEqual(cj.MSG_UNDO_NOT_READ,
                         'Não foi possível ler o valor atual; este ajuste não foi desfeito.')
        self.assertTrue(at.MSG_UNDO_WINDOWS_DEFAULT.endswith(
            'Este ajuste não foi alterado e continua na lista de alterações.'))


if __name__ == '__main__':
    unittest.main()
