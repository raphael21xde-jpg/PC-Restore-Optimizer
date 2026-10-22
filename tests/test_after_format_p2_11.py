"""P2-11: assistente "Depois de formatar".

Tudo com dados simulados: as "unidades" são textos ('C:\\', 'D:\\') com
disk_usage e tipo simulados, ou pastas dentro de TemporaryDirectory. Nunca
lista discos reais, nunca chama o Gerenciamento de Disco, nada é apagado.
"""
import gc
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import after_format as af
import game_launchers as gl
from windows_drive import WARNING as DRIVE_WARNING, windows_drive

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('formate', 'formatar o', 'apague', 'apagar', 'exclua', 'excluir',
             'desinstal', 'particion')


def _snapshot(root):
    out = []
    for folder, dirs, files in os.walk(root):
        for name in sorted(dirs) + sorted(files):
            p = Path(folder) / name
            st = os.lstat(p)
            out.append((str(p), st.st_size if not p.is_dir() else 0, st.st_mtime_ns))
    return sorted(out)


def _write_manifest(folder, sources=(), started=None, fingerprint=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for index, (source, relative) in enumerate(sources):
        files.append({'source': source, 'relative': relative, 'verified': True,
                      'sha256': hashlib.sha256(str(index).encode()).hexdigest(), 'size': 1})
    path = folder / 'manifest.json'
    doc = {'schema': 'pc-restore-backup-v0.5'}
    if started is not None:
        doc['started'] = started
    if fingerprint is not None:
        doc['plan_fingerprint'] = fingerprint
    doc['files'] = files
    # mesmo formato do backup_core.atomic_json (indent=2)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def _backup(root, name='backup-20261021-120000-jogos-abc123', started='2026-10-21T12:00:00',
            fingerprint='f' * 64):
    return _write_manifest(Path(root) / name, started=started, fingerprint=fingerprint)


def _usage(root):
    return (500 * 1024 ** 3, 100 * 1024 ** 3, 400 * 1024 ** 3)


WIN_ENV = {'SystemRoot': r'C:\Windows', 'SystemDrive': 'C:'}


class WindowsDriveTests(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(windows_drive(WIN_ENV), ('C:', ''))

    def test_windir_when_systemroot_missing(self):
        self.assertEqual(windows_drive({'windir': r'D:\Windows', 'SystemDrive': 'D:'}),
                         ('D:', ''))

    def test_different(self):
        self.assertEqual(windows_drive({'SystemRoot': r'D:\Windows', 'SystemDrive': 'C:'}),
                         (None, DRIVE_WARNING))
        self.assertIn('não deu para confirmar qual é o disco do windows', DRIVE_WARNING.lower())

    def test_missing(self):
        self.assertEqual(windows_drive({}), (None, DRIVE_WARNING))
        self.assertEqual(windows_drive({'SystemDrive': 'C:'}), (None, DRIVE_WARNING))
        self.assertEqual(windows_drive({'SystemRoot': r'C:\Windows'}), (None, DRIVE_WARNING))

    def test_lowercase(self):
        self.assertEqual(windows_drive({'systemroot': r'c:\windows', 'systemdrive': 'c:'}),
                         ('C:', ''))

    def test_not_a_letter(self):
        self.assertEqual(windows_drive({'SystemRoot': r'\\srv\x\Windows',
                                        'SystemDrive': r'\\srv\x'}), (None, DRIVE_WARNING))

    def test_module_imports_nothing_from_project(self):
        src = (ROOT / 'windows_drive.py').read_text(encoding='utf-8')
        imports = [line for line in src.splitlines() if line.startswith(('import ', 'from '))]
        for line in imports:
            name = line.split()[1].split('.')[0]
            self.assertFalse((ROOT / f'{name}.py').exists(), line)


class LauncherSystemDriveTests(unittest.TestCase):
    def test_divergent_systemroot_shows_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / 'A'
            (a / 'steamapps').mkdir(parents=True)
            (a / 'steamapps' / 'libraryfolders.vdf').write_text('x', encoding='utf-8')
            env = {'SystemRoot': r'D:\Windows', 'SystemDrive': 'C:'}
            with mock.patch.object(gl, '_on_windows', return_value=True), \
                    mock.patch.dict(os.environ, env, clear=True):
                result = gl.detect_launchers([a])
        self.assertIn(gl.UNKNOWN_SYSTEM_DRIVE_WARNING, result['warnings'])
        self.assertIsNone(result['libraries'][0]['on_system_drive'])

    def test_ui_shows_confira_for_unknown(self):
        try:
            from launcher_guide_ui import _drive_note
        except ImportError:
            self.skipTest('Sem Tk')
        self.assertEqual(_drive_note({'on_system_drive': None}), 'Confira')
        self.assertEqual(_drive_note({'on_system_drive': True}), 'Disco do Windows')
        self.assertEqual(_drive_note({'on_system_drive': False}), '')


class CheckDrivesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.manifest = _write_manifest(self.base / 'backup' / 'b1', [
            (r'C:\Users\x\Documents\a.txt', 'C/a.txt'),
            (r'D:\Jogos\save.dat', 'D/save.dat'),
            (r'D:\Jogos\save2.dat', 'D/save2.dat')])

    def check(self, roots, **kw):
        kw.setdefault('environ', WIN_ENV)
        kw.setdefault('usage', _usage)
        kw.setdefault('drive_type', lambda root: 'Disco local')
        return af.check_drives(self.manifest, roots=roots, **kw)

    def test_missing_letter_gives_guidance(self):
        result = self.check(['C:\\', 'E:\\'])
        self.assertEqual(result['missing'], ['D:'])
        self.assertEqual(result['backup_letters'], {'C:': 1, 'D:': 2})
        self.assertIn('Gerenciamento de Disco', result['guidance'])
        self.assertIn('Alterar letra de unidade e caminho', result['guidance'])
        self.assertIn('D:', result['guidance'])
        self.assertTrue(any('D:' in w for w in result['warnings']))

    def test_all_letters_present_no_guidance(self):
        result = self.check(['C:\\', 'D:\\'])
        self.assertEqual(result['missing'], [])
        self.assertEqual(result['guidance'], '')

    def test_windows_drive_marked(self):
        result = self.check(['C:\\', 'D:\\'])
        drives = {d['letter']: d for d in result['drives']}
        self.assertTrue(drives['C:']['windows'])
        self.assertFalse(drives['D:']['windows'])
        self.assertEqual(drives['C:']['type'], 'Disco local')
        self.assertEqual(drives['C:']['total'], 500 * 1024 ** 3)
        self.assertEqual(drives['C:']['free'], 400 * 1024 ** 3)

    def test_unknown_windows_drive_marks_none(self):
        result = self.check(['C:\\'], environ={})
        self.assertFalse(result['drives'][0]['windows'])
        self.assertIn(DRIVE_WARNING, result['warnings'])

    def test_listing_failure_is_empty_with_warning(self):
        with mock.patch.object(af, '_on_windows', return_value=True), \
                mock.patch('deep_discovery.local_drives', side_effect=OSError('x')):
            result = af.check_drives(self.manifest, environ=WIN_ENV)
        self.assertEqual(result['drives'], [])
        self.assertEqual(result['missing'], [])
        self.assertTrue(any('Não foi possível listar' in w for w in result['warnings']))

    def test_usage_failure_is_reported(self):
        def broken(root):
            raise OSError('sem acesso')
        result = self.check(['C:\\'], usage=broken)
        self.assertIsNone(result['drives'][0]['total'])
        self.assertEqual(result['drives'][0]['free_text'], 'não deu para ler')

    def test_bad_manifest_warns(self):
        bad = self.base / 'ruim' / 'manifest.json'
        bad.parent.mkdir()
        bad.write_text('{', encoding='utf-8')
        result = af.check_drives(bad, roots=['C:\\'], usage=_usage, environ=WIN_ENV,
                                 drive_type=lambda r: 'Disco local')
        self.assertTrue(any('manifest.json' in w for w in result['warnings']))

    def test_nothing_written_on_simulated_roots(self):
        roots = [self.base / 'A', self.base / 'B']
        for root in roots:
            (root / 'pasta').mkdir(parents=True)
            (root / 'pasta' / 'f.txt').write_text('x', encoding='utf-8')
        before = _snapshot(self.base)
        result = af.check_drives(self.manifest, roots=roots, environ=WIN_ENV)
        self.assertEqual(len(result['drives']), 2)
        self.assertEqual(_snapshot(self.base), before)

    def test_guidance_never_tells_to_format_or_delete(self):
        texts = [af.CHANGE_LETTER_GUIDE] + [s['title'] + ' ' + s['text'] for s in af.STEPS]
        for text in texts:
            for word in FORBIDDEN:
                self.assertNotIn(word, text.lower(), text)

    def test_password_alert_names_only(self):
        manifest = _write_manifest(self.base / 'backup' / 'b2', [
            (r'C:\Users\fulano\Downloads\Chrome Passwords.csv',
             'C/Users/fulano/Downloads/Chrome Passwords.csv'),
            (r'C:\Users\fulano\Documents\nota.txt', 'C/Users/fulano/Documents/nota.txt')])
        text = af.password_alert(manifest)
        self.assertIn('Chrome Passwords.csv', text)
        self.assertNotIn('fulano', text)
        self.assertNotIn('nota.txt', text)
        self.assertEqual(af.password_alert(self.manifest), '')


class ProgressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / 'progresso'
        self.manifest = _backup(self.tmp / 'E')

    def test_path_uses_stable_backup_key(self):
        path = af.progress_path(self.manifest, self.base)
        text = 'v2|backup-20261021-120000-jogos-abc123|2026-10-21T12:00:00|' + 'f' * 64
        key = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
        self.assertEqual(path, self.base / f'progresso-b-{key}.json')

    def test_unreadable_manifest_uses_path_key_with_warning(self):
        missing = self.tmp / 'X' / 'b1' / 'manifest.json'
        broken = _write_manifest(self.tmp / 'Y' / 'b2')  # sem started/plan_fingerprint
        for manifest in (missing, broken):
            self.assertIsNone(af.backup_identity(manifest))
            key = hashlib.sha256(os.path.normcase(os.path.abspath(str(manifest)))
                                 .encode('utf-8')).hexdigest()[:12]
            self.assertEqual(af.progress_path(manifest, self.base),
                             self.base / f'progresso-{key}.json')
            loaded = af.load_progress(manifest, self.base)
            self.assertIn(af.NO_IDENTITY_WARNING, loaded['warnings'])
            self.assertEqual(loaded['path'], self.base / f'progresso-{key}.json')

    def test_letter_change_finds_progress(self):
        # o mesmo backup, visto por outra "unidade" (outra raiz temporária)
        first = af.load_progress(self.manifest, self.base)
        af.save_progress(first['path'], dict(first['steps'], discos=af.DONE), first['backup'])
        moved = _backup(self.tmp / 'F')
        self.assertNotEqual(moved, self.manifest)
        again = af.load_progress(moved, self.base)
        self.assertEqual(again['steps']['discos'], af.DONE)
        self.assertEqual(again['path'], first['path'])
        self.assertEqual(af.window_key(moved), af.window_key(self.manifest))

    def test_folder_name_case_does_not_matter(self):
        upper = _backup(self.tmp / 'G', name='BACKUP-20261021-120000-JOGOS-ABC123')
        self.assertEqual(af.progress_path(upper, self.base),
                         af.progress_path(self.manifest, self.base))

    def test_different_backups_different_keys(self):
        other_time = _backup(self.tmp / 'E2', started='2026-10-22T08:00:00')
        other_plan = _backup(self.tmp / 'E3', fingerprint='a' * 64)
        other_name = _backup(self.tmp / 'E4', name='backup-outro')
        paths = {af.progress_path(m, self.base)
                 for m in (self.manifest, other_time, other_plan, other_name)}
        self.assertEqual(len(paths), 4)
        keys = {af.window_key(m) for m in (self.manifest, other_time, other_plan, other_name)}
        self.assertEqual(len(keys), 4)

    def test_big_manifest_reads_only_top_fields(self):
        big = self.tmp / 'H' / 'backup-grande' / 'manifest.json'
        big.parent.mkdir(parents=True)
        doc = {'schema': 'pc-restore-backup-v0.4', 'started': '2026-10-21T12:00:00',
               'item_descriptors': [{'started': 'falso', 'plan_fingerprint': 'falso'}],
               'plan_fingerprint': 'c' * 64, 'files': []}
        text = json.dumps(doc, indent=2)
        text = text.replace('"files": []', '"files": ["' + 'x' * 1024 + '"' +
                            (', "' + 'x' * 1024 + '"') * 9000 + ']')
        big.write_text(text, encoding='utf-8')
        self.assertGreater(big.stat().st_size, af.IDENTITY_FULL_READ_LIMIT)
        self.assertEqual(af.backup_identity(big),
                         {'folder': 'backup-grande', 'started': '2026-10-21T12:00:00',
                          'plan_fingerprint': 'c' * 64})

    def test_old_progress_is_read_and_never_rewritten(self):
        old = af.legacy_progress_path(self.manifest, self.base)
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({'schema': af.SCHEMA, 'steps': {'discos': af.DONE}}),
                       encoding='utf-8')
        before = (old.read_bytes(), os.stat(old).st_mtime_ns)
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['steps']['discos'], af.DONE)
        self.assertEqual(loaded['path'], af.progress_path(self.manifest, self.base))
        self.assertNotEqual(loaded['path'], old)
        af.save_progress(loaded['path'], dict(loaded['steps'], restaurar=af.DONE),
                         loaded['backup'])
        again = af.load_progress(self.manifest, self.base)
        self.assertEqual(again['steps']['restaurar'], af.DONE)
        self.assertEqual(again['steps']['discos'], af.DONE)
        self.assertEqual((old.read_bytes(), os.stat(old).st_mtime_ns), before)

    def test_other_identity_untouched_and_goes_to_2(self):
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        foreign = {'folder': 'outro', 'started': 'x', 'plan_fingerprint': 'y'}
        path.write_text(json.dumps({'schema': af.SCHEMA, 'backup': foreign,
                                    'steps': {'discos': af.DONE}}), encoding='utf-8')
        before = path.read_bytes()
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['steps']['discos'], af.PENDING)
        self.assertEqual(loaded['path'].name, path.stem + '-2.json')
        self.assertTrue(any('outro backup' in w for w in loaded['warnings']))
        af.save_progress(loaded['path'], loaded['steps'], loaded['backup'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(af.load_progress(self.manifest, self.base)['path'], loaded['path'])

    def test_default_base_uses_localappdata(self):
        base = af.default_base({'LOCALAPPDATA': str(self.base)})
        self.assertEqual(base, self.base / 'PC-Restore-Optimizer' / 'depois-de-formatar')

    def test_round_trip(self):
        first = af.load_progress(self.manifest, self.base)
        self.assertEqual(set(first['steps'].values()), {af.PENDING})
        self.assertEqual(first['warnings'], [])
        steps = dict(first['steps'], discos=af.DONE, launchers=af.SKIPPED)
        af.save_progress(first['path'], steps, first['backup'])
        again = af.load_progress(self.manifest, self.base)
        self.assertEqual(again['steps'], steps)
        self.assertEqual(again['path'], first['path'])

    def test_invalid_value_refused(self):
        path = af.load_progress(self.manifest, self.base)['path']
        with self.assertRaises(ValueError):
            af.save_progress(path, {'discos': 'talvez'})
        with self.assertRaises(ValueError):
            af.save_progress(path, {'formatar': af.DONE})
        self.assertFalse(path.exists())

    def test_corrupt_json_untouched_and_saved_in_2(self):
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        path.write_text('{ estragado', encoding='utf-8')
        before = path.read_bytes()
        loaded = af.load_progress(self.manifest, self.base)
        self.assertTrue(loaded['warnings'])
        self.assertEqual(set(loaded['steps'].values()), {af.PENDING})
        self.assertEqual(loaded['path'].name, path.stem + '-2.json')
        af.save_progress(loaded['path'], dict(loaded['steps'], discos=af.DONE),
                         loaded['backup'])
        self.assertEqual(path.read_bytes(), before)
        again = af.load_progress(self.manifest, self.base)
        self.assertEqual(again['steps']['discos'], af.DONE)
        self.assertEqual(again['path'], loaded['path'])

    def test_invalid_value_in_file_is_untouched(self):
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema': af.SCHEMA, 'steps': {'discos': 'x'}}),
                        encoding='utf-8')
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['path'].name, path.stem + '-2.json')
        self.assertTrue(path.exists())

    def test_too_big_untouched(self):
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        path.write_bytes(b' ' * (af.PROGRESS_LIMIT + 1))
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['path'].name, path.stem + '-2.json')
        self.assertEqual(path.stat().st_size, af.PROGRESS_LIMIT + 1)

    def test_separate_backups(self):
        other = _backup(self.tmp / 'E', name='backup-b2')
        a = af.load_progress(self.manifest, self.base)
        af.save_progress(a['path'], dict(a['steps'], discos=af.DONE), a['backup'])
        b = af.load_progress(other, self.base)
        self.assertNotEqual(a['path'], b['path'])
        self.assertEqual(b['steps']['discos'], af.PENDING)

    def test_link_refused(self):
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        target = self.base / 'alvo.json'
        target.write_text(json.dumps({'schema': af.SCHEMA, 'steps': {'discos': af.DONE}}),
                          encoding='utf-8')
        try:
            os.symlink(target, path)
        except (OSError, NotImplementedError):
            self.skipTest('não foi possível criar link simbólico neste sistema')
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['steps']['discos'], af.PENDING)
        self.assertEqual(loaded['path'].name, path.stem + '-2.json')
        self.assertTrue(loaded['warnings'])
        with self.assertRaises(OSError):
            af.save_progress(path, loaded['steps'])
        self.assertTrue(os.path.islink(path))
        self.assertIn(af.DONE, target.read_text(encoding='utf-8'))

    def test_leftover_partial_ignored(self):
        # .parcial antigo de nome fixo (P2-11) e um .parcial que é link: ignorados, intocados
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        partial = path.with_name(path.name + af.PARTIAL_SUFFIX)
        partial.write_text('{ meio gravado', encoding='utf-8')
        target = self.tmp / 'alvo.txt'
        target.write_text('não mexer', encoding='utf-8')
        link = path.with_name(path.name + af.PARTIAL_SUFFIX + '-link')
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            link = None
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['path'], path)
        self.assertEqual(loaded['warnings'], [])
        af.save_progress(path, dict(loaded['steps'], restaurar=af.DONE), loaded['backup'])
        self.assertEqual(af.load_progress(self.manifest, self.base)['steps']['restaurar'],
                         af.DONE)
        self.assertEqual(partial.read_text(encoding='utf-8'), '{ meio gravado')
        self.assertEqual(target.read_text(encoding='utf-8'), 'não mexer')
        if link is not None:
            self.assertTrue(os.path.islink(link))

    def _partials(self, path):
        return sorted(p.name for p in path.parent.iterdir()
                      if p.name.startswith(path.name + af.PARTIAL_SUFFIX + '-'))

    def test_partial_names_are_unique(self):
        path = af.progress_path(self.manifest, self.base)
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src).name)
            return real_replace(src, dst)
        with mock.patch.object(af.os, 'replace', side_effect=spy):
            for _ in range(3):
                af.save_progress(path, {}, af.backup_identity(self.manifest))
        self.assertEqual(len(set(seen)), 3)
        for name in seen:
            self.assertTrue(name.startswith(path.name + af.PARTIAL_SUFFIX + '-'), name)
        self.assertEqual(self._partials(path), [])

    def test_failed_replace_keeps_partial_and_final(self):
        loaded = af.load_progress(self.manifest, self.base)
        path = loaded['path']
        af.save_progress(path, dict(loaded['steps'], discos=af.DONE), loaded['backup'])
        before = path.read_bytes()
        with mock.patch.object(af.os, 'replace', side_effect=OSError('falhou')):
            with self.assertRaises(OSError):
                af.save_progress(path, dict(loaded['steps'], discos=af.SKIPPED),
                                 loaded['backup'])
        self.assertEqual(path.read_bytes(), before)
        partials = self._partials(path)
        self.assertEqual(len(partials), 1)  # fica no disco: nada é apagado
        self.assertIn(af.SKIPPED, (path.parent / partials[0]).read_text(encoding='utf-8'))

    def test_replace_retries_with_growing_wait(self):
        loaded = af.load_progress(self.manifest, self.base)
        real_replace = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) <= 3:
                raise PermissionError(13, 'em uso', str(dst))
            return real_replace(src, dst)
        waits = []
        with mock.patch.object(af.os, 'replace', side_effect=flaky), \
                mock.patch.object(af.time, 'sleep', side_effect=waits.append):
            af.save_progress(loaded['path'], dict(loaded['steps'], discos=af.DONE),
                             loaded['backup'])
        self.assertEqual(len(calls), 4)
        self.assertEqual(waits, sorted(waits))
        self.assertLess(waits[0], waits[-1])
        self.assertEqual(af.load_progress(self.manifest, self.base)['steps']['discos'], af.DONE)

    def test_replace_gives_up_after_about_two_seconds(self):
        loaded = af.load_progress(self.manifest, self.base)
        waits = []
        with mock.patch.object(af.os, 'replace',
                               side_effect=PermissionError(13, 'em uso', 'x')), \
                mock.patch.object(af.time, 'sleep', side_effect=waits.append):
            with self.assertRaises(PermissionError):
                af.save_progress(loaded['path'], loaded['steps'], loaded['backup'])
        self.assertAlmostEqual(sum(waits), af.REPLACE_TOTAL_WAIT, places=6)
        self.assertLessEqual(max(waits), af.REPLACE_MAX_WAIT)
        self.assertEqual(len(self._partials(loaded['path'])), 1)  # nada apagado

    def test_concurrent_saves_always_valid_json(self):
        import threading
        path = af.progress_path(self.manifest, self.base)
        identity = af.backup_identity(self.manifest)
        errors = []
        bad_reads = []
        stop = threading.Event()

        def writer(value):
            try:
                for i in range(50):
                    af.save_progress(path, {'discos': value if i % 2 else af.PENDING},
                                     identity)
            except Exception as exc:  # pragma: no cover - só aparece se falhar
                errors.append(exc)

        def reader():
            while not stop.is_set():
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                try:
                    json.loads(data.decode('utf-8'))
                except ValueError:
                    bad_reads.append(data)
                time.sleep(0.001)  # pausa curta: deixa a troca do arquivo acontecer
        threads = [threading.Thread(target=writer, args=(v,)) for v in (af.DONE, af.SKIPPED)]
        watcher = threading.Thread(target=reader)
        watcher.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        stop.set()
        watcher.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(bad_reads, [])
        self.assertEqual(af._read(path, identity)[0], 'ok')
        self.assertEqual(self._partials(path), [])

    def test_save_error_text_hides_full_path(self):
        # FIX-P2-11-01: o aviso leva no máximo o nome do arquivo e o tipo do erro
        exc = PermissionError(13, 'Acesso negado',
                              r'C:\Users\fulano\AppData\Local\PC-Restore-Optimizer'
                              r'\depois-de-formatar\progresso-abc.json.parcial')
        text = af.progress_error_text(exc)
        self.assertTrue(text.startswith('Não deu para salvar o progresso'))
        self.assertIn('progresso-abc.json.parcial', text)
        self.assertIn('PermissionError', text)
        for word in ('fulano', 'Users', 'AppData', 'Acesso negado'):
            self.assertNotIn(word, text)

    def test_save_error_text_without_filename(self):
        text = af.progress_error_text(ValueError(r'C:\Users\fulano\x'))
        self.assertIn('ValueError', text)
        self.assertNotIn('fulano', text)
        self.assertNotIn('Users', text)

    def test_never_deletes(self):
        src = (ROOT / 'after_format.py').read_text(encoding='utf-8')
        for word in ('unlink', 'os.remove', 'rmtree', 'rmdir', 'subprocess', 'os.system'):
            self.assertNotIn(word, src)


class ProgressSaverTests(unittest.TestCase):
    """FIX-P2-11-03: gravação do progresso fora da thread da interface (sem Tk)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.path = self.tmp / 'progresso' / 'progresso.json'
        self.steps = af._empty_steps()

    def marks(self, **changes):
        return dict(self.steps, **changes)

    def held_save(self):
        """save falso que espera um Event antes de cada gravação."""
        import threading
        release = threading.Event()
        started = threading.Event()
        calls = []

        def save(path, steps, backup=None):
            started.set()
            self.assertTrue(release.wait(5))
            calls.append((path, dict(steps), backup))
            return steps
        return save, release, started, calls

    def test_latest_request_wins_and_writes_in_order(self):
        save, release, started, calls = self.held_save()
        saver = af.ProgressSaver(self.path, 'id-1', save=save)
        first = self.marks(discos=af.DONE)
        second = self.marks(discos=af.DONE, restaurar=af.SKIPPED)
        third = self.marks(discos=af.PENDING, restaurar=af.SKIPPED, navegador=af.DONE)
        saver.request(first)
        self.assertTrue(started.wait(5))  # a 1ª gravação começou e está presa
        saver.request(second)
        saver.request(third)
        release.set()
        self.assertTrue(saver.join(5))
        self.assertLessEqual(len(calls), 2)
        self.assertEqual(calls[-1], (self.path, third, 'id-1'))
        self.assertNotIn(second, [c[1] for c in calls])  # intermediário foi juntado
        self.assertIsNone(saver.pending_steps())
        self.assertIsNone(saver.poll_error())

    def test_request_keeps_a_copy(self):
        save, release, started, calls = self.held_save()
        saver = af.ProgressSaver(self.path, None, save=save)
        steps = self.marks(discos=af.DONE)
        saver.request(steps)
        steps['discos'] = af.SKIPPED  # a tela muda o dicionário depois do pedido
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(calls[-1][1]['discos'], af.DONE)

    def test_pending_steps_reflects_last_request(self):
        save, release, started, calls = self.held_save()
        saver = af.ProgressSaver(self.path, None, save=save)
        self.assertIsNone(saver.pending_steps())
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(started.wait(5))
        saver.request(self.marks(launchers=af.SKIPPED))
        pending = saver.pending_steps()
        self.assertEqual(pending, self.marks(launchers=af.SKIPPED))
        pending['launchers'] = af.DONE  # cópia: não muda o que será gravado
        self.assertEqual(saver.pending_steps()['launchers'], af.SKIPPED)
        self.assertTrue(saver.busy())
        release.set()
        self.assertTrue(saver.join(5))
        self.assertFalse(saver.busy())
        self.assertIsNone(saver.pending_steps())

    def test_close_does_not_cancel_pending_save(self):
        save, release, started, calls = self.held_save()
        saver = af.ProgressSaver(self.path, None, save=save)
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(started.wait(5))
        saver.request(self.marks(discos=af.DONE, programas=af.DONE))
        saver.close()  # a janela fechou com um pedido ainda na fila
        self.assertTrue(saver.closed)
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(calls[-1][1], self.marks(discos=af.DONE, programas=af.DONE))

    def test_writer_thread_is_not_daemon(self):
        save, release, started, calls = self.held_save()
        saver = af.ProgressSaver(self.path, None, save=save)
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(started.wait(5))
        try:
            self.assertFalse(saver._thread.daemon)  # sair do app espera a gravação
        finally:
            release.set()
            self.assertTrue(saver.join(5))

    def test_save_error_becomes_text_without_path(self):
        def save(path, steps, backup=None):
            raise PermissionError(13, 'Acesso negado',
                                  r'C:\Users\fulano\AppData\progresso.json.parcial-abc')
        saver = af.ProgressSaver(self.path, None, save=save)
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(saver.join(5))
        text = saver.poll_error()
        self.assertTrue(text.startswith('Não deu para salvar o progresso'))
        self.assertIn('PermissionError', text)
        for word in ('fulano', 'Users', 'AppData', 'Acesso negado'):
            self.assertNotIn(word, text)
        self.assertIsNone(saver.poll_error())  # o aviso é entregue uma vez

    def test_error_then_success_keeps_working(self):
        results = [OSError('falhou'), None]
        calls = []

        def save(path, steps, backup=None):
            outcome = results.pop(0)
            if outcome is not None:
                raise outcome
            calls.append(dict(steps))
        saver = af.ProgressSaver(self.path, None, save=save)
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(saver.join(5))
        self.assertIsNotNone(saver.poll_error())
        saver.request(self.marks(discos=af.SKIPPED))
        self.assertTrue(saver.join(5))
        self.assertEqual(calls, [self.marks(discos=af.SKIPPED)])

    def test_real_save_in_background(self):
        manifest = _backup(self.tmp / 'E')
        loaded = af.load_progress(manifest, self.tmp / 'base')
        saver = af.ProgressSaver(loaded['path'], loaded['backup'])
        for value in (af.DONE, af.SKIPPED, af.DONE):
            saver.request(dict(loaded['steps'], discos=value, launchers=af.SKIPPED))
        saver.close()
        self.assertTrue(saver.join(10))
        self.assertIsNone(saver.poll_error())
        again = af.load_progress(manifest, self.tmp / 'base')
        self.assertEqual(again['steps']['discos'], af.DONE)
        self.assertEqual(again['steps']['launchers'], af.SKIPPED)
        self.assertEqual(again['path'], loaded['path'])

    def test_refuses_link_in_background(self):
        target = self.tmp / 'outro.json'
        target.write_text('não mexer', encoding='utf-8')
        self.path.parent.mkdir(parents=True)
        try:
            os.symlink(target, self.path)
        except (OSError, NotImplementedError):
            self.skipTest('Sem permissão para criar link simbólico')
        saver = af.ProgressSaver(self.path, None)
        saver.request(self.marks(discos=af.DONE))
        self.assertTrue(saver.join(5))
        self.assertIn('Não deu para salvar o progresso', saver.poll_error())
        self.assertEqual(target.read_text(encoding='utf-8'), 'não mexer')
        self.assertTrue(os.path.islink(self.path))

    def test_ui_mark_does_not_save_directly(self):
        src = (ROOT / 'after_format_ui.py').read_text(encoding='utf-8')
        self.assertFalse('save_progress' in src, 'a tela não pode gravar direto')
        start = src.index('    def mark(')
        end = src.index('\n    def ', start + 1)
        body = src[start:end]
        self.assertIn('.request(', body)
        self.assertIn('ProgressSaver', src)
        self.assertIn('after_format_savers', src)
        self.assertIn('poll_error()', src)
        self.assertIn('pending_steps()', src)


try:
    import tkinter as tk
    from tkinter import ttk
    import after_format_ui as afu
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = afu = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


class SourceTests(unittest.TestCase):
    def test_app_has_button_and_menu_item(self):
        src = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("'Depois de formatar  →'", src)
        self.assertIn("self._nav_action('✚', 'Depois de formatar', self.open_after_format)", src)

    def test_ui_never_passes_elevated_flags(self):
        src = (ROOT / 'after_format_ui.py').read_text(encoding='utf-8')
        for word in ('allow_elevated', 'allow_protected', 'subprocess', 'os.startfile'):
            self.assertNotIn(word, src)


FAKE_CHECK = ({'drives': [
    {'root': 'C:\\', 'letter': 'C:', 'type': 'Disco local', 'total': 1, 'free': 1,
     'total_text': '1 B', 'free_text': '1 B', 'windows': True},
    {'root': 'E:\\', 'letter': 'E:', 'type': 'Disco local', 'total': 1, 'free': 1,
     'total_text': '1 B', 'free_text': '1 B', 'windows': False}],
    'backup_letters': {'D:': 1}, 'missing': ['D:'], 'windows': 'C:',
    'warnings': ['letra D: sumiu'], 'guidance': af.CHANGE_LETTER_GUIDE.format(letters='D:')},
    'Atenção: senhas.csv')


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.busy = False
        self.addCleanup(self.root.destroy)
        self.addCleanup(gc.collect)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / 'progresso'
        self.manifest = _backup(self.tmp / 'E')

    def open(self, manifest=None):
        dlg = afu.show_after_format(self.root, manifest=manifest or self.manifest,
                                    base=self.base, checker=lambda m, c: FAKE_CHECK)
        until = time.monotonic() + 5
        while dlg.after_format_state['busy'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(dlg.after_format_state['busy'])
        return dlg

    def test_five_steps_with_buttons_and_drive_table(self):
        dlg = self.open()
        self.assertEqual(list(dlg.after_format_buttons), list(af.STEP_IDS))
        for step_id, own in dlg.after_format_buttons.items():
            self.assertEqual(set(own), {'Abrir', 'Feito', 'Pular'})
        tree = dlg.after_format_tree
        rows = tree.get_children('')
        self.assertEqual(len(rows), 2)
        self.assertEqual(tree.set(rows[0], 'note'), 'Disco do Windows')
        guide = dlg.after_format_guide.get('1.0', 'end')
        self.assertIn('Gerenciamento de Disco', guide)
        self.assertEqual(dlg.after_format_passwords.get(), 'Atenção: senhas.csv')
        dlg.destroy()

    def test_reopen_shows_progress(self):
        dlg = self.open()
        dlg.after_format_buttons['discos']['Feito'].invoke()
        dlg.after_format_buttons['launchers']['Pular'].invoke()
        saver = self.root.after_format_savers[dlg.after_format_state['key']]
        dlg.destroy()
        self.assertTrue(saver.join(5))  # fechar não cancelou a gravação
        dlg = self.open()
        self.assertEqual(dlg.after_format_status['discos'].get(), 'Feito')
        self.assertEqual(dlg.after_format_status['launchers'].get(), 'Pulado')
        self.assertEqual(dlg.after_format_status['restaurar'].get(), 'Pendente')
        dlg.after_format_buttons['discos']['Feito'].invoke()  # de novo: volta a pendente
        self.assertEqual(dlg.after_format_status['discos'].get(), 'Pendente')
        dlg.destroy()

    def test_each_open_calls_right_window(self):
        dlg = self.open()
        with mock.patch.object(afu, 'show_restore') as restore, \
                mock.patch.object(afu, 'show_programs') as programs, \
                mock.patch.object(afu, 'show_launchers') as launchers, \
                mock.patch.object(afu, 'show_recovery') as recovery:
            dlg.after_format_buttons['restaurar']['Abrir'].invoke()
            self.assertIn('etapa 1', dlg.after_format_notice.get())
            dlg.after_format_buttons['programas']['Abrir'].invoke()
            dlg.after_format_buttons['launchers']['Abrir'].invoke()
            dlg.after_format_buttons['navegador']['Abrir'].invoke()
        restore.assert_called_once_with(self.root, self.manifest)
        programs.assert_called_once_with(dlg, self.manifest.parent)
        launchers.assert_called_once_with(dlg)
        recovery.assert_called_once_with(dlg)
        self.assertEqual(dlg.after_format_notice.get(), 'Atenção: senhas.csv')
        dlg.destroy()

    def test_progress_warning_survives_open(self):
        # FIX-P2-11-01: o aviso do progresso tem linha própria que "Abrir" não apaga
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        path.write_text('{ estragado', encoding='utf-8')
        dlg = self.open()
        warning = dlg.after_format_progress_warning.get()
        self.assertIn('não pôde ser usado', warning)
        with mock.patch.object(afu, 'show_restore'), \
                mock.patch.object(afu, 'show_programs'):
            dlg.after_format_buttons['restaurar']['Abrir'].invoke()
            dlg.after_format_buttons['programas']['Abrir'].invoke()
        self.assertEqual(dlg.after_format_progress_warning.get(), warning)
        self.assertEqual(dlg.after_format_notice.get(), '')
        dlg.destroy()

    def test_save_failure_shown_without_full_path(self):
        dlg = self.open()
        error = PermissionError(13, 'negado', r'C:\Users\fulano\progresso.json.parcial')
        with mock.patch.object(af, 'save_progress', side_effect=error):
            dlg.after_format_buttons['discos']['Feito'].invoke()
            # FIX-P2-11-03: a gravação é em segundo plano; o aviso chega pelo timer
            until = time.monotonic() + 5
            while ('Não deu' not in dlg.after_format_progress_warning.get()
                   and time.monotonic() < until):
                self.root.update()
                time.sleep(0.02)
        with mock.patch.object(afu, 'show_programs'):
            dlg.after_format_buttons['programas']['Abrir'].invoke()
        warning = dlg.after_format_progress_warning.get()
        self.assertIn('Não deu para salvar o progresso', warning)
        self.assertNotIn('fulano', warning)
        dlg.destroy()

    def test_reopen_prefers_marks_not_yet_saved(self):
        # FIX-P2-11-03: reabrir enquanto a gravação ainda espera mostra a marcação nova
        import threading
        release = threading.Event()

        def slow_save(path, steps, backup=None):
            self.assertTrue(release.wait(5))
            return af.save_progress(path, steps, backup)
        dlg = self.open()
        saver = self.root.after_format_savers[dlg.after_format_state['key']]
        saver._save = slow_save
        dlg.after_format_buttons['discos']['Feito'].invoke()
        dlg.destroy()
        self.root.update()
        try:
            self.assertTrue(saver.closed)
            dlg = self.open()
            self.assertIs(dlg.after_format_state['saver'], saver)
            self.assertEqual(dlg.after_format_status['discos'].get(), 'Feito')
        finally:
            release.set()
            self.assertTrue(saver.join(5))
        dlg.destroy()
        again = af.load_progress(self.manifest, self.base)
        self.assertEqual(again['steps']['discos'], af.DONE)

    def test_skip_does_not_block(self):
        dlg = self.open()
        dlg.after_format_buttons['discos']['Pular'].invoke()
        with mock.patch.object(afu, 'show_restore') as restore:
            dlg.after_format_buttons['restaurar']['Abrir'].invoke()
        restore.assert_called_once()
        self.assertNotIn('etapa 1', dlg.after_format_notice.get())
        dlg.destroy()

    def test_closing_cancels_job(self):
        import threading
        started = threading.Event()
        seen = {}

        def checker(manifest, cancelled):
            seen['event'] = cancelled
            started.set()
            cancelled.wait(5)
            return FAKE_CHECK
        dlg = afu.show_after_format(self.root, manifest=self.manifest, base=self.base,
                                    checker=checker)
        self.assertTrue(started.wait(5))
        dlg.destroy()
        self.root.update()
        self.assertTrue(seen['event'].is_set())

    def test_same_backup_twice_one_window(self):
        dlg = self.open()
        moved = _backup(self.tmp / 'F')  # o mesmo backup visto por outra letra
        again = afu.show_after_format(self.root, manifest=moved, base=self.base,
                                      checker=lambda m, c: FAKE_CHECK)
        self.assertIs(again, dlg)
        dlg.iconify()
        self.root.update()
        self.assertIs(afu.show_after_format(self.root, manifest=moved, base=self.base,
                                            checker=lambda m, c: FAKE_CHECK), dlg)
        self.root.update()
        self.assertEqual(dlg.state(), 'normal')  # minimizada volta ao normal
        self.assertEqual(len(self.root.after_format_dialogs), 1)
        dlg.destroy()
        self.root.update()
        self.assertEqual(self.root.after_format_dialogs, {})
        dlg2 = self.open()
        self.assertIsNot(dlg2, dlg)
        dlg2.destroy()

    def test_different_backups_two_windows(self):
        one = self.open()
        two = self.open(_backup(self.tmp / 'E', name='backup-outro'))
        self.assertIsNot(one, two)
        self.assertEqual(len(self.root.after_format_dialogs), 2)
        one.destroy()
        two.destroy()

    def test_cancel_manifest_choice_opens_nothing(self):
        self.assertIsNone(afu.show_after_format(self.root, ask_manifest=lambda parent: None))


if __name__ == '__main__':
    unittest.main()
