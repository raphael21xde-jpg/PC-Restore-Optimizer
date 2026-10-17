"""Tk smoke tests for withdrawing an obsolete file choice without deleting data."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from workflow_ui import build_preservation
from app import App
from backup_core import Plan


def descend(widget):
    for child in widget.winfo_children():
        yield child
        yield from descend(child)


class PreservationRemoveChoiceUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("PCRO_REQUIRE_TK") == "1":
                self.fail(f"Janela Tk obrigatória: {exc}")
            self.skipTest(f"Tela indisponível: {exc}")
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.preservation = ttk.Frame(self.app)
        self.app.preservation.pack()
        self.old = r"C:\$Recycle.Bin\S-1-5-21-test\osu\bg.jpg"
        self.keep = r"C:\Users\exemplo\PCRO-TESTE-UI\preservar.txt"
        self.ignored = r"C:\$Recycle.Bin\S-1-5-21-test\nao-preservar.jpg"
        self.app.choices = {self.old: "keep", self.keep: "keep", self.ignored: "skip"}
        self.app.personal_paths = set(self.app.choices)
        self.app.auto_save_paths = set()
        self.app.catalog_choices = {}
        self.app.catalog_items = {}
        self.app._on_change = Mock()
        self.app.import_previous_choices = Mock()
        self.app.home = ttk.Frame(self.app)
        self.app.review = ttk.Frame(self.app)
        self.app.navigate = Mock()
        build_preservation(self.app)
        self.table = next(
            t for t in descend(self.app.preservation)
            if isinstance(t, ttk.Treeview) and "path" in t["columns"])
        self.remove_button = next(
            t for t in descend(self.app.preservation)
            if isinstance(t, ttk.Button)
            and str(t.cget("text")).startswith("Retirar escolha selecionada"))
        self.next_button = next(
            t for t in descend(self.app.preservation)
            if isinstance(t, ttk.Button)
            and str(t.cget("text")).startswith("Próximo: revisar backup"))
        self.app.update()

    def select_path(self, path):
        rows = [
            child
            for parent in self.table.get_children()
            for child in self.table.get_children(parent)
            if self.table.set(child, "path") == path
        ]
        self.assertEqual(len(rows), 1)
        self.table.selection_set(rows[0])

    def test_removes_only_obsolete_selection_and_refreshes_preview(self):
        self.select_path(self.old)
        with patch("workflow_ui.messagebox.askyesno", return_value=True) as confirm:
            self.remove_button.invoke()
        confirm.assert_called_once()
        self.assertNotIn(self.old, self.app.choices)
        self.assertNotIn(self.old, self.app.personal_paths)
        self.assertEqual(self.app.choices[self.keep], "keep")
        self.assertEqual(self.app.choices[self.ignored], "skip")
        self.assertEqual(
            self.app.last_preservation_audit["selection_metrics"]["backup_required_paths_c"], 1)
        self.app._on_change.assert_called_once()

    def test_cancel_keeps_every_choice_untouched(self):
        self.select_path(self.old)
        before = dict(self.app.choices)
        with patch("workflow_ui.messagebox.askyesno", return_value=False):
            self.remove_button.invoke()
        self.assertEqual(self.app.choices, before)
        self.app._on_change.assert_not_called()

    def test_parent_row_is_not_a_removable_choice(self):
        self.table.selection_set(self.table.get_children()[0])
        with patch("workflow_ui.messagebox.showwarning") as warning:
            self.remove_button.invoke()
        warning.assert_called_once()
        self.assertEqual(len(self.app.choices), 3)
        self.app._on_change.assert_not_called()

    def test_preservation_advances_directly_to_review(self):
        self.next_button.invoke()
        self.app.navigate.assert_called_once_with(self.app.review)
        self.assertEqual(len(self.app.choices), 3)

    def test_automatically_associated_save_is_not_removed_silently(self):
        self.app.auto_save_paths.add(self.old)
        self.select_path(self.old)
        with patch("workflow_ui.messagebox.showwarning") as warning:
            self.remove_button.invoke()
        warning.assert_called_once()
        self.assertIn(self.old, self.app.choices)
        self.app._on_change.assert_not_called()


class RecycleBinPreflightTests(unittest.TestCase):
    def test_recycle_bin_choice_blocks_backup_not_original_data(self):
        """An obsolete Recycle Bin keep rule is never copied unnoticed."""
        with tempfile.TemporaryDirectory(prefix="PCRO-REVIEW-PREFLIGHT-") as folder:
            dummy = SimpleNamespace(dest=SimpleNamespace(get=lambda: folder))
            plan = Plan(selected=[r"C:\\$Recycle.Bin\\SID\\trashed-file.osz"])
            issues = App._preflight(dummy, plan)
            self.assertTrue(any("Lixeira" in issue for issue in issues), issues)
            # Preview remains non-destructive: never modifies any original.
            plan.selected = [r"C:\\Users\\example\\PCRO-TESTE-UI\\preservar.txt"]
            clean = App._preflight(dummy, plan)
            self.assertFalse(any("Lixeira" in issue for issue in clean), clean)


if __name__ == "__main__":
    unittest.main()
