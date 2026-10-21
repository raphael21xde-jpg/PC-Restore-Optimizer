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


def _write_manifest(folder, sources):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for index, (source, relative) in enumerate(sources):
        files.append({'source': source, 'relative': relative, 'verified': True,
                      'sha256': hashlib.sha256(str(index).encode()).hexdigest(), 'size': 1})
    path = folder / 'manifest.json'
    path.write_text(json.dumps({'schema': 'pc-restore-backup-v0.5', 'files': files}),
                    encoding='utf-8')
    return path


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
        self.base = Path(tmp.name) / 'progresso'
        self.manifest = Path(tmp.name) / 'backup' / 'b1' / 'manifest.json'

    def test_path_uses_manifest_hash(self):
        path = af.progress_path(self.manifest, self.base)
        key = hashlib.sha256(os.path.normcase(os.path.abspath(str(self.manifest)))
                             .encode('utf-8')).hexdigest()[:12]
        self.assertEqual(path, self.base / f'progresso-{key}.json')

    def test_default_base_uses_localappdata(self):
        base = af.default_base({'LOCALAPPDATA': str(self.base)})
        self.assertEqual(base, self.base / 'PC-Restore-Optimizer' / 'depois-de-formatar')

    def test_round_trip(self):
        first = af.load_progress(self.manifest, self.base)
        self.assertEqual(set(first['steps'].values()), {af.PENDING})
        self.assertEqual(first['warnings'], [])
        steps = dict(first['steps'], discos=af.DONE, launchers=af.SKIPPED)
        af.save_progress(first['path'], steps)
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
        af.save_progress(loaded['path'], dict(loaded['steps'], discos=af.DONE))
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
        other = self.manifest.parent.parent / 'b2' / 'manifest.json'
        a = af.load_progress(self.manifest, self.base)
        af.save_progress(a['path'], dict(a['steps'], discos=af.DONE))
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
        path = af.progress_path(self.manifest, self.base)
        path.parent.mkdir(parents=True)
        partial = path.with_name(path.name + af.PARTIAL_SUFFIX)
        partial.write_text('{ meio gravado', encoding='utf-8')
        loaded = af.load_progress(self.manifest, self.base)
        self.assertEqual(loaded['path'], path)
        self.assertEqual(loaded['warnings'], [])
        af.save_progress(path, dict(loaded['steps'], restaurar=af.DONE))
        self.assertEqual(af.load_progress(self.manifest, self.base)['steps']['restaurar'],
                         af.DONE)
        self.assertFalse(partial.exists())

    def test_never_deletes(self):
        src = (ROOT / 'after_format.py').read_text(encoding='utf-8')
        for word in ('unlink', 'os.remove', 'rmtree', 'rmdir', 'subprocess', 'os.system'):
            self.assertNotIn(word, src)


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
        self.base = Path(tmp.name) / 'progresso'
        self.manifest = Path(tmp.name) / 'backup' / 'b1' / 'manifest.json'

    def open(self):
        dlg = afu.show_after_format(self.root, manifest=self.manifest, base=self.base,
                                    checker=lambda m, c: FAKE_CHECK)
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
        dlg.destroy()
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

    def test_cancel_manifest_choice_opens_nothing(self):
        self.assertIsNone(afu.show_after_format(self.root, ask_manifest=lambda parent: None))


if __name__ == '__main__':
    unittest.main()
