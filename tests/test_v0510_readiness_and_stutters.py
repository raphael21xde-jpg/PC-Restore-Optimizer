import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from reinstall_audit import audit_backup, audit_text
from stutter_deep import study_frames, study_text


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root/'C'/'Users'/'demo'
        self.data.mkdir(parents=True)
        self.file = self.data/'save.dat'
        self.file.write_bytes(b'save-state-123')
        self.rel = self.file.relative_to(self.root).as_posix()
        self.manifest = self.root/'manifest.json'
        self.doc = {
            'schema': 'pc-restore-backup-v0.4', 'status': 'concluido',
            'file_count_expected': 1, 'files': [
                {'relative': self.rel, 'bytes': len(self.file.read_bytes()),
                 'sha256': hashlib.sha256(self.file.read_bytes()).hexdigest(), 'verified': True}],
            'errors': []
        }
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        self.manifest.write_text(json.dumps(self.doc), encoding='utf8')

    def test_success_never_authorizes_format(self):
        result = audit_backup(self.manifest)
        self.assertTrue(result['integrity_ok'])
        self.assertFalse(result['approved_for_format'])
        self.assertEqual(result['valid'], 1)
        self.assertIn('NÃO AUTORIZADA', audit_text(result))

    def test_detect_tamper(self):
        self.file.write_bytes(b'save-state-124')
        result = audit_backup(self.manifest)
        self.assertFalse(result['integrity_ok'])
        self.assertIn('SHA-256', result['errors'][0])

    def test_reject_traversal(self):
        self.doc['files'][0]['relative'] = '../outside.txt'
        self.save()
        result = audit_backup(self.manifest)
        self.assertFalse(result['integrity_ok'])

    def test_reject_duplicate_entries(self):
        self.doc['files'].append(self.doc['files'][0].copy())
        self.doc['file_count_expected'] = 2
        self.save()
        result = audit_backup(self.manifest)
        self.assertFalse(result['integrity_ok'])

    def test_reject_partial_backup(self):
        self.doc['status'] = 'parcial_com_erros'
        self.save()
        result = audit_backup(self.manifest)
        self.assertFalse(result['integrity_ok'])


class StutterDeepTests(unittest.TestCase):
    def test_explicit_trim_preserves_original(self):
        frames = [(i / 100, 4.0) for i in range(1000)]
        frames[130] = (1.3, 80.0)
        result = study_frames(frames)
        self.assertEqual(result['original']['count'], 1000)
        self.assertEqual(result['after_exclusion']['count'], 500)
        self.assertEqual(result['original']['worst_ms'], 80.0)
        self.assertEqual(result['after_exclusion']['worst_ms'], 4.0)
        self.assertEqual(frames[130][1], 80.0)
        self.assertIn('QUADROS LENTOS', study_text(result))

    def test_reject_excessive_trim(self):
        with self.assertRaises(ValueError):
            study_frames([(i / 100, 4.0) for i in range(200)], 5.0)

    def test_detect_non_severe_microstutters(self):
        frames = [(i / 100, 4.) for i in range(800)]
        frames[620] = (6.2, 25.)
        r = study_frames(frames)
        self.assertEqual(r['after_exclusion']['event_count'], 0)
        self.assertEqual(r['threshold_counts']['25.00'], 1)
        self.assertGreater(len(r['slowest_frames']), 0)

if __name__ == '__main__':
    unittest.main()

# Regression: cancellation must not be displayed as a completed audit.
class AuditCancellationTests(unittest.TestCase):
    def test_cancelled_audit_raises(self):
        import threading
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'manifest.json'
            p.write_text(json.dumps({'schema':'pc-restore-backup-v0.4',
                                     'status':'concluido','file_count_expected':1,
                                     'files':[{'relative':'C/test.txt','verified':True,'bytes':0,
                                               'sha256':'0'*64}],'errors':[]}), encoding='utf8')
            ev=threading.Event();ev.set()
            with self.assertRaises(InterruptedError):
                audit_backup(p,cancelled=ev)
