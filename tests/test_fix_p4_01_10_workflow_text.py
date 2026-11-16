"""FIX-P4-01-10: os textos do workflow não citam letras fixas (D:, F:, G:).

Nenhum texto de tela (strings com mais de 3 caracteres) cita D:/F:/G:; a antiga
tupla fixa de build_preservation também foi substituída pelo plano no FIX-P4-01-14.
As frases de Visão geral e Preservação dizem que o app não apaga nenhum arquivo e que o que não
for copiado do C: se perde quando o instalador formatar o C: (R-88).

Lê `workflow_ui.py` e `workflow_texts.py` com `ast` e chama `workflow_texts` (módulo
sem `tkinter`), sem abrir janela. Nada é apagado.
"""
import ast
import unittest
from pathlib import Path
import workflow_texts

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')
TEXTS_SOURCE = (ROOT / 'workflow_texts.py').read_text(encoding='utf-8')
FUNCS = ('build_overview', 'build_preservation', 'build_installation',
         'overview_intro_text', 'preservation_intro_text', 'installation_steps')
NEW_TEXTS = (
    'Escolha o que manter em cada unidade. Prepare o C: antes de reinstalar o Windows: '
    'o que não for copiado dele não entra no backup e se perde quando o instalador formatar o C:. '
    'O app não apaga nenhum arquivo dos outros discos e unidades.',
    'C: exige cópia verificada antes de reinstalar. O app não apaga nenhum arquivo, nem os itens pendentes. '
    'O que ficar pendente ou desmarcado no C: não entra no backup e se perde quando o instalador '
    'formatar o C:. O app não apaga nenhum arquivo dos outros discos e unidades.',
    'Revisar dados do C: associados a jogos instalados em outros discos ou unidades; '
    'o app não apaga nenhum arquivo desses discos; o que é do C: só se salva com a cópia.',
    'Copiar e verificar arquivos pessoais, saves e configurações antes de o instalador apagar '
    'a partição do sistema.',
)
LOSS = 'se perde quando o instalador formatar o C:'
OLD_TEXTS = ('permanecem intactos', 'podem ficar intactos', 'permanecerão em D:',
             'nada é apagado.', 'que continuam onde estão',
             # frases da 1ª versão da PR #240, nunca estiveram na main (R-88, antiga R-89):
             'não mexe nos outros discos', 'não mexe nesses discos',
             'antes de apagar a partição do sistema',
             # 2ª versão da PR #240, nunca na main: "só" falso, o "Colocar no lugar
             # original" (restore_place.py) grava em qualquer disco (R-88, antiga R-90):
             'só grava a cópia na pasta que você escolher',
             'não apaga nada nos outros discos', 'não apaga nada nesses discos')


def _strings_of(func_name):
    for src in (SOURCE, TEXTS_SOURCE):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return [n.value for n in ast.walk(node)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    raise AssertionError(f'{func_name} não encontrado em workflow_ui.py / workflow_texts.py')


def _rendered_texts(drive='C:'):
    steps = [body for _num, _title, body in workflow_texts.installation_steps(drive)]
    return [
        workflow_texts.overview_intro_text(drive),
        workflow_texts.preservation_intro_text(drive),
        *steps,
    ]


class WorkflowTextTests(unittest.TestCase):
    def test_no_fixed_letters(self):
        for func in FUNCS:
            for text in _strings_of(func):
                if len(text) > 3:
                    for letter in ('D:', 'F:', 'G:'):
                        self.assertNotIn(letter, text, func)

    def test_new_texts_present(self):
        every = _rendered_texts('C:') + [t for f in FUNCS for t in _strings_of(f)]
        for text in NEW_TEXTS:
            self.assertIn(text, every)

    def test_loss_warning_next_to_not_deleted(self):
        for text in (workflow_texts.overview_intro_text('C:'),
                     workflow_texts.preservation_intro_text('C:')):
            self.assertIn('não apaga nenhum arquivo', text)
            self.assertIn(LOSS, text)

    def test_installation_step_says_c_only_saved_by_copy(self):
        texts = [body for _num, _title, body in workflow_texts.installation_steps('C:')
                 if 'só se salva com a cópia' in body]
        self.assertEqual(len(texts), 1)
        self.assertIn('o app não apaga nenhum arquivo desses discos', texts[0])

    def test_old_texts_gone(self):
        for old in OLD_TEXTS:
            self.assertNotIn(old, SOURCE)
            self.assertNotIn(old, TEXTS_SOURCE)


if __name__ == '__main__':
    unittest.main()
