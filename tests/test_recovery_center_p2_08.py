"""P2-08 (fatia 1): central de recuperação.

Os backups são sintéticos, feitos pelo backup_core.copy_backup dentro de
TemporaryDirectory. Nada aqui olha discos reais, e a restauração é simulada.
"""
import gc
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup_core
import recovery_center as rc
from backup_features import LABEL_FILE
from multi_source_plan import prepare_multi_source_preview
from transfer_engine import choose_strategy

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(root):
    """Retrato da árvore: caminho, tamanho, mtime e SHA-256 de cada item."""
    out = []
    for folder, dirs, files in os.walk(root):
        for name in sorted(dirs) + sorted(files):
            p = Path(folder) / name
            st = os.lstat(p)
            digest = ''
            if p.is_file() and not p.is_symlink():
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
            out.append((str(p), st.st_size if not p.is_dir() else 0, st.st_mtime_ns, digest))
    return sorted(out)


def _symlink(target, link, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        return False
    return True


class _FakeStat:
    """lstat falso: arquivo comum pequeno, sem atributos de reparse."""
    def __init__(self, attributes=0):
        self.st_mode = 0o100644
        self.st_size = 10
        self.st_file_attributes = attributes


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='pcro-p208-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.sources = self.root / 'origem'
        self.backups = self.root / 'backups'
        self.sources.mkdir()
        self.backups.mkdir()

    def make_backup(self, name='jogos', files=None, base=None):
        files = files or {'save.dat': b'progresso do jogo', 'notas.txt': b'texto'}
        source = self.sources / name
        source.mkdir(exist_ok=True)
        for rel, data in files.items():
            (source / rel).write_bytes(data)
        plan = prepare_multi_source_preview([str(source)], [str(self.sources)])
        with mock.patch.object(backup_core, 'choose_strategy',
                               lambda a, b, inventory=None: choose_strategy(a, b, inventory={})):
            folder, result = backup_core.copy_backup(
                plan, base or self.backups, display_name=name,
                test_space_probe=lambda p, d: (100 * 1024 ** 3, 10 * 1024 ** 3, True))
        self.assertEqual(result['status'], 'concluido')
        return folder / 'manifest.json'

    def edit(self, manifest, **changes):
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        doc.update(changes)
        manifest.write_text(json.dumps(doc, indent=2), encoding='utf-8')
        return doc


class FindBackupsTests(Base):
    def test_levels_zero_and_one_yes_two_no(self):
        level1 = self.make_backup('um')
        (self.root / 'fundo' / 'a' / 'b').mkdir(parents=True)
        level2 = self.make_backup('dois', base=self.root / 'fundo' / 'a')
        own = rc.find_backups(level1.parent)
        self.assertEqual(own['manifests'], [level1])
        found = rc.find_backups(self.backups)
        self.assertEqual(found['manifests'], [level1])
        self.assertEqual(rc.find_backups(self.root / 'fundo')['manifests'], [])
        self.assertEqual(rc.find_backups(self.root / 'fundo' / 'a')['manifests'], [level2])
        self.assertFalse(found['truncated'])
        self.assertEqual(found['warnings'], [])

    def test_skips_links(self):
        real = self.make_backup('real', base=self.root / 'fora')
        if not _symlink(real.parent, self.backups / 'atalho', directory=True):
            self.skipTest('não foi possível criar link simbólico neste sistema')
        alone = self.backups / 'solto'
        alone.mkdir()
        _symlink(real, alone / 'manifest.json')
        self.assertEqual(rc.find_backups(self.backups)['manifests'], [])
        self.assertTrue(rc.find_backups(self.backups / 'atalho')['warnings'])

    def test_limit_warns(self):
        for i in range(6):
            (self.backups / f'pasta{i}').mkdir()
        result = rc.find_backups(self.backups, max_entries=3)
        self.assertTrue(result['truncated'])
        self.assertTrue(any('parou depois de 3' in w for w in result['warnings']))

    def test_cancel(self):
        self.make_backup('um')
        event = threading.Event()
        event.set()
        result = rc.find_backups(self.backups, cancelled=event)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['manifests'], [])
        self.assertIn(rc.CANCELLED_TEXT, result['warnings'])

    def test_missing_folder(self):
        result = rc.find_backups(self.root / 'nao-existe')
        self.assertEqual(result['manifests'], [])
        self.assertTrue(result['warnings'])


class InspectTests(Base):
    def test_completed_is_restorable(self):
        row = rc.inspect_backup(self.make_backup('um'))
        self.assertTrue(row['restorable'], row['reason'])
        self.assertEqual(row['reason'], rc.REASON_OK)
        self.assertEqual(row['files'], 2)
        self.assertEqual(row['bytes'], len(b'progresso do jogo') + len(b'texto'))
        self.assertEqual(row['status_text'], 'Concluído')
        self.assertRegex(row['date'], r'^\d\d/\d\d/\d{4} \d\d:\d\d$')
        self.assertEqual(row['name'], 'um')
        self.assertTrue(row['key'])

    def test_label_appears(self):
        manifest = self.make_backup('um')
        (self.backups / LABEL_FILE).write_text(
            json.dumps({manifest.parent.name: 'Backup antes de formatar'}), encoding='utf-8')
        self.assertEqual(rc.inspect_backup(manifest)['name'], 'Backup antes de formatar')

    def assert_refused(self, manifest, reason=None):
        row = rc.inspect_backup(manifest)
        self.assertFalse(row['restorable'])
        self.assertTrue(row['reason'])
        self.assertNotEqual(row['reason'], rc.REASON_OK)
        if reason is not None:
            self.assertEqual(row['reason'], reason)
        return row

    def test_partial_or_interrupted(self):
        manifest = self.make_backup('um')
        self.edit(manifest, status='parcial_com_erros')
        self.assertIn('não terminou', self.assert_refused(manifest)['reason'])
        self.edit(manifest, status='interrompido')
        self.assertIn('interrompido', self.assert_refused(manifest)['reason'])

    def test_errors(self):
        manifest = self.make_backup('um')
        self.edit(manifest, errors=[{'error': 'x'}])
        self.assert_refused(manifest, rc.REASON_ERRORS)

    def test_wrong_count_and_size(self):
        manifest = self.make_backup('um')
        doc = self.edit(manifest, file_count_expected=3)
        self.assert_refused(manifest, rc.REASON_COUNT)
        self.edit(manifest, file_count_expected=2, bytes_expected=doc['bytes_expected'] + 1)
        self.assert_refused(manifest, rc.REASON_SIZE)

    def test_broken_json(self):
        manifest = self.make_backup('um')
        manifest.write_text('{ estragado', encoding='utf-8')
        self.assert_refused(manifest, rc.REASON_UNREADABLE)

    def test_unknown_schema(self):
        manifest = self.make_backup('um')
        self.edit(manifest, schema='outro-programa-v9')
        self.assert_refused(manifest, rc.REASON_SCHEMA)

    def test_link(self):
        real = self.make_backup('um')
        folder = self.backups / 'atalho'
        folder.mkdir()
        if not _symlink(real, folder / 'manifest.json'):
            self.skipTest('não foi possível criar link simbólico neste sistema')
        self.assert_refused(folder / 'manifest.json', rc.REASON_LINK)

    def test_old_version_without_expected_count(self):
        manifest = self.make_backup('um')
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        del doc['file_count_expected']
        manifest.write_text(json.dumps(doc, indent=2), encoding='utf-8')
        row = self.assert_refused(manifest, rc.REASON_OLD)
        self.assertIn('versão antiga', row['reason'])
        self.assertEqual(row['files'], 2)

    def test_manifest_read_once(self):
        manifest = self.make_backup('um')
        real_open = open
        opened = []

        def spy(path, *args, **kwargs):
            if Path(path).name == 'manifest.json':
                opened.append(path)
            return real_open(path, *args, **kwargs)
        with mock.patch('builtins.open', side_effect=spy), \
                mock.patch.object(Path, 'read_text',
                                  side_effect=AssertionError('não deve reler o manifesto')), \
                mock.patch.object(Path, 'read_bytes',
                                  side_effect=AssertionError('não deve reler o manifesto')):
            row = rc.inspect_backup(manifest)
        self.assertTrue(row['restorable'], row['reason'])
        self.assertEqual(len(opened), 1)

    def test_too_big(self):
        manifest = self.make_backup('um')
        with mock.patch.object(rc, 'MANIFEST_LIMIT', 10):
            self.assert_refused(manifest, rc.REASON_TOO_BIG)


class GroupTests(Base):
    def copy_folder(self, manifest, where):
        target = self.root / where / manifest.parent.name
        shutil.copytree(manifest.parent, target)
        return target / 'manifest.json'

    def test_equal_copies_ok(self):
        first = self.make_backup('um')
        second = self.copy_folder(first, 'outro-disco')
        rows = rc.group_copies([rc.inspect_backup(first), rc.inspect_backup(second)])
        self.assertTrue(all(row['restorable'] for row in rows))
        self.assertEqual([row['copies'] for row in rows], [2, 2])

    def test_different_sha_disables_both(self):
        first = self.make_backup('um')
        second = self.copy_folder(first, 'outro-disco')
        doc = json.loads(second.read_text(encoding='utf-8'))
        doc['files'][0]['sha256'] = 'a' * 64
        second.write_text(json.dumps(doc, indent=2), encoding='utf-8')
        original = [rc.inspect_backup(first), rc.inspect_backup(second)]
        self.assertTrue(all(row['restorable'] for row in original))
        rows = rc.group_copies(original)
        self.assertFalse(any(row['restorable'] for row in rows))
        self.assertTrue(all(row['reason'] == rc.REASON_COPIES for row in rows))
        self.assertTrue(all(row['restorable'] for row in original))  # entrada intacta

    def test_different_backups_not_grouped(self):
        rows = rc.group_copies([rc.inspect_backup(self.make_backup('um')),
                                rc.inspect_backup(self.make_backup('dois'))])
        self.assertTrue(all(row['restorable'] and row['copies'] == 1 for row in rows))


class VerifyTests(Base):
    def test_intact_ok(self):
        ok, text = rc.verify_backup(self.make_backup('um'))
        self.assertTrue(ok, text)
        self.assertIn('2 arquivo(s)', text)

    def test_changed_byte_fails(self):
        manifest = self.make_backup('um')
        target = next(p for p in manifest.parent.rglob('save.dat'))
        data = bytearray(target.read_bytes())
        data[0] ^= 1
        target.write_bytes(bytes(data))
        ok, text = rc.verify_backup(manifest)
        self.assertFalse(ok)
        self.assertIn('SHA-256', text)
        self.assertNotIn('save.dat', text)

    def test_cancelled(self):
        event = threading.Event()
        event.set()
        ok, text = rc.verify_backup(self.make_backup('um'), event)
        self.assertFalse(ok)
        self.assertIn('interrompida', text)


class SafetyTests(Base):
    def test_tree_unchanged(self):
        first = self.make_backup('um')
        self.make_backup('dois')
        bad = self.backups / 'estragado'
        bad.mkdir()
        (bad / 'manifest.json').write_text('{', encoding='utf-8')
        before = _snapshot(self.root)
        result = rc.scan(self.backups)
        self.assertEqual(len(result['rows']), 3)
        rc.verify_backup(first)
        self.assertEqual(_snapshot(self.root), before)

    def test_texts_never_show_full_path(self):
        fake = Path('C:/Users/fulano/Backups/backup-1/manifest.json')
        texts = []
        with mock.patch.object(rc.os, 'lstat', side_effect=OSError(2, 'x', str(fake))):
            row = rc.inspect_backup(fake)
            texts += [row['reason'], row['name'], row['folder']]
            texts.append(rc.verify_backup(fake)[1])
        error = OSError(2, 'Arquivo ausente', r'C:\Users\fulano\Backups\backup-1\C\save.dat')
        info = _FakeStat()
        with mock.patch.object(rc.os, 'lstat', return_value=info), \
                mock.patch.object(rc, 'verify_complete_manifest', side_effect=error):
            texts.append(rc.verify_backup(fake)[1])
        with mock.patch.object(rc.os, 'lstat', return_value=info), \
                mock.patch.object(rc, 'verify_complete_manifest',
                                  side_effect=ValueError(r'C:\Users\fulano')):
            texts.append(rc.verify_backup(fake)[1])
        self.assertIn('backup-1', texts[-1])
        for text in texts:
            self.assertNotIn('fulano', text)
            self.assertNotIn('Users', text)

    def test_none_file_attributes_does_not_break(self):
        # no Windows, um stat_result incompleto pode trazer st_file_attributes=None
        info = _FakeStat(attributes=None)
        self.assertFalse(rc._is_link(info))
        import after_format
        self.assertFalse(after_format._is_link(info))
        fake = Path('C:/Users/fulano/Backups/backup-1/manifest.json')
        with mock.patch.object(rc.os, 'lstat', return_value=info), \
                mock.patch.object(rc, 'verify_complete_manifest',
                                  return_value={'files_verified': 1, 'bytes_verified': 10}):
            ok, text = rc.verify_backup(fake)
        self.assertTrue(ok, text)
        with mock.patch.object(rc.os, 'lstat', return_value=info), \
                mock.patch('builtins.open', side_effect=OSError('x')):
            self.assertEqual(rc.inspect_backup(fake)['reason'], rc.REASON_UNREADABLE)

    def test_lstat_odd_result_in_verify_is_handled(self):
        class Odd:
            st_mode = 0o100644
            st_size = 10
            st_file_attributes = 'estranho'
        ok, text = None, None
        with mock.patch.object(rc.os, 'lstat', return_value=Odd()):
            ok, text = rc.verify_backup(Path('C:/Users/fulano/b/backup-1/manifest.json'))
        self.assertFalse(ok)
        self.assertNotIn('fulano', text)

    def test_module_never_writes(self):
        src = (ROOT / 'recovery_center.py').read_text(encoding='utf-8')
        for word in ('write_text', 'write_bytes', "open(manifest, 'w", 'os.remove', 'unlink',
                     'rmtree', 'os.replace', 'atomic_json', 'subprocess', 'os.system'):
            self.assertNotIn(word, src)
        ui = (ROOT / 'recovery_center_ui.py').read_text(encoding='utf-8')
        for word in ('allow_elevated', 'allow_protected', 'subprocess', 'os.startfile'):
            self.assertNotIn(word, ui)

    def test_app_has_button_and_menu_item(self):
        src = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("text='Central de recuperação'", src)
        self.assertIn("self._nav_action('⟲', 'Central de recuperação'", src)


try:
    import tkinter as tk
    from tkinter import ttk
    import recovery_center_ui as rcu
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = rcu = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


def _row(name, restorable):
    return {'manifest': Path('/tmp/x') / name / 'manifest.json', 'folder': name, 'name': name,
            'date': '21/10/2026 12:00', 'started': '', 'status': 'concluido',
            'status_text': 'Concluído', 'files': 1, 'bytes': 1, 'size_text': '1 B',
            'restorable': restorable,
            'reason': rc.REASON_OK if restorable else rc.REASON_ERRORS,
            'key': None, 'signature': None, 'copies': 1}


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.busy = False
        self.addCleanup(self.root.destroy)
        self.addCleanup(gc.collect)
        self.rows = [_row('backup-bom', True), _row('backup-ruim', False)]

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

    def test_restore_only_when_restorable(self):
        dlg = self.open()
        tree = dlg.center_tree
        rows = tree.get_children('')
        self.assertEqual(len(rows), 2)
        with mock.patch.object(rcu, 'show_restore') as restore:
            tree.selection_set(rows[1])
            self.root.update()
            dlg.center_buttons['Restaurar…'].invoke()  # desligado: não chama
            restore.assert_not_called()
            tree.selection_set(rows[0])
            self.root.update()
            dlg.center_buttons['Restaurar…'].invoke()
        restore.assert_called_once_with(self.root, self.rows[0]['manifest'])
        self.assertEqual(tree.set(rows[1], 'restore'), 'Não')
        dlg.destroy()

    def test_status_never_shows_chosen_folder_name(self):
        started = threading.Event()

        def scanner(folder, cancelled):
            started.set()
            cancelled.wait(5)
            return {'rows': [], 'truncated': False, 'cancelled': True, 'warnings': []}
        dlg = rcu.show_recovery_center(self.root, folder=Path('/tmp/fulano'), scanner=scanner)
        self.assertTrue(started.wait(5))
        self.assertNotIn('fulano', dlg.center_status.get())
        dlg.destroy()
        self.root.update()

    def test_one_window_only(self):
        dlg = self.open()
        dlg.iconify()
        self.root.update()
        again = rcu.show_recovery_center(self.root)
        self.assertIs(again, dlg)
        self.root.update()
        self.assertEqual(dlg.state(), 'normal')
        dlg.destroy()
        self.root.update()
        self.assertIsNone(self.root.recovery_center_dialog)

    def test_verify_runs_in_background(self):
        dlg = self.open()
        dlg.center_tree.selection_set(dlg.center_tree.get_children('')[0])
        self.root.update()
        dlg.center_buttons['Conferir integridade'].invoke()
        until = time.monotonic() + 5
        while dlg.center_state['busy'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertEqual(dlg.center_status.get(), 'conferido')
        dlg.destroy()

    def test_closing_cancels_search(self):
        started = threading.Event()
        seen = {}

        def scanner(folder, cancelled):
            seen['event'] = cancelled
            started.set()
            cancelled.wait(5)
            return {'rows': [], 'truncated': False, 'cancelled': True, 'warnings': []}
        dlg = rcu.show_recovery_center(self.root, folder=Path('/tmp/simulada'), scanner=scanner)
        self.assertTrue(started.wait(5))
        dlg.destroy()
        self.root.update()
        self.assertTrue(seen['event'].is_set())


if __name__ == '__main__':
    unittest.main()
