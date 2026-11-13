"""FIX-P4-01-05: passo a passo para Chrome, Edge e Firefox no "Restaurar navegador".

Sem Tk e sem perfil real: só texto, e uma pasta sintética em TemporaryDirectory.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path

import browser_recovery as br

ROOT = Path(__file__).resolve().parents[1]
FIVE = ('Opera', 'Opera GX', 'Google Chrome', 'Microsoft Edge', 'Mozilla Firefox')
OTHERS = ('Brave', 'Vivaldi', 'Chromium', '')
FAKE_PASSWORD = 'senha-falsa-12345'


def _synthetic_recovery(base):
    root = Path(base) / 'CONFERIR-NAVEGADOR'
    (root / 'profile').mkdir(parents=True)
    (root / 'manual-export').mkdir()
    (root / 'metadata').mkdir()
    (root / 'metadata' / 'info.json').write_text(json.dumps({'browser': 'Opera'}), encoding='utf-8')
    (root / 'profile' / 'Bookmarks').write_text(json.dumps({'roots': {'bookmark_bar': {
        'type': 'folder', 'name': 'Barra', 'children': [
            {'type': 'url', 'name': 'Exemplo', 'url': 'https://example.com/'}]}}}), encoding='utf-8')
    (root / 'manual-export' / 'senhas-exportadas.csv').write_text(
        'url,username,password\nhttps://example.com,fulano,' + FAKE_PASSWORD + '\n', encoding='utf-8')
    return root


class SupportTests(unittest.TestCase):
    def test_supported_five(self):
        for name in FIVE:
            self.assertTrue(br.destination_supported(name), name)

    def test_not_supported_others(self):
        for name in OTHERS:
            self.assertFalse(br.destination_supported(name), name)


class TextTests(unittest.TestCase):
    def test_bookmark_text_has_path_and_browser_name(self):
        path = r'C:\privada\favoritos.html'
        for name in FIVE:
            text = br.bookmark_import_steps(name, path)
            with self.subTest(name=name):
                self.assertIn(path, text)
                self.assertIn(name, text)
                self.assertIn('Ajuda oficial do navegador', text)
                if not name.startswith('Opera'):
                    self.assertNotIn('Opera', text)

    def test_bookmark_text_specific_menus(self):
        p = 'x.html'
        self.assertIn('Arquivo HTML de favoritos', br.bookmark_import_steps('Google Chrome', p))
        self.assertIn('Importar dados do navegador', br.bookmark_import_steps('Microsoft Edge', p))
        fx = br.bookmark_import_steps('Mozilla Firefox', p)
        self.assertIn('Ctrl+Shift+O', fx)
        self.assertIn('Importar favoritos de HTML', fx)
        self.assertIn('Ctrl+Shift+B', br.bookmark_import_steps('Opera GX', p))

    def test_password_text_orders_deleting_csv_and_has_no_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = br.inspect_recovery(_synthetic_recovery(tmp))
            self.assertTrue(info['password_csv'])
            for name in FIVE:
                text = br.password_import_steps(name)
                with self.subTest(name=name):
                    self.assertIn('apague o CSV', text)
                    self.assertNotIn(FAKE_PASSWORD, text)
                    self.assertIn('Ajuda oficial do navegador', text)
                    if not name.startswith('Opera'):
                        self.assertNotIn('Opera', text)
        self.assertIn('about:logins', br.password_import_steps('Mozilla Firefox'))
        self.assertIn('Importar de um arquivo', br.password_import_steps('Mozilla Firefox'))
        self.assertIn('Gerenciador de senhas', br.password_import_steps('Google Chrome'))

    def test_unsupported_browser_is_refused(self):
        with self.assertRaises(ValueError):
            br.bookmark_import_steps('Brave', 'x.html')
        with self.assertRaises(ValueError):
            br.password_import_steps('Vivaldi')

    def test_prepare_bookmarks_still_works_in_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / 'saida'
            out_dir.mkdir()
            out, count = br.prepare_bookmarks(_synthetic_recovery(tmp), out_dir)
            self.assertEqual(count, 1)
            self.assertIn(str(out), br.bookmark_import_steps('Mozilla Firefox', out))


class HelpTests(unittest.TestCase):
    def test_help_url_https_for_five(self):
        for name in FIVE:
            self.assertTrue(br.help_url(name).startswith('https://'), name)

    def test_help_url_empty_for_unknown(self):
        self.assertEqual(br.help_url('Navegador Inexistente'), '')


class UiSourceTests(unittest.TestCase):
    def setUp(self):
        self.src = (ROOT / 'browser_recovery_ui.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.src)

    def test_ready_has_no_fixed_opera_tuple(self):
        ready = [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == 'ready']
        self.assertEqual(len(ready), 1)
        for node in ast.walk(ready[0]):
            if isinstance(node, ast.Tuple):
                values = {e.value for e in node.elts if isinstance(e, ast.Constant)}
                self.assertFalse({'Opera GX', 'Opera'} <= values)
        names = {n.id for n in ast.walk(ready[0]) if isinstance(n, ast.Name)}
        self.assertIn('destination_supported', names)

    def test_old_texts_gone(self):
        for old in ('Destino ainda não suportado', 'Ajuda oficial do Opera',
                    'No Opera escolhido', 'Opera GX, pressione Ctrl+Shift+B'):
            self.assertNotIn(old, self.src)
        self.assertIn('Ajuda oficial do navegador', self.src)


if __name__ == '__main__':
    unittest.main()
