"""Non-destructive integrated rehearsal of inventory -> selection -> backup -> restore.

Only a freshly-created TemporaryDirectory is read/written. Never inspect real
user drives, change Windows boot, copy original user data, or authorize format.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup_core
import backup_features
from backup_core import norm
from index_choices_bridge import apply_imported_choices, read_index_choices
from inventory_index import FileMetadataIndex, index_roots
from selective_recovery import (prepare_selected_c, run_selected_backup,
                                 run_isolated_restore_test, verify_complete_manifest)
from transfer_engine import choose_strategy as actual_choose_strategy


class PreviewApp:
    def __init__(self):
        self.choices = {}
        self.personal_paths = set()
        self.busy = False
        self.deep_scan_running = False
        self.changed = 0

    def _on_change(self):
        self.changed += 1


def _no_hardware_probe(src, dst, inventory=None):
    # Exercise real file transfers without querying physical disks on the host.
    return actual_choose_strategy(src, dst, inventory={})


class TestSelectionBackupRestoreEndToEnd(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="PCRO-V047-")
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.source = self.base / "cliente" / "JogoExemplo"
        (self.source / "Songs").mkdir(parents=True)
        (self.source / "Cache").mkdir()
        self.song = self.source / "Songs" / "musica.osz"
        self.save = self.source / "Cache" / "save_importante.dat"
        self.skip = self.source / "Cache" / "temporario.dat"
        self.config = self.source / "opcoes.ini"
        self.samples = {
            self.song: b"beatmap ficticio 123",
            self.save: b"save ficticio unico",
            self.skip: b"cache temporario nao copiar",
            self.config: b"settings=teste\n",
        }
        for path, content in self.samples.items():
            path.write_bytes(content)
        self.source_hashes = {
            str(path): hashlib.sha256(contents).hexdigest()
            for path, contents in self.samples.items()
        }
        self.backups = self.base / "BACKUP_TESTE"
        self.restores = self.base / "RESTAURO_TESTE"
        self.backups.mkdir()
        self.restores.mkdir()

    def _index_export_and_plan(self):
        output = self.base / "indice.sqlite3"
        index_report = index_roots([self.source], output, page_size=2)
        self.assertEqual(index_report["indexed_files"], 4)
        self.assertFalse(index_report["ready_for_format"])
        db = FileMetadataIndex(output)
        try:
            db.set_decision(self.source, "preservar")
            db.set_decision(self.source / "Cache", "nao_copiar")
            db.set_decision(self.save, "preservar")
            exported = db.export_choices(self.base / "escolhas.json")
        finally:
            db.close()
        self.assertEqual(len(exported["choices"]), 3)
        self.assertEqual(len(exported["selected_directories"]), 2)
        self.assertFalse(exported["verified_backup"])
        self.assertFalse(exported["ready_for_format"])
        self.assertFalse(exported["installation_authorized"])

        if os.name == "nt":
            # On Windows this exercises the exact user-facing JSON importer.
            imported = read_index_choices(self.base / "escolhas.json")
            app = PreviewApp()
            result = apply_imported_choices(app, imported)
            self.assertEqual(result["applied"], 3)
            self.assertEqual(app.changed, 1)
            self.assertFalse(result["backup_started"])
            choices = app.choices
        else:
            # The JSON importer correctly rejects POSIX source paths; Linux
            # exercises the same real backup engine using mapped choices.
            translation = {"preservar": "keep", "nao_copiar": "skip"}
            choices = {norm(path): translation[decision]
                       for path, decision in exported["choices"].items()}
        selected = [path for path, choice in choices.items() if choice == "keep"]
        plan = prepare_selected_c(selected, choices=choices, test_root=str(self.base))
        self.assertFalse(plan.warnings)
        self.assertEqual(plan.count, 3)
        included = {norm(task.source) for task in plan.files}
        self.assertIn(norm(self.save), included)
        self.assertIn(norm(self.song), included)
        self.assertIn(norm(self.config), included)
        self.assertNotIn(norm(self.skip), included)
        return plan

    def test_full_real_copy_verify_and_isolated_restore_of_fixtures(self):
        plan = self._index_export_and_plan()
        with (patch.object(backup_core, "choose_strategy", _no_hardware_probe),
              patch.object(backup_features, "choose_strategy", _no_hardware_probe)):
            backup = run_selected_backup(plan, self.backups, test_root=str(self.base))
            self.assertTrue(backup["backup_verified"])
            self.assertFalse(backup["ready_for_format"])
            self.assertFalse(backup["installation_authorized"])
            manifest = Path(backup["backup_folder"]) / "manifest.json"
            verification = verify_complete_manifest(manifest)
            self.assertEqual(verification["files_verified"], 3)
            self.assertTrue(verification["backup_verified"])
            restored = run_isolated_restore_test(
                manifest, self.restores, test_root=str(self.base))
        self.assertTrue(restored["restore_verified"])
        self.assertFalse(restored["ready_for_format"])
        self.assertFalse(restored["installation_authorized"])
        restored_dir = Path(restored["restored_folder"])
        recovered_names = {p.name for p in restored_dir.rglob("*") if p.is_file()}
        self.assertIn(self.song.name, recovered_names)
        self.assertIn(self.save.name, recovered_names)
        self.assertIn(self.config.name, recovered_names)
        self.assertNotIn(self.skip.name, recovered_names)
        for source, expected in self.source_hashes.items():
            self.assertEqual(hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                             expected, "Source changed during integrated rehearsal")
        self.assertFalse((self.base / "escolhas.json").read_text(
            encoding="utf-8").find('"ready_for_format": false') == -1)

    def test_tampered_backup_must_fail_SHA256_verification(self):
        plan = self._index_export_and_plan()
        with patch.object(backup_core, "choose_strategy", _no_hardware_probe):
            backup = run_selected_backup(plan, self.backups, test_root=str(self.base))
        manifest = Path(backup["backup_folder"]) / "manifest.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        first = document["files"][0]["relative"]
        corrupted = manifest.parent / first
        original = corrupted.read_bytes()
        corrupted.write_bytes(b"x" * len(original))
        with self.assertRaises((ValueError, OSError)):
            verify_complete_manifest(manifest)
        self.assertFalse(any(str(p).startswith(str(self.source))
                             for p in [corrupted]))
        for source, expected in self.source_hashes.items():
            self.assertEqual(hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                             expected)

    def test_missing_selected_file_blocks_plan_before_backup(self):
        output = self.base / "indice.sqlite3"
        index_roots([self.source], output, page_size=3)
        db = FileMetadataIndex(output)
        try:
            db.set_decision(self.song, "preservar")
        finally:
            db.close()
        # Simulate disappearance in our private fixture, never user data.
        self.song.unlink()
        with self.assertRaises(ValueError):
            prepare_selected_c([str(self.song)], test_root=str(self.base))
        self.assertFalse(list(self.backups.iterdir()))


if __name__ == "__main__":
    unittest.main()
