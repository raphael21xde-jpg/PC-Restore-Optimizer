"""P2-02: restoration warns about and refuses an elevated (administrator) process.

Elevation is always simulated with an injected probe; nothing here asks the real
Windows API, and every file lives in a TemporaryDirectory.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup_core
import restore_elevation
from backup_features import restore_selected, verified_entries
from multi_source_plan import prepare_multi_source_preview
from restore_elevation import (
    ELEVATION_WARNING, ElevatedRestoreRefused, guarded_restore_selected,
    is_process_elevated, require_not_elevated,
)

ROOT = Path(__file__).resolve().parents[1]


def elevated():
    return True


def not_elevated():
    return False


class SyntheticBackupMixin:
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-p2-02-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source_folder = self.root / 'source'
        source_folder.mkdir()
        self.source = source_folder / 'osu!.db'
        self.payload = b'synthetic-osu-database-p2-02'
        self.source.write_bytes(self.payload)
        backups = self.root / 'backups'
        backups.mkdir()
        self.restores = self.root / 'restores'
        self.restores.mkdir()
        plan = prepare_multi_source_preview([str(self.source)], [str(source_folder)])
        folder, result = backup_core.copy_backup(plan, backups, strategy_inventory={})
        self.assertEqual(result['status'], 'concluido')
        self.manifest = folder / 'manifest.json'
        self.keys = list(verified_entries(self.manifest))


class ProbeTests(unittest.TestCase):
    def test_probe_true_false(self):
        self.assertIs(is_process_elevated(probe=elevated), True)
        self.assertIs(is_process_elevated(probe=not_elevated), False)
        self.assertIs(is_process_elevated(probe=lambda: 1), True)
        self.assertIs(is_process_elevated(probe=lambda: 0), False)

    def test_probe_exception_is_not_elevated(self):
        def broken():
            raise OSError('simulated failure')
        self.assertIs(is_process_elevated(probe=broken), False)

    def test_non_windows_returns_false(self):
        with patch.object(restore_elevation.sys, 'platform', 'linux'):
            self.assertIs(is_process_elevated(), False)

    def test_windows_uses_shell32_is_user_an_admin(self):
        class Shell32:
            calls = 0

            def IsUserAnAdmin(self):
                Shell32.calls += 1
                return 1

        class Windll:
            shell32 = Shell32()

        with (patch.object(restore_elevation.sys, 'platform', 'win32'),
              patch.object(restore_elevation.ctypes, 'windll', Windll(), create=True)):
            self.assertIs(is_process_elevated(), True)
        self.assertEqual(Shell32.calls, 1)

    def test_require_not_elevated(self):
        require_not_elevated(probe=not_elevated)
        require_not_elevated(allow_elevated=True, probe=elevated)
        with self.assertRaises(ElevatedRestoreRefused):
            require_not_elevated(probe=elevated)

    def test_refusal_is_permission_error(self):
        self.assertTrue(issubclass(ElevatedRestoreRefused, PermissionError))

    def test_warning_text(self):
        text = ELEVATION_WARNING.casefold()
        self.assertIn('administrador', text)
        self.assertIn('pasta', text)
        self.assertIn('permiss', text)
        self.assertIn('usuário normal', text)
        message = str(ElevatedRestoreRefused()).casefold()
        self.assertIn('administrador', message)
        self.assertIn('usuário normal', message)
        self.assertIn('permiss', message)


class GuardedRestoreTests(SyntheticBackupMixin, unittest.TestCase):
    def test_guarded_refuses_when_elevated(self):
        with self.assertRaises(ElevatedRestoreRefused):
            guarded_restore_selected(self.manifest, self.keys, self.restores,
                                     elevation_probe=elevated, strategy_inventory={})
        self.assertEqual(list(self.restores.iterdir()), [])

    def test_guarded_allows_with_explicit_flag(self):
        folder, count = guarded_restore_selected(
            self.manifest, self.keys, self.restores, allow_elevated=True,
            elevation_probe=elevated, strategy_inventory={})
        self.assertEqual(count, 1)
        restored = next(folder.rglob('osu!.db'))
        self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(),
                         hashlib.sha256(self.payload).hexdigest())

    def test_allow_elevated_must_be_true_literal(self):
        for value in (1, 'yes', 'True', [True], object()):
            with self.subTest(value=value):
                with self.assertRaises(ElevatedRestoreRefused):
                    guarded_restore_selected(
                        self.manifest, self.keys, self.restores,
                        allow_elevated=value, elevation_probe=elevated,
                        strategy_inventory={})
                with self.assertRaises(ElevatedRestoreRefused):
                    require_not_elevated(allow_elevated=value, probe=elevated)
        self.assertEqual(list(self.restores.iterdir()), [])

    def test_guarded_passes_through_when_not_elevated(self):
        plain_parent = self.root / 'plain'
        plain_parent.mkdir()
        guarded_parent = self.root / 'guarded'
        guarded_parent.mkdir()
        plain_folder, plain_count = restore_selected(
            self.manifest, self.keys, plain_parent, strategy_inventory={})
        guarded_folder, guarded_count = guarded_restore_selected(
            self.manifest, self.keys, guarded_parent,
            elevation_probe=not_elevated, strategy_inventory={})
        self.assertEqual(plain_count, guarded_count)
        self.assertEqual(next(guarded_folder.rglob('osu!.db')).read_bytes(), self.payload)
        plain = json.loads((plain_folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        guarded = json.loads((guarded_folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        self.assertEqual(guarded['status'], 'concluida')
        self.assertEqual(plain['status'], guarded['status'])
        self.assertEqual(plain.get('keys'), guarded.get('keys'))

    def test_guarded_forwards_keyword_arguments(self):
        calls = []

        def fake(*args, **kwargs):
            calls.append((args, kwargs))
            return 'folder', 7

        with patch('restore_elevation.restore_selected', side_effect=fake):
            result = guarded_restore_selected('m.json', ['k'], 'dest',
                                              elevation_probe=not_elevated,
                                              resume_from='r', progress=print)
        self.assertEqual(result, ('folder', 7))
        self.assertEqual(calls, [(('m.json', ['k'], 'dest'),
                                  {'resume_from': 'r', 'progress': print})])


class CallSiteTests(unittest.TestCase):
    def test_restore_ui_uses_guard(self):
        for name in ('restore_ui.py', 'app.py'):
            with self.subTest(file=name):
                source = (ROOT / name).read_text(encoding='utf-8')
                self.assertIn('guarded_restore_selected(', source)
                direct = re.findall(r'(?<![\w.])restore_selected\(', source)
                self.assertEqual(direct, [], f'{name} calls restore_selected( directly')


try:
    import tkinter as tk
    from tkinter import ttk
    HAVE_TK = True
except ImportError:  # the Linux container has no tkinter
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, 'tkinter indisponível')
@unittest.skipIf(sys.platform != 'win32' and not os.environ.get('DISPLAY'), 'No graphical display')
class ElevatedRestoreWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.busy = False
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def find(self, cls, widget=None):
        widget = widget or self.root
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.find(cls, child)

    def open(self, probe):
        from restore_ui import show_restore
        entries = {'C/Games/Other/save.dat': {
            'source': r'C:\Games\Other\save.dat', 'bytes': 99,
            'owners': [{'name': 'Other Game', 'category': 'Save do jogo',
                        'root': r'C:\Games\Other'}]}}
        with patch('restore_ui.verified_entries', return_value=entries):
            show_restore(self.root, 'unused.json', small=True, elevation_probe=probe)
            until = time.monotonic() + 5
            while self.root.busy and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(self.root.busy)
        return self.root.restore_dialog

    def labels(self, dlg):
        return [w.cget('text') for w in self.find(ttk.Label, dlg)]

    def test_elevated_window_warns_and_refuses_before_folder_prompt(self):
        dlg = self.open(elevated)
        self.assertIn(ELEVATION_WARNING, self.labels(dlg))
        buttons = {b.cget('text'): b for b in self.find(ttk.Button, dlg)}
        self.assertFalse(any('mesmo assim' in t.casefold() for t in buttons))
        with (patch('restore_ui.filedialog.askdirectory') as ask,
              patch('restore_ui.messagebox.showerror') as error):
            buttons['Restaurar arquivos marcados para pasta nova'].invoke()
            buttons['Retomar restauração interrompida'].invoke()
        ask.assert_not_called()
        self.assertEqual(error.call_count, 2)
        dlg.destroy()

    def test_normal_window_has_no_warning(self):
        dlg = self.open(not_elevated)
        self.assertNotIn(ELEVATION_WARNING, self.labels(dlg))
        dlg.destroy()


if __name__ == '__main__':
    unittest.main()
