"""User's main scenario: choosing a game in D: appears in preservation, and
identified C: saves remain visible without claiming a backup was made."""
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from app import App
from scan_sessions import cache_from_saved, merge_cache
from volume_paths import volume_of
from tk_helpers import track_tk_root


def widgets(widget):
    for item in widget.winfo_children():
        yield item
        yield from widgets(item)


def fake_report():
    return dict(schema='pcro-discovery-v1', roots=['C:/', 'D:/'],status='concluida',
                records=[dict(app_id='g42',app='Test Game',path='C:/Users/Test/Saves',
                              kind='Save local', evidence='Catálogo',confidence='candidato',edition=None),
                         dict(app_id='g42',app='Test Game',path='D:/SteamLibrary/Test Game',
                              kind='Pasta da instalação', evidence='Catálogo',confidence='candidato',edition=None)],
                apps=[dict(id='g42',name='Test Game',category='Jogo')],
                volume_stats={'C:':dict(files=10,directories=20),
                              'D:':dict(files=12,directories=15)},
                errors=[], skipped=[], unassociated_executables=[], directories=35,files=22)


class UnifiedGUI(TestCase):
    def test_d_game_selected_in_my_computer_shows_up_in_preservation_and_is_persisted(self):
        with patch.object(App, 'refresh_catalog', lambda self:None):
            app=App()
        track_tk_root(self, app)
        with tempfile.TemporaryDirectory() as temp:
            app.local_state=Path(temp)/'preferences.json'
            r=fake_report()
            app.deep_scan_report=r
            app.scan_reports_by_drive=cache_from_saved(r)
            # Rebuild home to simulate the resulting scan view; no actual scan.
            for child in app.home.winfo_children(): child.destroy()
            from deep_discovery_ui import show_deep_discovery
            with patch('deep_discovery_ui.local_drives',return_value=['C:/','D:/']):
                show_deep_discovery(app, container=app.home)
            app.navigate(app.home)
            app.update()
            tab=next(w for w in widgets(app.home) if isinstance(w,ttk.Notebook))
            tab.select(1)
            app.update()
            tree=next(w for w in widgets(app.home) if isinstance(w,ttk.Treeview))
            card_id=next(child for parent in tree.get_children()
                        for child in tree.get_children(parent)
                        if tree.item(child,'text') == 'Test Game')
            tree.selection_set(card_id)
            click=next(w for w in widgets(app.home) if isinstance(w,ttk.Button)
                       and w.cget('text')=='Manter selecionados')
            with patch('deep_discovery_ui.messagebox.askyesno', return_value=True):
                click.invoke()
            self.assertEqual(app.catalog_choices['deep:g42'],'keep')
            self.assertEqual(app.catalog_items['deep:g42']['observed_volumes'], ['D:'])
            self.assertTrue(app.local_state.exists())
            app.navigate(app.preservation)
            app.update()
            rows=[w for w in widgets(app.preservation) if isinstance(w,ttk.Treeview)]
            self.assertTrue(any('Test Game' in str(w.item(i,'text')) for w in rows for i in w.get_children()))
            from catalog_plan import selected_catalog_choices
            selected=selected_catalog_choices(app.catalog_choices,app.catalog_items)
            self.assertEqual(selected[0]['display_volume'],'D:')
            self.assertEqual(selected[0]['install_volume'],'SEM UNIDADE')
            self.assertEqual(selected[0]['backup_required_for_c'],[])
            # The cache contains the C candidate but it has not been approved.
            from unified_selection import index_cards, card_detail
            c=index_cards(r, app.catalog_items, app.catalog_choices, app.choices)['D:'][0]
            self.assertIn('C:/Users/Test/Saves',card_detail(c,app.catalog_items)['candidates'])
            self.assertFalse(card_detail(c,app.catalog_items)['confirmed'])
            # After restarting, the intent and observed volume survive.
            saved=__import__('json').loads(app.local_state.read_text())
            self.assertEqual(saved['catalog_choices']['deep:g42'],'keep')
            self.assertEqual(saved['catalog_snapshots']['deep:g42']['observed_volumes'],['D:'])


if __name__=='__main__':
    import unittest
    unittest.main()
