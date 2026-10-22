"""Real Tk usability regression: compact window, tabs and persistent actions."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from tk_helpers import track_tk_root


class TestBackupWindowUsability(unittest.TestCase):
    def test_small_window_latest_tests_and_export(self):
        import tkinter as tk
        from tkinter import ttk
        from selective_backup_ui import show_selective_backup

        try:
            app = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get('PCRO_REQUIRE_TK') == '1':
                self.fail(f'Tk obrigatório: {exc}')
            self.skipTest(f'Sem display Tk: {exc}')
        app.withdraw()
        track_tk_root(self, app)
        window = None

        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)

        try:
            with tempfile.TemporaryDirectory(prefix='PCRO-UI-TEST-') as temp:
                output = Path(temp) / 'resultado-autoteste39.json'
                fake_report = {
                    'schema': 'pcro-autoteste-bateria-v39',
                    'status': 'aprovado',
                    'ready_for_format': False,
                    'real_user_backups_accessed': False,
                }
                with (patch('selective_backup_ui.run_readonly_inventory_autotest',
                            return_value=fake_report) as scan,
                      patch('selective_backup_ui.filedialog.asksaveasfilename',
                            return_value=str(output)),
                      patch('selective_backup_ui.messagebox.showerror') as errors,
                      patch('selective_backup_ui.messagebox.showinfo')):
                    window = show_selective_backup(app, {'requires_verified_backup': []})
                    window.geometry('720x520+10+10')
                    app.update()
                    self.assertEqual(tuple(int(x) for x in window.resizable()), (1, 1))
                    notebooks = [w for w in widgets(window) if isinstance(w, ttk.Notebook)]
                    self.assertEqual(len(notebooks), 1)
                    tabs = notebooks[0]
                    labels = [tabs.tab(x, 'text') for x in tabs.tabs()]
                    self.assertIn('Novos #38–40', labels)
                    tabs.select(labels.index('Novos #38–40'))
                    app.update()
                    buttons = [w for w in widgets(window) if isinstance(w, ttk.Button)]
                    for number in (38, 39, 40):
                        button = next(w for w in buttons
                                      if f'Autoteste #{number}:' in str(w.cget('text')))
                        self.assertTrue(button.winfo_ismapped(),
                                        f'Autoteste #{number} inacessível na aba recente')
                        self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                             window.winfo_rootx() + window.winfo_width()+2)
                    export = next(w for w in buttons if w.cget('text') == 'Exportar relatório')
                    cancel = next(w for w in buttons if w.cget('text') == 'Cancelar operação')
                    self.assertTrue(export.winfo_ismapped())
                    self.assertTrue(cancel.winfo_ismapped())
                    self.assertLessEqual(export.winfo_rooty() + export.winfo_height(),
                                         window.winfo_rooty() + window.winfo_height()+2)

                    button = next(w for w in buttons if 'Autoteste #39:' in str(w.cget('text')))
                    button.invoke()
                    deadline = time.monotonic()+15
                    while (scan.call_count == 0 or button.instate(['disabled'])) and time.monotonic()<deadline:
                        app.update()
                        time.sleep(.01)
                    app.update()
                    scan.assert_called_once()
                    self.assertFalse(button.instate(['disabled']))
                    errors.assert_not_called()
                    export.invoke()
                    self.assertTrue(output.exists())
                    report = json.loads(output.read_text(encoding='utf-8'))
                    self.assertEqual(report['schema'], fake_report['schema'])
        finally:
            if window is not None and window.winfo_exists():
                window.destroy()
            app.destroy()


if __name__ == '__main__':
    unittest.main()
