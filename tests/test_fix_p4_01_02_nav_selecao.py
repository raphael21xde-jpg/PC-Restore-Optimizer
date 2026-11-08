"""FIX-P4-01-02: "Seleção avançada" no menu lateral (R-62).

Lê app.py com ``ast`` e roda só App._page_changed e App.navigate com objetos
falsos: sem Tk, sem disco real e sem abrir o app. Também confere o trecho do
manual sobre "Seleção avançada" (botão na aba certa e passos do navegador).
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app.py'
MANUAL = ROOT / 'docs' / 'MANUAL.md'


def _app_class():
    tree = ast.parse(APP.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'App':
            return node
    raise AssertionError('classe App não encontrada')


def _method(name):
    for node in _app_class().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'método {name} não encontrado')


def _nav_entries():
    """(chave, símbolo, rótulo) de cada self._nav_entry(...) em _build_sidebar."""
    found = []
    for node in ast.walk(_method('_build_sidebar')):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == '_nav_entry'):
            found.append(tuple(arg.value for arg in node.args))
    return found


def _page_map_keys():
    for node in ast.walk(_method('_page_changed')):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == 'page_map' for t in node.targets)):
            return {key.value for key in node.value.keys}
    raise AssertionError('page_map não encontrado em _page_changed')


def _texts(name):
    texts = set()
    for node in ast.walk(_method(name)):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == 'text' and isinstance(keyword.value, ast.Constant):
                    texts.add(keyword.value.value)
    return texts


def _load_method(name, namespace=None):
    """Compila só o método ``name`` de App, como função solta."""
    module = ast.Module(body=[_method(name)], type_ignores=[])
    namespace = dict(namespace or {})
    exec(compile(module, str(APP), 'exec'), namespace)
    return namespace[name]


def _load_page_changed():
    """Compila só App._page_changed, com as cores como nomes falsos."""
    func = _method('_page_changed')
    module = ast.Module(body=[func], type_ignores=[])
    namespace = {'HOVER': 'hover', 'SIDEBAR': 'sidebar', 'ACCENT': 'accent',
                 'TEXT': 'text', 'MUTED': 'muted'}
    exec(compile(module, str(APP), 'exec'), namespace)
    return namespace['_page_changed']


class _Widget:
    def __init__(self, name='w'):
        self.name = name
        self.options = {}

    def configure(self, **options):
        self.options.update(options)

    def __str__(self):
        return '.' + self.name


class _Var:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _Tabs:
    def __init__(self, selected):
        self.selected = selected

    def select(self):
        return str(self.selected)


class _FakeApp:
    def __init__(self, keys, selected_key):
        self.nav_buttons = {}
        for key in keys:
            setattr(self, key, _Widget(key))
            self.nav_buttons[key] = (_Widget(), _Widget(), _Widget())
        for extra in ('review', 'catalog', 'home', 'preservation'):
            if not hasattr(self, extra):
                setattr(self, extra, _Widget(extra))
        self.tabs = _Tabs(getattr(self, selected_key))
        self.page_eyebrow, self.page_title, self.page_description = _Var(), _Var(), _Var()
        self.metrics_refreshed = False

    def _refresh_home_metrics(self):
        self.metrics_refreshed = True


class SelecaoAvancadaNoMenuTests(unittest.TestCase):
    def test_sidebar_has_catalog_entry_after_preservation(self):
        entries = _nav_entries()
        keys = [entry[0] for entry in entries]
        self.assertIn('catalog', keys)
        catalog = entries[keys.index('catalog')]
        self.assertEqual(catalog[2], 'Seleção avançada')
        self.assertEqual(keys.index('catalog'), keys.index('preservation') + 1)
        self.assertEqual(keys.count('catalog'), 1, 'só uma entrada no menu')

    def test_every_nav_entry_has_page_map_entry(self):
        missing = {entry[0] for entry in _nav_entries()} - _page_map_keys()
        self.assertEqual(missing, set(), 'chave do menu sem entrada no page_map (KeyError)')

    def test_page_changed_on_catalog_highlights_item_without_keyerror(self):
        keys = [entry[0] for entry in _nav_entries()]
        fake = _FakeApp(keys, 'catalog')
        _load_page_changed()(fake)
        holder, stripe, label = fake.nav_buttons['catalog']
        self.assertEqual(stripe.options['bg'], 'accent')
        self.assertEqual(label.options['fg'], 'text')
        self.assertEqual(label.options['font'][2], 'bold')
        for key in keys:
            if key != 'catalog':
                self.assertEqual(fake.nav_buttons[key][1].options['bg'], 'sidebar', key)
        self.assertEqual(fake.page_title.value, 'Escolher jogos, apps, arquivos e navegadores')
        self.assertTrue(fake.metrics_refreshed)

    def test_review_page_keeps_its_header(self):
        keys = [entry[0] for entry in _nav_entries()]
        fake = _FakeApp(keys, 'review')
        _load_page_changed()(fake)
        self.assertEqual(fake.page_title.value, 'Ferramentas de backup e seleção')

    def test_catalog_buttons_open_files_and_browsers(self):
        texts = _texts('_build_catalog')
        for label in ('+ Arquivo ou pasta', 'Navegadores  →', 'Arquivos pessoais', 'Navegadores'):
            self.assertIn(label, texts)
        self.assertIn('Criar backup protegido do navegador', _texts('_build_browsers'))

    def test_tabs_hold_the_pages_the_manual_cites(self):
        # "Arquivos pessoais" é a página _build_inventory; "Navegadores", a _build_browsers.
        tabs = {}
        for node in ast.walk(_method('_build_catalog')):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add' and node.args
                    and isinstance(node.args[0], ast.Attribute)):
                for keyword in node.keywords:
                    if keyword.arg == 'text':
                        tabs[keyword.value.value] = node.args[0].attr
        self.assertEqual(tabs.get('Arquivos pessoais'), 'inventory')
        self.assertEqual(tabs.get('Navegadores'), 'browsers')
        inventory = _texts('_build_inventory')
        for label in ('+ Adicionar pasta', '+ Adicionar arquivo'):
            self.assertIn(label, inventory)
        browsers = _texts('_build_browsers')
        for label in ('Pesquisar perfis', 'Criar backup protegido do navegador'):
            self.assertIn(label, browsers)

    def test_manual_cites_buttons_in_the_right_tab_and_the_steps(self):
        text = ' '.join(MANUAL.read_text(encoding='utf-8').split())
        start = text.index('**Outros arquivos e navegadores.**')
        block = text[start:text.index('## ', start)]
        files_part = block[block.index('"Arquivos pessoais"'):block.index('"Navegadores"')]
        self.assertIn('"+ Adicionar pasta"', files_part)
        self.assertIn('"+ Adicionar arquivo"', files_part)
        browser_part = block[block.index('"Navegadores"'):]
        for needed in ('"Pesquisar perfis"', 'sincronização', 'feche o navegador',
                       '"Criar backup protegido do navegador"', 'frase-senha',
                       '"Escolher destino"', 'fora do C:', 'unidade do perfil'):
            self.assertIn(needed, browser_part)
        # A barra com estes botões some nas abas "Arquivos pessoais" e "Navegadores".
        self.assertNotIn('+ Arquivo ou pasta', block)
        self.assertNotIn('Navegadores →', block)
        self.assertNotIn('Nela', block)

    def test_navigate_sends_files_and_browsers_into_catalog(self):
        # Roda App.navigate de verdade, com abas falsas (sem Tk).
        navigate = _load_method('navigate')

        class _Notebook:
            def __init__(self):
                self.chosen = []

            def select(self, page=None):
                if page is None:
                    return self.chosen[-1] if self.chosen else None
                self.chosen.append(page)

        class _Fake:
            pass

        fake = _Fake()
        for name in ('catalog', 'inventory', 'browsers', 'overview'):
            setattr(fake, name, _Widget(name))
        fake.tabs = _Notebook()
        fake.catalog_tabs = _Notebook()
        fake.changed = 0
        fake._page_changed = lambda: setattr(fake, 'changed', fake.changed + 1)

        for page in (fake.inventory, fake.browsers):
            navigate(fake, page)
            self.assertIs(fake.tabs.select(), fake.catalog)
            self.assertIs(fake.catalog_tabs.select(), page)
        navigate(fake, fake.overview)
        self.assertIs(fake.tabs.select(), fake.overview)
        self.assertEqual(fake.catalog_tabs.chosen, [fake.inventory, fake.browsers])
        self.assertEqual(fake.changed, 3)


if __name__ == '__main__':
    unittest.main()
