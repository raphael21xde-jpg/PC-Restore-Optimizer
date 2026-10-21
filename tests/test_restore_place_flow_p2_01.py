"""P2-01 fatia 2: fluxo "Colocar no lugar original" (sem Tk).

Tudo sintetico, dentro de TemporaryDirectory. O "lugar original" e sempre uma
pasta temporaria: os caminhos de origem do manifesto ja apontam para dentro
do TemporaryDirectory. A elevacao e simulada com uma funcao de teste.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import restore_place
import restore_place_flow as flow
from restore_elevation import ElevatedRestoreRefused
from restore_place import place_files, plan_placement

TODAY = datetime.date(2026, 10, 21)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FlowFixture(unittest.TestCase):
    """Backup sintetico + pasta de conferencia como a restauracao cria."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-p2-01-flow-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.backup = self.root / 'backup'
        self.backup.mkdir()
        self.original = self.root / 'original'   # o "lugar original"
        self.original.mkdir()
        self.parent = self.root / 'restauracoes'
        self.parent.mkdir()
        self.staging = self.parent / 'TESTE-RESTAURACAO-v05-abcd1234'
        self.staging.mkdir()
        self.entries = []
        self.restored = []
        self.status = 'concluida'

    def add(self, relative, data, *, restored=True):
        backup_file = self.backup / relative
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(data)
        self.entries.append({'source': str(self.original / relative), 'relative': relative,
                             'bytes': len(data), 'sha256': sha(data), 'verified': True})
        if restored:
            staged = self.staging / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(data)
            self.restored.append(relative)

    def manifest(self):
        path = self.backup / 'manifest.json'
        path.write_text(json.dumps({'schema': 'pc-restore-backup-v0.4', 'files': self.entries}),
                        encoding='utf-8')
        return path

    def write_record(self, manifest, **changes):
        record = {'status': self.status, 'engine_version': '0.5.19',
                  'manifest_path': str(Path(manifest).resolve()), 'keys': list(self.restored),
                  'requested': len(self.restored), 'verified': len(self.restored),
                  'verified_keys': list(self.restored), 'resume_count': 0}
        record.update(changes)
        (self.staging / 'ESTADO-RESTAURACAO.json').write_text(json.dumps(record), encoding='utf-8')

    def ready(self, **changes):
        manifest = self.manifest()
        self.write_record(manifest, **changes)
        return manifest

    def plan_for(self, manifest, **kw):
        info = flow.staging_info(self.staging, manifest)
        kw.setdefault('today', TODAY)
        kw.setdefault('environ', {})
        return info, plan_placement(manifest, info['folder'], keys=info['keys'], **kw)

    def symlink_or_skip(self, link, target, directory=True):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'O sistema nao deixou criar link simbolico: {error}')


class PlanKeysTests(FlowFixture):
    def test_keys_excludes_files_not_restored(self):
        self.add('docs/a.txt', b'a')
        self.add('docs/b.txt', b'b', restored=False)
        manifest = self.ready()
        info, plan = self.plan_for(manifest)
        self.assertEqual(info['keys'], ['docs/a.txt'])
        self.assertEqual([i.key for i in plan.items], ['docs/a.txt'])
        self.assertEqual(plan.counts()['bloqueado'], 0)

    def test_keys_unknown_to_manifest_rejected(self):
        self.add('a.txt', b'a')
        manifest = self.manifest()
        with self.assertRaises(ValueError):
            plan_placement(manifest, self.staging, keys=['nao-existe.txt'], today=TODAY, environ={})


class StagingInfoTests(FlowFixture):
    def test_accepts_completed_and_verified(self):
        self.add('a.txt', b'a')
        manifest = self.ready()
        info = flow.staging_info(self.staging, manifest)
        self.assertEqual(info['folder'], self.staging.resolve())
        self.assertEqual(info['keys'], ['a.txt'])
        self.assertEqual(info['journal'], flow.journal_path_for(self.staging.resolve()))
        self.assertFalse(info['has_journal'])

    def test_refuses_folder_not_created_by_app(self):
        self.add('a.txt', b'a')
        manifest = self.ready()
        other = self.parent / 'MinhaPasta'
        other.mkdir()
        (other / 'ESTADO-RESTAURACAO.json').write_text(
            (self.staging / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'), encoding='utf-8')
        with self.assertRaises(ValueError):
            flow.staging_info(other, manifest)

    def test_refuses_not_completed(self):
        self.add('a.txt', b'a')
        for status in ('em_andamento', 'cancelada_parcial', 'falhou_parcial'):
            manifest = self.ready(status=status)
            with self.assertRaises(ValueError) as caught:
                flow.staging_info(self.staging, manifest)
            self.assertIn('concluída', str(caught.exception))

    def test_refuses_without_all_keys_verified(self):
        self.add('a.txt', b'a')
        self.add('b.txt', b'b')
        manifest = self.ready(verified_keys=['a.txt'])
        with self.assertRaises(ValueError):
            flow.staging_info(self.staging, manifest)
        manifest = self.ready(verified_keys=[], keys=[])
        with self.assertRaises(ValueError):
            flow.staging_info(self.staging, manifest)

    def test_refuses_other_manifest(self):
        self.add('a.txt', b'a')
        manifest = self.ready()
        other = self.root / 'outro-backup'
        other.mkdir()
        other_manifest = other / 'manifest.json'
        other_manifest.write_text(manifest.read_text(encoding='utf-8'), encoding='utf-8')
        with self.assertRaises(ValueError):
            flow.staging_info(self.staging, other_manifest)

    def test_refuses_journal_link(self):
        self.add('a.txt', b'a')
        manifest = self.ready()
        elsewhere = self.root / 'qualquer.json'
        elsewhere.write_text('{}', encoding='utf-8')
        self.symlink_or_skip(flow.journal_path_for(self.staging.resolve()), elsewhere,
                             directory=False)
        with self.assertRaises(ValueError):
            flow.staging_info(self.staging, manifest)


class JournalAndResumeTests(FlowFixture):
    def test_journal_is_beside_staging_not_inside(self):
        journal = flow.journal_path_for(self.staging)
        self.assertEqual(journal.parent, self.staging.parent)
        self.assertNotEqual(journal.parent, self.staging)
        self.assertIn(self.staging.name, journal.name)

    def test_run_writes_journal_outside_and_resume_skips_done(self):
        self.add('a.txt', b'a')
        self.add('b.txt', b'b')
        manifest = self.ready()
        _, plan = self.plan_for(manifest)
        result = flow.run_placement(plan, elevation_probe=lambda: False)
        self.assertEqual(result['status'], 'concluido')
        journal = flow.journal_path_for(self.staging.resolve())
        self.assertTrue(journal.is_file())
        self.assertNotIn('COLOCAR', ' '.join(p.name for p in self.staging.iterdir()))
        self.assertTrue(flow.staging_info(self.staging, manifest)['has_journal'])
        _, plan = self.plan_for(manifest)
        with mock.patch.object(restore_place, '_copy_and_verify') as copy:
            second = flow.run_placement(plan, elevation_probe=lambda: False)
        copy.assert_not_called()
        self.assertEqual(sorted(second['resumed']), ['a.txt', 'b.txt'])

    def test_elevated_refuses_without_writing(self):
        self.add('a.txt', b'a')
        manifest = self.ready()
        _, plan = self.plan_for(manifest)
        with self.assertRaises(ElevatedRestoreRefused):
            flow.run_placement(plan, elevation_probe=lambda: True)
        self.assertEqual(list(self.original.iterdir()), [])
        self.assertFalse(flow.journal_path_for(self.staging.resolve()).exists())

    def test_protected_skipped_without_allow(self):
        pf = self.root / 'ProgramFiles'
        self.add('a.txt', b'a')
        data = b'cfg'
        (self.backup / 'jogo.cfg').write_bytes(data)
        (self.staging / 'jogo.cfg').write_bytes(data)
        self.entries.append({'source': str(pf / 'Jogo' / 'jogo.cfg'), 'relative': 'jogo.cfg',
                             'bytes': 3, 'sha256': sha(data), 'verified': True})
        self.restored.append('jogo.cfg')
        manifest = self.ready()
        _, plan = self.plan_for(manifest, environ={'ProgramFiles': str(pf)})
        result = flow.run_placement(plan, elevation_probe=lambda: False)
        self.assertEqual(result['skipped_protected'], ['jogo.cfg'])
        self.assertFalse(pf.exists())
        self.assertEqual((self.original / 'a.txt').read_bytes(), b'a')
        # "Sim" vindo de outro tipo (1, 'sim') nao libera as pastas protegidas.
        result = flow.run_placement(plan, allow_protected=1, elevation_probe=lambda: False)
        self.assertFalse(pf.exists())
        self.assertIn('pasta', flow.confirmation_text(plan, allow_protected=False).lower())

    def test_cancel_then_resume_without_duplicates(self):
        for name in ('1.txt', '2.txt', '3.txt'):
            self.add(name, name.encode())
        manifest = self.ready()
        _, plan = self.plan_for(manifest)
        cancel = threading.Event()

        def progress(index, total, key):
            if index == 1:
                cancel.set()

        first = flow.run_placement(plan, cancelled=cancel, progress=progress,
                                   elevation_probe=lambda: False)
        self.assertEqual(first['status'], 'cancelado')
        _, plan = self.plan_for(manifest)
        second = flow.run_placement(plan, elevation_probe=lambda: False)
        self.assertEqual(second['status'], 'concluido')
        self.assertEqual(sorted(second['placed']), ['2.txt', '3.txt'])
        self.assertEqual(sorted(p.name for p in self.original.iterdir()),
                         ['1.txt', '2.txt', '3.txt'])


class TextTests(FlowFixture):
    INTERNAL = ('precisa_admin', 'renomear:', 'skipped_protected', 'concluido_com_falhas',
                'em_andamento', 'target_map', 'verified_keys', 'fingerprint', 'in_progress',
                'resumed', 'placed', 'None', "{'", 'staging')

    def scenario(self):
        pf = self.root / 'ProgramFiles'
        self.add('novo.txt', b'n')
        self.add('igual.txt', b'i')
        self.add('dif.txt', b'd')
        self.add('desktop.ini', b'ini')
        (self.original / 'igual.txt').write_bytes(b'i')
        (self.original / 'dif.txt').write_bytes(b'outro')
        (self.original / 'pasta.txt').mkdir()
        self.add('pasta.txt', b'x')
        data = b'cfg'
        (self.staging / 'jogo.cfg').write_bytes(data)
        self.entries.append({'source': str(pf / 'jogo.cfg'), 'relative': 'jogo.cfg',
                             'bytes': 3, 'sha256': sha(data), 'verified': True})
        self.restored.append('jogo.cfg')
        manifest = self.ready()
        return self.plan_for(manifest, environ={'ProgramFiles': str(pf)})[1]

    def test_preview_counts_in_portuguese(self):
        plan = self.scenario()
        text = flow.preview_summary(plan)
        for expected in ('1 arquivo(s) novo(s)', '1 arquivo(s) igual(is)',
                         'guardar o antigo', 'administrador', 'bloqueado',
                         'ignorado'):
            self.assertIn(expected, text)
        for word in self.INTERNAL[:2]:
            self.assertNotIn(word, text)

    def test_confirmation_mentions_protected_choice(self):
        plan = self.scenario()
        off = flow.confirmation_text(plan, allow_protected=False)
        on = flow.confirmation_text(plan, allow_protected=True)
        self.assertIn('não serão colocados', off)
        self.assertIn('administrador', on)
        self.assertIn('Nada será apagado', off)
        self.assertNotEqual(off, on)

    def test_friendly_report_has_no_internal_names(self):
        plan = self.scenario()
        result = flow.run_placement(plan, elevation_probe=lambda: False)
        text = flow.friendly_report(plan, result)
        for word in self.INTERNAL:
            self.assertNotIn(word, text)
        self.assertIn('antes-pcro', text)            # nome do arquivo antigo guardado
        self.assertIn('pasta de conferência', text)
        self.assertIn('não foram colocados', text)


class EngineReviewTests(FlowFixture):
    """Ressalvas do revisor da PR #58."""

    def test_root_link_is_blocked(self):
        self.add('a.txt', b'a')
        manifest = self.manifest()
        real_root = self.root / 'raiz-verdadeira'
        real_root.mkdir()
        link_root = self.root / 'raiz-link'
        self.symlink_or_skip(link_root, real_root)
        plan = plan_placement(manifest, self.staging, today=TODAY, environ={},
                              target_map={str(self.original): str(link_root)})
        self.assertEqual(plan.items[0].category, 'bloqueado')
        result = place_files(plan, confirmed_preview=True,
                             journal_path=self.root / 'diario.json')
        self.assertEqual([f['key'] for f in result['failures']], ['a.txt'])
        self.assertEqual(list(real_root.iterdir()), [])

    def journal_with_in_progress(self, plan, journal, identity):
        partial = Path(str(plan.items[0].target) + restore_place.PARTIAL_SUFFIX)
        data = {'schema': restore_place.JOURNAL_SCHEMA, 'manifest_path': str(plan.manifest_path),
                'staging_folder': str(plan.staging_folder), 'fingerprint': plan.fingerprint(),
                'status': 'em_andamento', 'done': {}, 'failures': [],
                'in_progress': {'key': plan.items[0].key, 'partial': str(partial)}}
        if identity is not None:
            data['in_progress']['identity'] = identity
        journal.write_text(json.dumps(data), encoding='utf-8')
        return partial

    def test_partial_with_other_identity_is_kept(self):
        self.add('a.txt', b'a')
        manifest = self.manifest()
        plan = plan_placement(manifest, self.staging, today=TODAY, environ={})
        journal = self.root / 'diario.json'
        partial = self.journal_with_in_progress(plan, journal, None)
        partial.write_bytes(b'de outro programa')
        info = os.lstat(partial)
        for identity in (None, [info.st_ino + 1, info.st_dev]):
            self.journal_with_in_progress(plan, journal, identity)
            result = place_files(plan, confirmed_preview=True, journal_path=journal)
            self.assertEqual(partial.read_bytes(), b'de outro programa')
            self.assertFalse((self.original / 'a.txt').exists())
            self.assertEqual([f['key'] for f in result['failures']], ['a.txt'])

    def test_own_partial_with_same_identity_is_discarded(self):
        self.add('a.txt', b'a')
        manifest = self.manifest()
        plan = plan_placement(manifest, self.staging, today=TODAY, environ={})
        journal = self.root / 'diario.json'
        partial = Path(str(plan.items[0].target) + restore_place.PARTIAL_SUFFIX)
        partial.write_bytes(b'sobra do app')
        info = os.lstat(partial)
        self.journal_with_in_progress(plan, journal, [info.st_ino, info.st_dev])
        result = place_files(plan, confirmed_preview=True, journal_path=journal)
        self.assertEqual(result['status'], 'concluido')
        self.assertFalse(partial.exists())
        self.assertEqual((self.original / 'a.txt').read_bytes(), b'a')

    def test_in_progress_records_identity_after_create(self):
        self.add('a.txt', b'a')
        manifest = self.manifest()
        plan = plan_placement(manifest, self.staging, today=TODAY, environ={})
        journal = self.root / 'diario.json'
        seen = {}

        def look(partial):
            data = json.loads(journal.read_text(encoding='utf-8'))
            seen['in_progress'] = data['in_progress']
            info = os.lstat(partial)
            seen['identity'] = [info.st_ino, info.st_dev]

        place_files(plan, confirmed_preview=True, journal_path=journal, test_after_copy_hook=look)
        self.assertEqual(seen['in_progress']['identity'], seen['identity'])
        self.assertIsNone(json.loads(journal.read_text(encoding='utf-8'))['in_progress'])


if __name__ == '__main__':
    unittest.main()
