import os
import tempfile
import unittest
from pathlib import Path

from deep_discovery import scan
from drive_catalog import (groups_by_volume, coverage, list_folder_page,
                           safe_to_mark, volume_of)


def record(app, app_id, path, kind='Pasta da instalação', edition=None):
    return dict(app=app, app_id=app_id, path=path, kind=kind,
                confidence='candidato', evidence='Teste', edition=edition)


class VolumeGroupingTests(unittest.TestCase):
    def test_drive_letter_normalization(self):
        self.assertEqual(volume_of('c:/Jogos/abc'), 'C:')
        self.assertEqual(volume_of('d:\\SteamLibrary\\apps'), 'D:')
        self.assertEqual(volume_of('/tmp/check'), 'SEM UNIDADE')
        self.assertEqual(volume_of('\\\\server\\share\\file'), 'SEM UNIDADE')

    def test_cross_drive_game_only_selects_its_volume(self):
        r = {'records': [record('osu!', 'osu', 'C:/osu/Songs', 'Músicas e beatmaps', 'stable'),
                         record('osu!', 'osu', 'D:/osu/Songs', 'Músicas e beatmaps', 'stable')]}
        tab = groups_by_volume(r)
        self.assertEqual(len(tab['C:']), 1)
        self.assertEqual(len(tab['D:']), 1)
        self.assertEqual(tab['D:'][0]['records'], [1])
        self.assertEqual(tab['C:'][0]['records'], [0])
        self.assertEqual(tab['D:'][0]['category'], 'Jogos')

    def test_classic_and_lazer_stay_separate(self):
        r = {'records': [record('osu!', 'a', 'F:/old/osu', edition='stable'),
                         record('osu!', 'b', 'F:/new/osu', edition='lazer')]}
        groups = groups_by_volume(r)['F:']
        self.assertEqual(len(groups), 2)
        self.assertEqual({g['name'] for g in groups}, {'osu! clássico (stable)', 'osu! lazer'})

    def test_same_game_spans_drives_but_not_mixed(self):
        r = {'records': [record('Steam', 'a', 'C:/Apps/Steam'),
                         record('Steam', 'a', 'D:/SteamLibrary'),
                         record('Steam', 'a', 'G:/Games')],
             'apps': [{'id': 'a', 'category': 'Jogo'}]}
        groups = groups_by_volume(r)
        self.assertEqual(set(groups), {'C:', 'D:', 'G:'})
        self.assertEqual([groups[k][0]['records'] for k in ('C:', 'D:', 'G:')], [[0], [1], [2]])

    def test_errors_and_exclusions_by_drive(self):
        r = {'status': 'concluida_com_lacunas', 'volume_stats': {'C:': {'directories': 50000, 'files': 45000}},
             'errors': [{'path': 'C:/private'}, {'path': 'D:/secret'}, {'path': 'Metadados Windows'}],
             'skipped': [{'path': 'C:/junction'}, {'path': 'G:/backup'}]}
        c = coverage(r, 'C:')
        self.assertEqual((c['directories'], c['files'], c['errors'], c['skipped']), (50000, 45000, 1, 1))

    def test_system_roots_cannot_be_marked_as_data(self):
        for path in ('C:/', 'C:/Windows', 'C:/Windows/System32', 'F:/EFI',
                     'D:/Program Files', 'C:/Users', 'G:relative', 'C:/Recovery'):
            self.assertFalse(safe_to_mark(path), path)
        self.assertTrue(safe_to_mark('C:/Users/Joao/Documents'))
        self.assertTrue(safe_to_mark('D:/SteamLibrary'))


class BoundedExplorerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_pagination_does_not_materialize_all_items(self):
        for n in range(401):
            (self.root / f'f_{n:04}.txt').touch()
        rows = []
        offset = 0
        while True:
            page = list_folder_page(self.root, offset=offset, limit=120)
            self.assertLessEqual(len(page['entries']), 120)
            rows.extend(x['name'] for x in page['entries'])
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        self.assertEqual(len(set(rows)), 401)

    def test_no_junction_traversal(self):
        target = self.root / 'real'
        target.mkdir()
        link = self.root / 'shortcut'
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Cannot create link in this environment')
        page = list_folder_page(self.root)
        linked = next(e for e in page['entries'] if e['name'] == 'shortcut')
        self.assertTrue(linked['special'])
        with self.assertRaises(ValueError):
            list_folder_page(link)

    def test_scan_emits_per_volume_counters(self):
        d = self.root / 'game' / 'saves'
        d.mkdir(parents=True)
        (d / 'test.dat').write_text('x')
        r = scan([], [self.root])
        volume = volume_of(str(self.root))
        self.assertGreaterEqual(r['volume_stats'][volume]['directories'], 2)
        self.assertEqual(r['volume_stats'][volume]['files'], 1)
        self.assertEqual(r['directories'], sum(v['directories'] for v in r['volume_stats'].values()))


if __name__ == '__main__':
    unittest.main()

