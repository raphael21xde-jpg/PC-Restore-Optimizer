"""FIX-P3-06-05: citação de regra juntada só na forma "antiga R-<nº>" nos .py.

Lê as regras juntadas em docs/REGRAS.md ("Juntada à **R-x**") e procura citações
delas em todos os .py versionados. O padrão é montado em código, a partir do
número lido, para este arquivo não acusar a si mesmo.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_MERGED_ROW = re.compile(r'^\|\s*R-(\d+)\s*\|\s*Juntada à \*\*R-\d+\*\*', re.MULTILINE)
_PREFIX = 'antiga '


def merged_rules(text):
    """Números das regras que foram juntadas a outra (ex.: ['22', '34'])."""
    return _MERGED_ROW.findall(text)


def loose_citations(source, numbers):
    """[(número, posição)] de cada citação que não vem logo depois de "antiga "."""
    found = []
    for number in numbers:
        pattern = re.compile('R-' + re.escape(number) + r'(?!\d)')
        for match in pattern.finditer(source):
            if not source[:match.start()].endswith(_PREFIX):
                found.append((number, match.start()))
    return found


def _versioned_py_files():
    output = subprocess.run(['git', 'ls-files', '*.py'], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout
    return [ROOT / line for line in output.splitlines() if line.strip()]


class RuleCitationsTest(unittest.TestCase):
    def test_reads_merged_rules(self):
        text = (ROOT / 'docs' / 'REGRAS.md').read_text(encoding='utf-8')
        numbers = merged_rules(text)
        self.assertIn('34', numbers)
        self.assertNotIn('32', numbers)

    def test_no_loose_citation_of_merged_rule_in_py_files(self):
        numbers = merged_rules((ROOT / 'docs' / 'REGRAS.md').read_text(encoding='utf-8'))
        try:
            files = _versioned_py_files()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('git não disponível para listar os arquivos versionados')
        self.assertTrue(files)
        problems = []
        for path in files:
            if not path.is_file():
                continue
            source = path.read_text(encoding='utf-8', errors='replace')
            for number, pos in loose_citations(source, numbers):
                line = source.count('\n', 0, pos) + 1
                problems.append(f'{path.relative_to(ROOT)}:{line} cita R-{number}')
        self.assertEqual(problems, [], 'use "antiga R-<nº>" ao citar regra juntada')

    def test_detects_loose_citation(self):
        number = '9' + '9'
        text = '| R-' + number + ' | Juntada à **R-1** na poda (confira a R-1). | x | y |\n'
        self.assertEqual(merged_rules(text), [number])
        loose = '# R-' + number + ': regra'
        self.assertEqual(loose_citations(loose, [number]), [(number, 2)])
        self.assertEqual(loose_citations('# (R-1, ' + _PREFIX + 'R-' + number + ')', [number]), [])
        self.assertEqual(loose_citations('# R-' + number + '0', [number]), [])


if __name__ == '__main__':
    unittest.main()
