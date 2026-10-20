"""Real isolated files, deterministic interleaving, no user data or disk APIs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import backup_core
import backup_features
from safe_publication import file_version, publish_copy


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pcro-publication-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'a.bin').write_bytes(b'original-a')
        (self.source / 'b.bin').write_bytes(b'original-b')
        self.plan = backup_core.build_plan({str(self.source): 'keep'}, [str(self.root)])
        self.output = self.root / 'output'
        self.output.mkdir()

    def external_write(self, destination):
        subprocess.run([sys.executable, '-c',
                        'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b"external!!")',
                        str(destination)], check=True, timeout=20)

    def backup(self, hook=None, **kwargs):
        return backup_core.copy_backup(self.plan, self.output, strategy_inventory={},
                                       test_fault_hook=hook, **kwargs)

    def run_race(self, restore, after_publish):
        if restore:
            folder, report = self.backup()
            manifest = folder / 'manifest.json'
            keys = list(backup_features.verified_entries(manifest))
            race_root = self.root / 'restore'
            race_root.mkdir()
        else:
            race_root = self.output
        changed = []
        def hook(stage):
            expected = ('restore' if restore else 'backup') + ('_after_publish' if after_publish else '_after_write')
            if stage == expected and not changed:
                if after_publish:
                    destination = next(race_root.rglob('a.bin'))
                else:
                    partial = next(race_root.rglob('*.partial-*'))
                    destination = partial.with_name(partial.name.split('.partial-')[0])
                self.external_write(destination)
                changed.append(destination)
        if restore:
            with self.assertRaises(OSError):
                backup_features.restore_selected(manifest, keys, race_root, strategy_inventory={}, test_fault_hook=hook)
            journal = json.loads(next(race_root.rglob('ESTADO-RESTAURACAO.json')).read_text(encoding='utf-8'))
            self.assertEqual(journal['status'], 'falhou_parcial')
            self.assertEqual(journal['verified'], 0)
        else:
            folder, report = self.backup(hook)
            self.assertEqual(report['status'], 'parcial_com_erros')
            self.assertTrue(report['errors'])
            self.assertFalse(any(Path(item['relative']).name == 'a.bin' for item in report['files']))
        self.assertEqual(len(changed), 1, 'Fault injection must actually run')
        self.assertEqual(changed[0].read_bytes(), b'external!!')
        self.assertEqual((self.source / 'a.bin').read_bytes(), b'original-a')
        self.assertFalse(list(race_root.rglob('*.partial-*')))

    def test_backup_preserves_new_concurrent_destination(self):
        self.run_race(False, False)

    def test_backup_rejects_mutation_after_publication(self):
        self.run_race(False, True)

    def test_restore_preserves_new_concurrent_destination(self):
        self.run_race(True, False)

    def test_restore_rejects_mutation_after_publication(self):
        self.run_race(True, True)

    def test_backup_final_audit_detects_earlier_file_changed(self):
        published = []
        def hook(stage):
            if stage == 'backup_after_publish':
                published.append(True)
                if len(published) == 2:
                    self.external_write(next(self.output.rglob('a.bin')))
        folder, report = self.backup(hook)
        self.assertEqual(len(published), 2)
        self.assertEqual(report['status'], 'parcial_com_erros')
        self.assertEqual(len(report['files']), 1)
        self.assertEqual(Path(report['files'][0]['relative']).name, 'b.bin')

    def test_restore_final_audit_detects_earlier_file_changed(self):
        folder, report = self.backup()
        manifest = folder / 'manifest.json'
        keys = list(backup_features.verified_entries(manifest))
        destination = self.root / 'restore'
        destination.mkdir()
        published = []
        def hook(stage):
            if stage == 'restore_after_publish':
                published.append(True)
                if len(published) == 2:
                    self.external_write(next(destination.rglob('a.bin')))
        with self.assertRaises(OSError):
            backup_features.restore_selected(manifest, keys, destination, strategy_inventory={}, test_fault_hook=hook)
        self.assertEqual(len(published), 2)
        journal = json.loads(next(destination.rglob('ESTADO-RESTAURACAO.json')).read_text(encoding='utf-8'))
        self.assertEqual(journal['status'], 'falhou_parcial')
        self.assertEqual(journal['verified'], 1)

    def test_resume_preserves_old_corrupt_copy(self):
        stopped = threading.Event()
        def progress(index, *args):
            if index == 2:
                stopped.set()
        folder, report = self.backup(cancelled=stopped, progress=progress)
        entry = report['files'][0]
        damaged = folder / entry['relative']
        damaged.write_bytes(b'old corrupt copy')
        _, report = self.backup(resume_manifest=folder / 'manifest.json')
        self.assertEqual(report['status'], 'concluido')
        self.assertEqual(damaged.read_bytes(), Path(entry['source']).read_bytes())
        self.assertEqual([p.read_bytes() for p in damaged.parent.glob(damaged.name + '.retained-*')], [b'old corrupt copy'])

    def test_resume_detects_changed_destination_before_publication(self):
        destination = self.output / 'file'
        temporary = self.output / 'partial'
        destination.write_bytes(b'old')
        temporary.write_bytes(b'replacement')
        previous = file_version(destination)
        destination.write_bytes(b'external changed content')
        with self.assertRaises(OSError):
            publish_copy(temporary, destination, previous)
        self.assertEqual(destination.read_bytes(), b'external changed content')

    def test_resume_concurrent_arrival_keeps_both_existing_copies(self):
        import safe_publication
        destination = self.output / 'file'
        temporary = self.output / 'partial'
        destination.write_bytes(b'old')
        temporary.write_bytes(b'replacement')
        previous = file_version(destination)
        move = safe_publication.move_exclusive
        def interleave(src, dst):
            move(src, dst)
            if '.retained-' in str(dst):
                destination.write_bytes(b'concurrent')
        with patch.object(safe_publication, 'move_exclusive', interleave):
            with self.assertRaises(OSError):
                publish_copy(temporary, destination, previous)
        self.assertEqual(destination.read_bytes(), b'concurrent')
        self.assertEqual([p.read_bytes() for p in self.output.glob('*.retained-*')], [b'old'])


if __name__ == '__main__':
    unittest.main()
