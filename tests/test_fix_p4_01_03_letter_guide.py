"""FIX-P4-01-03: o guia de trocar a letra avisa o efeito e como desfazer.

Só dados sintéticos: o manifesto fica num TemporaryDirectory e as unidades
são textos ('C:\\', 'E:\\') com tamanho e tipo simulados. Nunca lista discos
reais nem abre o Gerenciamento de Disco. Nada é apagado.
"""
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import after_format as af

# Cada parte da R-41 (R-80): risco, condição segura, o que fazer depois,
# como desfazer e se ignorar resolve.
WARN = ('Cuidado: programas e atalhos que usam a letra que a unidade tinha antes da troca '
        'param de achar os arquivos até essa letra voltar.')
SAFE = 'Não mude a letra do disco do Windows.'
AFTER = ('Depois de trocar, clique em "Abrir" na etapa "Conferir discos e letras" para '
         'conferir de novo.')
UNDO = 'Para desfazer, volte para a letra que a unidade tinha antes da troca, pelo mesmo caminho.'
SKIP = ('Se preferir não trocar a letra, ainda dá para restaurar os arquivos com "Restaurar '
        'arquivos marcados para pasta nova", na janela que abre pelo "Abrir" da etapa '
        '"Restaurar os arquivos"; só o "Colocar no lugar original", na mesma janela, precisa '
        'que a unidade volte a ter a letra de quando o backup foi feito.')
PARTS = (WARN, SAFE, AFTER, UNDO, SKIP)
# O manual tem limite de linhas (tests/test_manual.py); a frase de "não trocar"
# fica só na tela.
SHARED = (WARN, AFTER, UNDO)
FORBIDDEN = ('formate', 'formatar o', 'apague', 'apagar', 'exclua', 'excluir',
             'desinstal', 'particion')
WIN_ENV = {'SystemRoot': r'C:\Windows', 'SystemDrive': 'C:'}


def _usage(root):
    return (500 * 1024 ** 3, 100 * 1024 ** 3, 400 * 1024 ** 3)


def _function(module_file, name):
    tree = ast.parse((ROOT / module_file).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name} não encontrado em {module_file}')


def _button_labels(func):
    """Rótulos text='...' dos ttk.Button criados dentro da função (R-74, R-81)."""
    labels = set()
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'Button'):
            for kw in node.keywords:
                if kw.arg == 'text' and isinstance(kw.value, ast.Constant):
                    labels.add(kw.value.value)
    return labels


def _calls(func):
    return {n.func.id for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _flat(text):
    return ' '.join(text.split())


class LetterGuideTextTests(unittest.TestCase):
    def test_guide_has_every_r41_part(self):
        text = _flat(af.CHANGE_LETTER_GUIDE.format(letters='D:'))
        for part in PARTS:
            with self.subTest(part=part[:40]):
                self.assertIn(part, text)

    def test_old_ambiguous_wording_gone(self):
        self.assertNotIn('letra antiga', af.CHANGE_LETTER_GUIDE)

    def test_steps_named_in_guide_exist(self):
        titles = [s['title'] for s in af.STEPS]
        self.assertIn('Conferir discos e letras', titles)
        self.assertIn('Restaurar os arquivos', titles)

    def test_open_button_is_built_by_after_format_screen(self):
        screen = _function('after_format_ui.py', 'show_after_format')
        self.assertIn('Abrir', _button_labels(screen))

    def test_restore_step_opens_restore_window(self):
        screen = _function('after_format_ui.py', 'show_after_format')
        open_step = next(n for n in ast.walk(screen)
                         if isinstance(n, ast.FunctionDef) and n.name == 'open_step')
        branches = [n for n in ast.walk(open_step) if isinstance(n, ast.If)
                    and isinstance(n.test, ast.Compare)
                    and any(isinstance(c, ast.Constant) and c.value == 'restaurar'
                            for c in n.test.comparators)]
        self.assertEqual(len(branches), 1)
        body = ast.Module(body=branches[0].body, type_ignores=[])
        self.assertIn('show_restore', _calls(body))
        self.assertIn('restaurar', [s['id'] for s in af.STEPS
                                    if s['title'] == 'Restaurar os arquivos'])

    def test_restore_buttons_are_built_by_show_restore(self):
        labels = _button_labels(_function('restore_ui.py', 'show_restore'))
        self.assertIn('Restaurar arquivos marcados para pasta nova', labels)
        self.assertIn('Colocar no lugar original', labels)

    def test_guide_keeps_old_safety_lines(self):
        self.assertIn('{letters}', af.CHANGE_LETTER_GUIDE)
        text = af.CHANGE_LETTER_GUIDE.format(letters='D:')
        self.assertIn('Não mude a letra do disco do Windows', text)
        self.assertIn('O aplicativo nunca troca letras sozinho', text)
        self.assertIn('D:', text)

    def test_guide_has_no_forbidden_words(self):
        text = af.CHANGE_LETTER_GUIDE.format(letters='D:').lower()
        for word in FORBIDDEN:
            self.assertNotIn(word, text)

    def test_same_sentences_as_manual(self):
        manual = _flat((ROOT / 'docs' / 'MANUAL.md').read_text(encoding='utf-8'))
        for part in SHARED:
            with self.subTest(part=part[:40]):
                self.assertIn(part, manual)
        self.assertNotIn('letra antiga', manual)


class CheckDrivesGuidanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / 'backup' / 'b1'
        folder.mkdir(parents=True)
        files = []
        for index, (source, rel) in enumerate([(r'C:\Users\x\a.txt', 'C/a.txt'),
                                                (r'D:\Jogos\save.dat', 'D/save.dat')]):
            files.append({'source': source, 'relative': rel, 'verified': True, 'size': 1,
                          'sha256': hashlib.sha256(str(index).encode()).hexdigest()})
        self.manifest = folder / 'manifest.json'
        self.manifest.write_text(json.dumps({'schema': 'pc-restore-backup-v0.5',
                                             'files': files}), encoding='utf-8')

    def test_guidance_has_every_r41_part(self):
        result = af.check_drives(self.manifest, roots=['C:\\', 'E:\\'], usage=_usage,
                                 environ=WIN_ENV, drive_type=lambda root: 'Disco local')
        self.assertEqual(result['missing'], ['D:'])
        text = _flat(result['guidance'])
        for part in PARTS:
            with self.subTest(part=part[:40]):
                self.assertIn(part, text)
        for word in FORBIDDEN:
            self.assertNotIn(word, text.lower())


if __name__ == '__main__':
    unittest.main()
