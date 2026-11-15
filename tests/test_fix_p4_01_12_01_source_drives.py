"""FIX-P4-01-12-01: o backup grava o nome e o tamanho das unidades de origem.

Só dados sintéticos em TemporaryDirectory. O nome e o tamanho das unidades
são simulados (funções falsas); nenhum teste lê o nome ou o tamanho de uma
unidade real, e nada é gravado fora da pasta temporária. Sem Tk.
"""
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import after_format as af
import source_drives as sd
from backup_core import build_plan, copy_backup
from backup_features import restore_selected, verified_entries

GIB = 1024 ** 3
WIN_ENV = {'SystemRoot': r'C:\Windows', 'SystemDrive': 'C:'}


class FakeDisks:
    def __init__(self, labels=None, sizes=None):
        self.labels = dict(labels or {})
        self.sizes = dict(sizes or {})
        self.label_calls = []
        self.usage_calls = []

    def volume_label(self, root):
        self.label_calls.append(root)
        value = self.labels[root]
        if isinstance(value, Exception):
            raise value
        return value

    def usage(self, root):
        self.usage_calls.append(root)
        value = self.sizes[root]
        if isinstance(value, Exception):
            raise value
        return (value, value // 2, value // 2)


class ReadSourceDrivesTests(unittest.TestCase):
    def test_reads_label_and_size_of_each_source_letter(self):
        disks = FakeDisks({'C:\\': 'Windows', 'D:\\': 'Jogos', 'E:\\': ''},
                          {'C:\\': 500 * GIB, 'D:\\': 1000 * GIB, 'E:\\': 64 * GIB})
        result = sd.read_source_drives(
            [r'C:\Users\x\a.txt', r'd:\Jogos\save.dat', r'D:\Jogos\b.dat', r'E:\f.txt',
             r'\\servidor\pasta\x.txt'],
            volume_label=disks.volume_label, usage=disks.usage)
        self.assertEqual(result, {'C:': {'label': 'Windows', 'total': 500 * GIB},
                                  'D:': {'label': 'Jogos', 'total': 1000 * GIB},
                                  'E:': {'label': '', 'total': 64 * GIB}})
        self.assertEqual(sorted(disks.label_calls), ['C:\\', 'D:\\', 'E:\\'])

    def test_failed_read_leaves_drive_out(self):
        disks = FakeDisks({'C:\\': 'Windows', 'D:\\': OSError('sem acesso'), 'E:\\': None,
                           'F:\\': 'Dados', 'G:\\': 'Fotos'},
                          {'C:\\': OSError('sem acesso'), 'F:\\': 0, 'G:\\': 2 * GIB})
        result = sd.read_source_drives([r'C:\a', r'D:\b', r'E:\c', r'F:\d', r'G:\e'],
                                       volume_label=disks.volume_label, usage=disks.usage)
        self.assertEqual(result, {'G:': {'label': 'Fotos', 'total': 2 * GIB}})
        # sem nome lido, o tamanho nem é lido
        self.assertNotIn('D:\\', disks.usage_calls)
        self.assertNotIn('E:\\', disks.usage_calls)

    def test_strange_label_is_left_out(self):
        forged = 'Jogos\nTudo certo, pode formatar'
        disks = FakeDisks({'D:\\': forged, 'E:\\': 'x' * 33, 'F:\\': 'a"b', 'G:\\': 'x' * 32},
                          {'D:\\': GIB, 'E:\\': GIB, 'F:\\': GIB, 'G:\\': GIB})
        result = sd.read_source_drives([r'D:\a', r'E:\a', r'F:\a', r'G:\a'],
                                       volume_label=disks.volume_label, usage=disks.usage)
        self.assertEqual(result, {'G:': {'label': 'x' * 32, 'total': GIB}})
        self.assertNotIn('Tudo certo', json.dumps(result))

    def test_strange_size_is_left_out(self):
        disks = FakeDisks({'D:\\': 'A', 'E:\\': 'B', 'F:\\': 'C'},
                          {'D:\\': True, 'E:\\': -5, 'F:\\': 1.5})
        self.assertEqual(sd.read_source_drives([r'D:\a', r'E:\a', r'F:\a'],
                                               volume_label=disks.volume_label,
                                               usage=disks.usage), {})

    def test_off_windows_default_reads_nothing(self):
        if sys.platform == 'win32':
            self.skipTest('fora do Windows o nome da unidade não é lido')
        calls = []
        result = sd.read_source_drives([r'D:\Jogos\a'], usage=lambda r: calls.append(r))
        self.assertEqual(result, {})
        self.assertEqual(calls, [])

    def test_saved_field_round_trips_into_after_format(self):
        disks = FakeDisks({'D:\\': 'Jogos', 'E:\\': ''}, {'D:\\': 1000 * GIB, 'E:\\': GIB})
        result = sd.read_source_drives([r'D:\a', r'E:\b'], volume_label=disks.volume_label,
                                       usage=disks.usage)
        self.assertEqual(af._saved_drives({'source_drives': result}), result)


def _letter_d(_path):
    return 'D:'


class CopyBackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        folder = self.root / 'source'
        folder.mkdir()
        for index in range(4):
            (folder / f'{index}.dat').write_bytes(f'item {index}'.encode() * 50)
        self.plan = build_plan({str(folder): 'keep'}, [str(self.root)])
        self.disks = FakeDisks({'D:\\': 'Jogos'}, {'D:\\': 1000 * GIB})

    def reader(self, sources):
        # os caminhos do teste não têm letra; todos contam como vindos da D:
        return sd.read_source_drives(sources, volume_label=self.disks.volume_label,
                                     usage=self.disks.usage, letter=_letter_d)

    def test_new_manifest_has_source_drives(self):
        backup, manifest = copy_backup(self.plan, self.root / 'out',
                                       source_drives_reader=self.reader)
        self.assertEqual(manifest['status'], 'concluido')
        saved = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['source_drives'], {'D:': {'label': 'Jogos', 'total': 1000 * GIB}})
        self.assertEqual(af._saved_drives(saved), saved['source_drives'])
        # o resto do manifesto continua igual
        self.assertEqual(saved['schema'], 'pc-restore-backup-v0.4')
        self.assertEqual(len(saved['files']), self.plan.count)

    def test_failed_reads_do_not_stop_backup(self):
        self.disks = FakeDisks({'D:\\': OSError('sem acesso')}, {})
        backup, manifest = copy_backup(self.plan, self.root / 'out',
                                       source_drives_reader=self.reader)
        self.assertEqual(manifest['status'], 'concluido')
        self.assertNotIn('source_drives', manifest)

        self.disks = FakeDisks({'D:\\': 'Jogos'}, {'D:\\': OSError('sem acesso')})
        _, manifest = copy_backup(self.plan, self.root / 'out2',
                                  source_drives_reader=self.reader)
        self.assertEqual(manifest['status'], 'concluido')
        self.assertNotIn('source_drives', manifest)

    def test_reader_crash_does_not_stop_backup(self):
        def broken(_sources):
            raise RuntimeError('falhou')
        _, manifest = copy_backup(self.plan, self.root / 'out', source_drives_reader=broken)
        self.assertEqual(manifest['status'], 'concluido')
        self.assertNotIn('source_drives', manifest)

    def test_default_reader_off_windows_keeps_manifest_without_field(self):
        if sys.platform == 'win32':
            self.skipTest('no Windows o leitor padrão lê as unidades de verdade')
        _, manifest = copy_backup(self.plan, self.root / 'out')
        self.assertEqual(manifest['status'], 'concluido')
        self.assertNotIn('source_drives', manifest)

    def test_resume_keeps_field_and_does_not_read_again(self):
        stopped = threading.Event()

        def progress(n, *_args):
            if n == 2:
                stopped.set()
        backup, manifest = copy_backup(self.plan, self.root / 'out', cancelled=stopped,
                                       progress=progress, source_drives_reader=self.reader)
        self.assertEqual(manifest['status'], 'interrompido')
        first = manifest['source_drives']
        calls = []

        def must_not_run(sources):
            calls.append(sources)
            return {'Z:': {'label': 'Outro', 'total': 1}}
        _, final = copy_backup(self.plan, self.root / 'out',
                               resume_manifest=backup / 'manifest.json',
                               source_drives_reader=must_not_run)
        self.assertEqual(final['status'], 'concluido')
        self.assertEqual(final['source_drives'], first)
        self.assertEqual(calls, [])

    def test_resume_of_old_manifest_stays_without_field(self):
        stopped = threading.Event()

        def progress(n, *_args):
            if n == 2:
                stopped.set()
        backup, manifest = copy_backup(self.plan, self.root / 'out', cancelled=stopped,
                                       progress=progress, source_drives_reader=lambda s: {})
        self.assertNotIn('source_drives', manifest)
        _, final = copy_backup(self.plan, self.root / 'out',
                               resume_manifest=backup / 'manifest.json',
                               source_drives_reader=self.reader)
        self.assertEqual(final['status'], 'concluido')
        self.assertNotIn('source_drives', final)


class OldManifestTests(unittest.TestCase):
    """Manifesto antigo, sem 'source_drives', continua abrindo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _old_backup(self):
        folder = self.root / 'source'
        folder.mkdir()
        (folder / 'save.dat').write_bytes(b'save' * 100)
        plan = build_plan({str(folder): 'keep'}, [str(self.root)])
        backup, manifest = copy_backup(plan, self.root / 'out', source_drives_reader=lambda s: {})
        self.assertNotIn('source_drives', manifest)
        return backup / 'manifest.json'

    def test_old_manifest_restores(self):
        manifest = self._old_backup()
        keys = list(verified_entries(manifest))
        (self.root / 'restaurado').mkdir()
        result = restore_selected(manifest, keys, self.root / 'restaurado')
        self.assertTrue(result)
        restored = list((self.root / 'restaurado').rglob('save.dat'))
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].read_bytes(), b'save' * 100)

    def _write(self, sources, source_drives=None):
        files = [{'source': source, 'relative': f'f{i}.dat', 'verified': True, 'size': 1,
                  'sha256': hashlib.sha256(str(i).encode()).hexdigest()}
                 for i, source in enumerate(sources)]
        doc = {'schema': 'pc-restore-backup-v0.4', 'files': files}
        if source_drives is not None:
            doc['source_drives'] = source_drives
        path = self.root / 'b' / 'manifest.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding='utf-8')
        return path

    def _check(self, manifest, labels, sizes):
        disks = FakeDisks(labels, sizes)
        return af.check_drives(manifest, roots=['C:\\', 'D:\\'], usage=disks.usage,
                               environ=WIN_ENV, drive_type=lambda r: 'Disco local',
                               volume_label=disks.volume_label)

    def test_old_manifest_after_format_is_unconfirmed(self):
        manifest = self._write([r'C:\Users\x\a.txt', r'D:\Jogos\save.dat'])
        result = self._check(manifest, {'C:\\': 'Windows', 'D:\\': 'Jogos'},
                             {'C:\\': 500 * GIB, 'D:\\': 1000 * GIB})
        self.assertEqual(result['unconfirmed'], ['D:'])
        self.assertEqual(result['changed'], [])
        self.assertEqual(result['confirmed'], [])

    def test_new_field_after_format_confirms_or_warns(self):
        disks = FakeDisks({'C:\\': 'Windows', 'D:\\': 'Jogos'},
                          {'C:\\': 500 * GIB, 'D:\\': 1000 * GIB})
        sources = [r'C:\Users\x\a.txt', r'D:\Jogos\save.dat']
        saved = sd.read_source_drives(sources, volume_label=disks.volume_label,
                                      usage=disks.usage)
        manifest = self._write(sources, saved)
        same = self._check(manifest, {'C:\\': 'Windows', 'D:\\': 'Jogos'},
                           {'C:\\': 500 * GIB, 'D:\\': 1000 * GIB})
        self.assertEqual(same['confirmed'], ['D:'])
        other = self._check(manifest, {'C:\\': 'Windows', 'D:\\': 'Backup'},
                            {'C:\\': 500 * GIB, 'D:\\': 2000 * GIB})
        self.assertEqual(other['changed'], ['D:'])


if __name__ == '__main__':
    unittest.main()
