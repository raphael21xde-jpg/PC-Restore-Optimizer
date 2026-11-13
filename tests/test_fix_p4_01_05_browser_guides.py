"""FIX-P4-01-05: passo a passo para Chrome, Edge e Firefox no "Restaurar navegador".

Sem Tk e sem perfil real: só texto, e uma pasta sintética em TemporaryDirectory.
"""
import ast
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import browser_recovery as br

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
                self.assertIn('Se o menu estiver diferente', text)
                if not name.startswith('Opera'):
                    self.assertNotIn('Opera', text)
                    self.assertIn('"Ajuda oficial do navegador"', text)

    def test_bookmark_text_specific_menus(self):
        p = 'x.html'
        self.assertIn('Arquivo HTML de favoritos', br.bookmark_import_steps('Google Chrome', p))
        edge = br.bookmark_import_steps('Microsoft Edge', p)
        self.assertIn('Importar dados do navegador', edge)
        self.assertIn('em "Importar de" escolha "Arquivo HTML de favoritos ou marcadores"', edge)
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
                    self.assertIn('Se o menu estiver diferente', text)
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
    EXPECTED = {  # navegador -> etapa -> (domínio, pedaço obrigatório do caminho)
        'Google Chrome': {'favoritos': ('support.google.com', '/chrome/answer/96816'),
                          'senhas': ('support.google.com', '/chrome/answer/13068232')},
        'Microsoft Edge': {'favoritos': ('support.microsoft.com', 'import'),
                           'senhas': ('support.microsoft.com', 'import')},
        'Mozilla Firefox': {'favoritos': ('support.mozilla.org', 'import'),
                            'senhas': ('support.mozilla.org', 'import')},
    }

    def test_each_link_is_the_import_page_not_a_home_page(self):
        # R-83/R-84: https, domínio do fabricante e caminho do artigo; nunca a página inicial.
        from urllib.parse import urlsplit
        for name, steps in self.EXPECTED.items():
            for step, (domain, piece) in steps.items():
                with self.subTest(name=name, step=step):
                    url = br.help_url(name, step)
                    parts = urlsplit(url)
                    self.assertEqual(parts.scheme, 'https')
                    self.assertEqual(parts.netloc, domain)
                    self.assertIn(piece, parts.path)
                    self.assertGreater(len(parts.path.strip('/')), 8)

    def test_not_the_sync_page(self):
        import browser_vault
        for name in self.EXPECTED:
            # Chrome: a ajuda do cofre (13068232) já é a página de senhas; só os favoritos são conferidos.
            self.assertNotEqual(br.help_url(name, 'favoritos'), browser_vault.BROWSERS[name]['help'])

    def test_firefox_and_chrome_have_different_pages_per_step(self):
        for name in ('Google Chrome', 'Mozilla Firefox'):
            self.assertNotEqual(br.help_url(name, 'favoritos'), br.help_url(name, 'senhas'))

    def test_opera_has_no_link(self):
        for name in ('Opera', 'Opera GX', 'Brave', 'Vivaldi', 'Chromium', ''):
            for step in ('favoritos', 'senhas'):
                self.assertEqual(br.help_url(name, step), '')
        self.assertEqual(set(br.IMPORT_HELP), {'Google Chrome', 'Microsoft Edge', 'Mozilla Firefox'})

    def test_missing_help_texts(self):
        for name in ('Opera', 'Opera GX'):
            self.assertEqual(br.help_missing_text(name),
                             'Para o Opera e o Opera GX use os passos acima: não há página de ajuda '
                             'só sobre importar.')
        self.assertIn('sincronização', br.help_missing_text('Brave'))
        self.assertNotIn('Opera', br.help_missing_text('Brave'))

    def test_help_note_promises_button_only_where_it_opens_a_page(self):
        button = 'nesta janela, o botão "Ajuda oficial do navegador"'
        for name in ('Google Chrome', 'Microsoft Edge', 'Mozilla Firefox'):
            self.assertIn(button, br.bookmark_import_steps(name, 'x.html'))
            self.assertIn(button, br.password_import_steps(name))
        for name in ('Opera', 'Opera GX'):
            self.assertNotIn(button, br.bookmark_import_steps(name, 'x.html'))
            self.assertNotIn(button, br.password_import_steps(name))
            self.assertIn('procure por "importar" na ajuda', br.password_import_steps(name))

    def test_three_dots_spelled_out(self):
        for text in (br.password_import_steps('Microsoft Edge'), br.password_import_steps('Mozilla Firefox')):
            self.assertIn('botão de três pontos (...)', text)
            self.assertNotIn('"..."', text)


class UiSourceTests(unittest.TestCase):
    def setUp(self):
        self.src = (ROOT / 'browser_recovery_ui.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.src)

    def test_help_button_label_is_a_button_of_show_recovery(self):
        # R-81/R-74: o rótulo é conferido dentro da função que monta a tela, como text= de um Button.
        func = next(n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == 'show_recovery')
        labels = []
        for call in ast.walk(func):
            if isinstance(call, ast.Call) and getattr(call.func, 'attr', '') == 'Button' or \
                    isinstance(call, ast.Call) and getattr(call.func, 'id', '') == 'Button':
                for kw in call.keywords:
                    if kw.arg == 'text' and isinstance(kw.value, ast.Constant):
                        labels.append(kw.value.value)
        self.assertIn('Ajuda oficial do navegador', labels)
        self.assertNotIn('Ajuda oficial do Opera', labels)

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
        # 'No Opera escolhido' valia para qualquer destino; também some do módulo de textos.
        lib = (ROOT / 'browser_recovery.py').read_text(encoding='utf-8')
        self.assertNotIn('Ajuda oficial do Opera', lib)



# ---------------------------------------------------------------------------
# A tela (R-18): show_recovery roda com um tkinter falso, sem janela.
# ---------------------------------------------------------------------------
class _Var:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _Widget:
    registry = None

    def __init__(self, *args, **kw):
        self.kw = kw
        self.items = kw.get('values', [])
        self.sel = -1
        _Widget.registry.append(self)

    def current(self, index=None):
        if index is None:
            return self.sel
        self.sel = index

    def configure(self, *a, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


class _Top(_Widget):
    clip = None

    def clipboard_clear(self):
        _Top.clip = ''

    def clipboard_append(self, text):
        _Top.clip += text


def _load_screen():
    names = {}
    tk = types.ModuleType('tkinter')
    tk.Toplevel, tk.Text = _Top, _Widget
    tk.StringVar = tk.BooleanVar = _Var
    ttk = types.ModuleType('tkinter.ttk')
    for n in ('Frame', 'Label', 'Button', 'Checkbutton', 'Combobox'):
        setattr(ttk, n, type(n, (_Widget,), {}))
    dialogs = {}
    for n in ('filedialog', 'messagebox', 'simpledialog'):
        dialogs[n] = types.ModuleType('tkinter.' + n)
        setattr(tk, n, dialogs[n])
    tk.ttk = ttk
    stubs = {'tkinter': tk, 'tkinter.ttk': ttk, **{'tkinter.' + k: v for k, v in dialogs.items()}}
    # FIX-20261113-windows-tk: o tkinter de verdade (se já estava carregado) tem de voltar
    # para sys.modules no fim. Sem isso o próximo "import tkinter" carrega outra cópia do
    # módulo, que não conhece a janela principal aberta nem as classes dos widgets dela,
    # e os testes de tela seguintes falham ("no default root window", botão não achado).
    saved = {name: sys.modules[name] for name in stubs if name in sys.modules}
    before = set(sys.modules)
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location('_browser_recovery_ui_sem_tk', ROOT / 'browser_recovery_ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        fakes = set(map(id, stubs.values()))
        for name in set(sys.modules) - before:
            loaded = sys.modules.get(name)
            if name in stubs or any(id(value) in fakes for value in vars(loaded).values()):
                del sys.modules[name]  # o falso, e quem guardou o falso agora
        for name in stubs:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)
    return module, dialogs


class ScreenTests(unittest.TestCase):
    """Cliques nos botões reais da tela, com perfil, pasta e navegador falsos."""

    def run_screen(self, tmp, browser, pick_profile=True, protect=True):
        ui, dialogs = _load_screen()
        _Widget.registry = []
        _Top.clip = None
        root = _synthetic_recovery(tmp)
        out = Path(tmp) / 'saida'
        out.mkdir()
        profile = types.SimpleNamespace(browser=browser, label='Perfil', path=Path(tmp) / 'perfil-instalado')
        ui.discover_profiles = lambda: [profile] if pick_profile else []
        asked = iter([str(root), str(out)])
        dialogs['filedialog'].askdirectory = lambda *a, **k: next(asked)
        shown = []
        dialogs['messagebox'].showinfo = lambda title, text, **k: shown.append(('info', title, text))
        dialogs['messagebox'].showwarning = lambda title, text, **k: shown.append(('warn', title, text))
        dialogs['messagebox'].showerror = lambda title, text, **k: shown.append(('erro', title, text))
        opened = []
        ui.webbrowser = types.SimpleNamespace(open=opened.append)
        ui.show_recovery(types.SimpleNamespace(after=lambda ms, fn: fn()))
        buttons = {w.kw.get('text'): w.kw['command'] for w in _Widget.registry if 'command' in w.kw}
        combo = next(w for w in _Widget.registry if 'values' in w.kw)
        if pick_profile:
            combo.current(0)
        if protect:
            next(w for w in _Widget.registry if str(w.kw.get('text', '')).startswith('Já protegi')).kw['variable'].set(True)
        buttons['Usar pasta já recuperada']()
        return buttons, shown, opened

    def test_chrome_texts_on_screen_and_no_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            buttons, shown, opened = self.run_screen(tmp, 'Google Chrome')
            buttons['Preparar favoritos']()
            kind, title, text = shown[-1]
            self.assertEqual((kind, title), ('info', 'Importar favoritos'))
            self.assertIn('Arquivo HTML de favoritos', text)
            self.assertIn('Google Chrome', text)
            self.assertNotIn('Opera', text)
            self.assertTrue(_Top.clip.endswith('.html'))
            buttons['Orientar importação de senhas']()
            kind, title, text = shown[-1]
            self.assertEqual(title, 'Importar senhas')
            self.assertIn('No Google Chrome', text)
            self.assertIn('apague o CSV', text)
            self.assertNotIn('Opera', text)
            # o caminho copiado é o do CSV, e nem o aviso nem o caminho trazem a senha
            self.assertTrue(_Top.clip.endswith('senhas-exportadas.csv'))
            self.assertNotIn(FAKE_PASSWORD, text)
            self.assertNotIn(FAKE_PASSWORD, _Top.clip)
            # prova de que o teste enxerga a senha: ela existe no CSV sintético
            self.assertIn(FAKE_PASSWORD, Path(_Top.clip).read_text(encoding='utf-8'))
            self.assertEqual(opened, [])

    def test_firefox_and_edge_texts_on_screen(self):
        for browser, piece in (('Mozilla Firefox', 'Importar favoritos de HTML'),
                               ('Microsoft Edge', 'Importar dados do navegador')):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as tmp:
                buttons, shown, _ = self.run_screen(tmp, browser)
                buttons['Preparar favoritos']()
                self.assertIn(piece, shown[-1][2])

    def test_unsupported_browser_is_refused_on_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            buttons, shown, _ = self.run_screen(tmp, 'Brave')
            buttons['Preparar favoritos']()
            kind, title, text = shown[-1]
            self.assertEqual(title, 'Navegador sem passo a passo')
            self.assertIn('Mozilla Firefox', text)
            self.assertIn('apague o CSV', text)

    def test_help_button_opens_link_of_chosen_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            buttons, shown, opened = self.run_screen(tmp, 'Mozilla Firefox')
            buttons['Ajuda oficial do navegador']()
            self.assertEqual(opened, [br.IMPORT_HELP['Mozilla Firefox']['favoritos']])
            buttons['Orientar importação de senhas']()
            buttons['Ajuda oficial do navegador']()
            self.assertEqual(opened[-1], br.IMPORT_HELP['Mozilla Firefox']['senhas'])
            buttons['Preparar favoritos']()
            buttons['Ajuda oficial do navegador']()
            self.assertEqual(opened[-1], br.IMPORT_HELP['Mozilla Firefox']['favoritos'])

    def test_help_button_without_profile_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            buttons, shown, opened = self.run_screen(tmp, 'Google Chrome', pick_profile=False, protect=False)
            buttons['Ajuda oficial do navegador']()
            self.assertEqual(opened, [])
            self.assertEqual(shown[-1][1], 'Ajuda oficial')
            self.assertIn('Escolha um perfil', shown[-1][2])

    def test_help_button_opera_and_brave_explain_no_link(self):
        for browser, expected in (('Opera', br.NO_OPERA_HELP_TEXT),
                                  ('Opera GX', br.NO_OPERA_HELP_TEXT),
                                  ('Brave', br.NO_BROWSER_HELP_TEXT)):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as tmp:
                buttons, shown, opened = self.run_screen(tmp, browser)
                buttons['Ajuda oficial do navegador']()
                self.assertEqual(opened, [])
                self.assertEqual(shown[-1], ('info', 'Ajuda oficial', expected))
                self.assertNotIn('Escolha um perfil', shown[-1][2])


if __name__ == '__main__':
    unittest.main()
