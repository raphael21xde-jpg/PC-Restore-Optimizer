"""Focused tests: reuse existing indexed choices without re-scanning drives."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from index_audit_bridge import read_saved_index_choices
from index_choices_bridge import preview_import, apply_imported_choices
from inventory_index import FileMetadataIndex


class IndexAuditBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "inventario-pcro.sqlite3"
        db = FileMetadataIndex(self.path, create=True)
        try:
            db.conn.executemany(
                """INSERT INTO records
                   (path,volume_root,kind,bytes,mtime_ns,candidate,decision)
                   VALUES (?,?,?,?,?,?,?)""", [
                    (r"C:\Games\osu!\Songs", "C:", "directory", 0, 0, 1, "preservar"),
                    (r"C:\Games\osu!\Skins", "C:", "directory", 0, 0, 1, "nao_copiar"),
                    (r"D:\SteamLibrary\game.dat", "D:", "file", 200, 0, 1, "preservar"),
                    (r"C:\Users\rapha\private.bin", "C:", "file", 100, 0, 1, "revisar"),
                ])
            db.conn.commit()
        finally:
            db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_only_explicit_choices_without_modifying_index(self):
        before = self.path.read_bytes()
        state = self.path.stat().st_mtime_ns
        parsed = read_saved_index_choices(self.path)
        self.assertEqual(parsed["source_kind"], "sqlite-index-readonly")
        self.assertEqual(len(parsed["choices"]), 3)
        self.assertEqual(parsed["choices"][r"c:\games\osu!\songs"], "keep")
        self.assertEqual(parsed["choices"][r"c:\games\osu!\skins"], "skip")
        self.assertEqual(parsed["choices"][r"d:\steamlibrary\game.dat"], "keep")
        self.assertFalse(parsed["complete_backup"])
        self.assertFalse(parsed["ready_for_format"])
        self.assertFalse(parsed["installation_authorized"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, state)

    def test_preview_is_not_an_import_conflicts_are_explicit(self):
        app = SimpleNamespace(
            choices={r"c:\games\osu!\skins": "keep"},
            personal_paths=set(), busy=False, deep_scan_running=False,
            _on_change=Mock()
        )
        parsed = read_saved_index_choices(self.path)
        result = preview_import(app, parsed)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["keep"], 2)
        self.assertEqual(result["skip"], 1)
        self.assertEqual(app.choices[r"c:\games\osu!\skins"], "keep")
        app._on_change.assert_not_called()
        # Applying is a separate, previously reviewed operation.
        applied = apply_imported_choices(app, parsed)
        self.assertEqual(applied["applied"], 3)
        self.assertEqual(app.choices[r"c:\games\osu!\skins"], "skip")
        app._on_change.assert_called_once()

    def test_rejects_wrong_schema_and_invalid_paths(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE meta SET value='unknown' WHERE key='schema'")
        with self.assertRaises(ValueError):
            read_saved_index_choices(self.path)

    def test_rejects_invalid_selected_path_without_partial_import(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE records SET path=? WHERE path=?",
                       ("..\\bad", r"C:\Games\osu!\Songs"))
        with self.assertRaises(ValueError):
            read_saved_index_choices(self.path)

    def test_missing_index_fails_without_creating_a_file(self):
        missing = Path(self.temp.name) / "ausente.sqlite3"
        with self.assertRaises(ValueError):
            read_saved_index_choices(missing)
        self.assertFalse(missing.exists())

    def test_empty_saved_choices_still_report_partial_index(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE records SET decision='revisar'")
        data = read_saved_index_choices(self.path)
        self.assertEqual(data["choices"], {})
        self.assertEqual(data["source_state"], "parcial")


if __name__ == "__main__":
    unittest.main()
