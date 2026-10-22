"""Full first-launch -> manifest -> SHA-256 -> selection -> restore rehearsal.

All inputs are disposable TemporaryDirectory fixtures. Source files may be
removed to simulate a newly installed Windows computer. No real user files,
disk operations, format, EFI or production app workflows are exercised.
"""
import hashlib
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from multi_source_offline_reopen_ui import show_fixture_offline_reopen
from test_multi_source_recovery_center import _FixtureBase, descendants
from tk_helpers import track_tk_root


class OfflineCompleteRecoveryE2ETests(_FixtureBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.original_bytes = {
            'document.txt': self.first.read_bytes(),
            'game.sav': self.second.read_bytes(),
        }
        try:
            self.root_window = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Interface Tk indisponível: {exc}')
        self.root_window.withdraw()
        track_tk_root(self, self.root_window)

    def wait_until(self, predicate, *, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            self.root_window.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Operação gráfica de teste excedeu o tempo previsto.')

    @staticmethod
    def buttons(widget):
        return {control.cget('text'): control
                for control in descendants(widget)
                if isinstance(control, ttk.Button)}

    @staticmethod
    def trees(widget):
        return [control for control in descendants(widget)
                if isinstance(control, ttk.Treeview)]

    def launch_picker(self):
        picker = show_fixture_offline_reopen(
            self.root_window, test_root=str(self.root),
            restore_parent=str(self.restore_parent),
            initial_backup_roots=[str(self.t), str(self.u)])
        self.addCleanup(lambda: picker.winfo_exists() and picker.destroy())
        controls = self.buttons(picker)
        self.assertEqual(
            str(controls['Reabrir backups de teste'].cget('state')), 'normal')
        return picker, controls

    def open_center(self):
        picker, controls = self.launch_picker()
        self.assertFalse([
            child for child in picker.winfo_children()
            if isinstance(child, tk.Toplevel)])
        controls['Reabrir backups de teste'].invoke()

        def center_is_open():
            return any(isinstance(child, tk.Toplevel)
                       for child in picker.winfo_children())
        self.wait_until(center_is_open)
        child = next(child for child in picker.winfo_children()
                     if isinstance(child, tk.Toplevel))
        self.assertFalse(list(self.restore_parent.iterdir()))
        controls = self.buttons(child)
        tables = self.trees(child)
        self.assertEqual(len(tables), 3)
        self.assertEqual(
            str(controls['Restaurar selecionados (TESTE)'].cget('state')),
            'disabled')
        return picker, child, controls, tables

    def verify_and_select(self, controls, tables, *, names):
        controls['Verificar cópias (SHA-256)'].invoke()
        self.wait_until(
            lambda: (len(tables[1].get_children('')) == 2 and
                     str(controls['Verificar cópias (SHA-256)'].cget('state'))
                     == 'normal'))
        self.assertEqual(
            str(controls['Restaurar selecionados (TESTE)'].cget('state')),
            'disabled')
        for name in names:
            key = next((iid for iid in tables[1].get_children('')
                        if str(iid).endswith(name)), None)
            self.assertIsNotNone(key, f'Arquivo não encontrado na lista: {name}')
            tables[1].selection_set(key)
            controls['Marcar/desmarcar arquivo'].invoke()
        if names:
            self.assertEqual(
                str(controls['Restaurar selecionados (TESTE)'].cget('state')),
                'normal')

    def restored_folders(self):
        return list(self.restore_parent.glob('TESTE-RESTAURACAO-v05-*'))

    def completed_restore(self, tables, *, count):
        self.wait_until(lambda: len(tables[2].get_children('')) == count)
        self.assertEqual(len(self.restored_folders()), 1)
        folder = self.restored_folders()[0]
        state = json.loads(
            (folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'concluida')
        self.assertEqual(state['verified'], count)
        names = [
            'document.txt' if p.name == 'document.txt' else 'game.sav'
            for p in folder.rglob('*')
            if p.is_file() and p.name in self.original_bytes
        ]
        self.assertEqual(len(names), count)
        for name in names:
            restored = next(folder.rglob(name))
            self.assertEqual(
                hashlib.sha256(restored.read_bytes()).hexdigest(),
                hashlib.sha256(self.original_bytes[name]).hexdigest())
        for item in tables[2].get_children(''):
            self.assertEqual(
                tables[2].set(item, 'verification'), 'SHA-256 aprovado')
        return folder

    def test_first_launch_recovers_both_files_after_originals_are_gone(self):
        self.first.unlink()
        self.second.unlink()
        picker, center, controls, tables = self.open_center()
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assertFalse(self.restored_folders())
        self.verify_and_select(controls, tables,
                               names=['document.txt', 'game.sav'])
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ) as prompt:
            controls['Restaurar selecionados (TESTE)'].invoke()
            recovered = self.completed_restore(tables, count=2)
        prompt.assert_called_once()
        self.assertEqual(
            {p.name for p in recovered.rglob('*')
             if p.name in self.original_bytes},
            set(self.original_bytes))
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())

    def test_first_launch_restores_only_user_selected_save(self):
        self.first.unlink()
        picker, center, controls, tables = self.open_center()
        self.verify_and_select(controls, tables, names=['game.sav'])
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ):
            controls['Restaurar selecionados (TESTE)'].invoke()
            recovered = self.completed_restore(tables, count=1)
        self.assertFalse(list(recovered.rglob('document.txt')))
        self.assertTrue(list(recovered.rglob('game.sav')))
        self.assertEqual(self.second.read_bytes(), self.original_bytes['game.sav'])

    def test_first_launch_falls_back_to_second_backup_if_first_is_corrupt(self):
        first_manifest = Path(self.copies['destinations'][0]['manifest'])
        next(first_manifest.parent.rglob('document.txt')).write_bytes(b'bad')
        self.first.unlink()
        self.second.unlink()
        _, center, controls, tables = self.open_center()
        self.verify_and_select(controls, tables, names=['document.txt'])
        self.assertEqual(tables[0].set('copy:1', 'state'),
                         'Integridade reprovada')
        self.assertEqual(tables[0].set('copy:2', 'state'),
                         'SHA-256 aprovado')
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=True,
        ):
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.completed_restore(tables, count=1)
        item = tables[2].get_children('')[0]
        self.assertEqual(tables[2].set(item, 'copy'), '#2')

    def test_no_confirmation_means_no_restore_even_with_verified_copies(self):
        _, center, controls, tables = self.open_center()
        self.verify_and_select(controls, tables, names=['document.txt'])
        with patch(
            'multi_source_recovery_center_ui.messagebox.askyesno',
            return_value=False,
        ) as prompt, patch(
            'multi_source_recovery_center_ui.recover_from_fixture_copies',
        ) as engine:
            controls['Restaurar selecionados (TESTE)'].invoke()
            self.root_window.update()
        prompt.assert_called_once()
        engine.assert_not_called()
        self.assertFalse(self.restored_folders())
        self.assertFalse(tables[2].get_children(''))
        self.assertEqual(self.first.read_bytes(), self.original_bytes['document.txt'])

    def test_corrupt_both_backups_prevents_selection_and_restoration(self):
        for row in self.copies['destinations']:
            manifest = Path(row['manifest'])
            next(manifest.parent.rglob('document.txt')).write_bytes(b'bad')
        _, center, controls, tables = self.open_center()
        self.verify_and_select(controls, tables, names=[])
        self.assertEqual(tables[0].set('copy:1', 'state'),
                         'Integridade reprovada')
        self.assertEqual(tables[0].set('copy:2', 'state'),
                         'Integridade reprovada')
        key = tables[1].get_children('')[0]
        tables[1].selection_set(key)
        controls['Marcar/desmarcar arquivo'].invoke()
        self.assertEqual(
            str(controls['Restaurar selecionados (TESTE)'].cget('state')),
            'disabled')
        self.assertFalse(self.restored_folders())

    def test_conflicting_manifest_rejected_before_recovery_window_opens(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        doc = json.loads(first.read_text(encoding='utf-8'))
        doc['plan_fingerprint'] = '0' * 64
        first.write_text(json.dumps(doc), encoding='utf-8')
        picker, controls = self.launch_picker()
        controls['Reabrir backups de teste'].invoke()
        self.wait_until(lambda:
            str(controls['Reabrir backups de teste'].cget('state'))
            == 'normal')
        self.assertFalse([
            child for child in picker.winfo_children()
            if isinstance(child, tk.Toplevel)])
        self.assertFalse(self.restored_folders())

    def test_reopening_new_session_while_originals_missing_still_requires_sha(self):
        self.first.unlink()
        self.second.unlink()
        picker, center, controls, tables = self.open_center()
        # Closing first recovery center returns to the folder picker.
        controls['Cancelar / Fechar'].invoke()
        self.wait_until(lambda: not center.winfo_exists())
        self.assertEqual(picker.state(), 'normal')
        # Open from disk again, without stored in-memory plan.
        picker_buttons = self.buttons(picker)
        picker_buttons['Reabrir backups de teste'].invoke()
        self.wait_until(lambda:
            any(isinstance(child, tk.Toplevel)
                for child in picker.winfo_children()))
        again = next(child for child in picker.winfo_children()
                     if isinstance(child, tk.Toplevel))
        buttons = self.buttons(again)
        self.assertEqual(
            str(buttons['Restaurar selecionados (TESTE)'].cget('state')),
            'disabled')
        self.assertFalse(self.restored_folders())


if __name__ == '__main__':
    unittest.main()
