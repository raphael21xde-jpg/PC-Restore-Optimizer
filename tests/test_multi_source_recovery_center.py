"""Read-only recovery-center and Tk preview tests, limited to disposable fixtures."""
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import backup_core
from multi_source_fixture_runner import run_multi_source_fixture_backups
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from multi_source_recovery_center import inspect_fixture_recovery
from multi_source_recovery_center_ui import show_fixture_recovery_center
from transfer_engine import choose_strategy


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class _FixtureBase:
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-center-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.a = self.root / 'sourceA'
        self.b = self.root / 'sourceB'
        self.t = self.root / 'destinationT'
        self.u = self.root / 'destinationU'
        self.restore_parent = self.root / 'restore'
        for folder in (self.a, self.b, self.t, self.u, self.restore_parent):
            folder.mkdir()
        self.first = self.a / 'document.txt'
        self.second = self.b / 'game.sav'
        self.first.write_bytes(b'keep-first')
        self.second.write_bytes(b'keep-second')
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)],
            [str(self.a), str(self.b)])
        preview = preview_multi_source_targets(
            self.plan, [str(self.t), str(self.u)],
            volume_lookup=self.volume,
            usage=lambda _: SimpleNamespace(free=100 * 1024**3))
        with patch.object(backup_core, 'choose_strategy',
                          lambda a, b, inventory=None:
                          choose_strategy(a, b, inventory={})):
            self.copies = run_multi_source_fixture_backups(
                self.plan, preview, test_root=str(self.root),
                volume_lookup=self.volume,
                usage=lambda _: SimpleNamespace(free=100 * 1024**3))
        self.assertEqual(self.copies['copies_verified_locally'], 2)

    def volume(self, raw):
        path = Path(raw)
        for folder, letter in ((self.a, 'A:'), (self.b, 'B:'),
                               (self.t, 'T:'), (self.u, 'U:')):
            if path == folder or folder in path.parents:
                return letter
        return 'SEM UNIDADE'

    def inspect(self, copies=None, restore_parent=None, cancelled=None):
        return inspect_fixture_recovery(
            self.plan, self.copies if copies is None else copies,
            self.restore_parent if restore_parent is None else restore_parent,
            test_root=str(self.root), cancelled=cancelled)

    def assert_no_restore_writes(self):
        self.assertFalse(list(
            self.restore_parent.glob('TESTE-RESTAURACAO-v05-*')))

class RecoveryCenterFixtureTests(_FixtureBase, unittest.TestCase):
    def test_two_good_copies_are_read_only_and_never_authorize_format(self):
        report = self.inspect()
        self.assertEqual(report['status'], 'copy_available')
        self.assertEqual(report['copies_checked'], 2)
        self.assertEqual(report['copies_verified'], 2)
        self.assertEqual(report['suggested_copy_index'], 1)
        self.assertTrue(report['can_restore_in_fixture'])
        self.assertFalse(report['restore_verified'])
        self.assertFalse(report['ready_for_format'])
        self.assertFalse(report['installation_authorized'])
        self.assertFalse(report['physical_independence_verified'])
        self.assertEqual(len(report['files']), 2)
        self.assert_no_restore_writes()

    def test_corrupt_copy_shows_fallback_without_writing(self):
        first = Path(self.copies['destinations'][0]['manifest'])
        next(first.parent.rglob('document.txt')).write_bytes(b'bad')
        report = self.inspect()
        self.assertEqual(report['copies'][0]['status'], 'integrity_failed')
        self.assertEqual(report['copies'][1]['status'], 'copy_verified')
        self.assertEqual(report['suggested_copy_index'], 2)
        self.assertEqual(report['copies_verified'], 1)
        self.assert_no_restore_writes()

    def test_missing_manifest_marks_first_unavailable(self):
        Path(self.copies['destinations'][0]['manifest']).unlink()
        report = self.inspect()
        self.assertEqual(report['copies'][0]['status'], 'manifest_missing')
        self.assertEqual(report['suggested_copy_index'], 2)
        self.assert_no_restore_writes()

    def test_both_corrupted_never_offer_recovery(self):
        for item in self.copies['destinations']:
            m = Path(item['manifest'])
            next(m.parent.rglob('document.txt')).write_bytes(b'corrupted')
        report = self.inspect()
        self.assertEqual(report['status'], 'no_usable_copy')
        self.assertFalse(report['can_restore_in_fixture'])
        self.assertFalse(report['backup_verified'])
        self.assert_no_restore_writes()

    def test_conflicting_readable_manifests_block_recovery(self):
        manifest = Path(self.copies['destinations'][0]['manifest'])
        document = json.loads(manifest.read_text(encoding='utf-8'))
        document['files'][0]['sha256'] = 'f' * 64
        manifest.write_text(json.dumps(document), encoding='utf-8')
        report = self.inspect()
        self.assertEqual(report['status'], 'manifest_conflict')
        self.assertEqual(report['copies_verified'], 0)
        self.assertFalse(report['can_restore_in_fixture'])
        self.assertTrue(all(r['status'] == 'manifest_conflict'
                            for r in report['copies']))
        self.assert_no_restore_writes()

    def test_rejects_forged_copy_manifest_and_non_sandbox_restore(self):
        rows = [dict(row) for row in self.copies['destinations']]
        rows[0]['manifest'] = rows[1]['manifest']
        fake_report = dict(self.copies, destinations=rows)
        with self.assertRaisesRegex(ValueError, 'fora da cópia'):
            self.inspect(copies=fake_report)
        with tempfile.TemporaryDirectory(prefix='pcro-outside-center-') as tmp:
            with self.assertRaisesRegex(ValueError, 'fora da raiz'):
                self.inspect(restore_parent=tmp)
        self.assert_no_restore_writes()

    def test_inspection_survives_removed_original_sources(self):
        self.first.unlink()
        self.second.unlink()
        report = self.inspect()
        self.assertEqual(report['copies_verified'], 2)
        self.assertTrue(report['can_restore_in_fixture'])
        self.assert_no_restore_writes()

    def test_interruption_is_not_misreported_as_corruption(self):
        from threading import Event
        stop = Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            self.inspect(cancelled=stop)
        self.assert_no_restore_writes()


class RecoveryCenterTkTests(_FixtureBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.tk_root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display indisponível: {exc}')
        self.tk_root.withdraw()
        self.addCleanup(self.tk_root.destroy)

    def make_window(self):
        dlg = show_fixture_recovery_center(
            self.tk_root, self.plan, self.copies,
            test_root=str(self.root),
            restore_parent=str(self.restore_parent))
        self.addCleanup(lambda: dlg.winfo_exists() and dlg.destroy())
        return dlg

    def test_open_center_does_not_verify_or_write_automatically(self):
        with patch('multi_source_recovery_center_ui.inspect_fixture_recovery'
                   ) as inspection, patch(
                       'multi_source_recovery_center_ui.recover_from_fixture_copies'
                   ) as restoration:
            dlg = self.make_window()
            self.tk_root.update()
            buttons = [w for w in descendants(dlg)
                       if isinstance(w, ttk.Button)]
            restore = next(b for b in buttons
                           if b.cget('text') == 'Restaurar selecionados (TESTE)')
            self.assertEqual(str(restore.cget('state')), 'disabled')
            self.assertFalse(inspection.called)
            self.assertFalse(restoration.called)
            self.assert_no_restore_writes()

    def test_verify_and_explicit_selection_enable_only_test_restoration(self):
        dlg = self.make_window()
        buttons = [w for w in descendants(dlg) if isinstance(w, ttk.Button)]
        verify = next(b for b in buttons
                      if b.cget('text') == 'Verificar cópias (SHA-256)')
        toggle = next(b for b in buttons
                      if b.cget('text') == 'Marcar/desmarcar arquivo')
        restore = next(b for b in buttons
                       if b.cget('text') == 'Restaurar selecionados (TESTE)')
        verify.invoke()
        deadline = time.monotonic() + 8
        while str(verify.cget('state')) != 'normal' and time.monotonic() < deadline:
            self.tk_root.update()
            time.sleep(.01)
        self.assertEqual(str(verify.cget('state')), 'normal')
        self.assertEqual(str(restore.cget('state')), 'disabled')
        views = [w for w in descendants(dlg) if isinstance(w, ttk.Treeview)]
        items = next(view for view in views if
                     any(str(iid).endswith('.txt') or str(iid).endswith('.sav')
                         for iid in view.get_children('')))
        chosen = items.get_children('')[0]
        items.selection_set(chosen)
        toggle.invoke()
        self.assertEqual(str(restore.cget('state')), 'normal')
        self.assert_no_restore_writes()


if __name__ == '__main__':
    unittest.main()
