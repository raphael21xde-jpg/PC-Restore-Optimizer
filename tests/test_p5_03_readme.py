"""P5-03 fatia 3: o README explica como baixar, instalar e conferir o .zip.

Só lê o `README.md` do projeto (texto). Os testes negativos usam apenas
textos sintéticos gravados em TemporaryDirectory.
"""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

import personal_data_scan as scan

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / 'README.md'

# Cada trecho obrigatório: título da seção e o que precisa aparecer nela.
REQUIRED_SECTIONS = {
    '## Como baixar e instalar': ('.zip', 'Releases', 'PCRestoreOptimizer.exe', 'extra'),
    '## Como conferir o SHA-256 do .zip': ('Get-FileHash', 'certutil', 'SHA256', 'Release'),
    '## Aviso: o programa não tem assinatura digital': (
        'SmartScreen', 'Controle Inteligente de Aplicativos', 'não é assinado',
    ),
}
REQUIRED_PHRASES = (
    'funciona em qualquer PC com Windows',
    'só escreve onde você escolher',
    'nunca formata',
    'nunca apaga',
    'a confirmar na validação',
)
# Letra de unidade sozinha (`C:`, `D:\`...): o README não pode exigir nenhuma.
_DRIVE_LETTER = re.compile(r'(?<!\w)[A-Za-z]:(?=[\\/\s.,;)]|$)', re.MULTILINE)
# Ainda não há Release publicada: nenhum link de download inventado.
_RELEASE_LINK = re.compile(r'releases/(?:download|tag|latest)', re.IGNORECASE)


def _section(text: str, heading: str) -> str:
    start = text.find(heading + '\n')
    if start < 0:
        return ''
    rest = text[start + len(heading):]
    end = rest.find('\n## ')
    return rest if end < 0 else rest[:end]


def readme_problems(text: str) -> list[str]:
    """Lista o que falta ou sobra no README (vazia quando está tudo certo)."""
    problems = []
    for heading, needed in REQUIRED_SECTIONS.items():
        body = _section(text, heading)
        if not body:
            problems.append(f'falta a seção {heading!r}')
            continue
        for item in needed:
            if item not in body:
                problems.append(f'a seção {heading!r} não cita {item!r}')
    for phrase in REQUIRED_PHRASES:
        if phrase not in text:
            problems.append(f'falta a frase {phrase!r}')
    if _DRIVE_LETTER.search(text):
        problems.append('cita uma letra de unidade (como C:)')
    if _RELEASE_LINK.search(text):
        problems.append('tem link de Release que ainda não existe')
    problems.extend(scan.personal_data_findings('README.md', text))
    return problems


GOOD = (
    '# App\n\nO app funciona em qualquer PC com Windows. Ele só escreve onde você escolher,'
    ' nunca formata e nunca apaga. Espaço: a confirmar na validação.\n\n'
    '## Como baixar e instalar\nBaixe o .zip em Releases, extraia e abra PCRestoreOptimizer.exe.\n\n'
    '## Como conferir o SHA-256 do .zip\nGet-FileHash -Algorithm SHA256; certutil; compare com a Release.\n\n'
    '## Aviso: o programa não tem assinatura digital\nO .exe não é assinado: SmartScreen e'
    ' Controle Inteligente de Aplicativos podem avisar.\n'
)


class SyntheticReadmeTests(unittest.TestCase):
    """O próprio conferidor acha os problemas (textos inventados, em pasta temporária)."""

    def _problems_of(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'README.md'
            path.write_text(text, encoding='utf-8')
            return readme_problems(path.read_text(encoding='utf-8'))

    def test_good_synthetic_readme_has_no_problem(self):
        self.assertEqual(self._problems_of(GOOD), [])

    def test_missing_section_is_found(self):
        text = GOOD.replace('## Como conferir o SHA-256 do .zip', '## Outra coisa')
        self.assertIn("falta a seção '## Como conferir o SHA-256 do .zip'", self._problems_of(text))

    def test_missing_phrase_is_found(self):
        text = GOOD.replace('funciona em qualquer PC com Windows', 'funciona')
        self.assertIn("falta a frase 'funciona em qualquer PC com Windows'", self._problems_of(text))

    def test_required_drive_letter_is_found(self):
        for drive in ('C:', 'D:\\', 'F:/', 'G: '):
            with self.subTest(drive=drive):
                text = GOOD + f'\nÉ obrigatório ter o disco {drive} livre.\n'
                self.assertIn('cita uma letra de unidade (como C:)', self._problems_of(text))

    def test_words_ending_in_colon_are_not_drive_letters(self):
        text = GOOD + '\nNota: veja https://example.invalid e Windows: 10.\n'
        self.assertEqual(self._problems_of(text), [])

    def test_invented_release_link_is_found(self):
        text = GOOD + '\nhttps://github.com/exemplo/app/releases/download/v1/app.zip\n'
        self.assertIn('tem link de Release que ainda não existe', self._problems_of(text))

    def test_personal_path_is_found(self):
        fake = 'Zorv' + 'anqueta'  # nome inventado, montado por partes
        text = GOOD + '\nveja /home/' + fake + '/Downloads\n'
        problems = self._problems_of(text)
        self.assertTrue(any(p.endswith('caminho com nome de usuário') for p in problems), problems)
        self.assertFalse(any(fake in p for p in problems))  # o aviso não repete o nome


class ProjectReadmeTests(unittest.TestCase):
    def test_project_readme_has_every_required_part(self):
        text = README.read_text(encoding='utf-8')
        self.assertEqual(readme_problems(text), [])

    def test_project_readme_keeps_the_developer_notes(self):
        text = README.read_text(encoding='utf-8')
        self.assertIn('docs/MANUAL.md', text)
        self.assertIn('docs/ESTADO-DO-PROJETO-E-PROXIMOS-MARCOS.md', text)
        self.assertIn('## Princípios inegociáveis', text)


if __name__ == '__main__':
    unittest.main()
