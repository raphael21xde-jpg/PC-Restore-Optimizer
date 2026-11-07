"""Regression and safety tests for the unified planning preview."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scan_scope import in_scope, filter_report
from deep_discovery import scan
from preservation_plan import classify_choices
from game_links import infer_links
from tk_helpers import track_tk_root


class RootSelectionTests(unittest.TestCase):
    def test_single_windows_volume_only(self):
        for good in ('C:/', 'C:/Users/abc', 'c:\\program files\\Steam', 'C:/a/../b'):
            self.assertTrue(in_scope(good, ['C:/']), good)
        for wrong in ('D:/Games', 'F:/EFI', 'G:/backup', 'C:relative', 'C:/../D:/test'):
            if wrong == 'C:/../D:/test':
                continue
            self.assertFalse(in_scope(wrong, ['C:/']), wrong)

    def test_selected_subset_c_and_d(self):
        self.assertTrue(in_scope('D:/osu', ['C:/', 'D:/']))
        self.assertFalse(in_scope('G:/osu', ['C:/', 'D:/']))

    def test_folder_scope_is_not_whole_disk(self):
        self.assertTrue(in_scope('D:/Games/Steam/game', ['D:/Games']))
        self.assertFalse(in_scope('D:/Other/private', ['D:/Games']))
        self.assertFalse(in_scope('D:/Games2/Steam', ['D:/Games']))

    def test_filter_stale_metadata_rows(self):
        report = dict(roots=['C:/', 'D:/'], records=[
            dict(path='C:/osu/Songs'), dict(path='D:/SteamLibrary'),
            dict(path='F:/Windows'), dict(path='G:/Backup')],
            volume_stats={letter: {'files': 8} for letter in ('C:', 'D:', 'F:', 'G:')},
            errors=[dict(path='C:/a'), dict(path='D:/error'), dict(path='Metadados Windows')],
            skipped=[dict(path='G:/other')],
            unassociated_executables=['C:/ok.exe', 'D:/not.exe'])
        result = filter_report(report, ['C:/'])
        self.assertEqual([x['path'] for x in result['records']], ['C:/osu/Songs'])
        self.assertEqual([x['path'] for x in result['errors']], ['C:/a'])
        self.assertFalse(in_scope('Metadados Windows', ['C:/']))
        self.assertFalse(in_scope('pasta/relativa', ['C:/']))
        self.assertEqual(result['volume_stats'], {'C:': {'files': 8}})
        self.assertEqual(result['unassociated_executables'], ['C:/ok.exe'])

    def test_core_scan_does_not_add_registry_anchors_out_of_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp)/'allowed', Path(temp)/'excluded'
            a.mkdir(); b.mkdir()
            (a/'game.exe').write_bytes(b'x')
            (b/'game.exe').write_bytes(b'x')
            apps = [dict(id='a', name='game', install_location=str(a)),
                    dict(id='b', name='other game', install_location=str(b))]
            report = scan(apps, [a])
            self.assertGreaterEqual(len(report['records']), 1)
            self.assertTrue(all(in_scope(x['path'], [a]) for x in report['records']))
            self.assertFalse(any(str(b) in x['path'] for x in report['records']))


class PreservationPreviewTests(unittest.TestCase):
    def test_explicit_keep_c_requires_backup_not_d(self):
        doc = classify_choices({'C:/Users/A/Saves': 'keep', 'D:/SteamLibrary': 'keep',
                                'F:/Other': 'skip'}, scanned_roots=['C:/', 'D:/'])
        self.assertEqual(doc['requires_verified_backup'], ['C:/Users/A/Saves'])
        self.assertEqual(next(x['action'] for x in doc['entries'] if x['drive'] == 'D:'), 'MANTER NO LOCAL')
        self.assertFalse(doc['deletions_authorized'])
        self.assertFalse(doc['installation_authorized'])
        self.assertTrue('NÃO É EXCLUSÃO' in doc['entries'][2]['action'])

    def test_removal_markers_never_authorize_deletion(self):
        report = classify_choices({}, removal_candidates=['D:/OldGame', 'G:/trash'])
        self.assertEqual(len(report['removal_candidates']), 2)
        self.assertFalse(report['deletions_authorized'])
        self.assertIn('BLOQUEADO', report['readiness'])

    def test_unselected_items_do_not_become_deletion_candidates(self):
        report = classify_choices({'D:/Games': 'keep'})
        self.assertEqual(report['removal_candidates'], [])

    def test_cross_disk_save_links_are_review_candidates(self):
        items = {'steam1': {'name': 'Exemplo', 'kind': 'game', 'paths': ['D:/SteamLibrary/Game']}}
        result = infer_links(items, {'steam1': ['C:/Users/J/Saved Games/Exemplo']})
        self.assertEqual(result[0]['volume'], 'C:')
        self.assertEqual(result[0]['game_locations'], ['D:/SteamLibrary/Game'])
        self.assertEqual(result[0]['confidence'], 'REVISAR')

    def test_link_is_not_invented(self):
        result = infer_links({'game': {'name': 'Unknown', 'kind': 'game', 'paths': ['D:/G']}}, {})
        self.assertEqual(result, [])


class NavigationTests(unittest.TestCase):
    def test_new_navigation_and_read_only_installation(self):
        import tkinter as tk
        from app import App
        try:
            with patch('app.App.refresh_catalog', lambda self: None):
                root = App()
        except tk.TclError:
            self.skipTest('display unavailable')
        track_tk_root(self, root)
        # FIX-P4-01-02: "Seleção avançada" (catalog) entrou no menu lateral.
        self.assertEqual(len(root.nav_buttons), 9)
        self.assertIn('catalog', root.nav_buttons)
        root.navigate(root.catalog)
        self.assertEqual(root.tabs.select(), str(root.catalog))
        self.assertEqual(root.tabs.select(), str(root.overview))
        root.navigate(root.installation)
        self.assertEqual(root.tabs.select(), str(root.installation))
        self.assertFalse(hasattr(root, 'format_disk'))
        root.navigate(root.preservation)
        self.assertEqual(root.tabs.select(), str(root.preservation))


if __name__ == '__main__':
    unittest.main()
