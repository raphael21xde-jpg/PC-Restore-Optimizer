"""Safe import/export bridge integration tests; never copy or delete sources."""
import json
import ntpath
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from index_choices_bridge import read_index_choices, preview_import, apply_imported_choices


def example(choices, **overrides):
    result = {
        "schema": "pcro-index-choices-v1",
        "ready_for_format": False,
        "installation_authorized": False,
        "verified_backup": False,
        "contains_file_contents": False,
        "index_state": "terminado_com_lacunas",
        "choices": choices,
    }
    result.update(overrides)
    return result


def pathlike(*parts):
    return "\\".join(parts)


class DummyApp:
    def __init__(self):
        self.choices = {r"c:\Users\cliente\Documentos\atual.txt": "skip"}
        self.personal_paths = set()
        self.busy = False
        self.deep_scan_running = False
        self.notifications = 0
    def _on_change(self):
        self.notifications += 1


class TestIndexChoicesBridge(unittest.TestCase):
    def parse(self, doc):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "escolhas.json"
            file.write_text(json.dumps(doc), encoding="utf-8")
            return read_index_choices(file)

    def test_preview_counts_and_conflicts_without_writing(self):
        document = example({
            r"C:\Users\cliente\Documentos\atual.txt": "preservar",
            r"D:\Games\osu\Songs\map.osz": "preservar",
            r"G:\Data\cache\temporary.bin": "nao_copiar",
        })
        parsed = self.parse(document)
        app = DummyApp()
        plan = preview_import(app, parsed)
        self.assertEqual(plan["keep"], 2)
        self.assertEqual(plan["skip"], 1)
        self.assertEqual(plan["conflicts"], 1)
        self.assertEqual(app.notifications, 0)

    def test_apply_requires_external_confirmation_and_invalidates_old_plan(self):
        app = DummyApp()
        parsed = self.parse(example({
            r"C:\Users\cliente\Documentos\atual.txt": "preservar",
            r"D:\Games\osu\Songs\map.osz": "preservar",
        }))
        # Stand-in for Windows backup_core.norm during Linux CI tests.
        with patch("index_choices_bridge.norm", side_effect=lambda s: ntpath.normcase(ntpath.normpath(s))):
            result = apply_imported_choices(app, parsed)
        self.assertEqual(result["applied"], 2)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(app.notifications, 1)
        self.assertTrue(result["backup_started"] is False)
        self.assertFalse(result["installation_authorized"])
        self.assertEqual(app.choices[r"c:\users\cliente\documentos\atual.txt"], "keep")
        self.assertIn(r"d:\games\osu\songs\map.osz", app.personal_paths)

    def test_invalid_schema_flags_decisions_and_paths_fail_before_any_change(self):
        invalid = [
            example({r"C:\a.txt": "apagar"}),
            example({r"\\servidor\file": "preservar"}),
            example({r"C:relativo.txt": "preservar"}),
            example({r"C:\\": "preservar"}),
            example({r"C:\temp\..\file.txt": "preservar"}),
            example({r"C:\temp\a.txt:ads": "preservar"}),
            example({r"C:\users\file.txt": "preservar"}, ready_for_format=True),
            example({r"C:\users\file.txt": "preservar"}, verified_backup=True),
            example({r"C:\users\file.txt": "preservar"}, installation_authorized=True),
            {"schema": "pcro-old", "choices": {}},
        ]
        for doc in invalid:
            with self.subTest(doc=doc):
                with self.assertRaises((ValueError, TypeError)):
                    self.parse(doc)

    def test_case_insensitive_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(example({
                r"C:\Users\CLIENTE\Doc.txt": "preservar",
                r"c:\users\cliente\doc.txt": "nao_copiar",
            }))

    def test_folder_rule_and_specific_file_exception_reach_preview(self):
        folder = r"C:\Users\cliente\Saved Games"
        nested = folder + r"\Demo\settings.ini"
        parsed = self.parse(example({
            folder: "preservar",
            nested: "nao_copiar",
        }))
        app = DummyApp()
        preview = preview_import(app, parsed)
        self.assertEqual((preview["keep"], preview["skip"]), (1, 1))
        with patch("index_choices_bridge.norm", side_effect=lambda s: ntpath.normcase(ntpath.normpath(s))):
            result = apply_imported_choices(app, parsed)
        self.assertEqual(result["applied"], 2)
        self.assertEqual(app.choices[ntpath.normcase(folder)], "keep")
        self.assertEqual(app.choices[ntpath.normcase(nested)], "skip")
        self.assertEqual(app.notifications, 1)
        self.assertFalse(result["backup_started"])

    def test_busy_does_not_mutate_app(self):
        app = DummyApp()
        app.busy = True
        parsed = self.parse(example({r"C:\Users\CLIENTE\Doc.txt": "preservar"}))
        with self.assertRaises(RuntimeError):
            apply_imported_choices(app, parsed)
        self.assertEqual(app.notifications, 0)

    def test_source_backup_folders_remain_unread(self):
        # Parsing only reads the explicitly selected JSON file, never source paths.
        parsed = self.parse(example({r"D:\Users\alguem\Movies\video.mkv": "nao_copiar"}))
        self.assertEqual(parsed["choices"][r"d:\users\alguem\movies\video.mkv"], "skip")


if __name__ == "__main__":
    unittest.main()
