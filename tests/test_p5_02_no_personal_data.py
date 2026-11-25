"""P5-02 fatia 2: nenhum arquivo rastreado pelo git tem dado pessoal.

O teste do repositório só lê `git ls-files` (texto do próprio projeto). Os
testes negativos usam só arquivos sintéticos em TemporaryDirectory, com um
repositório git de mentira criado ali dentro.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import personal_data_scan as scan

ROOT = Path(__file__).resolve().parents[1]
# Os exemplos negativos são montados por partes, para este arquivo não ser
# apontado pelo próprio teste do repositório.
FAKE = 'Mariana'
WIN = 'C:\\Users\\'


def _load_build_exe():
    spec = importlib.util.spec_from_file_location('build_exe_p5_02', ROOT / 'scripts' / 'build_exe.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracked_findings(repo: Path) -> list[str]:
    """Aplica a busca a cada arquivo de `git ls-files` do repositório dado."""
    listed = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=repo, check=True, capture_output=True,
    ).stdout.decode('utf-8').split('\0')
    findings = []
    for name in filter(None, listed):
        path = repo / name
        try:
            data = path.read_bytes()
        except OSError:
            data = b''
        if b'\0' in data[:8192]:
            text = ''  # binário: só o nome é conferido
        else:
            text = data.decode('utf-8', errors='replace')
        findings.extend(scan.personal_data_findings(name, text))
    return findings


def _git_available() -> bool:
    return shutil.which('git') is not None


class FindingsTests(unittest.TestCase):
    def test_real_looking_windows_user_path_is_found(self):
        self.assertEqual(
            scan.personal_data_findings('notas.md', f'ok\nveja {WIN}{FAKE}\\Documents\n'),
            ['notas.md:2: caminho com nome de usuário'],
        )

    def test_escaped_and_forward_slash_and_unix_paths_are_found(self):
        for prefix in ('C:\\\\Users\\\\', 'C:/Users/', '/home/', '/Users/', 'D:\\Usuarios\\',
                       'C:\\Documents and Settings\\'):
            text = prefix + FAKE + '/x'
            with self.subTest(prefix=prefix):
                self.assertEqual(len(scan.personal_data_findings('a.py', text)), 1)

    def test_finding_never_repeats_the_name_or_secret(self):
        token = 'ghp_' + 'Q' * 36
        findings = scan.personal_data_findings('a.py', f'{WIN}{FAKE}\\x {token}')
        self.assertEqual(len(findings), 2)
        self.assertNotIn(FAKE, ' '.join(findings))
        self.assertNotIn(token, ' '.join(findings))

    def test_placeholders_and_generic_names_are_allowed(self):
        text = '\n'.join([
            'C:\\Users\\<nome>\\Documents', 'C:\\Users\\{usuario}', 'C:\\Users\\%USERNAME%',
            'C:\\Users\\*\\AppData', 'C:\\Users\\Public', 'C:\\Users\\Default',
            'C:\\Users\\Fulano\\x', 'C:\\Users\\FULANO-SECRETO', 'C:\\Users\\usuario_secreto',
            '/home/fulano', 'C:\\Users\\x\\y', '$env:USERPROFILE',
        ])
        self.assertEqual(scan.personal_data_findings('a.md', text), [])

    def test_allow_list_is_small_and_explicit(self):
        self.assertLessEqual(len(scan.ALLOWED_USER_NAMES), 30)
        self.assertFalse(scan.is_allowed_user_name(FAKE))
        self.assertTrue(scan.is_allowed_user_name('Fulano'))

    def test_personal_file_names_are_found(self):
        for name in ('preferencias-v05.json', 'sub/deteccao-detalhada-v065.json',
                     'deteccao-detalhada-v099.json', '.env', 'cert.pfx', 'id_rsa'):
            with self.subTest(name=name):
                self.assertTrue(scan.personal_data_findings(name, ''))

    def test_same_personal_names_as_the_exe_build(self):
        build_exe = _load_build_exe()
        for name in sorted(build_exe.FORBIDDEN_NAMES) + ['deteccao-detalhada-v070.json', 'preferencias-v06.json']:
            with self.subTest(name=name):
                self.assertTrue(build_exe.is_personal_data_file(name))
                self.assertIsNotNone(scan.personal_file_name_reason(name))

    def test_obvious_credentials_are_found(self):
        for text in ('-----BEGIN RSA ' + 'PRIVATE KEY-----', 'ghp_' + 'Z9' * 18, 'github_pat_' + 'A1' * 15,
                     'AKIA' + 'ABCDEFGHIJKLMNOP', 'sk-ant-' + 'x' * 30, 'xoxb-' + '1234567890-abc'):
            with self.subTest(kind=text[:6]):
                self.assertTrue(scan.personal_data_findings('a.txt', text))

    def test_detector_source_text_and_known_fake_token_are_allowed(self):
        text = (r'(?i)\b(?:github_pat_[a-z0-9_]{12,}|gh[pousr]_[a-z0-9_]{12,}|sk-[a-z0-9_-]{10,})\b'
                '\nghp_abcdefghijklmnopqrstuvwxyz123456')
        self.assertEqual(scan.personal_data_findings('a.py', text), [])


@unittest.skipUnless(_git_available(), 'git não está instalado neste PC')
class TrackedFilesTests(unittest.TestCase):
    def _repo(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
        for name, content in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add', '--', *files], cwd=repo, check=True)
        return repo

    def test_synthetic_repo_with_user_path_fails(self):
        repo = self._repo({'ok.md': 'C:\\Users\\<nome>', 'docs/ruim.md': f'linha\n{WIN}{FAKE}\\Desktop\n'})
        self.assertEqual(tracked_findings(repo), ['docs/ruim.md:2: caminho com nome de usuário'])

    def test_synthetic_repo_with_personal_file_fails(self):
        repo = self._repo({'preferencias-v05.json': '{}', 'deteccao-detalhada-v065.json': '{}'})
        self.assertEqual(len(tracked_findings(repo)), 2)

    def test_untracked_file_is_not_checked(self):
        repo = self._repo({'ok.md': 'nada pessoal'})
        (repo / 'solto.md').write_text(WIN + FAKE, encoding='utf-8')
        self.assertEqual(tracked_findings(repo), [])

    def test_project_tracked_files_have_no_personal_data(self):
        if not (ROOT / '.git').exists():
            self.skipTest('pasta do projeto sem .git (cópia sem histórico)')
        findings = tracked_findings(ROOT)
        self.assertEqual(findings, [], 'Dados pessoais em arquivos do git:\n' + '\n'.join(findings))


if __name__ == '__main__':
    unittest.main()
