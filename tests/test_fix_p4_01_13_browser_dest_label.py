"""FIX-P4-01-13: o rótulo 'Destino atual' na aba 'Navegadores' acompanha 'Escolher destino'.

Sem `tkinter` e sem tocar em discos reais: lê `app.py` com `ast`, executa os
métodos `choose_dest` e `_update_browser_dest_label` com objetos falsos e
confere a formatação pura em `workflow_texts.browser_dest_label_text`.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest

import workflow_texts

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app.py'
APP_SOURCE = APP.read_text(encoding='utf-8')


def _app_class() -> ast.ClassDef:
    tree = ast.parse(APP_SOURCE)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'App':
            return node
    raise AssertionError('classe App não encontrada em app.py')


def _method(name: str) -> ast.FunctionDef:
    for node in _app_class().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'método {name} não encontrado em App')


def _load_method(name: str, namespace: dict | None = None):
    module = ast.Module(body=[_method(name)], type_ignores=[])
    ns = dict(namespace or {})
    exec(compile(module, str(APP), 'exec'), ns)
    return ns[name]


class _FakeVar:
    def __init__(self, value: str = ''):
        self.value = value
        self._callbacks = []

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value
        for cb in list(self._callbacks):
            cb(None, None, 'write')

    def trace_add(self, mode: str, callback) -> str:
        assert mode == 'write'
        self._callbacks.append(callback)
        return f'trace_{len(self._callbacks)}'


class BrowserDestLabelTests(unittest.TestCase):
    def test_browser_dest_label_text_formats_destination(self):
        text = workflow_texts.browser_dest_label_text(r'E:\BackupsPCRO')
        self.assertEqual(
            text,
            r'Destino atual: E:\BackupsPCRO   •   Sem sobrescrever perfis originais',
        )

    def test_build_browsers_binds_label_to_dest_with_textvariable_and_trace(self):
        method = _method('_build_browsers')
        uses_textvariable = False
        traces_dest = False
        static_concat_present = False

        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg == 'textvariable'
                            and isinstance(kw.value, ast.Attribute)
                            and kw.value.attr == 'browser_dest_text'):
                        uses_textvariable = True
                    if kw.arg == 'text' and isinstance(kw.value, ast.BinOp):
                        src_segment = ast.get_source_segment(APP_SOURCE, kw.value) or ''
                        if 'Destino atual:' in src_segment:
                            static_concat_present = True
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'trace_add'
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == 'dest'):
                    traces_dest = True

        self.assertTrue(
            uses_textvariable,
            'o rótulo em _build_browsers deve usar textvariable=self.browser_dest_text',
        )
        self.assertTrue(
            traces_dest,
            'self.dest deve registrar trace_add em _build_browsers para atualizar o rótulo',
        )
        self.assertFalse(
            static_concat_present,
            '_build_browsers não deve mais montar text="Destino atual: " estático',
        )

    def test_changing_dest_or_calling_choose_dest_updates_browser_label(self):
        update_fn = _load_method(
            '_update_browser_dest_label',
            {'browser_dest_label_text': workflow_texts.browser_dest_label_text},
        )

        class _FakeFileDialog:
            chosen = r'F:\NovoDestinoCofre'

            @classmethod
            def askdirectory(cls, **_kwargs):
                return cls.chosen

        choose_fn = _load_method('choose_dest', {'filedialog': _FakeFileDialog})

        class _DummyApp:
            def __init__(self):
                self.dest = _FakeVar(r'D:\DestinoInicial')
                self.browser_dest_text = _FakeVar(
                    workflow_texts.browser_dest_label_text(self.dest.get())
                )
                self.changed = 0
                self.dest.trace_add('write', self._update_browser_dest_label)

            def _update_browser_dest_label(self, *args):
                return update_fn(self, *args)

            def _on_change(self):
                self.changed += 1

        app = _DummyApp()
        self.assertIn(r'D:\DestinoInicial', app.browser_dest_text.get())

        # 1) Mudança via choose_dest ("Escolher destino" na revisão do backup)
        choose_fn(app)
        self.assertEqual(app.dest.get(), r'F:\NovoDestinoCofre')
        self.assertEqual(
            app.browser_dest_text.get(),
            r'Destino atual: F:\NovoDestinoCofre   •   Sem sobrescrever perfis originais',
        )
        self.assertEqual(app.changed, 1)

        # 2) Mudança direta em self.dest (ex.: digitação no Entry de destino)
        app.dest.set(r'G:\OutroDisco\Backup')
        self.assertEqual(
            app.browser_dest_text.get(),
            r'Destino atual: G:\OutroDisco\Backup   •   Sem sobrescrever perfis originais',
        )

        # 3) Cancelar o diálogo não altera o destino nem o rótulo
        _FakeFileDialog.chosen = ''
        choose_fn(app)
        self.assertEqual(app.dest.get(), r'G:\OutroDisco\Backup')
        self.assertIn(r'G:\OutroDisco\Backup', app.browser_dest_text.get())
        self.assertEqual(app.changed, 1)

    def test_runs_without_tkinter(self):
        code = (
            "import sys, unittest; "
            "sys.modules['tkinter'] = None; "
            "sys.modules['tkinter.ttk'] = None; "
            "sys.modules['tkinter.filedialog'] = None; "
            "sys.modules['tkinter.messagebox'] = None; "
            "import tests.test_fix_p4_01_13_browser_dest_label as m; "
            "suite = unittest.TestSuite(["
            "m.BrowserDestLabelTests('test_browser_dest_label_text_formats_destination'), "
            "m.BrowserDestLabelTests('test_build_browsers_binds_label_to_dest_with_textvariable_and_trace'), "
            "m.BrowserDestLabelTests('test_changing_dest_or_calling_choose_dest_updates_browser_label')"
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
