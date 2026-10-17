"""Real Tk smoke test for the searchable metadata index; synthetic roots only."""
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import os
import unittest
from unittest.mock import patch

from file_index_ui import show_file_index


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


class TestFileIndexUI(unittest.TestCase):
    def test_create_search_choose_export_in_small_resizable_window(self):
        try:
            app = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("PCRO_REQUIRE_TK") == "1":
                self.fail(f"Tk required for UI validation: {exc}")
            self.skipTest(f"Display unavailable: {exc}")
        app.withdraw()
        win = None
        with tempfile.TemporaryDirectory(prefix="PCRO-INDEX-UI-") as tmp:
            try:
                root = Path(tmp)
                source = root / "source"
                source.mkdir()
                target_file = source / "osu-beatmap.dat"
                target_file.write_bytes(b"beatmap fixture")
                index_file = root / "test-index.sqlite3"
                choices_file = root / "choices.json"
                with (patch("file_index_ui.discover_local_roots", return_value=[source]),
                      patch("file_index_ui.filedialog.asksaveasfilename",
                            side_effect=[str(index_file), str(choices_file)]),
                      patch("file_index_ui.messagebox.showerror") as errors,
                      patch("file_index_ui.messagebox.showinfo")):
                    win = show_file_index(app)
                    win.geometry("720x520+10+10")
                    app.update()
                    self.assertEqual(tuple(int(x) for x in win.resizable()), (1, 1))
                    buttons = [w for w in walk(win) if isinstance(w, ttk.Button)]
                    def button(prefix):
                        return next(b for b in buttons if str(b.cget("text")).startswith(prefix))
                    for text in ("CRIAR índice", "ABRIR índice", "Exportar escolhas",
                                 "Marcar PRESERVAR", "NÃO COPIAR", "Revisar depois"):
                        self.assertTrue(button(text).winfo_ismapped(), text)
                    button("CRIAR índice").invoke()
                    deadline = time.monotonic() + 20
                    trees = [w for w in walk(win) if isinstance(w, ttk.Treeview)]
                    self.assertEqual(len(trees), 1)
                    tree = trees[0]
                    while not tree.get_children() and time.monotonic() < deadline:
                        app.update()
                        time.sleep(.015)
                    app.update()
                    self.assertTrue(index_file.exists(), "SQLite index not generated")
                    self.assertEqual(len(tree.get_children()), 1)
                    tree.selection_set(tree.get_children()[0])
                    button("Marcar PRESERVAR").invoke()
                    button("Exportar escolhas").invoke()
                    self.assertTrue(choices_file.exists())
                    choices = json.loads(choices_file.read_text(encoding="utf-8"))
                    self.assertEqual(choices["choices"][str(target_file)], "preservar")
                    self.assertFalse(choices["ready_for_format"])
                    self.assertFalse(choices["verified_backup"])
                    self.assertEqual(target_file.read_bytes(), b"beatmap fixture")
                    errors.assert_not_called()
            finally:
                # Follow the window's real close handler while the temporary
                # folder still exists: it closes SQLite before Windows cleanup.
                if win is not None and win.winfo_exists():
                    close_command = win.protocol("WM_DELETE_WINDOW")
                    win.tk.call(close_command)
                app.destroy()


if __name__ == "__main__":
    unittest.main()
