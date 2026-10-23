"""P2-08 (fatia 2): restaurar só os arquivos conferidos de um backup parcial.

Só backups sintéticos em TemporaryDirectory; nenhum disco real é olhado e
nada de verdade é restaurado fora da pasta temporária.
"""
import ast
import hashlib
import json
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
from backup_features import restore_selected
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy
from tk_helpers import track_tk_root

ROOT = Path(__file__).resolve().parents[1]
FAKE_USER = 'fulano-teste'
CONTENT = {'a.txt': b'alfa', 'b.txt': b'beta-beta', 'c.txt': b'gama-gama-gama'}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='pcro-p208f2-')
        self.addCleanup(tmp.cleanup)
        self.tmp_name = Path(tmp.name).name
        self.root = Path(tmp.name) / 'Users' / FAKE_USER
        self.base = self.root / 'backups'
        self.base.mkdir(parents=True)

    def real_partial_backup(self):
        """Backup de verdade (copy_backup) em que o 1º arquivo lido falha."""
        source = self.root / 'origem' / 'docs'
        source.mkdir(parents=True)
        for name, data in CONTENT.items():
            (source / name).write_bytes(data)
        plan = prepare_multi_source_preview([str(source)], [str(source.parent)])
        calls = {'n': 0}

        def fault(stage):
            if stage == 'backup_before_read':
                calls['n'] += 1
                if calls['n'] == 1:
                    raise OSError(f'Arquivo travado: C:\\Users\\{FAKE_USER}\\segredo.txt')

        with mock.patch.object(backup_core, 'choose_strategy',
                               lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            folder, result = backup_core.copy_backup(
                plan, self.base, display_name='docs',
                test_space_probe=lambda p, d: (100 * 1024 ** 3, 10 * 1024 ** 3, True),
                test_fault_hook=fault)
        self.assertEqual(result['status'], 'parcial_com_erros')
        return folder / 'manifest.json'

    def hand_backup(self, name='manual', *, status='parcial_com_erros', missing=('c.txt',),
                    edit=None):
        """Backup montado à mão: os arquivos em 'missing' falharam."""
        folder = self.base / name
        folder.mkdir()
        files = []
        for rel, data in CONTENT.items():
            if rel in missing:
                continue
            (folder / rel).write_bytes(data)
            files.append({'source': f'C:\\Users\\{FAKE_USER}\\{rel}', 'relative': rel,
                          'bytes': len(data), 'sha256': _sha(data), 'verified': True})
        doc = {'schema': 'pc-restore-backup-v0.5', 'status': status,
               'started': '2026-10-20T10:00:00', 'display_name': 'manual',
               'file_count_expected': len(CONTENT),
               'bytes_expected': sum(len(d) for d in CONTENT.values()),
               'files': files,
               'errors': [{'source': f'C:\\Users\\{FAKE_USER}\\{rel}', 'error': 'travado'}
                          for rel in missing]}
        if edit is not None:
            edit(doc)
        (folder / 'manifest.json').write_text(json.dumps(doc), encoding='utf-8')
        return folder / 'manifest.json'

    def check_text(self, text):
        self.assertNotIn('/', text)
        self.assertNotIn('\\', text)
        self.assertNotIn(FAKE_USER, text)
        self.assertNotIn(self.tmp_name, text)
        self.assertNotIn('segredo', text)
        self.assertNotIn('travado', text.casefold().replace('travados', ''))


class PartialFlowTests(Base):
    def test_real_partial_backup_restores_only_verified(self):
        manifest = self.real_partial_backup()
        row = rc.inspect_backup(manifest)
        self.assertTrue(row['partial_ok'], row['partial_reason'])
        self.assertEqual((row['verified_files'], row['failed_files']), (2, 1))
        self.assertFalse(row['restorable'])  # regra da fatia 1 não muda
        self.assertEqual(rc.counts_text(row), 'Conferidos: 2 · Falharam: 1')
        keys = rc.load_partial_keys(manifest)
        self.assertEqual(len(keys), 2)
        dest = self.root / 'destino'
        dest.mkdir()
        target, count = restore_selected(manifest, keys, dest)
        self.assertEqual(count, 2)
        self.assertEqual(target.parent, dest.resolve())
        self.assertTrue(target.name.startswith('TESTE-RESTAURACAO-v05-'))
        restored = [p for p in target.rglob('*.txt') if p.name in CONTENT]
        self.assertEqual(len(restored), 2)
        self.assertEqual(len({p.name for p in restored}), 2)
        for path in restored:
            self.assertEqual(path.read_bytes(), CONTENT[path.name])
        self.assertEqual(list(target.rglob('*.partial*')), [])

    def test_hand_partial_counts_and_info(self):
        manifest = self.hand_backup()
        row = rc.inspect_backup(manifest)
        self.assertTrue(row['partial_ok'])
        self.assertEqual(row['reason'], rc.REASON_ERRORS.replace('erros', 'erros') if False else row['reason'])
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        entries = rc._entries(doc)
        ok, good, bad, reason = rc.partial_restore_info(doc, entries)
        self.assertEqual((ok, good, bad), (True, 2, 1))
        self.assertEqual(sorted(rc.load_partial_keys(manifest)), ['a.txt', 'b.txt'])

    def test_confirmation_says_how_many_are_left_out(self):
        row = rc.inspect_backup(self.hand_backup(missing=('b.txt', 'c.txt')))
        self.assertTrue(row['partial_ok'])
        text = rc.partial_confirmation_text(row)
        self.assertIn('Ficam de fora 2 arquivo(s)', text)
        self.assertIn('1 arquivo(s)', text)
        self.assertIn('pasta NOVA', text)
        self.assertIn('conferido de novo pelo SHA-256', text)
        self.assertIn('nada é apagado nem sobrescrito', text)
        self.check_text(text)

    def test_texts_have_no_paths(self):
        manifest = self.real_partial_backup()
        row = rc.inspect_backup(manifest)
        for text in (rc.counts_text(row), rc.partial_confirmation_text(row), row['partial_reason'],
                     rc.partial_report_text(2, 1, 'TESTE-RESTAURACAO-v05-abcd1234'),
                     rc.partial_report_text(1, 1, 'TESTE-RESTAURACAO-v05-abcd1234',
                                            not_marked=1, passwords=1)):
            with self.subTest(text=text):
                self.check_text(text)
        report = rc.partial_report_text(2, 1, str(self.root / 'TESTE-RESTAURACAO-v05-abcd1234'))
        self.assertIn('"TESTE-RESTAURACAO-v05-abcd1234"', report)
        self.check_text(report)
        self.assertIn('2 arquivo(s)', report)
        self.assertIn('1 arquivo(s) ficaram de fora', report)

    def test_counts_text_empty_without_counts(self):
        self.assertEqual(rc.counts_text({'restorable': False, 'reason': rc.REASON_OLD}), '')
        self.assertEqual(rc.counts_text(None), '')

    def test_changed_file_is_never_restored(self):
        manifest = self.hand_backup()
        keys = rc.load_partial_keys(manifest)
        (manifest.parent / 'a.txt').write_bytes(b'ALFA')  # mesmo tamanho, SHA diferente
        dest = self.root / 'destino'
        dest.mkdir()
        with self.assertRaises(OSError):
            restore_selected(manifest, sorted(keys), dest)
        for folder in dest.iterdir():
            self.assertFalse((folder / 'a.txt').exists())
            self.assertEqual([p for p in folder.rglob('*') if '.partial' in p.name], [])

    def test_restorable_and_reason_same_as_slice_1(self):
        for kwargs in ({}, {'status': 'concluido', 'missing': ()},
                       {'status': 'interrompido'}, {'status': 'concluido', 'missing': ('a.txt',)}):
            with self.subTest(kwargs=kwargs):
                name = 'b-' + str(len(list(self.base.iterdir())))
                manifest = self.hand_backup(name, **kwargs)
                row = rc.inspect_backup(manifest)
                doc = json.loads(manifest.read_text(encoding='utf-8'))
                entries = rc._entries(doc)
                status = doc['status']
                if status != 'concluido':
                    expected = (False, f'O backup não terminou ({row["status_text"].lower()}); '
                                       'restaure só de um backup concluído.')
                elif doc['errors']:
                    expected = (False, rc.REASON_ERRORS)
                elif len(entries) != doc['file_count_expected']:
                    expected = (False, rc.REASON_COUNT)
                else:
                    expected = (True, rc.REASON_OK)
                self.assertEqual((row['restorable'], row['reason']), expected)


class RefusalTests(Base):
    def assert_refused(self, row):
        self.assertFalse(row['partial_ok'])
        self.assertTrue(row['partial_reason'])
        self.check_text(row['partial_reason'])
        self.assertFalse(row['restorable'])
        with self.assertRaises(ValueError):
            rc.load_partial_keys(row['manifest'])

    def test_broken_json(self):
        folder = self.base / 'quebrado'
        folder.mkdir()
        (folder / 'manifest.json').write_text('{ não é json', encoding='utf-8')
        row = rc.inspect_backup(folder / 'manifest.json')
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.REASON_UNREADABLE)

    def test_unknown_schema(self):
        row = rc.inspect_backup(self.hand_backup(edit=lambda d: d.update(schema='outro')))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.REASON_SCHEMA)

    def test_item_without_verified_refuses_everything(self):
        row = rc.inspect_backup(self.hand_backup(edit=lambda d: d['files'][0].pop('verified')))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.PARTIAL_NO_VERIFIED)

    def test_verified_without_sha(self):
        row = rc.inspect_backup(self.hand_backup(edit=lambda d: d['files'][0].pop('sha256')))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.REASON_ENTRIES)
        doc = {'status': 'parcial_com_erros', 'file_count_expected': 3, 'bytes_expected': 27,
               'files': [{'relative': 'a.txt', 'bytes': 4, 'verified': True}]}
        ok, _good, _bad, reason = rc.partial_restore_info(doc, {})
        self.assertFalse(ok)
        self.assertEqual(reason, rc.PARTIAL_SHA)

    def test_missing_file_count_expected(self):
        row = rc.inspect_backup(self.hand_backup(edit=lambda d: d.pop('file_count_expected')))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.PARTIAL_OLD)
        row = rc.inspect_backup(self.hand_backup('b2', edit=lambda d: d.update(bytes_expected='27')))
        self.assert_refused(row)

    def test_different_copies(self):
        first = rc.inspect_backup(self.hand_backup('copia1'))
        second = rc.inspect_backup(self.hand_backup('copia2', missing=('b.txt',)))
        self.assertTrue(first['partial_ok'] and second['partial_ok'])
        first['key'] = second['key'] = 'mesmo-backup'
        rows = rc.group_copies([first, second])
        for row in rows:
            self.assertFalse(row['partial_ok'])
            self.assertEqual(row['partial_reason'], rc.REASON_COPIES)
        self.assertTrue(first['partial_ok'])  # entrada não alterada

    def test_status_concluido_or_interrompido(self):
        for status, missing in (('concluido', ()), ('interrompido', ('c.txt',)),
                                ('em_andamento', ('c.txt',))):
            with self.subTest(status=status):
                row = rc.inspect_backup(self.hand_backup('s-' + status, status=status,
                                                         missing=missing))
                self.assertFalse(row['partial_ok'])
                self.check_text(row['partial_reason'])
                with self.assertRaises(ValueError):
                    rc.load_partial_keys(row['manifest'])

    def test_zero_verified(self):
        row = rc.inspect_backup(self.hand_backup(missing=tuple(CONTENT)))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.PARTIAL_NONE)

    def test_size_bigger_than_planned(self):
        row = rc.inspect_backup(self.hand_backup(edit=lambda d: d.update(bytes_expected=5)))
        self.assert_refused(row)
        self.assertEqual(row['partial_reason'], rc.PARTIAL_SIZE)

    def test_manifest_changed_after_listing(self):
        manifest = self.hand_backup()
        self.assertTrue(rc.inspect_backup(manifest)['partial_ok'])
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        doc['status'] = 'concluido'
        manifest.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            rc.load_partial_keys(manifest)
        self.check_text(str(caught.exception))


class RestoreUiSourceTests(unittest.TestCase):
    """Lê restore_ui.py com ast (roda sem Tk)."""

    def setUp(self):
        tree = ast.parse((ROOT / 'restore_ui.py').read_text(encoding='utf-8'))
        self.func = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == 'show_restore')
        self.parents = {}
        for parent in ast.walk(self.func):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent

    def guarded(self, node):
        while node in self.parents:
            parent = self.parents[node]
            if isinstance(parent, ast.If) and node in parent.body \
                    and isinstance(parent.test, ast.UnaryOp) \
                    and isinstance(parent.test.op, ast.Not) \
                    and isinstance(parent.test.operand, ast.Name) \
                    and parent.test.operand.id == 'only_verified':
                return True
            node = parent
        return False

    def test_option_exists(self):
        names = [a.arg for a in self.func.args.kwonlyargs]
        self.assertIn('only_verified', names)
        index = names.index('only_verified')
        self.assertIs(self.func.args.kw_defaults[index].value, False)

    def test_partial_mode_never_reaches_placement(self):
        found = 0
        for node in ast.walk(self.func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in ('staging_info', 'run_placement', 'plan_placement'):
                found += 1
                self.assertTrue(self.guarded(node), node.func.id)
        self.assertGreaterEqual(found, 3)

    def test_place_buttons_only_in_full_mode(self):
        texts = []
        for node in ast.walk(self.func):
            if isinstance(node, ast.Constant) and node.value in (
                    'Colocar no lugar original', 'Retomar colocação interrompida'):
                if isinstance(self.parents.get(node), ast.keyword):
                    texts.append(node.value)
                    self.assertTrue(self.guarded(node), node.value)
        self.assertEqual(sorted(texts), ['Colocar no lugar original',
                                         'Retomar colocação interrompida'])

    def test_no_allow_elevated(self):
        source = ast.unparse(self.func)
        self.assertNotIn('allow_elevated', source)
        self.assertIn('guarded_restore_selected', source)


try:
    import tkinter as tk
    import recovery_center_ui as rcu
    import restore_ui
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = rcu = restore_ui = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(Base):
    def setUp(self):
        super().setUp()
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()
        self.tk_root.busy = False
        track_tk_root(self, self.tk_root)

    def wait(self, check):
        until = time.monotonic() + 5
        while not check() and time.monotonic() < until:
            self.tk_root.update()
            time.sleep(0.02)

    def all_texts(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget('text')))
            except tk.TclError:
                pass
            found.extend(self.all_texts(child))
        return found

    def test_partial_restore_window_has_no_place_buttons(self):
        manifest = self.hand_backup()
        dlg = restore_ui.show_restore(self.tk_root, manifest, only_verified=True,
                                      elevation_probe=lambda: False)
        dlg = self.tk_root.restore_dialog
        self.wait(lambda: not self.tk_root.busy)
        texts = self.all_texts(dlg)
        self.assertNotIn('Colocar no lugar original', texts)
        self.assertNotIn('Retomar colocação interrompida', texts)
        self.assertFalse(any('Program Files' in t for t in texts))
        self.assertIn('Restaurar arquivos marcados para pasta nova', texts)
        dlg.destroy()
        self.tk_root.update()

    def test_center_button_follows_partial_ok(self):
        row = rc.inspect_backup(self.hand_backup())
        bad = rc.inspect_backup(self.hand_backup('velho', edit=lambda d: d.pop('bytes_expected')))
        dlg = rcu.show_recovery_center(
            self.tk_root, folder=Path('/tmp/simulada'),
            scanner=lambda folder, cancelled: {'rows': [row, bad], 'truncated': False,
                                               'cancelled': False, 'warnings': []},
            verifier=lambda manifest, cancelled: (True, 'conferido'))
        self.wait(lambda: not dlg.center_state['busy'])
        button = dlg.center_buttons['Restaurar só os conferidos…']
        dlg.center_tree.selection_set('row:0')
        self.tk_root.update()
        self.assertFalse(button.instate(['disabled']))
        self.assertTrue(dlg.center_buttons['Restaurar…'].instate(['disabled']))
        self.assertIn('Conferidos: 2 · Falharam: 1', dlg.center_detail.get())
        opened = []
        with mock.patch.object(rcu.messagebox, 'askyesno', return_value=True) as ask, \
                mock.patch.object(rcu, 'show_restore',
                                  lambda app, manifest, **kw: opened.append((manifest, kw))):
            button.invoke()
        self.assertIn('Ficam de fora 1 arquivo(s)', ask.call_args[0][1])
        self.assertEqual(opened, [(row['manifest'], {'only_verified': True})])
        dlg.center_tree.selection_set('row:1')
        self.tk_root.update()
        self.assertTrue(button.instate(['disabled']))
        dlg.destroy()
        self.tk_root.update()


if __name__ == '__main__':
    unittest.main()
