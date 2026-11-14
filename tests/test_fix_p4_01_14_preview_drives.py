"""FIX-P4-01-14: a prévia da Preservação monta a lista de unidades a partir do plano (só leitura).

Testa com plano falso e arquivos sintéticos em `TemporaryDirectory`, sem `tkinter`
e sem tocar em discos reais:
1. Unidades fora da antiga tupla fixa `('C:', 'D:', 'F:', 'G:')`, como `E:` e `H:`,
   aparecem na prévia.
2. Uma unidade do plano sem entradas de caminhos (por exemplo, em `scan_roots` ou
   com jogo/app associado) aparece com `0 caminho(s)`.
3. A prévia de remoção (`removal_candidates`) continua apenas prévia (`SOMENTE MARCADO • NÃO APAGAR`),
   sem apagar nenhum arquivo sintético.
4. `workflow_ui.py` não tem mais a tupla fixa `('C:', 'D:', 'F:', 'G:')`.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from preservation_audit import build_audit
import workflow_texts

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_SOURCE = (ROOT / 'workflow_ui.py').read_text(encoding='utf-8')


class PreservationPreviewDrivesTests(unittest.TestCase):
    def test_drives_outside_c_d_f_g_appear_in_preview_from_plan(self):
        with tempfile.TemporaryDirectory(prefix='PCRO-FIX14-') as tmp:
            plan_file = Path(tmp) / 'plano-sintetico.json'
            synth_file = Path(tmp) / 'nao-apagar.txt'
            synth_file.write_text('conteudo sintetico intacto', encoding='utf-8')

            plan = build_audit(
                choices={
                    r'C:\Users\Teste\Documentos': 'keep',
                    r'E:\Projetos\App': 'keep',
                },
                catalog_choices={'jogo_h': 'keep'},
                catalog_items={
                    'jogo_h': {
                        'kind': 'game',
                        'name': 'Jogo em H',
                        'install_location': r'H:\Games\JogoH',
                        'paths': [],
                        'possible_paths': [],
                    }
                },
                scanned_roots=[r'C:\\', r'E:\\', r'H:\\', r'Z:\\'],
                removal_candidates=[r'E:\Temp\Velho'],
            )
            plan_file.write_text('ok', encoding='utf-8')

            drives = workflow_texts.preview_drives(plan, drive='C:')
            self.assertEqual(drives, ['C:', 'E:', 'H:', 'Z:'])
            for fixed_absent in ('D:', 'F:', 'G:'):
                self.assertNotIn(fixed_absent, drives)

            rows = workflow_texts.preview_drive_rows(plan, drive='C:')
            by_drive = {r['drive']: r for r in rows}

            # E: (fora de C/D/F/G) aparece com 1 caminho e 1 candidato de remoção
            self.assertIn('E:', by_drive)
            self.assertEqual(by_drive['E:']['header'], 'E:  •  1 caminho(s), 0 jogo(s)/app(s)')
            self.assertEqual(by_drive['E:']['scan_status'], 'Varredura atual: sim')
            self.assertEqual(len(by_drive['E:']['entries']), 1)
            self.assertEqual(by_drive['E:']['removed'], [r'E:\Temp\Velho'])

            # H: (unidade com jogo mas 0 entradas de caminhos) aparece com 0 caminho(s)
            self.assertIn('H:', by_drive)
            self.assertEqual(by_drive['H:']['header'], 'H:  •  0 caminho(s), 1 jogo(s)/app(s)')
            self.assertEqual(by_drive['H:']['entries'], [])

            # Z: (unidade em scan_roots sem entradas e sem jogos) aparece com 0 caminho(s), 0 jogo(s)/app(s)
            self.assertIn('Z:', by_drive)
            self.assertEqual(by_drive['Z:']['header'], 'Z:  •  0 caminho(s), 0 jogo(s)/app(s)')
            self.assertEqual(by_drive['Z:']['entries'], [])
            self.assertEqual(by_drive['Z:']['removed'], [])

            # Arquivo sintético continua existindo (nada é apagado)
            self.assertTrue(synth_file.is_file())
            self.assertEqual(synth_file.read_text(encoding='utf-8'), 'conteudo sintetico intacto')
            self.assertFalse(plan['deletions_authorized'])
            self.assertFalse(plan['installation_authorized'])

    def test_removal_preview_remains_read_only_and_never_deletes_files(self):
        with tempfile.TemporaryDirectory(prefix='PCRO-FIX14-RO-') as tmp:
            candidate_file = Path(tmp) / 'candidato.txt'
            candidate_file.write_text('protegido', encoding='utf-8')
            fake_e_candidate = r'E:\PastaTeste\candidato.txt'

            plan = build_audit(
                choices={},
                catalog_choices={},
                catalog_items={},
                scanned_roots=[],
                removal_candidates=[str(candidate_file), fake_e_candidate],
            )
            rows = workflow_texts.preview_drive_rows(plan, drive='C:')
            by_drive = {r['drive']: r for r in rows}

            self.assertIn('E:', by_drive)
            self.assertEqual(by_drive['E:']['header'], 'E:  •  0 caminho(s), 0 jogo(s)/app(s)')
            self.assertEqual(by_drive['E:']['removed'], [fake_e_candidate])
            self.assertEqual(by_drive['E:']['scan_status'], 'Varredura atual: não confirmada')

            # O arquivo real dentro do TemporaryDirectory continua intacto
            self.assertTrue(candidate_file.is_file())
            self.assertEqual(candidate_file.read_text(encoding='utf-8'), 'protegido')
            self.assertFalse(plan['deletions_authorized'])

    def test_workflow_ui_no_longer_has_hardcoded_c_d_f_g_tuple(self):
        self.assertNotIn("('C:', 'D:', 'F:', 'G:')", WORKFLOW_SOURCE)
        self.assertNotIn("('C:','D:','F:','G:')", WORKFLOW_SOURCE)
        tree = ast.parse(WORKFLOW_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'build_preservation':
                constants = [
                    child.value
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                ]
                for letter in ('C:', 'D:', 'F:', 'G:'):
                    self.assertNotIn(letter, constants)
                calls = [
                    getattr(child.func, 'id', None)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                ]
                self.assertIn('preview_drive_rows', calls)

    def test_runs_without_tkinter(self):
        code = (
            "import sys, unittest; "
            "sys.modules['tkinter'] = None; "
            "sys.modules['tkinter.ttk'] = None; "
            "sys.modules['tkinter.filedialog'] = None; "
            "sys.modules['tkinter.messagebox'] = None; "
            "import tests.test_fix_p4_01_14_preview_drives as m; "
            "suite = unittest.TestSuite(["
            "m.PreservationPreviewDrivesTests('test_drives_outside_c_d_f_g_appear_in_preview_from_plan'), "
            "m.PreservationPreviewDrivesTests('test_removal_preview_remains_read_only_and_never_deletes_files'), "
            "m.PreservationPreviewDrivesTests('test_workflow_ui_no_longer_has_hardcoded_c_d_f_g_tuple')"
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
