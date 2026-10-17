"""Synthetic tests for the durable, searchable, explicitly selected index."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from inventory_index import FileMetadataIndex, index_roots


class TestInventoryIndex(unittest.TestCase):
    def make_tree(self, root):
        (root / "SteamApps").mkdir()
        sample1 = root / "SteamApps" / "demo.dat"
        sample1.write_bytes(b"original content must be preserved")
        sample2 = root / "save_file_002.txt"
        sample2.write_bytes(b"private sample")
        return sample1, sample2

    def test_create_search_review_export_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix="PCRO-INDEX-TEST-") as tmp:
            base = Path(tmp)
            source = base / "volume"
            source.mkdir()
            sample1, sample2 = self.make_tree(source)
            original = sample1.read_bytes()
            dbfile = base / "metadata.sqlite3"
            report = index_roots([source], dbfile, page_size=1)
            self.assertEqual(report["status"], "concluido_com_lacunas")
            self.assertEqual(report["indexed_files"], 2)
            self.assertTrue(report["partial_coverage"])
            self.assertFalse(report["ready_for_format"])
            self.assertTrue(dbfile.exists())
            db = FileMetadataIndex(dbfile)
            try:
                self.assertEqual(db.metadata()["state"], "terminado_com_lacunas")
                self.assertEqual(db.search("demo.dat")[0]["bytes"], len(original))
                self.assertEqual(len(db.search()), 3)
                self.assertEqual(db.search("SAVE_FILE")[0]["path"], str(sample2))
                db.set_decision(sample1, "preservar")
                db.set_decision(sample2, "nao_copiar")
                with self.assertRaises(ValueError):
                    db.set_decision(source / "SteamApps", "preservar")
                with self.assertRaises(ValueError):
                    db.set_decision(sample2, "apagar")
                choices_file = base / "choices.json"
                choices = db.export_choices(choices_file)
                self.assertEqual(choices["choices"][str(sample1)], "preservar")
                self.assertEqual(choices["choices"][str(sample2)], "nao_copiar")
                self.assertFalse(choices["verified_backup"])
                self.assertFalse(choices["ready_for_format"])
                self.assertEqual(choices, json.loads(choices_file.read_text(encoding="utf-8")))
                with self.assertRaises(FileExistsError):
                    db.export_choices(choices_file)
                with self.assertRaises(ValueError):
                    db.export_choices(dbfile)
            finally:
                db.close()
            reopened = FileMetadataIndex(dbfile)
            try:
                self.assertEqual(reopened.decision_counts()["preservar"], 1)
                self.assertEqual(reopened.decision_counts()["nao_copiar"], 1)
            finally:
                reopened.close()
            self.assertEqual(sample1.read_bytes(), original)
            self.assertEqual(sample2.read_bytes(), b"private sample")

    def test_legacy_or_foreign_index_rejected_and_source_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing.sqlite3"
            existing.write_bytes(b"unchanged")
            with self.assertRaises(FileExistsError):
                FileMetadataIndex(existing, create=True)
            self.assertEqual(existing.read_bytes(), b"unchanged")
            with self.assertRaises(Exception):
                FileMetadataIndex(existing)
            self.assertEqual(existing.read_bytes(), b"unchanged")

    def test_cancel_before_start_creates_no_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "never-created.sqlite3"
            stop = threading.Event()
            stop.set()
            with self.assertRaises(InterruptedError):
                index_roots([root], target, cancelled=stop)
            self.assertFalse(target.exists())

    def test_cancel_during_scan_marks_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            for idx in range(20):
                (source / f"item-{idx}.txt").write_bytes(b"x")
            target = root / "interrupted.sqlite3"
            stop = threading.Event()
            def progress(seen, pending):
                if seen >= 3:
                    stop.set()
            with self.assertRaises(InterruptedError):
                index_roots([source], target, cancelled=stop, page_size=3, progress=progress)
            db = FileMetadataIndex(target)
            try:
                self.assertEqual(db.metadata()["state"], "interrompido")
                self.assertEqual(len(db.search()), 3)
                self.assertEqual(db.decision_counts().get("preservar", 0), 0)
            finally:
                db.close()

    def test_metadata_only_not_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            self.make_tree(source)
            out = root / "metadata.sqlite3"
            # Avoid mocking db open; use Path.read_bytes on source fixture
            # after complete to confirm no source mutations.
            before = {(p.relative_to(source), p.stat().st_mtime_ns)
                      for p in source.rglob("*") if p.is_file()}
            report = index_roots([source], out, page_size=1)
            self.assertEqual(report["source_files_read"], 0)
            after = {(p.relative_to(source), p.stat().st_mtime_ns)
                     for p in source.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
