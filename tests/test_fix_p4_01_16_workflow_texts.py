"""FIX-P4-01-16: textos "intactos" e "C:" fixo em `deep_discovery_ui.py` e `workflow_ui.py` (R-88).

1. `deep_discovery_ui.py` (`skip`): não diz mais "Arquivos originais permanecem intactos." solto;
   diz que o app não apaga nenhum arquivo e lembra que o que não for copiado do disco do Windows
   não entra no backup e se perde quando o instalador formatar esse disco (R-88).
2. `workflow_ui.py` + `workflow_texts.py`: monta os textos da unidade do sistema a partir de
   `system_drive` (que reaproveita `windows_drive.py`), em vez de "C:" fixo, e remove
   "outras unidades permanecem no local".

Lê o código-fonte com `ast` e chama as funções puras de `workflow_texts` (sem `tkinter`).
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import workflow_texts

ROOT = Path(__file__).resolve().parents[1]
DEEP_SOURCE = (ROOT / 'deep_discovery_ui.py').read_text(encoding='utf-8')
WORKFLOW_SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')
TEXTS_SOURCE = (ROOT / 'workflow_texts.py').read_text(encoding='utf-8')

DEEP_NEW_TEXT = (
    'Retirar os itens do plano de preservação? O app não apaga nenhum arquivo, '
    'mas o que não for copiado do disco do Windows não entra no backup e se perde '
    'quando o instalador formatar esse disco.'
)
DEEP_OLD_TEXTS = (
    'Arquivos originais permanecem intactos.',
    'permanecem intactos',
    'não mexe',
    'só grava',
)


def _all_strings(source: str) -> list[str]:
    tree = ast.parse(source)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


class DeepDiscoverySkipTextTests(unittest.TestCase):
    def test_new_skip_text_present_and_follows_r88(self):
        strings = _all_strings(DEEP_SOURCE)
        self.assertIn(DEEP_NEW_TEXT, strings)
        self.assertIn('O app não apaga nenhum arquivo', DEEP_NEW_TEXT)
        self.assertIn('não entra no backup', DEEP_NEW_TEXT)
        self.assertIn('se perde quando o instalador formatar', DEEP_NEW_TEXT)

    def test_old_intactos_text_gone_from_deep_discovery_ui(self):
        for old in DEEP_OLD_TEXTS:
            self.assertNotIn(old, DEEP_SOURCE)


class WorkflowSystemDriveTextTests(unittest.TestCase):
    def test_system_drive_reads_environ_and_defaults_to_c(self):
        self.assertEqual(workflow_texts.system_drive({'SystemDrive': 'c:'}), 'C:')
        self.assertEqual(workflow_texts.system_drive({'SystemDrive': 'W:'}), 'W:')
        self.assertEqual(
            workflow_texts.system_drive({'SystemRoot': r'D:\Windows', 'SystemDrive': 'D:'}),
            'D:',
        )
        self.assertEqual(workflow_texts.system_drive({'SystemDrive': r'X:\Windows'}), 'X:')
        self.assertEqual(workflow_texts.system_drive({}), 'C:')
        self.assertEqual(workflow_texts.system_drive({'SystemDrive': 'invalido'}), 'C:')

    def test_texts_adapt_to_non_c_system_drive(self):
        with mock.patch.dict(
            workflow_texts.os.environ,
            {'SystemRoot': r'W:\Windows', 'SystemDrive': 'W:'},
            clear=False,
        ):
            overview = workflow_texts.overview_intro_text()
            preservation = workflow_texts.preservation_intro_text()
            steps = workflow_texts.installation_steps()
        self.assertIn('Prepare o W: antes de reinstalar o Windows', overview)
        self.assertIn('quando o instalador formatar o W:.', overview)
        self.assertNotIn('C:', overview)

        self.assertIn('W: exige cópia verificada antes de reinstalar.', preservation)
        self.assertIn('pendente ou desmarcado no W: não entra no backup', preservation)
        self.assertIn('formatar o W:.', preservation)
        self.assertNotIn('C:', preservation)

        step1_title = steps[0][1]
        step2_body = steps[1][2]
        self.assertEqual(step1_title, 'Preservar o W:')
        self.assertIn('Revisar dados do W:', step2_body)
        self.assertIn('o que é do W: só se salva com a cópia.', step2_body)
        self.assertNotIn('C:', step1_title)
        self.assertNotIn('C:', step2_body)

    def test_workflow_ui_no_longer_hardcodes_c_in_screen_sentences(self):
        # A única ocorrência literal de 'C:' que resta em build_preservation é a
        # tupla ('C:', 'D:', 'F:', 'G:'), reservada ao FIX-P4-01-14.
        for src, funcs in (
            (WORKFLOW_SOURCE, ('build_overview', 'build_preservation', 'build_installation',
                               'show_c_preflight')),
            (TEXTS_SOURCE, ('overview_intro_text', 'preservation_intro_text', 'installation_steps')),
        ):
            tree = ast.parse(src)
            for func_name in funcs:
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == func_name:
                        doc_id = (id(node.body[0].value)
                                  if node.body and isinstance(node.body[0], ast.Expr) else None)
                        for child in ast.walk(node):
                            if (isinstance(child, ast.Constant)
                                    and isinstance(child.value, str)
                                    and id(child) != doc_id):
                                if len(child.value) > 3:
                                    self.assertNotIn('C:', child.value, f'{func_name}: {child.value}')
        self.assertNotIn('outras unidades permanecem no local', WORKFLOW_SOURCE)

    def test_tests_run_without_tkinter(self):
        code = (
            "import sys, unittest; "
            "sys.modules['tkinter'] = None; "
            "sys.modules['tkinter.ttk'] = None; "
            "sys.modules['tkinter.filedialog'] = None; "
            "sys.modules['tkinter.messagebox'] = None; "
            "suite = unittest.defaultTestLoader.loadTestsFromNames(["
            "'tests.test_fix_p4_01_10_workflow_text', "
            "'tests.test_fix_p4_01_16_workflow_texts.DeepDiscoverySkipTextTests'"
            "]); "
            "res = unittest.TextTestRunner(verbosity=0).run(suite); "
            "sys.exit(0 if res.wasSuccessful() else 1)"
        )
        proc = subprocess.run(
            [sys.executable, '-c', code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == '__main__':
    unittest.main()
