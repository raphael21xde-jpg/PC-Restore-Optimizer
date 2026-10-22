"""Tk regression for the paginated real metadata scanner and newest test controls."""
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from selective_backup_ui import show_selective_backup
from tk_helpers import track_tk_root


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


class TestPaginatedInventoryGUI(unittest.TestCase):
    def test_new_tab_mini_window_and_actual_paged_scan(self):
        try:
            app = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("PCRO_REQUIRE_TK") == "1":
                self.fail(f"Tk display required: {exc}")
            self.skipTest(f"No display: {exc}")
        app.withdraw()
        track_tk_root(self, app)
        window = None
        try:
            with tempfile.TemporaryDirectory(prefix="PCRO-UI-PAGE-") as tmp:
                source = Path(tmp) / "volume"
                source.mkdir()
                for i in range(19):
                    (source / f"arquivo-{i:02d}.txt").write_bytes(b"fixture")
                out = Path(tmp) / "relatorio.json"
                with (patch("selective_backup_ui.discover_local_roots",
                            return_value=[source]),
                      patch("selective_backup_ui.filedialog.asksaveasfilename",
                            return_value=str(out)),
                      patch("selective_backup_ui.messagebox.showerror") as errors,
                      patch("selective_backup_ui.messagebox.showinfo")):
                    window = show_selective_backup(app, {"requires_verified_backup": []})
                    window.geometry("720x520+5+5")
                    app.update()
                    book = next(w for w in widgets(window) if isinstance(w, ttk.Notebook))
                    labels = [book.tab(t, "text") for t in book.tabs()]
                    self.assertIn("Novos #44–46", labels)
                    self.assertIn("Novos #38–40", labels)
                    book.select(labels.index("Novos #44–46"))
                    app.update()
                    buttons = [w for w in widgets(window) if isinstance(w, ttk.Button)]
                    for n in (44, 45, 46):
                        button = next(w for w in buttons
                                      if f"Autoteste #{n}:" in str(w.cget("text")))
                        self.assertTrue(button.winfo_ismapped(), str(n))
                    start = next(w for w in buttons
                                 if w.cget("text") == "Inventário real: NOVA sessão de leitura")
                    export = next(w for w in buttons if w.cget("text") == "Exportar relatório")
                    self.assertTrue(export.winfo_ismapped())
                    start.invoke()
                    limit = time.monotonic() + 15
                    while start.instate(["disabled"]) and time.monotonic() < limit:
                        app.update()
                        time.sleep(.01)
                    app.update()
                    self.assertFalse(start.instate(["disabled"]))
                    errors.assert_not_called()
                    export.invoke()
                    report = json.loads(out.read_text(encoding="utf-8"))
                    self.assertEqual(report["schema"], "pcro-inventario-paginado-v1")
                    self.assertEqual(report["entries_examined"], 19)
                    self.assertTrue(report["finished_current_session"])
                    self.assertEqual(report["status"], "concluido_escopo_observado")
                    self.assertFalse(report["ready_for_format"])
                    self.assertFalse(report["writes_performed"])
        finally:
            if window is not None and window.winfo_exists():
                window.destroy()
            app.destroy()


if __name__ == "__main__":
    unittest.main()
