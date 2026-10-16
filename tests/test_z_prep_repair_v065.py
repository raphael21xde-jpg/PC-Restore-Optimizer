"""v0.6.5 regression: misclassified game, discriminating imported JSON, read-only C audit."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from tkinter import ttk
from app import App
from preservation_audit import build_audit
from preservation_preflight import prepare_c_preflight
from inventory_import import read_inventory, explain_document
from workflow_ui import show_c_preflight


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class Repair065(TestCase):
    def test_manual_approved_deep_app_displayed_as_associated_not_verified(self):
        # Reproduces real class mismatch: deep-discovered game was stored as app.
        key='deep:forza6'
        save=r'C:\Users\rapha\AppData\Local\ForzaHorizon6'
        plan=build_audit({save:'keep'}, {key:'keep'},
            {key:{'kind':'app','name':'Forza Horizon 6',
                  'install_location':r'D:\Games\ForzaHorizon6',
                  'paths':[save], 'observed_volumes':['D:']}},
            approved_paths={key:[save]})
        self.assertEqual(plan['selection_metrics']['selected_games_apps'],1)
        self.assertEqual(plan['selection_metrics']['backup_required_paths_c'],1)
        self.assertEqual(len(plan['game_save_candidates']),1)
        link=plan['game_save_candidates'][0]
        self.assertEqual(link['volume'],'C:')
        self.assertEqual(link['install_volume'],'D:')
        self.assertEqual(link['confidence'],'CONFIRMADO PELO USUÁRIO')
        self.assertTrue(link['classification_pending'])
        self.assertFalse(link['backup_verified'])
        self.assertFalse(plan['installation_authorized'])

    def test_unknown_app_unapproved_never_shows_link(self):
        key='deep:x'
        selected={key:'keep'}
        records={key:{'kind':'app','name':'X','paths':['C:/untrusted']}}
        self.assertEqual(build_audit({},selected,records)['game_save_candidates'],[])

    def test_unselected_approved_app_never_shows_link(self):
        item={'x':{'kind':'app','name':'X'}}
        self.assertEqual(build_audit({}, {'x':'skip'}, item, {'x':['C:/Data']})['game_save_candidates'],[])

    def test_case_and_separator_duplicate_dedupe(self):
        key='g'
        item={key:dict(kind='game',name='Game',install_location='D:/Game',paths=[])}
        report=build_audit({}, {key:'keep'},item,
                   {key:[r'C:\Users\A\Saves', 'c:/users/a/saves']})
        self.assertEqual(len(report['game_save_candidates']),1)

    def test_inventory_import_guides_instead_of_generic_error(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'preferencias-v05.json'
            path.write_text(json.dumps({'choices':{},'catalog_choices':{}}), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'Preservação > Importar escolhas'):
                read_inventory(path)
            path.write_text(json.dumps({'schema':'pcro-preservation-dry-run-v1'}), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'Plano de preservação'):
                read_inventory(path)
            path.write_text(json.dumps({'schema':'pcro-discovery-v1', 'roots':['F:/'],
                'records':[], 'apps':[], 'status':'concluida',
                'volume_stats':{'F:':{'directories':1,'files':2}},
                'errors':[],'skipped':[]}), encoding='utf8')
            cache=read_inventory(path)
            self.assertEqual(list(cache),['F:'])

    def test_preflight_never_checks_content_or_claims_backup(self):
        with patch('preservation_preflight._check_one') as probe:
            probe.side_effect=lambda p: {'path':p, 'status':'LOCALIZADO'}
            report=prepare_c_preflight(['C:/Users/R/Save','c:\\users\\r\\save','D:/Other'])
            self.assertEqual(report['selected_paths'],2)
            self.assertEqual(probe.call_count,2)
            self.assertFalse(report['backup_verified'])
            self.assertFalse(report['restore_verified'])
            self.assertFalse(report['ready_for_format'])

    def test_preflight_unsafe_volume_is_blocked(self):
        report=prepare_c_preflight(['D:/Data','C:/'])
        self.assertTrue(all(row['status']=='BLOQUEADO' for row in report['entries']))

    def test_preflight_does_not_enumerate_directory(self):
        with patch('preservation_preflight.os.lstat') as lstat, \
             patch('preservation_preflight.os.scandir') as scandir:
            import stat
            lstat.return_value=type('Info',(),{'st_mode':stat.S_IFDIR, 'st_size':0,'st_file_attributes':0})()
            row=prepare_c_preflight([r'C:\Users\rapha\Saved Games\GOW'])['entries'][0]
            self.assertEqual(row['status'],'LOCALIZADO')
            self.assertIsNone(row['size_bytes'])
            scandir.assert_not_called()

    def test_live_ui_has_read_only_check_and_new_link(self):
        with patch.object(App,'refresh_catalog',lambda self:None):
            app=App()
        self.addCleanup(app.destroy)
        key='deep:forza'
        path=r'C:\Users\R\Forza'
        app.catalog_items={key:dict(kind='app',name='Forza',install_location='D:/Games/Forza',paths=[path])}
        app.catalog_choices={key:'keep'}
        app.approved_catalog_paths={key:[path]}
        app.choices={path:'keep'}
        app.update_preservation_preview()
        tree=next(w for w in descendants(app.preservation)
                  if isinstance(w,ttk.Treeview) and 'situation' in w['columns'])
        lines=[tree.item(row,'values') for row in tree.get_children()]
        self.assertTrue(any('Forza' in t[0] and 'Tipo do item a conferir' in t[3]
                            for t in lines))
        btn=next(w for w in descendants(app.preservation)
                 if isinstance(w,ttk.Button) and w.cget('text')=='Conferir fontes do C: (sem copiar)')
        with patch('workflow_ui.prepare_c_preflight',return_value={
             'selected_paths':1,'checked_paths':1,'not_checked':0,
             'entries':[{'path':path,'status':'LOCALIZADO','file_type':'pasta','note':'Metadados'}]}):
            btn.invoke()
            from tkinter import Toplevel
            window=next(w for w in app.winfo_children()
                        if isinstance(w,Toplevel) and w.title().startswith('Conferência dos caminhos'))
            self.assertTrue(window.winfo_exists())
            window.destroy()
