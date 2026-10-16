import os
import unittest
import tkinter as tk
from unittest.mock import patch


class OptimizationGUIV057Tests(unittest.TestCase):
    def test_optimization_is_one_main_section(self):
        from app import App
        try:
            with patch('app.App.refresh_catalog', lambda self: None):
                root=App()
        except tk.TclError:
            self.skipTest('Sem servidor gráfico')
        try:
            root.update()
            self.assertEqual(len(root.tabs.tabs()),10)  # expanded unified workflow
            root.navigate(root.optimization)
            root.update_idletasks()
            self.assertEqual(root.tabs.select(),str(root.optimization))
            self.assertEqual(len(root.optimizer_panel.tabs.tabs()),6)
            self.assertFalse(root.optimizer_panel.running)
            self.assertIsNone(root.optimizer_panel.report)
            self.assertFalse(root.optimizer_panel.power_journal.exists())
            root.optimizer_panel.tabs.select(3)
            root.update_idletasks()
            self.assertTrue(root.optimizer_panel.btn_apply.winfo_ismapped())
        finally:
            root.destroy()

    def test_no_power_switch_on_launch(self):
        from unittest.mock import patch
        from app import App
        try:
            with patch('optimization_engine._run') as command, patch('app.App.refresh_catalog', lambda self: None):
                root=App()
                root.update_idletasks()
                command.assert_not_called()
        except tk.TclError:
            self.skipTest('Sem servidor gráfico')
        else:
            root.destroy()

if __name__ == '__main__':
    unittest.main()
