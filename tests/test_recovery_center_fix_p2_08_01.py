"""FIX-P2-08-01: motivo completo abaixo da tabela da Central de recuperação.

Só arquivos sintéticos em TemporaryDirectory; nenhum disco real é olhado.
"""
import copy
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tk_helpers
import backup_core
import recovery_center as rc
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy
from tk_helpers import track_tk_root

FAKE_USER = 'fulano-teste'
REASONS = [getattr(rc, name) for name in dir(rc) if name.startswith('REASON_')]


def _row(name, restorable, reason):
    return {'manifest': Path('/tmp/x') / FAKE_USER / name / 'manifest.json', 'folder': name,
            'name': name, 'date': '21/10/2026 12:00', 'started': '', 'status': 'concluido',
            'status_text': 'Concluído', 'files': 1, 'bytes': 1, 'size_text': '1 B',
            'restorable': restorable, 'reason': reason,
            'key': None, 'signature': None, 'copies': 1}


class ReasonTextTests(unittest.TestCase):
    def test_no_selection(self):
        self.assertEqual(rc.NO_SELECTION_TEXT, 'Nenhum backup selecionado')
        self.assertEqual(rc.reason_detail_text(None), 'Nenhum backup selecionado')

    def test_every_reason_is_shown_whole(self):
        self.assertGreaterEqual(len(REASONS), 10)
        self.assertIn(rc.REASON_OLD, REASONS)
        self.assertIn(rc.REASON_COPIES, REASONS)
        for reason in REASONS:
            with self.subTest(reason=reason):
                text = rc.reason_detail_text(_row('b', False, reason))
                self.assertEqual(text, f'Pode restaurar: Não. Motivo: {reason}')

    def test_yes_no_follows_restorable(self):
        self.assertEqual(rc.reason_detail_text(_row('b', True, rc.REASON_OK)),
                         'Pode restaurar: Sim. Motivo: Pronto para restaurar.')
        self.assertTrue(rc.reason_detail_text(_row('b', False, rc.REASON_OK))
                        .startswith('Pode restaurar: Não.'))

    def test_uses_only_restorable_and_reason(self):
        row = _row('pasta-' + FAKE_USER, False, rc.REASON_ERRORS)
        before = copy.deepcopy(row)
        text = rc.reason_detail_text(row)
        self.assertEqual(row, before)  # a linha não é alterada
        self.assertNotIn(FAKE_USER, text)
        self.assertEqual(rc.reason_detail_text({'restorable': False,
                                                'reason': rc.REASON_ERRORS}), text)


class RealRowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='pcro-fix-p20801-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'Users' / FAKE_USER

    def make_backup(self):
        source = self.root / 'origem' / 'jogos'
        source.mkdir(parents=True)
        (source / 'save.dat').write_bytes(b'progresso')
        base = self.root / 'backups'
        base.mkdir()
        plan = prepare_multi_source_preview([str(source)], [str(source.parent)])
        with mock.patch.object(backup_core, 'choose_strategy',
                               lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            folder, result = backup_core.copy_backup(
                plan, base, display_name='jogos',
                test_space_probe=lambda p, d: (100 * 1024 ** 3, 10 * 1024 ** 3, True))
        self.assertEqual(result['status'], 'concluido')
        return folder / 'manifest.json'

    def check(self, row):
        text = rc.reason_detail_text(row)
        self.assertIn(row['reason'], text)
        self.assertNotIn(FAKE_USER, text)
        self.assertNotIn('\\', text)
        self.assertNotIn('/', text)
        return text

    def test_good_backup(self):
        row = rc.inspect_backup(self.make_backup())
        self.assertTrue(row['restorable'])
        self.assertEqual(self.check(row), 'Pode restaurar: Sim. Motivo: Pronto para restaurar.')

    def test_broken_manifest(self):
        folder = self.root / 'backups' / 'quebrado'
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text('{ isto não é json', encoding='utf-8')
        row = rc.inspect_backup(folder / 'manifest.json')
        self.assertFalse(row['restorable'])
        self.assertEqual(self.check(row), f'Pode restaurar: Não. Motivo: {rc.REASON_UNREADABLE}')


try:
    import tkinter as tk
    import recovery_center_ui as rcu
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = rcu = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.busy = False
        track_tk_root(self, self.root)
        self.rows = [_row('backup-velho', False, rc.REASON_OLD)]

    def open(self):
        dlg = rcu.show_recovery_center(
            self.root, folder=Path('/tmp/simulada'),
            scanner=lambda folder, cancelled: {'rows': self.rows, 'truncated': False,
                                               'cancelled': False, 'warnings': []},
            verifier=lambda manifest, cancelled: (True, 'conferido'))
        until = time.monotonic() + 5
        while dlg.center_state['busy'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(dlg.center_state['busy'])
        return dlg

    def test_detail_follows_selection(self):
        dlg = self.open()
        self.assertEqual(dlg.center_detail.get(), 'Nenhum backup selecionado')
        self.assertIn('reason', dlg.center_tree['columns'])
        dlg.center_tree.selection_set('row:0')
        self.root.update()
        self.assertEqual(dlg.center_detail.get(), f'Pode restaurar: Não. Motivo: {rc.REASON_OLD}')
        dlg.destroy()
        self.root.update()


if __name__ == '__main__':
    unittest.main()
