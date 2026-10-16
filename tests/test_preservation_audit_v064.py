"""v0.6.4 regressions: audited selections, cross-volume confirmed saves and scan gaps."""
import tempfile
import tkinter as tk
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from tkinter import ttk

from preservation_audit import build_audit
from game_links import infer_links
from scan_gaps import report_by_drive
from app import App
from workflow_ui import show_scan_gaps


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


class AuditTests(TestCase):
    def test_confirmed_gow_save_survives_presentation_with_two_units(self):
        key = 'steam:2322010'
        save = 'C:/Users/Test/Saved Games/God of War Ragnarök'
        items = {key: {'kind': 'game', 'name': 'God of War Ragnarök',
                       'install_location': 'D:/SteamLibrary/steamapps/common/God of War Ragnarok',
                       'paths': [save], 'possible_paths': ['C:/Users/Test/Other']}}
        audit = build_audit({save:'keep'}, {key:'keep'}, items,
                            approved_paths={key:[save]}, game_saves={})
        self.assertEqual(audit['selection_metrics']['selected_games_apps'], 1)
        self.assertEqual(audit['selection_metrics']['explicit_keep_paths'], 1)
        self.assertEqual(audit['selection_metrics']['backup_required_paths_c'], 1)
        self.assertEqual(audit['requires_verified_backup'], [save])
        link = audit['game_save_candidates'][0]
        self.assertEqual(link['install_volume'], 'D:')
        self.assertEqual(link['volume'], 'C:')
        self.assertEqual(link['relation'], 'ENTRE UNIDADES')
        self.assertEqual(link['confidence'], 'CONFIRMADO PELO USUÁRIO')
        self.assertFalse(link['backup_verified'])
        self.assertTrue(link['needs_backup_if_c_formatted'])
        self.assertNotIn('C:/Users/Test/Other', [l['data_path'] for l in audit['game_save_candidates']])

    def test_saves_without_manual_confirm_are_review_only(self):
        key='game-1'
        path='C:/Users/A/Saved Games/game1'
        audit=build_audit({}, {key:'keep'}, {key:dict(kind='game',name='Example',
                            install_location='D:/Games/Example',paths=[path])},
                          game_saves={key:[path]})
        self.assertEqual(audit['game_save_candidates'][0]['confidence'],'REVISAR')
        self.assertEqual(audit['selection_metrics']['confirmed_user_links'],0)
        self.assertEqual(audit['selection_metrics']['possible_links_to_review'],1)
        self.assertFalse(audit['deletions_authorized'])
        self.assertFalse(audit['installation_authorized'])

    def test_no_double_count_same_folder_two_variants(self):
        key='g'
        save='C:/Users/A/Saves/Test'
        report=build_audit({save:'keep'}, {key:'keep'},
                  {key:dict(name='Example',kind='game',install_location='D:/Games',paths=[save])},
                  approved_paths={key:[save.replace('/','\\')]}, game_saves={key:[save]})
        self.assertEqual(len(report['requires_verified_backup']),1)
        self.assertEqual(len(report['game_save_candidates']),1)
        self.assertFalse(report['deletions_authorized'])

    def test_unknown_install_volume_not_claimed(self):
        report=build_audit({}, {'unknown':'keep'},
                     {'unknown': dict(name='Unknown Game',kind='game',paths=[],observed_volumes=['D:'])})
        self.assertEqual(report['catalog_selections'][0]['display_volume'],'D:')
        self.assertFalse(report['catalog_selections'][0]['installation_confirmed'])
        self.assertEqual(report['game_save_candidates'],[])

    def test_unselected_game_links_do_not_pollute_preservation(self):
        items={'kept':dict(kind='game',name='Kept',paths=[],install_location='D:/Kept'),
               'removed':dict(kind='game',name='Removed',paths=[],install_location='F:/Removed')}
        report=build_audit({}, {'kept':'keep', 'removed':'skip'},items,
                 approved_paths={'removed':['C:/secrets']})
        self.assertEqual(report['game_save_candidates'],[])


class GapTests(TestCase):
    def test_split_c_d_and_non_volume_errors(self):
        report={'scanned_drives':['C:','D:'], 'volume_stats':{'C:':{},'D:':{}},
            'status':'concluida_com_lacunas',
            'errors':[{'path':'C:/Locked','reason':'Acesso negado'},
                      {'path':'D:/Nope','reason':'Não encontrado'},
                      {'path':'Windows metadata','reason':'registro'}],
            'skipped':[{'path':'D:/junction','reason':'reparse point'}]}
        groups=report_by_drive(report)
        self.assertEqual((groups['C:']['errors_count'],groups['C:']['skipped_count']), (1,0))
        self.assertEqual((groups['D:']['errors_count'],groups['D:']['skipped_count']), (1,1))
        self.assertEqual(groups['OUTROS']['errors_count'],1)
        self.assertTrue(any(e['path']=='D:/junction' for e in groups['D:']['skipped']))

    def test_previous_snapshots_keep_dates_and_errors(self):
        report={'scanned_drives':['C:','D:'],'volume_stats':{'C:':{},'D:':{}},'errors':[],'skipped':[]}
        cache={'C:': {'errors':[{'path':'C:/Locked'}], 'skipped':[],
                      'last_scanned_utc':'2026-10-16T15:00:00Z','status':'concluida_com_lacunas'},
               'D:': {'errors':[], 'skipped':[{'path':'D:/Temp'}], 'status':'concluida_com_lacunas'}}
        groups=report_by_drive(report,cache)
        self.assertEqual(groups['C:']['errors_count'],1)
        self.assertEqual(groups['D:']['skipped_count'],1)
        self.assertTrue(groups['C:']['last_scanned_utc'])


class GUIAuditTests(TestCase):
    def setUp(self):
        with patch.object(App, 'refresh_catalog', lambda self:None):
            self.app=App()
        self.addCleanup(self.app.destroy)
        self.app.catalog_items={'g': dict(name='God of War Ragnarök',kind='game',
                                     install_location='D:/SteamLibrary/GOW',paths=[],possible_paths=[])}
        self.app.catalog_choices={'g':'keep'}
        self.app.approved_catalog_paths={'g':['C:/Users/Test/Saved Games/God of War Ragnarök']}
        self.app.choices={'C:/Users/Test/Saved Games/God of War Ragnarök':'keep'}

    def test_preservation_live_links_and_separate_totals(self):
        self.app.update_preservation_preview()
        report=self.app.last_preservation_audit
        self.assertEqual(report['selection_metrics']['selected_games_apps'],1)
        self.assertEqual(report['selection_metrics']['explicit_keep_paths'],1)
        self.assertEqual(report['selection_metrics']['backup_required_paths_c'],1)
        trees=[w for w in children(self.app.preservation) if isinstance(w, ttk.Treeview)]
        linked=next(w for w in trees if 'situation' in w['columns'])
        rows=[linked.item(x,'values') for x in linked.get_children()]
        self.assertTrue(any('God of War' in row[0] and row[1]=='D:' and 'Entre discos' in row[3] for row in rows))

    def test_gaps_window_lists_paths_without_disk_changes(self):
        report={'scanned_drives':['F:'],'volume_stats':{'F:':{}},
                'errors':[{'path':'F:/noaccess','reason':'Acesso negado'}],'skipped':[], 'status':'concluida_com_lacunas'}
        window=show_scan_gaps(self.app,report)
        try:
            self.app.update()
            tree=next(w for w in children(window) if isinstance(w, ttk.Treeview))
            vals=[tree.item(row,'values') for row in tree.get_children()]
            self.assertTrue(any('F:/noaccess' in row[1] for row in vals))
        finally:
            window.destroy()


class ImportOldInventoryTests(TestCase):
    def test_import_old_report_without_rescanning_or_overwriting_selection(self):
        import json
        from deep_discovery_ui import show_deep_discovery
        with patch.object(App, 'refresh_catalog', lambda self: None):
            app=App()
        self.addCleanup(app.destroy)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'deteccao-detalhada-v063.json'
            path.write_text(json.dumps({
                'schema':'pcro-discovery-v1','roots':['C:/'],'status':'concluida',
                'records':[dict(app_id='old',app='Old Game',path='C:/Old',kind='Jogo',evidence='Teste',confidence='candidato',edition=None)],
                'apps':[dict(id='old',name='Old Game')],
                'volume_stats':{'C:':{'files':2,'directories':4}},
                'errors':[], 'skipped':[], 'unassociated_executables':[],
            }),encoding='utf-8')
            for widget in list(app.home.winfo_children()): widget.destroy()
            with patch('deep_discovery_ui.local_drives',return_value=['C:/','D:/']):
                show_deep_discovery(app,container=app.home)
            app.catalog_choices['old']='keep'
            import_btn=next(w for w in children(app.home) if isinstance(w,ttk.Button)
                            and w.cget('text')=='Importar inventário anterior')
            with patch('deep_discovery_ui.filedialog.askopenfilename',return_value=str(path)):
                import_btn.invoke()
            self.assertIn('C:',app.scan_reports_by_drive)
            self.assertEqual(app.catalog_choices['old'],'keep')
            self.assertNotIn('D:',app.scan_reports_by_drive)
            # Re-import may not overwrite already-scanned data.
            app.scan_reports_by_drive['C:']['volume_stats']['C:']['files']=999
            with patch('deep_discovery_ui.filedialog.askopenfilename',return_value=str(path)), \
                 patch('deep_discovery_ui.messagebox.showinfo'):
                import_btn.invoke()
            self.assertEqual(app.scan_reports_by_drive['C:']['volume_stats']['C:']['files'],999)
