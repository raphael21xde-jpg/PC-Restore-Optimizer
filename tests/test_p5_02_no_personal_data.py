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
# Nome claramente inventado, que não começa por nenhum nome da lista de permitidos.
FAKE = 'Zorvald'
WIN = 'C:\\Users\\'
UNC = '\\\\PC\\c$\\Users\\'
SKIP_NO_GIT = 'IGNORADO: git não encontrado; a busca de dados pessoais no repositório NÃO rodou'
SKIP_NO_DOT_GIT = ('IGNORADO: sem pasta .git; a busca de dados pessoais no repositório NÃO rodou '
                   '(cópia do projeto sem histórico)')


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
        text = scan.decode_tracked_text(data)  # binário: só o nome é conferido
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
            'C:\\Users\\Fulano\\x', 'C:\\Users\\FULANO', '/home/fulano', 'C:\\Users\\x\\y',
            '$env:USERPROFILE', '/root/x', 'C:\\Users\\Beltrano\\Desktop',
        ])
        self.assertEqual(scan.personal_data_findings('a.md', text), [])

    def test_generic_name_with_suffix_is_found(self):
        # Antes eram aceitos de propósito (só a primeira parte era comparada).
        for name in ('FULANO-SECRETO', 'usuario_secreto', 'Fulano.Silva', 'Public2', 'Beltrano2'):
            with self.subTest(name=name):
                self.assertFalse(scan.is_allowed_user_name(name))
                self.assertEqual(
                    scan.personal_data_findings('a.md', WIN + name + '\\x'),
                    ['a.md:1: caminho com nome de usuário'],
                )

    def test_exact_generic_names_and_placeholders_are_not_found(self):
        for name in ('Fulano', 'Public', 'Default', 'ADMINISTRADOR', 'x'):
            with self.subTest(name=name):
                self.assertTrue(scan.is_allowed_user_name(name))
        text = f'{WIN}Fulano\n{WIN}Public\\x\n{WIN}<nome>\n{WIN}%USERNAME%\\AppData\n'
        self.assertEqual(scan.personal_data_findings('a.md', text), [])

    def test_removed_odd_words_are_no_longer_allowed(self):
        for name in ('segredo', 'abc', 'file', 'other'):
            with self.subTest(name=name):
                self.assertNotIn(name, scan.ALLOWED_USER_NAMES)
                self.assertFalse(scan.is_allowed_user_name(name))

    def test_network_share_user_path_is_found(self):
        for text in (UNC + FAKE + '\\Documents', UNC.replace('\\', '\\\\') + FAKE,
                     '//PC/c$/Users/' + FAKE, '\\\\servidor.local\\D$\\Usuarios\\' + FAKE):
            with self.subTest(text=text[:12]):
                self.assertEqual(scan.personal_data_findings('a.md', text),
                                 ['a.md:1: caminho com nome de usuário'])
        self.assertEqual(scan.personal_data_findings('a.md', UNC + 'Fulano\\x'), [])

    def test_root_home_is_not_treated_as_a_person(self):
        # Limite documentado: /root/ é a conta do administrador no Linux, não nome de pessoa.
        self.assertEqual(scan.personal_data_findings('a.sh', 'cd /root/x\nls /root/' + FAKE), [])

    def test_new_forms_never_repeat_the_name(self):
        name = 'Fulano.' + FAKE
        findings = (scan.personal_data_findings('a.md', WIN + name)
                    + scan.personal_data_findings('b.md', UNC + FAKE)
                    + scan.personal_data_findings('c.md', scan.decode_tracked_text((WIN + FAKE).encode('utf-16'))))
        self.assertEqual(len(findings), 3)
        self.assertNotIn(FAKE, ' '.join(findings))

    def test_decode_reads_utf16_before_the_binary_rule(self):
        text = 'linha\n' + WIN + FAKE + '\\Desktop\n'
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be'):
            with self.subTest(encoding=encoding):
                self.assertEqual(scan.decode_tracked_text(text.encode(encoding)), text)
        self.assertEqual(scan.decode_tracked_text(text.encode('utf-8')), text)
        self.assertEqual(scan.decode_tracked_text(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01'), '')

    def test_skip_reasons_say_the_scan_did_not_run(self):
        for reason in (SKIP_NO_GIT, SKIP_NO_DOT_GIT):
            with self.subTest(reason=reason[:20]):
                self.assertTrue(reason.startswith('IGNORADO:'))
                self.assertIn('NÃO rodou', reason)

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


@unittest.skipUnless(_git_available(), SKIP_NO_GIT)
class TrackedFilesTests(unittest.TestCase):
    def _repo(self, files: dict[str, str | bytes]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
        for name, content in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add', '--', *files], cwd=repo, check=True)
        return repo

    def test_synthetic_repo_with_user_path_fails(self):
        repo = self._repo({'ok.md': 'C:\\Users\\<nome>', 'docs/ruim.md': f'linha\n{WIN}{FAKE}\\Desktop\n'})
        self.assertEqual(tracked_findings(repo), ['docs/ruim.md:2: caminho com nome de usuário'])

    def test_synthetic_repo_with_personal_file_fails(self):
        repo = self._repo({'preferencias-v05.json': '{}', 'deteccao-detalhada-v065.json': '{}'})
        self.assertEqual(len(tracked_findings(repo)), 2)

    def test_synthetic_repo_with_utf16_user_path_fails(self):
        repo = self._repo({
            'ok.txt': 'nada pessoal',
            'notas-le.txt': ('linha\r\n' + WIN + FAKE + '\\Desktop\r\n').encode('utf-16-le'),
            'notas-bom.txt': (WIN + FAKE).encode('utf-16'),
        })
        self.assertEqual(sorted(tracked_findings(repo)), [
            'notas-bom.txt:1: caminho com nome de usuário',
            'notas-le.txt:2: caminho com nome de usuário',
        ])

    def test_synthetic_repo_binary_file_only_has_its_name_checked(self):
        repo = self._repo({'img.png': b'\x89PNG\x00\x00' + (WIN + FAKE).encode('ascii')})
        self.assertEqual(tracked_findings(repo), [])

    def test_untracked_file_is_not_checked(self):
        repo = self._repo({'ok.md': 'nada pessoal'})
        (repo / 'solto.md').write_text(WIN + FAKE, encoding='utf-8')
        self.assertEqual(tracked_findings(repo), [])

    def test_project_tracked_files_have_no_personal_data(self):
        if not (ROOT / '.git').exists():
            self.skipTest(SKIP_NO_DOT_GIT)
        findings = tracked_findings(ROOT)
        self.assertEqual(findings, [], 'Dados pessoais em arquivos do git:\n' + '\n'.join(findings))


if __name__ == '__main__':
    unittest.main()
