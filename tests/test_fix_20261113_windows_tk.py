"""FIX-20261113-windows-tk: o tkinter falso dos testes não pode sumir com o tkinter de verdade.

Alguns testes carregam uma tela com um "tkinter" de mentira em ``sys.modules`` para
checar o fluxo sem abrir janela. Se, ao terminar, o tkinter verdadeiro não voltar para
``sys.modules``, o próximo ``import tkinter`` carrega uma cópia nova do módulo: a cópia
não conhece a janela principal já aberta (``_default_root``) e as classes de widget dela
são diferentes das que as janelas existentes usam. Os testes de tela que rodam depois
quebram com "no default root window" ou param de achar os botões.

Sem arquivos reais: só módulos e uma janela, quando houver tela.
"""
import importlib
import sys
import unittest


LOADERS = (  # módulo de teste, função que carrega a tela com o tkinter falso
    ('test_fix_p4_01_05_browser_guides', '_load_screen'),
    ('test_power_reuse_fix_m3_t3_01', '_load_ui_without_tk'),
)


class RealTkinterSurvivesTests(unittest.TestCase):
    def setUp(self):
        self.real = importlib.import_module('tkinter')
        self.real_ttk = importlib.import_module('tkinter.ttk')
        # Enquanto a falha existir, este teste também não pode atrapalhar os seguintes.
        saved = {name: module for name, module in sys.modules.items()
                 if name == 'tkinter' or name.startswith('tkinter.')}
        self.addCleanup(sys.modules.update, saved)

    def _call(self, module_name, function_name):
        module = importlib.import_module(module_name)
        getattr(module, function_name)()

    def test_loaders_leave_the_real_tkinter_in_place(self):
        for module_name, function_name in LOADERS:
            with self.subTest(module=module_name):
                self._call(module_name, function_name)
                self.assertIs(sys.modules.get('tkinter'), self.real)
                self.assertIs(sys.modules.get('tkinter.ttk'), self.real_ttk)
                self.assertIs(importlib.import_module('tkinter'), self.real)
                self.assertIs(importlib.import_module('tkinter.ttk').Button,
                              self.real_ttk.Button)

    def test_default_root_still_seen_after_the_loaders(self):
        tk = self.real
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Sem servidor gráfico: {exc}')
        root.withdraw()
        try:
            for module_name, function_name in LOADERS:
                with self.subTest(module=module_name):
                    self._call(module_name, function_name)
                    fresh = importlib.import_module('tkinter')
                    # A janela já aberta continua sendo a principal para quem importar agora.
                    self.assertIs(fresh._default_root, root)
                    fresh.StringVar(value='')  # não pode levantar RuntimeError
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
