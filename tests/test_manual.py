"""P4-01: confere o manual curto (docs/MANUAL.md).

Só lê arquivos do repositório: sem disco real, sem Tk e sem rodar o app.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / 'docs' / 'MANUAL.md'

REQUIRED_SECTIONS = (
    'O que o app faz',
    'Instalar e abrir',
    'Diagnóstico de discos',
    'Backup',
    'Testar e restaurar',
    'Reinstalação guiada',
    'Otimização',
    'Desfazer',
    'Check-up',
    'BIOS e drivers',
    'O que o app NUNCA faz',
)


def _norm(text):
    """Junta espaços seguidos num só (as abas usam dois espaços: "8  Ajustes seguros")."""
    return re.sub(r'\s+', ' ', text).strip()


def _manual_text():
    return MANUAL.read_text(encoding='utf-8')


def _sections(text):
    """Devolve {título: corpo} das seções de nível ##."""
    found = {}
    current = None
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return {title: '\n'.join(body) for title, body in found.items()}


def _section(text, start):
    for title, body in _sections(text).items():
        if title.startswith(start):
            return body
    raise AssertionError(f'seção "{start}" não encontrada')


def _code_text():
    parts = []
    for path in sorted(ROOT.glob('*.py')):
        parts.append(path.read_text(encoding='utf-8', errors='replace'))
    return _norm('\n'.join(parts))


class ManualTests(unittest.TestCase):
    def test_manual_exists_and_is_short(self):
        self.assertTrue(MANUAL.is_file())
        self.assertLessEqual(len(_manual_text().splitlines()), 260)

    def test_every_quoted_ui_name_exists_in_code(self):
        text = _manual_text()
        quoted = re.findall(r'"([^"\n]+)"', text)
        self.assertGreater(len(quoted), 20)
        code = _code_text()
        missing = sorted({q for q in quoted if _norm(q) not in code})
        self.assertEqual(missing, [], 'nomes citados no manual que não existem no código')

    def test_has_required_sections(self):
        titles = list(_sections(_manual_text()))
        for wanted in REQUIRED_SECTIONS:
            with self.subTest(section=wanted):
                self.assertTrue(any(t.startswith(wanted) for t in titles),
                                f'falta a seção "## {wanted}"')
        self.assertEqual(len(titles), len(REQUIRED_SECTIONS))

    def test_no_user_paths_or_personal_data(self):
        text = _manual_text()
        lowered = text.lower()
        self.assertIsNone(re.search(r'[a-z]:\\users\\', lowered))
        self.assertIsNone(re.search(r'[a-z]:/users/', lowered))
        self.assertNotIn('/home/', lowered)
        self.assertNotIn('preferencias-v05.json', lowered)
        self.assertNotIn('raphael', lowered)
        self.assertIsNone(re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text))
        for word in ('token', 'senha:', 'password', 'ghp_', 'sk-'):
            self.assertNotIn(word, lowered)

    def test_never_section_lists_forbidden_actions(self):
        body = _section(_manual_text(), 'O que o app NUNCA faz').lower()
        for word in ('formata', 'particiona', 'apaga', 'efi', 'bcd', 'instala o windows',
                     'defender', 'windows update', 'debloat', 'bios'):
            with self.subTest(word=word):
                self.assertIn(word, body)

    def test_reinstall_is_guided(self):
        body = _section(_manual_text(), 'Reinstalação guiada')
        self.assertIn('instalador oficial', body)
        self.assertIn('Microsoft', body)

    def test_protected_copy_not_presented_as_ready(self):
        text = _manual_text()
        self.assertIn('Cópia protegida para outro disco', text)
        self.assertIn('ainda em teste', text)

    def test_readme_links_manual(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('docs/MANUAL.md', readme)


if __name__ == '__main__':
    unittest.main()
