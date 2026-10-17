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

from file_index_ui import show_file_index, format_index_row


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
                    search_button = button("Pesquisar")
                    self.assertTrue(search_button.instate(["disabled"]))
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
                    self.assertFalse(search_button.instate(["disabled"]))
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

    def test_selected_volume_does_not_inventory_other_source(self):
        try:
            app = tk.Tk()
        except tk.TclError as err:
            if os.environ.get("PCRO_REQUIRE_TK") == "1":
                self.fail(f"Tk required: {err}")
            self.skipTest(str(err))
        app.withdraw()
        win = None
        with tempfile.TemporaryDirectory(prefix="PCRO-VOL-UI-") as tmp:
            try:
                root = Path(tmp)
                source_a, source_b = root / "volumeA", root / "volumeB"
                source_a.mkdir()
                source_b.mkdir()
                file_a, file_b = source_a / "a.txt", source_b / "b.txt"
                file_a.write_bytes(b"A nao modificar")
                file_b.write_bytes(b"B nao modificar")
                target = root / "apenas-volumeA.sqlite3"
                with (patch("file_index_ui.discover_local_roots",
                            return_value=[source_a, source_b]),
                      patch("file_index_ui.filedialog.asksaveasfilename",
                            return_value=str(target)),
                      patch("file_index_ui.messagebox.showerror") as errors):
                    win = show_file_index(app)
                    app.update()
                    def button(container, prefix):
                        return next(child for child in walk(container)
                            if isinstance(child, ttk.Button)
                            and str(child.cget("text")).startswith(prefix))
                    button(win, "ESCOLHER unidades").invoke()
                    app.update()
                    pickers = [w for w in win.winfo_children()
                               if isinstance(w, tk.Toplevel)]
                    self.assertEqual(len(pickers), 1)
                    picker = pickers[0]
                    boxes = [w for w in walk(picker)
                             if isinstance(w, ttk.Checkbutton)]
                    self.assertEqual(len(boxes), 2)
                    boxes[1].invoke()  # Only volumeA stays selected.
                    button(picker, "Confirmar unidades").invoke()
                    app.update()
                    button(win, "CRIAR índice").invoke()
                    deadline = time.monotonic() + 20
                    from inventory_index import FileMetadataIndex
                    finished = False
                    while time.monotonic() < deadline:
                        app.update()
                        if target.exists():
                            try:
                                db = FileMetadataIndex(target)
                                try:
                                    finished = (db.metadata().get("state")
                                                == "terminado_com_lacunas")
                                finally:
                                    db.close()
                                if finished:
                                    break
                            except Exception:
                                pass
                        time.sleep(.02)
                    self.assertTrue(finished, "Index did not finish")
                    app.update()
                    db = FileMetadataIndex(target)
                    try:
                        paths = {item["path"] for item in db.search()}
                        self.assertEqual(paths, {str(file_a)})
                    finally:
                        db.close()
                    self.assertEqual(file_a.read_bytes(), b"A nao modificar")
                    self.assertEqual(file_b.read_bytes(), b"B nao modificar")
                    errors.assert_not_called()
            finally:
                if win is not None and win.winfo_exists():
                    win.tk.call(win.protocol("WM_DELETE_WINDOW"))
                app.destroy()

    def test_directories_display_unmeasured_not_zero(self):
        row = format_index_row({
            "path": r"C:\\Games\\MeuJogo", "kind": "directory",
            "bytes": 0, "decision": "revisar",
        })
        self.assertEqual(row[1], "Pasta")
        self.assertEqual(row[2], "Não calculado")
        file_row = format_index_row({
            "path": r"C:\\Games\\MeuJogo\\save.dat", "kind": "file",
            "bytes": 0, "decision": "preservar",
        })
        self.assertEqual(file_row[1], "Arquivo")
        self.assertEqual(file_row[2], 0)


if __name__ == "__main__":
    unittest.main()
