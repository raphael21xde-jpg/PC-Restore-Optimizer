"""P2-01: colocar arquivos conferidos de volta no lugar original.

Todos os arquivos sao sinteticos e ficam dentro de TemporaryDirectory.
O "lugar original" e sempre uma pasta temporaria (via target_map ou
caminhos de origem ja temporarios). Nada de discos reais, nada de
elevacao de privilegio: subprocess e similares sao simulados com mocks.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import restore_place
from restore_place import placement_report, place_files, plan_placement

TODAY = datetime.date(2026, 10, 21)
STAMP = '20261021'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class PlacementFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-p2-01-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.staging = self.root / 'conferencia'
        self.original_root = self.root / 'original'   # como era no PC antigo
        self.target_root = self.root / 'alvo'          # onde o teste coloca
        self.staging.mkdir()
        self.target_root.mkdir()
        self.entries = []
        self.environ = {}
        self.journal = self.root / 'diario' / 'colocar.json'

    def add(self, relative, data, *, source=None, verified=True):
        staged = self.staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        if source is None:
            source = str(self.original_root / relative)
        self.entries.append({'source': source, 'relative': relative,
                             'bytes': len(data), 'sha256': sha(data),
                             'verified': verified})
        return staged

    def manifest(self):
        path = self.staging / 'manifest.json'
        path.write_text(json.dumps({'schema': 'pc-restore-backup-v0.4',
                                    'files': self.entries}), encoding='utf-8')
        return path

    def target(self, relative):
        return self.target_root / relative

    def plan(self, **kw):
        kw.setdefault('target_map', {str(self.original_root): str(self.target_root)})
        kw.setdefault('today', TODAY)
        kw.setdefault('environ', self.environ)
        return plan_placement(self.manifest(), self.staging, **kw)

    def place(self, plan, **kw):
        kw.setdefault('confirmed_preview', True)
        kw.setdefault('journal_path', self.journal)
        return place_files(plan, **kw)

    def by_key(self, plan):
        return {item.key: item for item in plan.items}

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix(): sha(p.read_bytes())
                for p in sorted(folder.rglob('*')) if p.is_file()}


class PlanTests(PlacementFixture):
    def test_plan_classifies_all_categories(self):
        self.add('docs/novo.txt', b'novo')
        self.add('docs/igual.txt', b'igual')
        self.add('docs/diferente.txt', b'versao do backup')
        self.add('docs/Desktop.INI', b'[.ShellClassInfo]')
        pf = self.root / 'pf'
        self.environ = {'ProgramFiles': str(pf)}
        self.add('jogo.cfg', b'cfg', source=str(pf / 'Jogo' / 'jogo.cfg'))
        self.target('docs').mkdir(parents=True)
        self.target('docs/igual.txt').write_bytes(b'igual')
        self.target('docs/diferente.txt').write_bytes(b'versao atual')
        plan = self.plan(target_map={str(self.original_root): str(self.target_root),
                                     str(pf): str(pf)})
        cats = {k: v.category for k, v in self.by_key(plan).items()}
        self.assertEqual(cats, {'docs/novo.txt': 'novo', 'docs/igual.txt': 'igual',
                                'docs/diferente.txt': 'renomear',
                                'docs/Desktop.INI': 'ignorado',
                                'jogo.cfg': 'precisa_admin'})
        self.assertEqual(plan.counts()['novo'], 1)
        # A previa e somente leitura: nada foi criado no alvo.
        self.assertFalse(self.target('docs/novo.txt').exists())
        self.assertFalse((pf / 'Jogo').exists())

    def test_rejects_target_escape(self):
        self.add('ok.txt', b'x')
        self.entries[0]['relative'] = '../fora.txt'
        with self.assertRaises(ValueError):
            self.plan()
        self.entries[0]['relative'] = str(self.root / 'abs.txt')
        with self.assertRaises(ValueError):
            self.plan()
        self.entries[0]['relative'] = 'ok.txt'
        self.entries[0]['source'] = str(self.original_root / '..' / '..' / 'fora.txt')
        with self.assertRaises(ValueError):
            self.plan()
        self.entries[0]['source'] = 'relativo/ok.txt'
        with self.assertRaises(ValueError):
            self.plan()
        # Origem fora do mapa de destino nunca cai no caminho real.
        self.entries[0]['source'] = str(self.root / 'outro' / 'ok.txt')
        with self.assertRaises(ValueError):
            self.plan()


class PlaceTests(PlacementFixture):
    def test_place_refuses_without_confirmed_preview(self):
        self.add('a.txt', b'a')
        plan = self.plan()
        with self.assertRaises(ValueError):
            place_files(plan, journal_path=self.journal)
        self.assertFalse(self.target('a.txt').exists())
        self.assertFalse(self.journal.exists())

    def test_places_new_file_at_original_path(self):
        self.add('Documents/carta.txt', b'conteudo da carta')
        result = self.place(self.plan())
        self.assertEqual(self.target('Documents/carta.txt').read_bytes(), b'conteudo da carta')
        self.assertEqual(result['status'], 'concluido')
        self.assertEqual(result['placed'], ['Documents/carta.txt'])
        self.assertFalse(self.target('Documents/carta.txt.pcro-partial').exists())

    def test_sha_mismatch_after_copy_keeps_original_and_reports(self):
        self.add('a.txt', b'backup')
        self.target('a.txt').write_bytes(b'atual')

        def corrupt(partial):
            Path(partial).write_bytes(b'corrompido')

        result = self.place(self.plan(), test_after_copy_hook=corrupt)
        self.assertEqual(self.target('a.txt').read_bytes(), b'atual')
        self.assertEqual(list(self.target_root.iterdir()), [self.target('a.txt')])
        self.assertEqual(result['status'], 'concluido_com_falhas')
        self.assertEqual([f['key'] for f in result['failures']], ['a.txt'])
        self.assertIn('SHA-256', result['failures'][0]['error'])

    def test_existing_different_renamed_antes_pcro(self):
        self.add('save.dat', b'do backup')
        self.target('save.dat').write_bytes(b'atual')
        result = self.place(self.plan())
        aside = self.target(f'save.dat.antes-pcro-{STAMP}')
        self.assertEqual(aside.read_bytes(), b'atual')
        self.assertEqual(self.target('save.dat').read_bytes(), b'do backup')
        self.assertEqual(result['renamed'], [{'key': 'save.dat', 'target': str(self.target('save.dat')),
                                              'aside': str(aside)}])

    def test_rename_suffix_collision(self):
        self.add('save.dat', b'do backup')
        self.target('save.dat').write_bytes(b'atual')
        self.target(f'save.dat.antes-pcro-{STAMP}').write_bytes(b'antigo 1')
        self.target(f'save.dat.antes-pcro-{STAMP}-2').write_bytes(b'antigo 2')
        self.place(self.plan())
        self.assertEqual(self.target(f'save.dat.antes-pcro-{STAMP}').read_bytes(), b'antigo 1')
        self.assertEqual(self.target(f'save.dat.antes-pcro-{STAMP}-2').read_bytes(), b'antigo 2')
        self.assertEqual(self.target(f'save.dat.antes-pcro-{STAMP}-3').read_bytes(), b'atual')
        self.assertEqual(self.target('save.dat').read_bytes(), b'do backup')

    def test_equal_file_untouched(self):
        self.add('igual.txt', b'mesmo')
        target = self.target('igual.txt')
        target.write_bytes(b'mesmo')
        os.utime(target, ns=(1_000_000_000, 1_000_000_000))
        before = os.stat(target)
        result = self.place(self.plan())
        after = os.stat(target)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assertEqual(result['equal'], ['igual.txt'])
        self.assertEqual(sorted(p.name for p in self.target_root.iterdir()), ['igual.txt'])

    def test_desktop_ini_ignored(self):
        self.add('Pasta/desktop.ini', b'[.ShellClassInfo]')
        self.add('Outra/DESKTOP.INI', b'x')
        result = self.place(self.plan())
        self.assertFalse(self.target('Pasta/desktop.ini').exists())
        self.assertFalse(self.target('Outra/DESKTOP.INI').exists())
        self.assertEqual(sorted(result['ignored']), ['Outra/DESKTOP.INI', 'Pasta/desktop.ini'])
        self.assertEqual(result['placed'], [])

    def test_protected_paths_need_allow_protected(self):
        pd = self.root / 'ProgramData'
        pf86 = self.root / 'pf86'
        self.environ = {'ProgramData': str(pd), 'ProgramFiles(x86)': str(pf86)}
        self.add('a.cfg', b'a', source=str(pd / 'App' / 'a.cfg'))
        self.add('b.cfg', b'b', source=str(pf86 / 'App' / 'b.cfg'))
        mapping = {str(pd): str(pd), str(pf86): str(pf86)}
        plan = self.plan(target_map=mapping)
        result = self.place(plan)
        self.assertEqual(sorted(result['skipped_protected']), ['a.cfg', 'b.cfg'])
        self.assertFalse(pd.exists())
        self.assertFalse(pf86.exists())
        self.journal.unlink()
        result = self.place(self.plan(target_map=mapping), allow_protected=True)
        self.assertEqual(sorted(result['placed']), ['a.cfg', 'b.cfg'])
        self.assertEqual((pd / 'App' / 'a.cfg').read_bytes(), b'a')

    def test_never_requests_elevation(self):
        pd = self.root / 'ProgramData'
        self.environ = {'ProgramData': str(pd)}
        self.add('a.cfg', b'a', source=str(pd / 'a.cfg'))
        plan = self.plan(target_map={str(pd): str(pd)})
        real_replace = os.replace

        def denied(src, dst):
            if str(dst) == str(pd / 'a.cfg'):
                raise PermissionError(13, 'Acesso negado')
            return real_replace(src, dst)

        with mock.patch.object(subprocess, 'run') as run, \
                mock.patch.object(subprocess, 'Popen') as popen, \
                mock.patch.object(restore_place.os, 'replace', side_effect=denied), \
                mock.patch.object(os, 'startfile', create=True) as startfile:
            result = self.place(plan, allow_protected=True)
        run.assert_not_called()
        popen.assert_not_called()
        startfile.assert_not_called()
        self.assertEqual([f['key'] for f in result['failures']], ['a.cfg'])
        self.assertIn('Não foi possível gravar (pasta protegida', result['failures'][0]['error'])
        self.assertEqual([p.name for p in pd.iterdir()], [])
        source = Path(restore_place.__file__).read_text(encoding='utf-8').lower()
        for word in ('runas', 'shellexecute', 'subprocess', 'ctypes'):
            self.assertNotIn(word, source)

    def test_placed_file_is_new_inode_not_rename_of_staging(self):
        staged = self.add('x/arquivo.bin', b'dados' * 100)
        before = os.stat(staged)
        self.place(self.plan())
        target = os.stat(self.target('x/arquivo.bin'))
        self.assertTrue(staged.exists())
        self.assertNotEqual(before.st_ino, target.st_ino)
        self.assertEqual(os.stat(staged).st_nlink, 1)
        self.assertEqual(os.stat(staged).st_ino, before.st_ino)

    def test_copy_is_exclusive_partial_in_final_folder_then_replace(self):
        # Prova estrutural da heranca de permissoes (sem ferramenta externa):
        # o arquivo nasce do zero com open(..., 'xb') na pasta final e so
        # depois troca de nome com os.replace na mesma pasta. A conferencia
        # real da DACL no Windows e teste manual do Raphael.
        self.add('acl/arquivo.txt', b'acl')
        target = self.target('acl/arquivo.txt')
        partial = Path(str(target) + '.pcro-partial')
        opened, replaced = [], []
        real_open, real_replace = open, os.replace

        def spy_open(path, mode='r', *args, **kwargs):
            opened.append((str(path), mode))
            return real_open(path, mode, *args, **kwargs)

        def spy_replace(src, dst):
            replaced.append((str(src), str(dst)))
            return real_replace(src, dst)

        plan = self.plan()
        with mock.patch('restore_place.open', side_effect=spy_open, create=True), \
                mock.patch.object(restore_place.os, 'replace', side_effect=spy_replace), \
                mock.patch.object(restore_place.os, 'rename') as rename:
            result = self.place(plan)
        self.assertEqual(result['placed'], ['acl/arquivo.txt'])
        writes = [(path, mode) for path, mode in opened if 'b' in mode and mode != 'rb']
        self.assertEqual(writes, [(str(partial), 'xb')])
        self.assertEqual(Path(writes[0][0]).parent, target.parent)
        self.assertIn((str(partial), str(target)), replaced)
        self.assertFalse([pair for pair in replaced if str(self.staging) in pair[0]])
        rename.assert_not_called()
        source = Path(restore_place.__file__).read_text(encoding='utf-8')
        self.assertNotIn('shutil', source)

    def test_target_appearing_during_copy_is_preserved(self):
        self.add('novo.txt', b'do backup')
        target = self.target('novo.txt')

        def someone_creates_target(partial):
            target.write_bytes(b'apareceu agora')

        plan = self.plan()
        self.assertEqual(self.by_key(plan)['novo.txt'].category, 'novo')
        result = self.place(plan, test_after_copy_hook=someone_creates_target)
        self.assertEqual(target.read_bytes(), b'apareceu agora')
        self.assertEqual([p.name for p in self.target_root.iterdir()], ['novo.txt'])
        self.assertEqual([f['key'] for f in result['failures']], ['novo.txt'])
        self.assertIn('apareceu', result['failures'][0]['error'])
        self.assertEqual(result['placed'], [])

    def test_existing_changed_during_copy_is_preserved(self):
        self.add('save.dat', b'do backup')
        target = self.target('save.dat')
        target.write_bytes(b'atual')

        def someone_edits_target(partial):
            target.write_bytes(b'editado durante a copia')

        result = self.place(self.plan(), test_after_copy_hook=someone_edits_target)
        self.assertEqual(target.read_bytes(), b'editado durante a copia')
        self.assertEqual([p.name for p in self.target_root.iterdir()], ['save.dat'])
        self.assertEqual([f['key'] for f in result['failures']], ['save.dat'])

    def test_staging_and_backup_untouched(self):
        self.add('a.txt', b'a')
        self.add('b/c.txt', b'c')
        self.target('a.txt').write_bytes(b'outro')
        manifest = self.manifest()
        before = self.snapshot(self.staging)
        result = self.place(plan_placement(manifest, self.staging, today=TODAY, environ={},
                                           target_map={str(self.original_root): str(self.target_root)}))
        self.assertEqual(result['status'], 'concluido')
        self.assertEqual(self.snapshot(self.staging), before)


class BlockedTests(PlacementFixture):
    def symlink_or_skip(self, link, target):
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'O sistema nao deixou criar link simbolico: {error}')

    def assert_blocked(self, key):
        plan = self.plan()
        self.assertEqual(self.by_key(plan)[key].category, 'bloqueado')
        result = self.place(plan)
        self.assertEqual([f['key'] for f in result['failures']], [key])
        self.assertEqual(result['placed'], [])
        return result

    def test_blocked_when_target_is_folder(self):
        self.add('a.txt', b'a')
        self.target('a.txt').mkdir()
        self.assert_blocked('a.txt')
        self.assertTrue(self.target('a.txt').is_dir())
        self.assertEqual(list(self.target('a.txt').iterdir()), [])

    def test_blocked_when_target_is_symlink(self):
        self.add('a.txt', b'a')
        elsewhere = self.root / 'outro-lugar'
        elsewhere.mkdir()
        try:
            os.symlink(elsewhere / 'alvo.txt', self.target('a.txt'))
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'O sistema nao deixou criar link simbolico: {error}')
        self.assert_blocked('a.txt')
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_blocked_when_parent_is_symlink(self):
        self.add('pasta/a.txt', b'a')
        elsewhere = self.root / 'outro-lugar'
        elsewhere.mkdir()
        self.symlink_or_skip(self.target('pasta'), elsewhere)
        self.assert_blocked('pasta/a.txt')
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_blocked_when_any_ancestor_below_root_is_symlink(self):
        self.add('n1/n2/n3/a.txt', b'a')
        elsewhere = self.root / 'outro-lugar'
        elsewhere.mkdir()
        self.symlink_or_skip(self.target('n1'), elsewhere)
        self.assert_blocked('n1/n2/n3/a.txt')
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_system_root_and_windir_are_protected(self):
        system_root = self.root / 'Windows'
        windir = self.root / 'WINDIR2'
        self.environ = {'SystemRoot': str(system_root), 'windir': str(windir)}
        self.add('a.dll', b'a', source=str(system_root / 'System32' / 'a.dll'))
        self.add('b.ini', b'b', source=str(windir / 'b.ini'))
        mapping = {str(system_root): str(system_root), str(windir): str(windir)}
        plan = self.plan(target_map=mapping)
        self.assertEqual({i.key: i.category for i in plan.items},
                         {'a.dll': 'precisa_admin', 'b.ini': 'precisa_admin'})
        result = self.place(plan)
        self.assertEqual(sorted(result['skipped_protected']), ['a.dll', 'b.ini'])
        self.assertFalse(system_root.exists())
        self.assertFalse(windir.exists())


class JournalTests(PlacementFixture):
    def test_resume_skips_verified(self):
        self.add('a.txt', b'a')
        self.add('b.txt', b'b')
        first = self.place(self.plan())
        self.assertEqual(sorted(first['placed']), ['a.txt', 'b.txt'])
        journal = json.loads(self.journal.read_text(encoding='utf-8'))
        self.assertEqual(sorted(journal['done']), ['a.txt', 'b.txt'])
        with mock.patch.object(restore_place, '_copy_and_verify') as copy:
            second = self.place(self.plan())
        copy.assert_not_called()
        self.assertEqual(second['placed'], [])
        self.assertEqual(sorted(second['resumed']), ['a.txt', 'b.txt'])

    def test_resume_rejects_journal_from_other_plan(self):
        self.add('a.txt', b'a')
        self.place(self.plan())
        self.entries[0]['sha256'] = sha(b'outro')
        (self.staging / 'a.txt').write_bytes(b'outro')
        with self.assertRaises(ValueError):
            self.place(self.plan())

    def test_cancel_midway_then_resume(self):
        for name in ('1.txt', '2.txt', '3.txt'):
            self.add(name, name.encode())
        cancel = threading.Event()
        seen = []

        def progress(index, total, key):
            seen.append(key)
            if index == 1:
                cancel.set()

        first = self.place(self.plan(), cancelled=cancel, progress=progress)
        self.assertEqual(first['status'], 'cancelado')
        self.assertEqual(first['placed'], ['1.txt'])
        self.assertFalse(self.target('2.txt').exists())
        self.assertEqual([p.name for p in self.target_root.iterdir()], ['1.txt'])
        journal = json.loads(self.journal.read_text(encoding='utf-8'))
        self.assertEqual(journal['status'], 'cancelado')
        second = self.place(self.plan())
        self.assertEqual(second['status'], 'concluido')
        self.assertEqual(sorted(second['placed']), ['2.txt', '3.txt'])
        self.assertIn('1.txt', second['resumed'] + second['equal'])
        for name in ('1.txt', '2.txt', '3.txt'):
            self.assertEqual(self.target(name).read_bytes(), name.encode())

    def test_cancel_during_copy_discards_only_own_partial(self):
        self.add('grande.bin', b'x' * (3 * restore_place.CHUNK))
        cancel = threading.Event()
        real = restore_place._write_chunk

        def write_then_cancel(stream, data):
            real(stream, data)
            cancel.set()

        with mock.patch.object(restore_place, '_write_chunk', side_effect=write_then_cancel):
            result = self.place(self.plan(), cancelled=cancel)
        self.assertEqual(result['status'], 'cancelado')
        self.assertEqual(list(self.target_root.iterdir()), [])

    def test_foreign_partial_is_never_discarded(self):
        self.add('a.txt', b'a')
        foreign = self.target('a.txt.pcro-partial')
        foreign.write_bytes(b'nao e do app')
        result = self.place(self.plan())
        self.assertEqual(foreign.read_bytes(), b'nao e do app')
        self.assertFalse(self.target('a.txt').exists())
        self.assertEqual([f['key'] for f in result['failures']], ['a.txt'])

    def test_report_lists_counts(self):
        self.add('novo.txt', b'n')
        self.add('igual.txt', b'i')
        self.add('dif.txt', b'd')
        self.add('desktop.ini', b'ini')
        self.target('igual.txt').write_bytes(b'i')
        self.target('dif.txt').write_bytes(b'outro')
        self.add('ruim.txt', b'r')
        plan = self.plan()

        def corrupt(partial):
            if Path(partial).name.startswith('ruim'):
                Path(partial).write_bytes(b'?')

        result = self.place(plan, test_after_copy_hook=corrupt)
        text = placement_report(plan, result)
        for expected in ('novo: 2', 'igual: 1', 'renomear: 1', 'ignorado: 1',
                         'precisa_admin: 0', 'Falhas: 1', 'ruim.txt',
                         f'dif.txt.antes-pcro-{STAMP}', 'pasta de conferência'):
            self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
