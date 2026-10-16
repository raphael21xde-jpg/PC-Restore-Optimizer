import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app_recovery import command, package_id, selected_items, data_files, restore_data, query, game_help
from backup_core import build_plan, copy_backup

class AppRecoveryTests(unittest.TestCase):
    def test_install_is_exact_interactive_no_upgrade(self):
        c=command('install','Vendor.Product')
        self.assertIn('--exact',c);self.assertIn('--interactive',c);self.assertIn('--no-upgrade',c)
        self.assertNotIn('--accept-package-agreements',c)
    def test_reject_command_injection_and_options(self):
        for text in ['--help','A.B & del C:', 'A.B\nwhoami','A.B;cmd','https://x']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):package_id(text)
    def test_query_cannot_install(self):
        with self.assertRaises(ValueError):query('install','A.B')
    def test_only_keep_items(self):
        plan={'items':[dict(kind='app',decision='keep'),dict(kind='app',decision='skip'),dict(kind='game',decision='pending')]}
        self.assertEqual(len(selected_items(plan)),1)
    def test_search_name_is_one_argument(self):
        self.assertEqual(command('search','My App & Other')[3],'My App & Other')
    def test_game_help_does_not_promise_installation_backup(self):
        self.assertIn('Saves',game_help({'origin':'Steam'})[0])
        self.assertIn('depende da versão',game_help({'origin':'Epic'})[0])
    def test_matching_files_only_and_verified_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); a=root/'game'; b=root/'game2';a.mkdir();b.mkdir()
            (a/'save').write_text('my progress');(b/'save').write_text('other progress')
            plan=build_plan({str(a):'keep',str(b):'keep'},[str(root)])
            folder,_=copy_backup(plan,root/'backups')
            item={'name':'Game','kind':'game','save_paths':[str(a)]}
            manifest=folder/'manifest.json'
            self.assertEqual(len(data_files(manifest,item)),1)
            _,count=restore_data(manifest,item,root);self.assertEqual(count,1)
            item['save_paths']=[str(root/'missing')]
            with self.assertRaises(ValueError):restore_data(manifest,item,root)
    def test_tampered_backup_blocks_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'data';a.mkdir();(a/'save').write_text('valid')
            folder,m=copy_backup(build_plan({str(a):'keep'},[str(root)]),root/'backup')
            (folder/m['files'][0]['relative']).write_text('corrupt')
            with self.assertRaises((ValueError,OSError)):
                restore_data(folder/'manifest.json',{'kind':'app','data_paths':[str(a)]},root)
