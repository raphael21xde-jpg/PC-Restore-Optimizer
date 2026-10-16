import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completeness_audit_v067 import (
    _within, selected_c_paths, discover_candidate_locations,
    audit_candidate_rows, collect_disk_evidence, classify_boot_evidence,
    build_completeness_report, DISK_QUERY,
)


class CompletenessAudit067Tests(unittest.TestCase):
    def test_windows_containment_is_segment_safe(self):
        self.assertTrue(_within(r'C:\Users\Rapha\Saved Games\game', r'c:\users\rapha\Saved Games'))
        self.assertFalse(_within(r'C:\Users\Rapha\Documents-malware', r'C:\Users\Rapha\Documents'))
        self.assertFalse(_within(r'D:\games', 'C:\\'))
        self.assertFalse(_within(r'C:\x', r'D:\x'))

    def test_selected_only_explicit_c(self):
        p = {'requires_verified_backup': [r'C:\Games\save', r'D:\Steam', 'nonsense']}
        self.assertEqual(selected_c_paths(p), [r'C:\Games\save'])

    def test_never_guess_username_without_profile(self):
        self.assertEqual(discover_candidate_locations({}), [])

    def test_windows_user_known_folders_and_browser_discovery(self):
        env = {'USERPROFILE': r'C:\Users\Tester', 'APPDATA': r'C:\Users\Tester\AppData\Roaming',
               'LOCALAPPDATA': r'C:\Users\Tester\AppData\Local'}
        paths = discover_candidate_locations(env)
        self.assertIn(r'C:\Users\Tester\Saved Games', [x['path'] for x in paths])
        self.assertTrue(any('osu!' in x['path'] for x in paths))
        self.assertTrue(any('Chrome' in x['path'] for x in paths))

    def test_redirection_to_other_disk_not_wiped_c(self):
        paths = discover_candidate_locations({'USERPROFILE': r'C:\Users\Tester'},
                   registry_folders={'Documentos': r'D:\Documents'})
        self.assertIn(r'D:\Documents', [x['path'] for x in paths])

    def test_covered_parent_vs_selected_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = root/'sub'; child.mkdir(); (child/'one').write_text('demo')
            candidates = [{'name':'parent', 'path': str(root), 'category':'PESSOAL'},
                          {'name':'child', 'path': str(child), 'category':'PESSOAL'}]
            # Synthetic Windows paths require injected metadata for Linux tests.
            lookups = {r'C:\Users\Demo\parent': root, r'C:\Users\Demo\parent\sub': child}
            def ls(path): return os.lstat(lookups[path])
            def sd(path): return os.scandir(lookups[path])
            candidates = [{**c, 'path': k} for c,k in zip(candidates, lookups)]
            rows = audit_candidate_rows(candidates, [r'C:\Users\Demo\parent\sub'], lstat=ls, scandir=sd)
            self.assertEqual(rows[0]['status'], 'REVISAR — NÃO SELECIONADO')
            self.assertEqual(rows[1]['status'], 'SELECIONADO — NÃO COMPROVADO')
            self.assertFalse(rows[1]['backup_verified'])

    def test_permission_error_is_not_silenced(self):
        def denied(_): raise PermissionError('denied')
        rows = audit_candidate_rows([{'name':'docs', 'path':r'C:\Docs', 'category':'PESSOAL'}], [], lstat=denied)
        self.assertEqual(rows[0]['status'], 'SEM ACESSO')

    def test_missing_path_not_claimed_clean(self):
        def missing(_): raise FileNotFoundError()
        rows = audit_candidate_rows([{'name':'docs', 'path':r'C:\Docs', 'category':'PESSOAL'}], [], lstat=missing)
        self.assertEqual(rows[0]['status'], 'AUSENTE')

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder)/'link'; target = Path(folder)/'target'; target.mkdir()
            link.symlink_to(target, target_is_directory=True)
            row = audit_candidate_rows([{'name':'link', 'path':str(link), 'category':'PESSOAL'}],
                                       [], lstat=os.lstat)[0]
            self.assertEqual(row['status'], 'REVISAR LINK')

    def test_efi_other_disk_requires_review(self):
        e = {'available':True, 'data': {'windows_disk_number':2,
                'efi_partitions':[{'disk_number':1}]}}
        report = classify_boot_evidence(e)
        self.assertEqual(report['status'], 'DEPENDÊNCIA POSSÍVEL')
        self.assertTrue(report['manual_boot_test_needed'])

    def test_efi_same_disk_not_proof(self):
        e = {'available':True, 'data': {'windows_disk_number':2,
                'efi_partitions':[{'disk_number':2}]}}
        self.assertEqual(classify_boot_evidence(e)['status'], 'TESTE MANUAL NECESSÁRIO')

    def test_efi_multiple_disk_review(self):
        e = {'available':True, 'data': {'windows_disk_number':2,
                'efi_partitions':[{'disk_number':1},{'disk_number':2}]}}
        self.assertEqual(classify_boot_evidence(e)['status'], 'REVISAR')

    def test_not_windows_doesnt_launch_powershell(self):
        with mock.patch('completeness_audit_v067.subprocess.run', side_effect=AssertionError('spawned')):
            r = collect_disk_evidence(platform='posix')
        self.assertFalse(r['available'])

    def test_only_read_commands(self):
        lower = DISK_QUERY.lower()
        for unsafe in ('remove-partition', 'clear-disk', 'format-volume', 'new-partition',
                       'set-partition', 'set-disk', 'bcdboot ', 'bcdedit /set'):
            self.assertNotIn(unsafe, lower)

    def test_report_keeps_errors_and_always_blocks_format(self):
        report = {'scanned_drives':['C:'], 'errors':[{'path':r'C:\Users\Demo\Important', 'error':'Access denied'}],
                  'skipped':[{'path':r'C:\Users\Demo\Skip','reason':'ignored'}]}
        created = build_completeness_report({'requires_verified_backup':[r'C:\Users\Demo\Saved Games']},
                                            report, {}, candidates=[], disk_evidence={'available':False,'error':'offline'})
        self.assertEqual(created['counts']['c_scan_errors'], 1)
        self.assertEqual(created['counts']['c_scan_skipped'], 1)
        self.assertFalse(created['ready_for_format'])
        self.assertFalse(created['deletions_authorized'])
        self.assertFalse(created['backup_verified'])
        self.assertFalse(created['installation_authorized'])
        self.assertEqual(created['recovery_map'][0]['restore_target_after_windows'],
                         r'C:\Users\Demo\Saved Games')

    def test_module_does_not_modify_filesystem(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder)/'original.txt'; original.write_text('SAVE')
            report = build_completeness_report({'requires_verified_backup':[]}, {}, {},
                candidates=[{'name':'file','path':str(original),'category':'JOGOS'}],
                disk_evidence={'available':False, 'error':'offline'})
            self.assertEqual(original.read_text(), 'SAVE')
            self.assertFalse(report['backup_verified'])


if __name__ == '__main__':
    unittest.main()
