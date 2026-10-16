from pathlib import Path
import json, sys, tempfile, threading, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backup_core import build_plan, copy_backup
from backup_features import restore_selected, verified_entries
from restore_jobs import Job
from unittest.mock import patch
from backup_core import sha256_file
class RestoreTests(unittest.TestCase):
    def prepare(self,root):
        source=root/'source';source.mkdir()
        (source/'song.bin').write_bytes(b'x'*(5*1024*1024))
        backup,_=copy_backup(build_plan({str(source):'keep'},[str(root)]),root/'backup')
        manifest=backup/'manifest.json'
        return manifest,list(verified_entries(manifest))
    def test_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,keys=self.prepare(root);events=[]
            with patch('backup_features.sha256_file', wraps=sha256_file) as hashing:
                target,count=restore_selected(manifest,keys,root,progress=lambda *args:events.append(args))
                self.assertEqual(hashing.call_count,1)  # Source hashed during copy; only destination reread.
            self.assertEqual(count,1)
            self.assertEqual((target/keys[0]).read_bytes(),b'x'*(5*1024*1024))
            self.assertEqual(json.loads((target/'ESTADO-RESTAURACAO.json').read_text())['status'],'concluida')
            self.assertEqual(events[-1][1:3],(1,1))
            self.assertFalse(list(target.rglob('*.partial-*')))
    def test_cancel_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,keys=self.prepare(root);cancel=threading.Event()
            def progress(phase,n,total,path,done,size):
                if phase=='Copiando' and done>0:cancel.set()
            with self.assertRaises(InterruptedError):restore_selected(manifest,keys,root,cancelled=cancel,progress=progress)
            target=next(root.glob('TESTE-RESTAURACAO-*'))
            self.assertEqual(json.loads((target/'ESTADO-RESTAURACAO.json').read_text())['status'],'cancelada_parcial')
            self.assertFalse((target/keys[0]).exists())
            self.assertEqual((manifest.parent/keys[0]).stat().st_size,5*1024*1024)
    def test_cancel_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cancel=threading.Event();cancel.set()
            with self.assertRaises(InterruptedError):restore_selected(root/'missing',[],root,cancelled=cancel)
            self.assertEqual(list(root.iterdir()),[])
    def test_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,keys=self.prepare(root)
            (manifest.parent/keys[0]).write_bytes(b'corrupted')
            with self.assertRaises(OSError):restore_selected(manifest,keys,root)
            target=next(root.glob('TESTE-RESTAURACAO-*'))
            self.assertEqual(json.loads((target/'ESTADO-RESTAURACAO.json').read_text())['status'],'falhou_parcial')
            self.assertFalse((target/keys[0]).exists())
    def test_worker_nonblocking(self):
        started=threading.Event();release=threading.Event();main=threading.get_ident()
        def work(cancel,progress):
            started.set();release.wait(3);return threading.get_ident()
        job=Job(work)
        try:self.assertTrue(started.wait(2));self.assertIsNone(job.poll())
        finally:release.set();job.thread.join(3)
        kind,worker=job.poll();self.assertEqual(kind,'done');self.assertNotEqual(main,worker)
    def test_worker_cancel(self):
        def work(cancel,progress):raise InterruptedError('cancelled')
        job=Job(work);job.thread.join(3)
        self.assertEqual(job.poll()[0],'cancelled')
