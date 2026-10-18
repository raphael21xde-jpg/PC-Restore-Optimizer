"""Focused tests: reuse existing indexed choices without re-scanning drives."""
import sqlite3
import json
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from index_audit_bridge import read_saved_index_choices
from index_choices_bridge import preview_import, apply_imported_choices, read_index_choices
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
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE meta SET value='unknown' WHERE key='schema'")
        with self.assertRaises(ValueError):
            read_saved_index_choices(self.path)

    def test_rejects_invalid_selected_path_without_partial_import(self):
        with closing(sqlite3.connect(self.path)) as db, db:
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
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE records SET decision='revisar'")
        data = read_saved_index_choices(self.path)
        self.assertEqual(data["choices"], {})
        self.assertEqual(data["source_state"], "parcial")


    def test_recycle_bin_saved_decisions_are_visible_but_never_importable(self):
        old_keep = r"C:\$Recycle.Bin\S-1-5-21-123\deleted-osu.osz"
        old_skip = r"C:\$Recycle.Bin\S-1-5-21-123\deleted-config.json"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany(
                "INSERT INTO records "
                "(path,volume_root,kind,bytes,mtime_ns,candidate,decision) "
                "VALUES (?,?,?,?,?,?,?)",
                [(old_keep, "C:", "file", 17, 0, 1, "preservar"),
                 (old_skip, "C:", "file", 8, 0, 1, "nao_copiar")]
            )
        before = self.path.read_bytes()
        parsed = read_saved_index_choices(self.path)
        self.assertEqual(len(parsed["ignored_system_choices"]), 2)
        self.assertFalse(any("$recycle.bin" in p for p in parsed["choices"]))
        self.assertEqual(len(parsed["choices"]), 3)
        self.assertFalse(parsed["ready_for_format"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_recycle_bin_only_index_does_not_offer_choices_to_apply(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE records SET decision='revisar'")
            db.execute(
                "INSERT INTO records "
                "(path,volume_root,kind,bytes,mtime_ns,candidate,decision) "
                "VALUES (?,?,?,?,?,?,?)",
                (r"C:\$Recycle.Bin\S-1-5-21-test\file.txt", "C:", "file",
                 10, 0, 1, "preservar"),
            )
        parsed = read_saved_index_choices(self.path)
        self.assertEqual(parsed["choices"], {})
        self.assertEqual(len(parsed["ignored_system_choices"]), 1)

    def test_importers_reject_lixeira_even_when_bypassing_sqlite_preview(self):
        old = r"C:\$Recycle.Bin\S-1-5-21-test\file.txt"
        valid = r"C:\Users\cliente\Documents\keep.txt"
        doc = {
            "schema": "pcro-index-choices-v1",
            "ready_for_format": False,
            "installation_authorized": False,
            "verified_backup": False,
            "contains_file_contents": False,
            "choices": {old: "preservar", valid: "preservar"},
        }
        exported = Path(self.temp.name) / "escolhas.json"
        exported.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Lixeira"):
            read_index_choices(exported)
        app = SimpleNamespace(choices={}, personal_paths=set(),
                              busy=False, deep_scan_running=False,
                              _on_change=Mock())
        # A crafted in-memory decision must also fail before applying valid ones.
        with self.assertRaisesRegex(ValueError, "Lixeira"):
            apply_imported_choices(app, {
                "choices": {valid.lower(): "keep", old.lower(): "skip"}
            })
        self.assertEqual(app.choices, {})
        self.assertEqual(app.personal_paths, set())
        app._on_change.assert_not_called()


if __name__ == "__main__":
    unittest.main()
