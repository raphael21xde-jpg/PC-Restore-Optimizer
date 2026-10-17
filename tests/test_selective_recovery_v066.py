"""v0.6.6 non-destructive selective copy and all-file restore regressions."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest import TestCase

from selective_recovery import (prepare_selected_c, validate_target, run_selected_backup,
                                verify_complete_manifest, run_isolated_restore_test)


class SelectiveRecovery066(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base/'fake_volume'
        self.src = self.root/'Users'/'sample'/'Saved Games'/'GoW'
        self.src.mkdir(parents=True)
        self.backup = self.base/'different_storage'
        self.restore = self.base/'restore_stage'
        self.backup.mkdir(); self.restore.mkdir()
        (self.src/'save0.dat').write_bytes(b'save data GOw'*100)
        (self.src/'save1.dat').write_bytes(b'next'*8192)
        self.prepare = lambda: prepare_selected_c([str(self.src)], test_root=self.root)

    def test_preview_enumerates_file_counts_and_bytes(self):
        plan = self.prepare()
        self.assertEqual(plan.count, 2)
        self.assertEqual(plan.total, 1300+4*8192)
        self.assertFalse(plan.warnings)

    def test_full_backup_and_all_file_restore_into_new_folder(self):
        plan = self.prepare()
        report = run_selected_backup(plan, self.backup, test_root=self.root)
        self.assertTrue(report['backup_verified'])
        self.assertFalse(report['restore_verified'])
        self.assertFalse(report['ready_for_format'])
        result = run_isolated_restore_test(report['manifest'],self.restore,test_root=self.root)
        self.assertTrue(result['restore_verified'])
        self.assertFalse(result['installation_authorized'])
        self.assertEqual(result['files_verified'],2)
        folder = Path(result['restored_folder'])
        self.assertEqual(len(list(folder.rglob('save*.dat'))),2)
        for original in self.src.glob('*.dat'):
            found = list(folder.rglob(original.name))
            self.assertEqual(len(found),1)
            self.assertEqual(found[0].read_bytes(), original.read_bytes())
        self.assertEqual(len(list(self.backup.glob('backup-*/manifest.json'))),1)
        self.assertTrue((folder/'RESULTADO-TESTE-PCRO-066.json').is_file())

    def test_corrupt_backup_detected_before_restore(self):
        backup = run_selected_backup(self.prepare(),self.backup,test_root=self.root)
        backupfolder = Path(backup['backup_folder'])
        file = next(backupfolder.rglob('save0.dat'))
        file.write_bytes(b'CORRUPTED!')
        with self.assertRaises((OSError,ValueError)):
            verify_complete_manifest(backup['manifest'])
        with self.assertRaises((OSError,ValueError)):
            run_isolated_restore_test(backup['manifest'],self.restore,test_root=self.root)
        self.assertEqual(list(self.restore.iterdir()), [])

    def test_partial_manifest_is_not_approved(self):
        backup = run_selected_backup(self.prepare(),self.backup,test_root=self.root)
        manifest = Path(backup['manifest'])
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        doc['status']='parcial_com_erros'
        manifest.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'parcial'):
            verify_complete_manifest(manifest)

    def test_reject_symlink_source(self):
        linked = self.root/'Users'/'sample'/'link'
        try:
            linked.symlink_to(self.src, target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('filesystem symlinks unavailable')
        with self.assertRaisesRegex(ValueError,'Link/junção'):
            prepare_selected_c([str(linked)],test_root=self.root)

    def test_no_outside_paths_and_no_unselected_copy(self):
        with self.assertRaisesRegex(ValueError,'fora da raiz'):
            prepare_selected_c([str(self.base)],test_root=self.root)
        with self.assertRaisesRegex(ValueError,'Nenhum caminho'):
            prepare_selected_c([],test_root=self.root)
        (self.src/'skip-me.dat').write_bytes(b'secret data')
        plan=prepare_selected_c([str(self.src)],choices={str(self.src/'skip-me.dat'):'skip'},test_root=self.root)
        self.assertEqual(plan.count,2)
        self.assertNotIn('skip-me.dat',[Path(t.source).name for t in plan.files])

    def test_target_overlap_or_reparse_rejected(self):
        with self.assertRaisesRegex(ValueError,'sobrepor'):
            validate_target(self.src,forbidden=[self.src/'save0.dat'],test_root=self.root)
        bad = self.base/'symlink_dest'
        try:
            bad.symlink_to(self.backup, target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('filesystem symlinks unavailable')
        with self.assertRaisesRegex(ValueError,'Link/junção'):
            validate_target(bad,test_root=self.root)

    def test_change_since_preview_rejected_and_cancelled(self):
        plan=self.prepare()
        (self.src/'save1.dat').write_bytes(b'CHANGED')
        with self.assertRaises(OSError):
            run_selected_backup(plan,self.backup,test_root=self.root)
        stop=threading.Event();stop.set()
        with self.assertRaises(InterruptedError):
            run_selected_backup(plan,self.backup,test_root=self.root,cancelled=stop)

    def test_restore_cannot_write_inside_backup(self):
        backup = run_selected_backup(self.prepare(),self.backup,test_root=self.root)
        with self.assertRaisesRegex(ValueError,'sobrepor'):
            run_isolated_restore_test(backup['manifest'],backup['backup_folder'],test_root=self.root)

    def test_source_missing_raises_not_fake_success(self):
        with self.assertRaisesRegex(ValueError,'Fonte não encontrada'):
            prepare_selected_c([str(self.src/'not-existing')],test_root=self.root)

