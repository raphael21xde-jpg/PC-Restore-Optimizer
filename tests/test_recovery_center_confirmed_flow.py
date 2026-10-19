"""End-to-end confirmed Tk restore flow in disposable sandbox directories.

No formatting, production drive access, original-file writes or GitHub Actions.
"""
import hashlib
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from test_multi_source_recovery_center import _FixtureBase, descendants
from multi_source_fixture_restore import recover_from_fixture_copies
from multi_source_recovery_center_ui import show_fixture_recovery_center


class RecoveryCenterConfirmedFlowTests(_FixtureBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.tk_root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display indisponível: {exc}')
        self.tk_root.withdraw()
        self.addCleanup(self.tk_root.destroy)
        self.content_hashes = {
            self.first.name: hashlib.sha256(self.first.read_bytes()).hexdigest(),
            self.second.name: hashlib.sha256(self.second.read_bytes()).hexdigest(),
        }

    def open_center(self):
        dlg = show_fixture_recovery_center(
            self.tk_root, self.plan, self.copies,
            test_root=str(self.root), restore_parent=str(self.restore_parent))
        self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
        widgets = list(descendants(dlg))
        controls = {
            w.cget('text'): w for w in widgets
            if isinstance(w, ttk.Button)}
        trees = [w for w in widgets if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(trees), 3)
        return dlg, controls, trees

    def wait_for(self, predicate, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            self.tk_root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Não concluiu dentro do prazo de teste.')

    def inspect_and_select_one(self, controls, trees):
        controls['Verificar cópias (SHA-256)'].invoke()
        self.wait_for(lambda:
            len(trees[1].get_children('')) == 2 and
            str(controls['Verificar cópias (SHA-256)'].cget('state')) == 'normal')
        self.assertEqual(
            str(controls['Restaurar selecionados (TESTE)'].cget('state')),
            'disabled')
        document = next(key for key in trees[1].get_children('')
                        if str(key).endswith('document.txt'))
        trees[1].selection_set(document)
        controls['Marcar/desmarcar arquivo'].invoke()
        self.assertEqual(
            str(controls['Restaurar selecionados (TESTE)'].cget('state')),
            'normal')
        return document

    def assert_sources_unchanged(self):
        for file in (self.first, self.second):
            self.assertEqual(
                hashlib.sha256(file.read_bytes()).hexdigest(),
                self.content_hashes[file.name])

    def test_declined_confirmation_never_calls_restore_engine(self):
        _, controls, trees = self.open_center()
        self.inspect_and_select_one(controls, trees)
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=False,
        ) as confirm, patch(
            'multi_source_recovery_center_ui.recover_from_fixture_copies'
        ) as restore:
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.tk_root.update()
        confirm.assert_called_once()
        restore.assert_not_called()
        self.assertFalse(trees[2].get_children(''))
        self.assert_no_restore_writes()
        self.assert_sources_unchanged()

    def test_confirmed_restore_recovers_only_checked_document(self):
        _, controls, trees = self.open_center()
        self.inspect_and_select_one(controls, trees)
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ) as confirm:
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.wait_for(lambda: len(trees[2].get_children('')) == 1)
        confirm.assert_called_once()
        item = trees[2].get_children('')[0]
        self.assertTrue(trees[2].item(item, 'text').endswith('document.txt'))
        self.assertEqual(trees[2].set(item, 'verification'), 'SHA-256 aprovado')
        self.assertEqual(trees[2].set(item, 'copy'), '#1')
        restored = list(self.restore_parent.rglob('document.txt'))
        self.assertEqual(len(restored), 1)
        self.assertEqual(
            hashlib.sha256(restored[0].read_bytes()).hexdigest(),
            self.content_hashes['document.txt'])
        self.assertFalse(list(self.restore_parent.rglob('game.sav')))
        self.assert_sources_unchanged()

    def test_corruption_after_inspection_falls_back_to_second_copy(self):
        _, controls, trees = self.open_center()
        self.inspect_and_select_one(controls, trees)
        backup = Path(self.copies['destinations'][0]['manifest'])
        next(backup.parent.rglob('document.txt')).write_bytes(b'corrupted')
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ):
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.wait_for(lambda: len(trees[2].get_children('')) == 1)
        item = trees[2].get_children('')[0]
        self.assertEqual(trees[2].set(item, 'copy'), '#2')
        self.assert_sources_unchanged()

    def test_both_copies_bad_after_inspection_never_display_verification(self):
        _, controls, trees = self.open_center()
        self.inspect_and_select_one(controls, trees)
        for row in self.copies['destinations']:
            backup = Path(row['manifest'])
            next(backup.parent.rglob('document.txt')).write_bytes(b'corrupted')
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ):
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.wait_for(lambda:
                str(controls['Verificar cópias (SHA-256)'].cget('state'))
                == 'normal')
        self.assertFalse(trees[2].get_children(''))
        self.assert_no_restore_writes()
        self.assert_sources_unchanged()

    def test_new_inspection_clears_previous_result_details(self):
        _, controls, trees = self.open_center()
        self.inspect_and_select_one(controls, trees)
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ):
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.wait_for(lambda: len(trees[2].get_children('')) == 1)
        self.wait_for(lambda:
            str(controls['Verificar cópias (SHA-256)'].cget('state'))
            == 'normal')
        controls['Verificar cópias (SHA-256)'].invoke()
        self.assertFalse(trees[2].get_children(''))

    def test_close_while_worker_is_busy_cancels_and_removes_callbacks(self):
        started = threading.Event()

        def blocked_inspection(*_args, **kwargs):
            started.set()
            cancelled = kwargs['cancelled']
            if not cancelled.wait(timeout=3):
                raise AssertionError('Worker did not receive cancellation')
            raise InterruptedError('cancelled')

        with patch('multi_source_recovery_center_ui.inspect_fixture_recovery',
                   side_effect=blocked_inspection):
            dlg, controls, trees = self.open_center()
            controls['Verificar cópias (SHA-256)'].invoke()
            self.assertTrue(started.wait(2))
            controls['Cancelar / Fechar'].invoke()
            self.wait_for(lambda: not dlg.winfo_exists(), timeout=4)
        self.assert_no_restore_writes()
        self.assert_sources_unchanged()

    def test_result_details_are_only_reported_after_verified_restore(self):
        document = next(task.destination for task in self.plan.files
                        if task.destination.endswith('document.txt'))
        outcome = recover_from_fixture_copies(
            self.plan, self.copies, [document], self.restore_parent,
            test_root=str(self.root))
        self.assertTrue(outcome['restore_verified'])
        self.assertEqual(outcome['files_restored'], 1)
        self.assertEqual(outcome['restored_files'], [{
            'key': document, 'bytes': self.first.stat().st_size,
            'status': 'sha256_verified', 'copy_index': 1,
        }])
        self.assertFalse(outcome['ready_for_format'])
        self.assertFalse(outcome['installation_authorized'])
        self.assert_sources_unchanged()


if __name__ == '__main__':
    unittest.main()
