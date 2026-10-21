"""P2-06: senhas de navegador exportadas em texto puro (.csv).

Tudo com arquivos sintéticos em TemporaryDirectory e pastas/env injetados.
Nunca usa o USERPROFILE real nem pastas reais.
"""
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import plaintext_passwords as pp

ROOT = Path(__file__).resolve().parents[1]
FAKE_SECRET = 'SenhaFalsa-123-nao-real'
HAS_TK = importlib.util.find_spec('tkinter') is not None


def _snapshot(root):
    """Lista, tamanho e mtime de tudo sob root (sem seguir links)."""
    state = {}
    for current, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(current) / name
            info = path.lstat()
            state[str(path.relative_to(root))] = (info.st_size, info.st_mtime_ns)
    return state


class NameDetectionTests(unittest.TestCase):
    def test_detects_common_export_names(self):
        for name in ('Chrome Passwords.csv', 'senhas.CSV', 'Firefox logins.csv',
                     'Microsoft Edge Passwords.csv', 'minhas-credenciais.csv',
                     'credentials.csv', 'Opera Passwords.csv', 'SENHA_banco.Csv'):
            with self.subTest(name=name):
                self.assertTrue(pp.is_password_export(name))

    def test_ignores_other_names_and_extensions(self):
        for name in ('passwords.txt', 'relatorio.csv', 'senhas.xlsx', 'logins',
                     'password.csv.bak', 'fotos.csv', ''):
            with self.subTest(name=name):
                self.assertFalse(pp.is_password_export(name))


class FindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _file(self, relative, content=b'url,username,password\n'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_finds_by_name_in_given_folders(self):
        hit1 = self._file('Downloads/Chrome Passwords.csv')
        hit2 = self._file('Documents/senhas.CSV')
        self._file('Documents/relatorio.csv')
        self._file('Desktop/passwords.txt')
        result = pp.find_password_exports([self.root / 'Downloads', self.root / 'Documents',
                                           self.root / 'Desktop', self.root / 'naoexiste'])
        self.assertEqual(sorted(result.findings), sorted([hit1, hit2]))
        self.assertFalse(result.incomplete)

    def test_depth_limit(self):
        shallow = self._file('Docs/a/b/logins.csv')        # profundidade 2
        self._file('Docs/a/b/c/passwords.csv')             # profundidade 3: fora
        result = pp.find_password_exports([self.root / 'Docs'], max_depth=2)
        self.assertEqual(result.findings, [shallow])
        zero = pp.find_password_exports([self.root / 'Docs'], max_depth=0)
        self.assertEqual(zero.findings, [])

    def test_entry_limit_marks_incomplete(self):
        for number in range(30):
            self._file(f'Muitos/arquivo{number:02}.txt', b'x')
        result = pp.find_password_exports([self.root / 'Muitos'], max_entries=10)
        self.assertTrue(result.incomplete)
        lines = pp.alert_lines(result.findings, result.incomplete)
        self.assertTrue(any('parou antes do fim' in line for line in lines))

    @unittest.skipUnless(hasattr(os, 'symlink'), 'sem links simbólicos')
    def test_does_not_follow_links(self):
        outside = self.root / 'fora'
        self._file('fora/passwords.csv')
        self._file('fora/sub/senhas.csv')
        base = self.root / 'Downloads'
        base.mkdir()
        try:
            os.symlink(outside, base / 'link-pasta', target_is_directory=True)
            os.symlink(outside / 'passwords.csv', base / 'link-passwords.csv')
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'não deu para criar link: {exc}')
        result = pp.find_password_exports([base])
        self.assertEqual(result.findings, [])

    def test_never_reads_content_and_secret_not_in_alert(self):
        self._file('Downloads/Chrome Passwords.csv',
                   f'url,user,password\nhttps://x,ana,{FAKE_SECRET}\n'.encode())
        with mock.patch('builtins.open', side_effect=AssertionError('abriu arquivo')), \
                mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('leu')), \
                mock.patch.object(Path, 'read_text', side_effect=AssertionError('leu')), \
                mock.patch.object(Path, 'open', side_effect=AssertionError('abriu')):
            result = pp.find_password_exports([self.root / 'Downloads'])
            lines = pp.alert_lines(result.findings)
        self.assertEqual(len(result.findings), 1)
        text = '\n'.join(lines)
        self.assertNotIn(FAKE_SECRET, text)
        self.assertIn('Chrome Passwords.csv', text)

    def test_nothing_changes_before_and_after(self):
        self._file('Downloads/Chrome Passwords.csv')
        self._file('Documents/sub/senhas.csv')
        self._file('Documents/outro.txt')
        before = _snapshot(self.root)
        result = pp.find_password_exports([self.root / 'Downloads', self.root / 'Documents'])
        pp.alert_lines(result.findings)
        pp.scan_paths(result.findings)
        self.assertEqual(len(result.findings), 2)
        self.assertEqual(_snapshot(self.root), before)

    def test_scandir_is_injectable(self):
        calls = []

        def fake_scandir(folder):
            calls.append(folder)
            raise PermissionError('sem acesso')
        result = pp.find_password_exports([self.root / 'X'], scandir=fake_scandir)
        self.assertEqual(calls, [self.root / 'X'])
        self.assertEqual(result.findings, [])


class ScanPathsTests(unittest.TestCase):
    def test_accepts_strings_paths_and_tasks(self):
        from backup_core import FileTask
        task = FileTask(source=r'C:\Users\Exemplo\Downloads\Chrome Passwords.csv', size=1,
                        mtime_ns=0, destination='')
        found = pp.scan_paths(['pasta/logins.csv', Path('pasta/relatorio.csv'), task,
                               'outra/senhas.txt'])
        names = [p.name for p in found]
        self.assertIn('logins.csv', names)
        self.assertEqual(len(found), 2)
        self.assertNotIn('relatorio.csv', names)

    def test_does_not_touch_disk(self):
        with mock.patch('os.scandir', side_effect=AssertionError('olhou o disco')), \
                mock.patch('os.stat', side_effect=AssertionError('olhou o disco')):
            self.assertEqual(len(pp.scan_paths(['nao/existe/passwords.csv'])), 1)


class AlertTests(unittest.TestCase):
    def test_empty_means_no_alert(self):
        self.assertEqual(pp.alert_lines([]), [])

    def test_cut_at_twenty_with_more(self):
        findings = [Path(f'pasta/passwords{n}.csv') for n in range(25)]
        lines = pp.alert_lines(findings)
        shown = [line for line in lines if line.strip().startswith('!')]
        self.assertEqual(len(shown), 20)
        self.assertTrue(any('e mais 5' in line for line in lines))
        text = '\n'.join(lines)
        self.assertIn('25 arquivo(s)', text)
        self.assertIn('importe', text)
        self.assertIn('Lixeira', text)
        self.assertIn('nunca apaga', text)

    def test_shows_name_and_folder(self):
        lines = pp.alert_lines([Path('A') / 'B' / 'senhas.csv'])
        self.assertTrue(any('senhas.csv' in l and str(Path('A') / 'B') in l for l in lines))


class UserFoldersTests(unittest.TestCase):
    def test_synthetic_env(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'USERPROFILE': temp}
            folders = pp.user_folders(env)
            for name in ('Documents', 'Downloads', 'Desktop'):
                self.assertIn(Path(temp) / name, folders)
            self.assertIn(Path(temp) / 'OneDrive' / 'Documentos', folders)
            self.assertIn(Path(temp) / 'OneDrive' / 'Área de Trabalho', folders)
            self.assertEqual(len(folders), len(set(map(str, folders))))

    def test_custom_onedrive_and_missing_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            other = Path(temp) / 'OneDrive - Empresa'
            folders = pp.user_folders({'USERPROFILE': temp, 'OneDrive': str(other)})
            self.assertIn(other / 'Desktop', folders)
        self.assertEqual(pp.user_folders({}), [])

    def test_end_to_end_with_synthetic_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            hit = Path(temp) / 'Downloads' / 'Firefox logins.csv'
            hit.parent.mkdir()
            hit.write_bytes(b'x')
            result = pp.find_password_exports(pp.user_folders({'USERPROFILE': temp}))
            self.assertEqual(result.findings, [hit])


class SourceSafetyTests(unittest.TestCase):
    def test_module_never_deletes_or_opens(self):
        source = (ROOT / 'plaintext_passwords.py').read_text(encoding='utf-8')
        for forbidden in ('unlink', 'remove(', 'rmtree', 'send2trash', 'rmdir',
                          'open(', 'read_bytes', 'read_text', 'startfile'):
            self.assertNotIn(forbidden, source)
        self.assertIsNone(re.search(r'^\s*(from|import)\s+(app|backup_|restore_)', source, re.M))

    def test_app_and_restore_screen_use_alerts(self):
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        worker = app.split('def generate_preview', 1)[1].split('def _preview_ready', 1)[0]
        self.assertIn('find_password_exports(user_folders())', worker)
        ready = app.split('def _preview_ready', 1)[1].split('def _preflight', 1)[0]
        self.assertIn('_password_section', ready)
        section = app.split('def _password_section', 1)[1].split('def _preview_ready', 1)[0]
        self.assertIn('password_alert_lines', section)
        self.assertIn('não é criptografado', section)
        ui = (ROOT / 'restore_ui.py').read_text(encoding='utf-8')
        done = ui.split('def done(result)', 1)[1].split('poll(done)', 1)[0]
        self.assertIn('scan_paths', done)
        self.assertIn('alert_lines', done)
        placed = ui.split('def placed(result)', 1)[1].split('poll(placed)', 1)[0]
        self.assertIn('scan_paths', placed)
        self.assertIn('alert_lines', placed)
        self.assertIn('show_report(report)', placed)

    @unittest.skipUnless(HAS_TK, 'tkinter indisponível')
    def test_preview_section_flags_files_in_copy(self):
        from app import App
        from backup_core import FileTask, Plan
        with tempfile.TemporaryDirectory() as temp:
            inside = Path(temp) / 'Downloads' / 'Chrome Passwords.csv'
            outside = Path(temp) / 'Documents' / 'senhas.csv'
            plan = Plan(files=[FileTask(str(inside), 1, 0, 'x')])
            scan = pp.ScanResult(findings=[outside])
            lines = App._password_section(None, plan, scan)
        text = '\n'.join(lines)
        self.assertIn(pp.TITLE, text)
        self.assertIn('2 arquivo(s)', text)
        self.assertIn('1 desses arquivos entram nesta cópia', text)
        self.assertEqual(App._password_section(None, Plan(), pp.ScanResult()), [])


if __name__ == '__main__':
    unittest.main()
