"""Regressões da arquitetura de seleção unificada (somente leitura no PC)."""
import json
import tempfile
import tkinter as tk
from pathlib import Path
from unittest import TestCase, mock
from tk_helpers import track_tk_root


class UnifiedSelectionTests(TestCase):
    def setUp(self):
        try:
            probe = tk.Tk();probe.withdraw();probe.destroy()
        except tk.TclError:
            self.skipTest('Display server not available')
        from app import App
        drives = mock.patch('app.DISKS', ['C'])
        drives.start()
        self.addCleanup(drives.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with mock.patch.object(App, 'refresh_catalog', lambda self: None):
            with mock.patch.object(App, '_restore_choices', lambda self: None):
                self.app=App()
        self.app.local_state=Path(self.temp.name)/'preferences.json'
        track_tk_root(self, self.app)
        self.app.update()

    def test_one_main_selection_page_and_four_categories(self):
        app=self.app
        self.assertGreaterEqual(len(app.tabs.tabs()),6)  # nova seção de otimização da v0.5.7
        self.assertEqual([app.catalog_tabs.tab(x,'text') for x in app.catalog_tabs.tabs()],
                         ['Jogos','Aplicativos','Arquivos pessoais','Navegadores'])
        self.assertNotIn('inventory',app.nav_buttons)
        self.assertNotIn('browsers',app.nav_buttons)
        for sub in [app.inventory,app.browsers]:
            app.navigate(sub);app.update()
            self.assertEqual(app.tabs.select(),str(app.catalog))
            self.assertEqual(app.catalog_tabs.select(),str(sub))

    def test_manual_file_enters_one_plan_without_searching_disks(self):
        app=self.app
        file=Path(self.temp.name)/'important.txt';file.write_text('my data')
        with mock.patch('app.drive_of', return_value='C:'), mock.patch('app.DISKS', ['C']):
            app._add_path(str(file))
        key=__import__('app').norm(str(file))
        self.assertEqual(app.choices[key],'keep')
        self.assertIn(key,app.tree.get_children())
        app.tree.selection_set(key);app.set_choice('skip')
        self.assertEqual(app.choices[key],'skip')
        self.assertTrue(file.exists())
        app.tree.selection_set(key);app.remove_personal_item()
        self.assertNotIn(key,app.choices)
        self.assertTrue(file.exists())

    def test_catalog_game_links_recognized_save_without_individual_check(self):
        app=self.app
        path=Path(self.temp.name)/'saves';path.mkdir()
        (path/'savegame.sav').write_text('saved')
        app._catalog_game('steam:42','Test Game','Steam',[str(path)],[],{})
        app.games_tree.selection_set('steam:42')
        app.mark_catalog('game','keep')
        self.assertEqual(app.catalog_choices['steam:42'],'keep')
        self.assertEqual(app.choices[__import__('app').norm(str(path))],'keep')
        self.assertIn(__import__('app').norm(str(path)),app.auto_save_paths)
        self.assertNotIn(__import__('app').norm(str(path)),app.personal_paths)

    def test_selected_browser_is_plan_metadata_not_password_extraction(self):
        from browser_vault import BrowserProfile
        app=self.app
        path=Path(self.temp.name)/'profile';path.mkdir()
        (path/'Preferences').write_text('{}')
        browser=BrowserProfile('Google Chrome','Default',path)
        app.browser_profiles=[browser]
        app.browser_picker['values']=['Google Chrome - Default']
        app.browser_picker.current(0)
        app._browser_selected()
        app.browser_want_keep.set(True)
        app._mark_browser_keep()
        app._save_choices()
        data=json.loads(app.local_state.read_text())
        self.assertEqual(len(data['browser_keep_paths']),1)
        self.assertNotIn('password',json.dumps(data).lower())
        from backup_core import Plan
        app._preview_ready(Plan())
        report=app.summary.get('1.0','end')
        self.assertIn('COFRE NÃO CONFIRMADO',report)
        self.assertIn('NAVEGADORES ESCOLHIDOS',report)
        self.assertIn('nenhuma cópia realizada',report)

    def test_old_preferences_import_still_supported(self):
        app=self.app
        file=Path(self.temp.name)/'family.jpg';file.write_bytes(b'image')
        from app import norm
        app.local_state.write_text(json.dumps({'choices':{str(file):'keep'},'catalog_choices':{'steam:1':'keep'},'destination':'C:/Backups'}))
        app._restore_choices()
        self.assertIn(norm(str(file)),app.personal_paths)
        self.assertEqual(app.catalog_choices['steam:1'],'keep')
        self.assertEqual(app.dest.get(),'C:/Backups')

