"""Safe interrupted-job recovery, media evidence and regression tests."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backup_core import build_plan, copy_backup, sha256_file
from backup_features import verified_entries, restore_selected, resume_information
from transfer_engine import classify_drive, choose_strategy, TransferMeter


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.inventory={
            'partitions':[{'DriveLetter':'C','DiskNumber':0},{'DriveLetter':'G','DiskNumber':1},
                          {'DriveLetter':'H','DiskNumber':2},{'DriveLetter':'J','DiskNumber':3}],
            'disks':[{'Number':0,'BusType':'NVMe','FriendlyName':'Fast nvme'},
                     {'Number':1,'BusType':'SATA','SerialNumber':'ssd1'},
                     {'Number':2,'BusType':'SATA','SerialNumber':'hdd1'},
                     {'Number':3,'BusType':'SATA','FriendlyName':'mystery'}],
            'physical_disks':[{'SerialNumber':'ssd1','MediaType':'SSD'},
                              {'SerialNumber':'hdd1','MediaType':'HDD'}]}

    def test_classify_only_with_evidence(self):
        self.assertEqual(classify_drive(r'C:\Games\x',self.inventory),'ssd-nvme')
        self.assertEqual(classify_drive(r'G:\Backup',self.inventory),'ssd-sata')
        self.assertEqual(classify_drive(r'H:\Backup',self.inventory),'hdd')
        self.assertEqual(classify_drive(r'J:\Backup',self.inventory),'desconhecido')
        self.assertEqual(classify_drive(r'Z:\Backup',self.inventory),'desconhecido')
        self.assertEqual(choose_strategy(r'C:\Games',r'G:\Backup',self.inventory).chunk,4*1024**2)
        self.assertEqual(choose_strategy(r'C:\Games',r'C:\Backup',self.inventory).chunk,8*1024**2)
        self.assertEqual(choose_strategy(r'H:\Games',r'G:\Backup',self.inventory).chunk,1024**2)

    def test_meter(self):
        meter=TransferMeter(1000,10)
        snap=meter.snapshot(bytes_done=250,files_done=4)
        self.assertGreaterEqual(snap['remaining_sec'],0)
        self.assertEqual(snap['files_done'],4)


class ResumeTests(unittest.TestCase):
    def setup_items(self,root):
        folder=root/'source'; folder.mkdir()
        for i in range(7):
            (folder/f'{i}.dat').write_bytes((f'item {i}'.encode())*100)
        plan=build_plan({str(folder):'keep'},[str(root)])
        return folder, plan

    def test_resume_backup_keeps_hashes_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); folder,plan=self.setup_items(root)
            stopped=threading.Event()
            def progress(n,total,copied,allbytes,source):
                if n == 3: stopped.set()
            backup,manifest=copy_backup(plan,root/'out',cancelled=stopped,progress=progress)
            self.assertEqual(manifest['status'],'interrompido')
            self.assertGreaterEqual(len(manifest['files']),2)
            hashes={item['relative']:item['sha256'] for item in manifest['files']}
            out,final=copy_backup(plan,root/'out',resume_manifest=backup/'manifest.json')
            self.assertEqual(out,backup)
            self.assertEqual(final['status'],'concluido')
            self.assertEqual(len(final['files']),plan.count)
            self.assertEqual({i['relative']:i['sha256'] for i in final['files'] if i['relative'] in hashes},hashes)
            self.assertTrue(all(sha256_file(out/i['relative'])==i['sha256'] for i in final['files']))
            self.assertEqual(final['resume_count'],1)

    def test_resume_adopts_uncheckpointed_file_by_double_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); _,plan=self.setup_items(root)
            stopped=threading.Event()
            def progress(n,total,copied,allbytes,source):
                if n == 2: stopped.set()
            backup,manifest=copy_backup(plan,root/'out',cancelled=stopped,progress=progress)
            first=manifest['files'][0]
            saved=backup/first['relative']
            prior_inode=saved.stat().st_ino
            # Simulate a process crash before the atomic manifest checkpoint.
            manifest['files']=[x for x in manifest['files'] if x['relative']!=first['relative']]
            (backup/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            _,finished=copy_backup(plan,root/'out',resume_manifest=backup/'manifest.json')
            self.assertEqual(finished['status'],'concluido')
            self.assertEqual(saved.stat().st_ino,prior_inode)
            self.assertEqual(len(finished['files']),plan.count)

    def test_backup_resume_rejects_changed_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source,plan=self.setup_items(root)
            stopped=threading.Event();stopped.set()
            backup,manifest=copy_backup(plan,root/'out',cancelled=stopped)
            (source/'new.txt').write_text('changed')
            revised=build_plan({str(source):'keep'},[str(root)])
            with self.assertRaises(ValueError):copy_backup(revised,root/'out',resume_manifest=backup/'manifest.json')

    def test_restore_resume_verified_and_recopy_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); _,plan=self.setup_items(root)
            backup,_=copy_backup(plan,root/'out')
            manifest=backup/'manifest.json';keys=list(verified_entries(manifest))
            stopped=threading.Event()
            def progress(phase,n,total,path,done,size):
                if phase=='Arquivo verificado' and n == 3:stopped.set()
            with self.assertRaises(InterruptedError):
                restore_selected(manifest,keys,root,cancelled=stopped,progress=progress)
            target=next(root.glob('TESTE-RESTAURACAO-*'))
            record=resume_information(target,manifest)
            self.assertEqual(record['keys'],keys)
            # Tamper one completed destination to ensure it is revalidated on resume.
            (target/keys[0]).write_bytes(b'bad')
            path,n=restore_selected(manifest,keys,root,resume_from=target)
            self.assertEqual(n,7)
            self.assertEqual(path.resolve(), target.resolve())
            self.assertEqual(json.loads((path/'ESTADO-RESTAURACAO.json').read_text())['status'],'concluida')
            self.assertTrue(all(sha256_file(path/k)==verified_entries(manifest)[k]['sha256'] for k in keys))
            with self.assertRaises(ValueError):resume_information(path,manifest)

    def test_restore_resume_cross_backup_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,plan=self.setup_items(root)
            backup,_=copy_backup(plan,root/'out'); m=backup/'manifest.json';keys=list(verified_entries(m))
            done=threading.Event();done.set()
            with self.assertRaises(InterruptedError):restore_selected(m,keys,root,cancelled=done)
            # No target created from a pre-cancelled operation.
            self.assertFalse(list(root.glob('TESTE-RESTAURACAO-*')))

if __name__ == '__main__':unittest.main()

