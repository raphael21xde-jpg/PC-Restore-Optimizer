import copy
import struct
import unittest
from unittest.mock import patch
from audit_v069 import enhance_report_069, apply_volume_mappings, classify_boot_069
from volume_extents import parse_extents, collect_extents

class Audit069Tests(unittest.TestCase):
    def report(self):
        return {'selected_c_paths':[r'C:\Users\Other\Game\Songs', r'C:\Saves\Example'],
                'candidate_locations':[{'path':r'C:\Users\Other\Game', 'status':'REVISAR — NÃO SELECIONADO',
                                        'detail':'Conteúdo não auditado.', 'covered_by':''}],
                'recovery_map':[{'source_path':r'C:\Users\Other\Game\Songs'},
                                {'source_path':r'C:\Saves\Example'}]}

    def test_partial_selection_and_copy_isolation(self):
        old=self.report(); original=copy.deepcopy(old)
        new=enhance_report_069(old)
        self.assertEqual(old, original)
        self.assertEqual(new['candidate_locations'][0]['selection_state'], 'partial')
        self.assertIn('PARCIAL', new['candidate_locations'][0]['status'])
        self.assertFalse(new['backup_verified'])

    def test_verified_files_not_whole_folder_or_restoration(self):
        proof={'backup_verified':True,'verified_source_files':[r'C:\Saves\Example\save.dat'],
               'files_verified':1, 'bytes_verified':100}
        new=enhance_report_069(self.report(),proof=proof)
        self.assertEqual(new['recovery_map'][0]['backup_state'], 'not_proven')
        row=new['recovery_map'][1]
        self.assertEqual(row['verified_manifest_files'],1)
        self.assertEqual(row['coverage_state'],'not_proven')
        self.assertEqual(row['restore_state'],'not_proven')
        self.assertTrue(new['backup_evidence']['manifest_verified'])
        self.assertFalse(new['restore_verified'])
        self.assertFalse(new['ready_for_format'])

    def test_sibling_prefix_is_not_coverage(self):
        proof={'backup_verified':True,'verified_source_files':[r'C:\Saves\Example2\save.dat']}
        self.assertEqual(enhance_report_069(self.report(),proof=proof)['recovery_map'][1]['verified_manifest_files'],0)

    def test_failed_proof_and_missing_metadata_keep_caution(self):
        old=self.report();old['candidate_locations'][0]['status']='SEM ACESSO'
        new=enhance_report_069(old,proof={'backup_verified':False,'verified_source_files':[r'C:\Saves\Example\a']})
        self.assertEqual(new['candidate_locations'][0]['status'],'SEM ACESSO')
        self.assertFalse(new['backup_evidence']['manifest_verified'])

    def test_scan_overlap_detects_parent_and_child(self):
        old=self.report();old['scan_c']={'errors':[{'path':r'C:\Saves', 'reason':'denied'}],
                                       'skipped':[{'path':r'C:\Saves\Example\link','reason':'link'}]}
        self.assertEqual(len(enhance_report_069(old)['scan_summary']['selected_path_overlaps']),2)

    def test_preservation_readiness_counts_verified_files_without_claiming_full_coverage(self):
        sample = self.report()
        sample['boot'] = {'status': 'SISTEMA EM OUTRO DISCO'}
        proof = {'backup_verified': True, 'manifest': 'manifest.json',
                 'verified_source_files': [r'C:\\Saves\\Example\\save.dat'],
                 'files_verified': 1, 'bytes_verified': 128}
        result = enhance_report_069(sample, proof=proof)
        progress = result['preservation_readiness']
        self.assertEqual(progress['selected_paths'], 2)
        self.assertEqual(progress['paths_with_verified_manifest_files'], 1)
        self.assertEqual(progress['paths_without_manifest_proof'], 1)
        self.assertEqual(progress['selected_paths_with_full_coverage_proven'], 0)
        self.assertEqual(progress['selected_paths_with_restore_proven'], 0)
        self.assertTrue(progress['manifest_verified_in_this_session'])
        self.assertEqual(progress['boot_status'], 'SISTEMA EM OUTRO DISCO')
        self.assertFalse(progress['ready_for_format'])
        self.assertFalse(progress['installation_authorized'])

    def test_preservation_readiness_without_proof_stays_pending(self):
        result = enhance_report_069(self.report())
        progress = result['preservation_readiness']
        self.assertEqual(progress['paths_without_manifest_proof'], 2)
        self.assertEqual(progress['paths_with_verified_manifest_files'], 0)
        self.assertFalse(progress['manifest_verified_in_this_session'])
        self.assertEqual(progress['boot_status'], 'NÃO CONFERIDO')
        self.assertFalse(progress['installation_authorized'])

    def test_readiness_includes_scan_overlap_without_repeating_scans(self):
        report = self.report()
        report['scan_c'] = {'status': 'COM LACUNAS', 'errors': [
            {'path': r'C:\\Saves\\Example\\locked.dat', 'reason': 'access denied'}],
            'skipped': []}
        progress = enhance_report_069(report)['preservation_readiness']
        self.assertEqual(progress['scan_gaps_overlapping_choices'], 1)

    def test_extent_parser_multidisk_and_offsets(self):
        raw=struct.pack('<I4x',2)+struct.pack('<I4xqq',0,1048576,200)+struct.pack('<I4xqq',7,4096,100)
        self.assertEqual([x['disk_number'] for x in parse_extents(raw)],[0,7])
        self.assertEqual(parse_extents(raw)[1]['starting_offset'],4096)

    def test_extent_parser_rejects_truncated_and_invalid(self):
        for raw in [b'',struct.pack('<I4x',0),struct.pack('<I4x',4097),struct.pack('<I4x',2)+bytes(24),
                    struct.pack('<I4xI4xqq',1,1,-1,10)]:
            with self.assertRaises(ValueError):parse_extents(raw)

    def test_extent_failure_preserves_other_results(self):
        def query(device):
            if device=='bad':raise OSError('access denied')
            return [{'disk_number':0,'starting_offset':1,'extent_length':2}]
        rows=collect_extents([{'device_id':'bad'},{'device_id':'good'}],query)
        self.assertEqual([x['status'] for x in rows],['unmapped','mapped'])

    def mapped(self,numbers=(0,),system=True):
        data={'windows_disk_number':7,'legacy_volumes':[{'device_id':'VOL\\','letter':None,
              'filesystem':'FAT32','system_volume':system}],'efi_partitions':[]}
        mappings=[{'device_id':'vol','status':'mapped','source':'IOCTL',
                   'extents':[{'disk_number':n} for n in numbers]}]
        return {'available':True,'data':apply_volume_mappings(data,mappings)}

    def test_system_other_disk_zero_and_no_fake_efi(self):
        result=classify_boot_069(self.mapped())
        self.assertEqual(result['status'],'SISTEMA EM OUTRO DISCO')
        self.assertEqual(result['system_volume_disk_numbers'],[0])
        self.assertEqual(result['efi_disk_numbers'],[])
        self.assertTrue(result['manual_boot_test_needed'])

    def test_fat32_without_system_flag_not_boot_proof(self):
        self.assertEqual(classify_boot_069(self.mapped(system=False))['status'],'MAPEAMENTO INCOMPLETO')

    def test_spanned_volume_keeps_all_disks(self):
        result=classify_boot_069(self.mapped((1,7)))
        self.assertEqual(result['system_volume_disk_numbers'],[1,7])
        self.assertIn('VÁRIOS',result['status'])

    def test_mapping_same_disk_not_boot_certification(self):
        self.assertEqual(classify_boot_069(self.mapped((7,)))['status'],'TESTE MANUAL NECESSÁRIO')

    def test_readonly_native_api_closes_handle_and_retries(self):
        import ctypes
        from volume_extents import query_volume
        class Fn:
            def __init__(self, callback):self.callback=callback
            def __call__(self,*args):return self.callback(*args)
        calls=[]
        def ioctl(handle,code,inp,insize,buf,size,returned,overlap):
            calls.append(size)
            raw=struct.pack('<I4x',2)+struct.pack('<I4xqq',1,0,100)+struct.pack('<I4xqq',2,100,200)
            ctypes.memmove(buf,raw,min(size,len(raw)))
            returned._obj.value=min(size,len(raw))
            return size>=len(raw)
        class Kernel:pass
        k=Kernel(); opened=[]; closed=[]
        k.CreateFileW=Fn(lambda *a: opened.append(a) or 12)
        k.DeviceIoControl=Fn(ioctl);k.CloseHandle=Fn(lambda h:closed.append(h) or 1)
        with patch('volume_extents.os.name','nt'), patch.object(ctypes,'WinDLL',return_value=k,create=True), patch.object(ctypes,'get_last_error',return_value=234,create=True):
            rows=query_volume('\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\')
        self.assertEqual(opened[0][1],0)
        self.assertEqual(opened[0][4],3)
        self.assertEqual(closed,[12]);self.assertEqual(len(calls),2)
        self.assertEqual([x['disk_number'] for x in rows],[1,2])

if __name__=='__main__':unittest.main()
