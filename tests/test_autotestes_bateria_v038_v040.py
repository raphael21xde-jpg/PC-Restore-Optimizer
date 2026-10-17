"""Unit tests for synthetic #38/#40 and opt-in metadata-only #39."""
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from autotestes_bateria import (
    run_tiny_files_stress_autotest,
    run_readonly_inventory_autotest,
    run_isolated_full_restore_autotest,
    scan_readonly_metadata,
)


class TestBateria38a40(unittest.TestCase):
    def common(self, report, number):
        self.assertEqual(report['schema'], f'pcro-autoteste-bateria-v{number}')
        self.assertEqual(report['status'], 'aprovado')
        self.assertFalse(report['ready_for_format'])
        self.assertFalse(report['installation_authorized'])
        self.assertFalse(report['physical_independence_verified'])
        self.assertFalse(report['real_user_backups_accessed'])

    def test_38_many_small_files_verified_both_ways(self):
        report = run_tiny_files_stress_autotest(count=128)
        self.common(report, 38)
        self.assertEqual(report['fixture_files'], 128)
        self.assertTrue(report['backup_sha256_verified'])
        self.assertTrue(report['restore_sha256_verified'])
        self.assertTrue(report['temporary_data_cleaned'])
        self.assertTrue(report['originals_preserved'])

    def test_38_bounded_count_and_pre_cancel(self):
        with self.assertRaises(ValueError):
            run_tiny_files_stress_autotest(count=4097)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            run_tiny_files_stress_autotest(cancelled=cancelled, count=3)

    def test_39_read_only_metadata_and_coverage_limit(self):
        with tempfile.TemporaryDirectory(prefix='PCRO-TESTE39-') as temp:
            root = Path(temp) / 'volume'
            (root / 'SteamApps').mkdir(parents=True)
            (root / 'SteamApps' / 'abc.txt').write_text('sintetico', encoding='utf-8')
            before = (root / 'SteamApps' / 'abc.txt').read_bytes()
            with patch('builtins.open', side_effect=AssertionError('Nunca abrir conteúdo')), \
                 patch('pathlib.Path.write_text', side_effect=AssertionError('Nunca gravar')): 
                report = run_readonly_inventory_autotest(roots=[root])
            self.common(report, 39)
            self.assertEqual(report['roots_seen'], 1)
            self.assertGreaterEqual(report['entries_examined'], 2)
            self.assertEqual(report['candidate_folder_names_observed'], 1)
            self.assertTrue(report['partial_coverage'])
            self.assertTrue(report['no_write_calls'])
            self.assertEqual(report['content_files_opened'], 0)
            self.assertEqual((root / 'SteamApps' / 'abc.txt').read_bytes(), before)

    def test_39_skips_links_without_traversing_outside(self):
        with tempfile.TemporaryDirectory(prefix='PCRO-TESTE39-LINK-') as temp:
            root = Path(temp) / 'root'
            other = Path(temp) / 'elsewhere'
            root.mkdir()
            other.mkdir()
            (other / 'marker.txt').write_text('keep', encoding='utf-8')
            try:
                (root / 'link').symlink_to(other, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('No permission to create symlinks in this environment')
            result = scan_readonly_metadata([root])
            self.assertEqual(result[0]['reparse_skipped'], 1)
            self.assertEqual(result[0]['files'], 0)

    def test_39_limits_and_cancelled_probe(self):
        with tempfile.TemporaryDirectory(prefix='PCRO-TESTE39-LIMIT-') as temp:
            root = Path(temp)
            for i in range(10):
                (root / f'folder-{i}').mkdir()
            result = scan_readonly_metadata([root], max_entries_per_root=3)
            self.assertTrue(result[0]['truncated'])
            self.assertEqual(result[0]['examined'], 3)
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            run_readonly_inventory_autotest(cancelled=event, roots=['do-not-read'])
        with self.assertRaises(ValueError):
            scan_readonly_metadata([], max_depth=99)

    def test_40_selective_backup_full_restore_and_conflict_guard(self):
        report = run_isolated_full_restore_autotest()
        self.common(report, 40)
        self.assertEqual(report['fixture_files'], 6)
        self.assertEqual(report['selected_files'], 5)
        self.assertTrue(report['excluded_item_absent'])
        self.assertTrue(report['restore_isolated'])
        self.assertTrue(report['existing_destination_file_preserved'])
        self.assertTrue(report['unsafe_relative_path_blocked'])
        self.assertTrue(report['temporary_data_cleaned'])

    def test_40_fail_closed_when_path_validation_is_broken(self):
        with patch('autotestes_bateria.safe_relative', return_value=Path('unsafe')):
            with self.assertRaisesRegex(AssertionError, 'escape de pasta'):
                run_isolated_full_restore_autotest()


if __name__ == '__main__':
    unittest.main()
