"""Regression tests for reported disappearing selections and cross-disk scan leakage."""
import itertools
import unittest

from scan_sessions import split_by_drive, merge_cache, cache_from_saved
from catalog_plan import selected_catalog_choices
from scan_scope import in_scope
from volume_paths import volume_of


def fake_report(drives, extra=False):
    records = [dict(app_id='shared-game', app='Example', path=f'{d}/Games/Example',
                    kind='Save', evidence='demo') for d in drives]
    if extra:
        records.append(dict(app_id='intruder', app='Wrong', path='Z:/unselected',
                            kind='Save', evidence='should be blocked'))
    return dict(schema='pcro-discovery-v1', roots=[d+'/' for d in drives], status='concluida',
                records=records, apps=[dict(id='shared-game',name='Example'),
                                       dict(id='intruder',name='Wrong')],
                volume_stats={d:dict(files=10, directories=5) for d in drives},
                errors=[],skipped=[],unassociated_executables=[],directories=5*len(drives),
                files=10*len(drives))


class ScopeAndCacheTests(unittest.TestCase):
    def test_all_15_subsets_exactly_once_without_cross_drive_records(self):
        drives = ['C:', 'D:', 'F:', 'G:']
        for count in range(1,5):
            for subset in itertools.combinations(drives, count):
                with self.subTest(drives=subset):
                    cache = split_by_drive(fake_report(subset, extra=True), subset)
                    merged = merge_cache(cache, latest=subset)
                    self.assertEqual(set(merged['scanned_drives']), set(subset))
                    self.assertEqual(set(volume_of(row['path']) for row in merged['records']), set(subset))
                    self.assertEqual(set(merged['volume_stats']), set(subset))
                    self.assertEqual(len(merged['records']), len(subset))
                    for dr in subset:
                        self.assertTrue(all(volume_of(row['path']) == dr for row in cache[dr]['records']))
                    self.assertFalse(any(row['path'].startswith('Z:') for row in merged['records']))

    def test_reexamine_d_updates_only_d_and_keeps_c(self):
        cache = split_by_drive(fake_report(['C:', 'D:']))
        first_c = list(cache['C:']['records'])
        new_d = fake_report(['D:'])
        new_d['records'][0]['path'] = 'D:/Games/Updated'
        cache.update(split_by_drive(new_d))
        final = merge_cache(cache, latest=['D:'])
        self.assertEqual(cache['C:']['records'], first_c)
        self.assertEqual(final['latest_scanned_drives'], ['D:'])
        self.assertEqual(set(row['path'] for row in final['records']),
                         {'C:/Games/Example','D:/Games/Updated'})
        persisted = cache_from_saved(final)
        self.assertEqual(set(persisted), {'C:', 'D:'})
        self.assertEqual(set(row['path'] for row in merge_cache(persisted)['records']),
                         {'C:/Games/Example','D:/Games/Updated'})


class CatalogPersistenceTests(unittest.TestCase):
    def test_marked_app_without_known_data_is_visible_and_uncertain(self):
        selections=selected_catalog_choices({'app:nba':'keep'},
                          {'app:nba': {'kind':'app','name':'NBA 2026',
                                       'install_location': 'D:/Applications/NBA2026', 'paths':[],
                                       'possible_paths': ['C:/Users/A/AppData/NBA']}})
        self.assertEqual(len(selections),1)
        self.assertEqual(selections[0]['name'],'NBA 2026')
        self.assertEqual(selections[0]['install_volume'],'D:')
        self.assertFalse(selections[0]['has_confirmed_data'])
        self.assertEqual(selections[0]['backup_required_for_c'], [])
        self.assertEqual(len(selections[0]['possible_paths']),1)

    def test_c_saves_of_d_game_are_listed_and_require_backup(self):
        selections=selected_catalog_choices({'steam:42':'keep'},
                     {'steam:42': {'kind':'game','name':'Example','install_location':'D:/SteamLibrary',
                                   'paths':['C:/Users/A/Saved Games/Game','D:/Games/config']}})
        self.assertEqual(selections[0]['install_volume'],'D:')
        self.assertEqual(selections[0]['known_data_volumes'], ['C:', 'D:'])
        self.assertEqual(selections[0]['backup_required_for_c'], ['C:/Users/A/Saved Games/Game'])

    def test_saved_choice_without_loaded_catalog_is_not_discarded(self):
        selections=selected_catalog_choices({'steam:forgotten':'keep'}, {})
        self.assertEqual(selections[0]['name'],'steam:forgotten')
        self.assertFalse(selections[0]['has_confirmed_data'])


if __name__=='__main__': unittest.main()

class PreferenceMigrationTests(unittest.TestCase):
    def test_previous_decisions_import_without_disk_actions(self):
        from choice_migration import merge_preferences
        from types import SimpleNamespace
        app = SimpleNamespace(choices={}, catalog_choices={}, auto_save_paths=set(),
                              personal_paths=set(), browser_keep_paths=set(),cleanup_candidates=set(),
                              approved_catalog_paths={}, retained_discoveries={})
        doc = dict(choices={'D:/Jogos/SteamLibrary':'keep'},catalog_choices={'game:steam':'keep'},
                   format_disks=['C','D','F','G'],destination='F:/Destroy',
                   approved_catalog_paths={'game:steam':['D:/Jogos/SteamLibrary']})
        paths,games=merge_preferences(app,doc)
        self.assertEqual((paths,games),(1,1))
        self.assertEqual(app.catalog_choices['game:steam'],'keep')
        self.assertFalse(hasattr(app,'format_disks'))
        self.assertFalse(hasattr(app,'destination'))
        self.assertEqual(len(app.approved_catalog_paths['game:steam']),1)
