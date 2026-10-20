"""Offline first-launch Tk interactions using disposable test backups only."""
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from test_multi_source_recovery_center import _FixtureBase, descendants
from multi_source_offline_reopen_ui import show_fixture_offline_reopen


class OfflineReopenUiTests(_FixtureBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.tk_root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display indisponível: {exc}')
        self.tk_root.withdraw()
        self.addCleanup(self.tk_root.destroy)

    def window(self, roots=()):
        dialog = show_fixture_offline_reopen(
            self.tk_root, test_root=str(self.root),
            restore_parent=str(self.restore_parent),
            initial_backup_roots=[str(x) for x in roots])
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        buttons = {w.cget('text'): w for w in descendants(dialog)
                   if isinstance(w, ttk.Button)}
        folder_tree = next(w for w in descendants(dialog)
                           if isinstance(w, ttk.Treeview))
        entry = next(w for w in descendants(dialog)
                     if isinstance(w, ttk.Entry))
        return dialog, buttons, folder_tree, entry

    def wait_for(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.tk_root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Janela não completou a operação no prazo.')

    @staticmethod
    def put_path(entry, buttons, path):
        entry.delete(0, 'end')
        entry.insert(0, str(path))
        buttons['Adicionar'].invoke()

    def test_open_window_does_not_load_scan_or_restore_automatically(self):
        with patch('multi_source_offline_reopen_ui.reopen_fixture_backup_session'
                   ) as read, patch(
                       'multi_source_offline_reopen_ui.show_fixture_recovery_center'
                   ) as child:
            _, buttons, tree, _ = self.window()
            self.tk_root.update()
            self.assertEqual(len(tree.get_children('')), 0)
            self.assertEqual(str(buttons['Reabrir backups de teste'].cget('state')),
                             'disabled')
            read.assert_not_called()
            child.assert_not_called()
        self.assert_no_restore_writes()

    def test_two_backup_folders_reopen_without_origins_or_user_plan(self):
        self.first.unlink()
        self.second.unlink()
        captured = []
        windows = []

        def child_window(parent, plan, copies_report, **kwargs):
            captured.append((plan, copies_report, kwargs))
            dlg = tk.Toplevel(parent)
            windows.append(dlg)
            return dlg

        with patch('multi_source_offline_reopen_ui.show_fixture_recovery_center',
                   side_effect=child_window):
            parent, buttons, tree, _ = self.window((self.t, self.u))
            self.assertEqual(len(tree.get_children('')), 2)
            buttons['Reabrir backups de teste'].invoke()
            self.wait_for(lambda: bool(captured))
        self.assertEqual(len(captured), 1)
        plan, copies, kwargs = captured[0]
        self.assertEqual(plan.count, 2)
        self.assertEqual(copies['copies_verified_locally'], 0)
        self.assertFalse(copies['backup_verified'])
        self.assertTrue(all(row['status'] == 'discovered_unverified'
                            for row in copies['destinations']))
        self.assertEqual(kwargs['test_root'], str(self.root))
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assert_no_restore_writes()
        windows[0].destroy()
        self.tk_root.update()
        self.assertEqual(parent.state(), 'normal')

    def test_add_two_selected_paths_and_remove_one_without_writes(self):
        _, buttons, tree, entry = self.window()
        self.put_path(entry, buttons, self.t)
        self.put_path(entry, buttons, self.u)
        self.assertEqual(len(tree.get_children('')), 2)
        self.assertEqual(str(buttons['Reabrir backups de teste'].cget('state')),
                         'normal')
        tree.selection_set(tree.get_children('')[0])
        buttons['Remover pasta'].invoke()
        self.assertEqual(len(tree.get_children('')), 1)
        self.assert_no_restore_writes()

    def test_duplicate_or_nested_backup_directory_is_rejected(self):
        _, buttons, tree, entry = self.window((self.t,))
        self.put_path(entry, buttons, self.t)
        self.assertEqual(len(tree.get_children('')), 1)
        child = next(self.t.glob('backup-*'))
        self.put_path(entry, buttons, child)
        self.assertEqual(len(tree.get_children('')), 1)
        self.assert_no_restore_writes()

    def test_paths_outside_test_root_are_rejected_on_add_and_open(self):
        with tempfile.TemporaryDirectory(prefix='pcro-outside-picker-') as name:
            with self.assertRaisesRegex(ValueError, 'fora da raiz'):
                self.window((name,))
            _, buttons, tree, entry = self.window()
            self.put_path(entry, buttons, name)
            self.assertFalse(tree.get_children(''))
            self.assertEqual(str(buttons['Reabrir backups de teste'].cget('state')),
                             'disabled')
            self.assert_no_restore_writes()

    def test_native_folder_picker_is_validated_against_sandbox(self):
        _, buttons, tree, _ = self.window()
        with tempfile.TemporaryDirectory(prefix='pcro-external-picker-') as name:
            with patch('multi_source_offline_reopen_ui.filedialog.askdirectory',
                       return_value=name):
                buttons['Escolher pasta…'].invoke()
            self.assertFalse(tree.get_children(''))
        with patch('multi_source_offline_reopen_ui.filedialog.askdirectory',
                   return_value=str(self.t)):
            buttons['Escolher pasta…'].invoke()
        self.assertEqual(len(tree.get_children('')), 1)
        self.assert_no_restore_writes()

    def test_empty_backup_folder_blocks_open_without_child(self):
        empty = self.root / 'empty-backup-base'
        empty.mkdir()
        with patch('multi_source_offline_reopen_ui.show_fixture_recovery_center'
                   ) as child:
            _, buttons, tree, _ = self.window((empty,))
            buttons['Reabrir backups de teste'].invoke()
            self.wait_for(lambda: str(
                buttons['Reabrir backups de teste'].cget('state')) == 'normal')
            child.assert_not_called()
            self.assertEqual(len(tree.get_children('')), 1)
        self.assert_no_restore_writes()

    def test_cancel_during_manifest_read_closes_when_worker_finishes(self):
        started = threading.Event()

        def blocked(*_args, **kwargs):
            started.set()
            if not kwargs['cancelled'].wait(timeout=3):
                raise AssertionError('Cancelamento não foi recebido.')
            raise InterruptedError('cancelled')

        with patch('multi_source_offline_reopen_ui.reopen_fixture_backup_session',
                   side_effect=blocked):
            dialog, buttons, _, _ = self.window((self.t,))
            buttons['Reabrir backups de teste'].invoke()
            self.assertTrue(started.wait(2))
            buttons['Cancelar / Fechar'].invoke()
            self.wait_for(lambda: not dialog.winfo_exists(), timeout=4)
        self.assert_no_restore_writes()


if __name__ == '__main__':
    unittest.main()
