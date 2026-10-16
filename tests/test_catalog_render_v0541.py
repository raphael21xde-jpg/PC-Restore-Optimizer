"""Regression: the games/apps tables must be children of their own scrolling panel.

Run with a graphical display (e.g. xvfb-run on Linux); skips gracefully headless.
"""
import tkinter as tk
from unittest import TestCase, mock


class CatalogRenderTest(TestCase):
    def test_catalog_lists_are_visible_and_filter_reversible(self):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest('Display server not available')

        from app import App
        with mock.patch.object(App, 'refresh_catalog', lambda self: None):
            app = App()
        try:
            app.geometry('1300x850')
            app.navigate(app.catalog)
            app._catalog_game('steam:one', 'Witcher 3', 'Steam', [], [], {})
            app._catalog_game('steam:two', 'Counter-Strike 2', 'Steam', [], [], {})
            app._catalog_app('app:one', 'Mouse Driver', 'Periférico', 'Instalado')
            app.update()
            self.assertEqual(str(app.games_tree.master), str(app.games_tree.winfo_parent()))
            self.assertTrue(app.games_tree.winfo_ismapped())
            self.assertTrue(app.games_tree.bbox('steam:one'))
            app.catalog_filter.set('Witcher')
            app.update()
            self.assertEqual(app.games_tree.get_children(), ('steam:one',))
            app.catalog_filter.set('')
            app.update()
            self.assertEqual(len(app.games_tree.get_children()), 2)
            # The apps table must be visible after switching nested tabs.
            app.apps_tree.master.master.master.select(1)
            app.update()
            self.assertTrue(app.apps_tree.winfo_ismapped())
            self.assertTrue(app.apps_tree.bbox('app:one'))
        finally:
            app.destroy()
