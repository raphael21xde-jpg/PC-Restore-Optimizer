import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from audit_v068 import (DISK_QUERY_068, collect_disk_evidence_068, classify_boot_068,
                        inspect_children_once, safe_review_choice, import_snapshot_068,
                        enhance_report_068, inspect_verified_manifest)

class Audit068Tests(unittest.TestCase):
    def test_new_diagnostics_non_destructive(self):
        script = DISK_QUERY_068.lower()
        for bad in ('remove-partition', 'clear-disk', 'format-volume', 'new-partition',
                    'set-disk', 'set-partition', 'bcdboot ', 'bcdedit /set',
                    'remove-item', 'format-disk', 'initialize-disk'):
            self.assertNotIn(bad, script)
        self.assertIn('win32_diskdrive', script)
        self.assertIn('win32_volume', script)

    def test_nonwindows_no_subprocess(self):
        with mock.patch('audit_v068.subprocess.run', side_effect=AssertionError('not called')):
            proof = collect_disk_evidence_068(platform='posix')
        self.assertFalse(proof['available'])

    def test_normalize_powershell_singleton_lists(self):
        doc = {'windows_disk_number':2, 'disks':{'number':2}, 'physical_disks':{'index':1},
               'efi_partitions':None, 'legacy_volumes':{'letter':'F:', 'system_volume':True}}
        def runner(*args, **kwargs):
            return type('R', (), {'returncode':0, 'stdout':json.dumps(doc),'stderr':''})()
        result=collect_disk_evidence_068(platform='nt', runner=runner)
        self.assertEqual(len(result['data']['physical_disks']), 1)
        self.assertEqual(result['data']['efi_partitions'], [])

    def test_dynamic_volume_missing_efi_not_absence(self):
        e={'available':True,'data':{'windows_disk_number':2, 'efi_partitions':[],
            'legacy_volumes':[{'letter':'F:', 'system_volume':True}], 'volumes':[],
            'physical_disks':[{'index':1,'model':'Kingston'}]}}
        b=classify_boot_068(e)
        self.assertEqual(b['status'], 'MAPEAMENTO INCOMPLETO')
        self.assertIn('NÃO significa', b['note'])
        self.assertTrue(b['manual_boot_test_needed'])

    def test_known_other_efi_still_not_certified(self):
        e={'available':True,'data':{'windows_disk_number':2, 'efi_partitions':[{'disk_number':1}],
             'legacy_volumes':[], 'physical_disks':[]}}
        self.assertEqual(classify_boot_068(e)['status'], 'DEPENDÊNCIA POSSÍVEL')

    def test_single_efi_on_c_not_independent_boot(self):
        e={'available':True,'data':{'windows_disk_number':2, 'efi_partitions':[{'disk_number':2}],
             'legacy_volumes':[], 'physical_disks':[]}}
        self.assertEqual(classify_boot_068(e)['status'], 'TESTE MANUAL NECESSÁRIO')

    def test_bounded_preview(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            for i in range(126): (p/f'data-{i:03}.txt').write_text('abc')
            result=inspect_children_once(p,limit=30)
            self.assertEqual(len(result['rows']),30)
            self.assertTrue(result['has_more'])
            self.assertEqual(result['next_offset'], 30)
            r2=inspect_children_once(p,offset=30,limit=30)
            self.assertEqual(len(r2['rows']),30)

    def test_symlink_preview_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); t=p/'target';t.mkdir(); link=p/'ln'
            try:
                link.symlink_to(t,target_is_directory=True)
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    self.skipTest('Windows sem privilégio para criar symlink (WinError 1314)')
                raise
            with self.assertRaises(ValueError): inspect_children_once(link)

    def test_preview_reparse_child_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); t=p/'target'; t.mkdir()
            try:
                (p/'ln').symlink_to(t,target_is_directory=True)
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    self.skipTest('Windows sem privilégio para criar symlink (WinError 1314)')
                raise
            rows=inspect_children_once(p)['rows']
            self.assertEqual(next(x for x in rows if x['name']=='ln')['type'], 'LINK — NÃO SEGUIR')

    def test_reject_root_and_other_drive(self):
        candidates=[{'path':r'C:\Users\Rapha\Documents'}, {'path':r'D:\Other'}]
        for x in ('C:\\', r'D:\Other', r'C:\Windows', r'C:\Users\Rapha\NotListed'):
            with self.assertRaises(ValueError): safe_review_choice(x,candidates)

    def test_explicit_selection_only(self):
        c=[{'path':r'C:\Users\Rapha\Documents'}]
        self.assertEqual(safe_review_choice(r'C:\Users\Rapha\Documents',c).lower(),r'c:\users\rapha\documents')

    def test_reject_broad_appdata_if_requested(self):
        c=[{'path':r'C:\Users\Rapha\AppData\Local'}]
        with self.assertRaises(ValueError): safe_review_choice(c[0]['path'],c,deny_broad=True)

    def test_import_does_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'inventory.json'
            doc={'schema':'pcro-discovery-v1', 'roots':['C:\\'], 'records':[],
                 'volume_stats':{'C:':{'files':3, 'directories':2}}, 'files':3,'directories':2}
            file.write_text(json.dumps(doc))
            current={'C:':{'schema':'pcro-discovery-v1','roots':['C:\\'],'status':'cached'}}
            merged, added=import_snapshot_068(file,current)
            self.assertFalse(added)
            self.assertEqual(merged['C:']['status'],'cached')

    def test_import_rejects_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'prefs.json';file.write_text('{"choices":{},"catalog_choices":{}}')
            with self.assertRaises(ValueError): import_snapshot_068(file,{})

    def test_manifest_not_trusted_from_success_flag(self):
        with tempfile.TemporaryDirectory() as root:
            fake=Path(root)/'manifest.json';fake.write_text('{"backup_verified": true}')
            with self.assertRaises(ValueError): inspect_verified_manifest(fake)

    def test_safe_report_does_not_claim_full_backup(self):
        old={'selected_c_paths':[r'C:\Saves\Game'],
             'recovery_map':[{'source_path':r'C:\Saves\Game','status':'old'}]}
        proof={'backup_verified':True,'verified_source_files':[r'C:\Saves\Game\save.dat'],
               'files_verified':1,'bytes_verified':5,'manifest':'G:/manifest.json'}
        new=enhance_report_068(old,proof=proof)
        self.assertEqual(len(new['backup_evidence']['matching_selected_paths']),1)
        for flag in ('backup_verified','restore_verified','ready_for_format','installation_authorized','deletions_authorized'):
            self.assertFalse(new[flag])
        self.assertIn('COBERTURA NÃO COMPROVADA',new['backup_evidence']['status'])

if __name__=='__main__':unittest.main()
