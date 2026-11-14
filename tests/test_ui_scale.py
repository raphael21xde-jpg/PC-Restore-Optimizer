"""P4-04 (Fatia 0): testes do módulo puro `ui_scale.py` (sem `tkinter`).

Confere:
1. `ui_scale.py` não tem nenhum import de `tkinter` nem de módulos externos e
   passa num processo separado com `sys.modules['tkinter'] = None`;
2. Os valores da escala seguem a regra dos 8 pontos (8, 16, 24, 32, 48, mais 4
   e a exceção fina de 2 px);
3. Tokens semânticos, preenchimentos de controles, tipografia e paleta de cores
   seguem exatamente `docs/P4-04-PROPOSTA.md`;
4. `safe_window_size`, `safe_window_geometry`, `scale_px` e `safe_wraplength`
   protegem janelas em telas Full HD com escala de 125% (1536x864) e 150%
   (1280x720).
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import sys
import unittest

import ui_scale

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'ui_scale.py').read_text(encoding='utf-8')
HEX_COLOR_RE = re.compile(r'^#[0-9A-F]{6}$')


class UiScaleModuleTests(unittest.TestCase):
    def test_module_has_zero_runtime_imports(self):
        tree = ast.parse(SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.fail(f'Import inesperado em ui_scale.py: {ast.dump(node)}')
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.module, '__future__')

    def test_spacing_scale_follows_8_point_rule(self):
        self.assertEqual(ui_scale.ESPACO_ZERO, 0)
        self.assertEqual(ui_scale.ESPACO_FINO, 2)
        self.assertEqual(ui_scale.ESPACO_MINIMO, 4)
        self.assertEqual(ui_scale.ESPACO_P, 8)
        self.assertEqual(ui_scale.ESPACO_M, 16)
        self.assertEqual(ui_scale.ESPACO_G, 24)
        self.assertEqual(ui_scale.ESPACO_GG, 32)
        self.assertEqual(ui_scale.ESPACO_SECAO, 48)

        for step in (
            ui_scale.ESPACO_P,
            ui_scale.ESPACO_M,
            ui_scale.ESPACO_G,
            ui_scale.ESPACO_GG,
            ui_scale.ESPACO_SECAO,
        ):
            self.assertEqual(step % 8, 0)

        self.assertEqual(
            list(ui_scale.ESCALA_ESPACAMENTO),
            sorted(ui_scale.ESCALA_ESPACAMENTO),
        )

    def test_semantic_tokens_and_control_metrics(self):
        self.assertEqual(ui_scale.PADDING_DIALOGO, 16)
        self.assertEqual(ui_scale.PADDING_PAINEL_COMPACTO, 16)
        self.assertEqual(ui_scale.PADDING_PAINEL, 24)
        self.assertEqual(ui_scale.PADDING_PAINEL_ESPACOSO, 32)
        self.assertEqual(ui_scale.PADDING_ABA_NOTEBOOK, 8)
        self.assertEqual(ui_scale.PADDING_CAIXA_TEXTO, (16, 8))
        self.assertEqual(ui_scale.ESPACO_ENTRE_BOTOES, (0, 8))
        self.assertEqual(ui_scale.ESPACO_ROTULO_CAMPO, (0, 4))
        self.assertEqual(ui_scale.ESPACO_DENTRO_GRUPO, (0, 8))
        self.assertEqual(ui_scale.ESPACO_ENTRE_BLOCOS, (0, 16))
        self.assertEqual(ui_scale.ESPACO_ENTRE_GRUPOS, (0, 24))

        self.assertEqual(ui_scale.PADDING_BOTAO, (16, 8))
        self.assertEqual(ui_scale.PADDING_CAMPO_ENTRADA, 8)
        self.assertEqual(ui_scale.PADDING_TITULO_ABA, (16, 8))
        self.assertEqual(ui_scale.PADDING_CABECALHO_TABELA, (8, 8))
        self.assertEqual(ui_scale.ALTURA_LINHA_TABELA, 32)
        self.assertEqual(ui_scale.ALTURA_LINHA_TABELA % 8, 0)
        self.assertGreaterEqual(ui_scale.ALTURA_MINIMA_TABELA_LINHAS, 6)

    def test_typography_and_color_palette(self):
        self.assertEqual(ui_scale.FONTE_UI, 'Segoe UI')
        self.assertEqual(ui_scale.FONTE_MONO, 'Consolas')
        self.assertEqual(ui_scale.FONTE_SIMBOLO, 'Segoe UI Symbol')

        sizes = (
            ui_scale.TAMANHO_APOIO,
            ui_scale.TAMANHO_CORPO,
            ui_scale.TAMANHO_SUBTITULO,
            ui_scale.TAMANHO_TITULO_MODAL,
            ui_scale.TAMANHO_TITULO_ABA,
            ui_scale.TAMANHO_TITULO_HERO,
        )
        self.assertEqual(sizes, (9, 10, 12, 14, 16, 20))
        self.assertEqual(list(sizes), sorted(sizes))

        colors = (
            ui_scale.COR_FUNDO,
            ui_scale.COR_PAINEL,
            ui_scale.COR_BARRA_LATERAL,
            ui_scale.COR_TEXTO,
            ui_scale.COR_TEXTO_SECUNDARIO,
            ui_scale.COR_DESTAQUE,
            ui_scale.COR_DESTAQUE_ATIVO,
            ui_scale.COR_SUCESSO,
            ui_scale.COR_ALERTA,
            ui_scale.COR_PERIGO,
            ui_scale.COR_BORDA,
            ui_scale.COR_HOVER,
            ui_scale.COR_SELECAO,
            ui_scale.COR_GRADE_GRAFICO,
            ui_scale.COR_BRANCO,
        )
        for color in colors:
            self.assertRegex(color, HEX_COLOR_RE)

        self.assertEqual(ui_scale.BG, ui_scale.COR_FUNDO)
        self.assertEqual(ui_scale.PANEL, ui_scale.COR_PAINEL)
        self.assertEqual(ui_scale.SIDEBAR, ui_scale.COR_BARRA_LATERAL)
        self.assertEqual(ui_scale.TEXT, ui_scale.COR_TEXTO)
        self.assertEqual(ui_scale.MUTED, ui_scale.COR_TEXTO_SECUNDARIO)
        self.assertEqual(ui_scale.ACCENT, ui_scale.COR_DESTAQUE)
        self.assertEqual(ui_scale.GREEN, ui_scale.COR_SUCESSO)
        self.assertEqual(ui_scale.AMBER, ui_scale.COR_ALERTA)
        self.assertEqual(ui_scale.BORDER, ui_scale.COR_BORDA)
        self.assertEqual(ui_scale.HOVER, ui_scale.COR_HOVER)
        self.assertEqual(ui_scale.WHITE, ui_scale.COR_BRANCO)

    def test_safe_window_geometry_for_100_125_and_150_percent_dpi(self):
        # 100% em 1920x1080: cabe folgado
        self.assertEqual(
            ui_scale.safe_window_geometry(960, 620, 1920, 1080),
            '960x620',
        )
        # 125% em Full HD (1536x864 lógicos): 1400x875 é limitado na altura (864 - 80 = 784)
        self.assertEqual(
            ui_scale.safe_window_geometry(1400, 875, 1536, 864),
            '1400x784',
        )
        # 150% em Full HD (1280x720 lógicos): 1400x875 é limitado em largura (1200) e altura (640)
        self.assertEqual(
            ui_scale.safe_window_geometry(1400, 875, 1280, 720),
            '1200x640',
        )
        # Valores de tela desconhecidos/zero mantêm o tamanho desejado
        self.assertEqual(
            ui_scale.safe_window_geometry(960, 620, 0, 0),
            '960x620',
        )

    def test_scale_px_and_safe_wraplength(self):
        self.assertEqual(ui_scale.scale_px(0, 1.5), 0)
        self.assertEqual(ui_scale.scale_px(16, 1.0), 16)
        self.assertEqual(ui_scale.scale_px(16, 1.25), 20)
        self.assertEqual(ui_scale.scale_px(16, 1.5), 24)
        # Arredonda sempre para par quando fator > 1.0
        self.assertEqual(ui_scale.scale_px(10, 1.5) % 2, 0)

        self.assertEqual(ui_scale.safe_wraplength(960, padding=16), 928)
        self.assertEqual(ui_scale.safe_wraplength(200, padding=16, min_wrap=320), 320)

    def test_runs_in_subprocess_without_tkinter(self):
        code = (
            "import sys, unittest; "
            "sys.modules['tkinter'] = None; "
            "sys.modules['tkinter.ttk'] = None; "
            "import tests.test_ui_scale as m; "
            "suite = unittest.TestSuite(["
            "m.UiScaleModuleTests('test_module_has_zero_runtime_imports'), "
            "m.UiScaleModuleTests('test_spacing_scale_follows_8_point_rule'), "
            "m.UiScaleModuleTests('test_safe_window_geometry_for_100_125_and_150_percent_dpi')"
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
