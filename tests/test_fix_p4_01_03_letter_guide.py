"""FIX-P4-01-03: o guia de trocar a letra avisa o efeito e como desfazer.

Só dados sintéticos: o manifesto fica num TemporaryDirectory e as unidades
são textos ('C:\\', 'E:\\') com tamanho e tipo simulados. Nunca lista discos
reais nem abre o Gerenciamento de Disco. Nada é apagado.
"""
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
        'arquivos marcados para pasta nova"; só o "Colocar no lugar original" precisa que a '
        'unidade volte a ter a letra de quando o backup foi feito.')
PARTS = (WARN, SAFE, AFTER, UNDO, SKIP)
# O manual tem limite de linhas (tests/test_manual.py); a frase de "não trocar"
# fica só na tela.
SHARED = (WARN, AFTER, UNDO)
FORBIDDEN = ('formate', 'formatar o', 'apague', 'apagar', 'exclua', 'excluir',
             'desinstal', 'particion')
WIN_ENV = {'SystemRoot': r'C:\Windows', 'SystemDrive': 'C:'}


def _usage(root):
    return (500 * 1024 ** 3, 100 * 1024 ** 3, 400 * 1024 ** 3)


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

    def test_after_step_names_real_button_and_step(self):
        self.assertIn('Conferir discos e letras', [s['title'] for s in af.STEPS])
        ui = (ROOT / 'after_format_ui.py').read_text(encoding='utf-8')
        self.assertIn("text='Abrir'", ui)
        restore = (ROOT / 'restore_ui.py').read_text(encoding='utf-8')
        self.assertIn("text='Restaurar arquivos marcados para pasta nova'", restore)
        self.assertIn("text='Colocar no lugar original'", restore)

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
