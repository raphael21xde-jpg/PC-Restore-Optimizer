"""P4-01: confere o manual curto (docs/MANUAL.md).

Só lê arquivos do repositório (e um módulo sintético em TemporaryDirectory):
sem disco real, sem Tk e sem rodar o app.

R-61/R-62: um nome citado entre aspas no manual precisa ser rótulo (text=,
_nav_entry/_nav_action ou a lista de abas/etapas que a função usa) DENTRO da
função que monta a tela citada, e essa função precisa ser alcançável a partir
de App.__init__, seguindo chamadas e referências por nome com ``ast``.
Comentários, docstrings, funções nunca chamadas e as páginas escondidas
(abas do notebook sem menu) não contam; o que só é aberto a partir de uma página
escondida também não conta (as arestas dela não são seguidas).

Limite: o mapa UI_LABELS e a lista HIDDEN_BUILDERS são escritos à mão. O teste
não abre a interface; ele confia que a função do mapa é mesmo a da tela citada
no manual e que toda página escondida está em HIDDEN_BUILDERS. Uma página nova
escondida, ou um rótulo trocado de tela, precisa ser atualizado aqui à mão.

Outros dois limites conhecidos:
- aresta por atributo: ``algo.nome`` liga a TODOS os métodos chamados ``nome`` do
  mesmo módulo, de qualquer classe; um método de mesmo nome que outro realmente
  usado parece alcançável mesmo se nunca for chamado;
- ``_APP_DOES`` só pega os verbos e auxiliares da lista dele; uma frase com outro
  verbo ("o app limpa o disco") ou outra construção passa despercebida.
"""
import ast
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / 'docs' / 'MANUAL.md'
ROOTS = (('app.py', 'App.__init__'),)

REQUIRED_SECTIONS = (
    'O que o app faz',
    'Instalar e abrir',
    'Diagnóstico de discos',
    'Backup',
    'Testar e restaurar',
    'Reinstalação guiada',
    'Otimização',
    'Desfazer',
    'Check-up',
    'BIOS e drivers',
    'O que o app NUNCA faz',
)

SIDEBAR = ('app.py', 'App._build_sidebar')
REVIEW = ('app.py', 'App._build_review')
HISTORY = ('app.py', 'App._build_history')
RECOVERY = ('app.py', 'App._build_recovery')
DIAGNOSTIC = ('app.py', 'App._build_diagnostic')
OPT_TABS = ('optimization_ui.py', 'OptimizationPanel._build')
OPT_DIAG = ('optimization_ui.py', 'OptimizationPanel._build_diagnostics')
AFTER = ('after_format_ui.py', 'show_after_format')
INSTALL = ('workflow_ui.py', 'build_installation')

# Nome da tela citado no manual -> (módulo, função que monta a tela).
UI_LABELS = {
    # menu lateral
    'Visão geral': SIDEBAR,
    'Meu computador': SIDEBAR,
    'Preservação': SIDEBAR,
    'Instalar Windows': SIDEBAR,
    'Recuperação': SIDEBAR,
    'Depois de formatar': SIDEBAR,
    'Central de recuperação': SIDEBAR,
    'Cópia protegida para outro disco': SIDEBAR,
    'Otimização': SIDEBAR,
    'Diagnóstico': SIDEBAR,
    'Histórico e relatórios': SIDEBAR,
    # Diagnóstico
    'Analisar computador e discos': DIAGNOSTIC,
    'Simular destino de backup (somente leitura)': DIAGNOSTIC,
    'Conferir origens e destinos (somente leitura)': DIAGNOSTIC,
    'Exportar relatório JSON': DIAGNOSTIC,
    # backup
    'Examinar unidades marcadas': ('deep_discovery_ui.py', 'show_deep_discovery'),
    'Manter selecionados': ('deep_discovery_ui.py', 'show_deep_discovery'),
    'Não preservar': ('deep_discovery_ui.py', 'show_deep_discovery'),
    'Retirar do backup (não apaga)': ('workflow_ui.py', 'build_preservation'),
    'Próximo: revisar backup dos arquivos escolhidos →': ('workflow_ui.py', 'build_preservation'),
    'Escolher destino': REVIEW,
    '1. Recalcular plano e espaço': REVIEW,
    '2. Iniciar backup (confirmação dupla)': REVIEW,
    'Retomar backup interrompido': REVIEW,
    # testar e restaurar
    'Testar restauração de arquivo pequeno': HISTORY,
    'Escolher arquivo para testar': HISTORY,
    'Atualizar histórico': HISTORY,
    '5. Conferir TODO o backup (SHA-256)': RECOVERY,
    'Cancelar auditoria': RECOVERY,
    'Salvar relatório de auditoria': RECOVERY,
    'Colocar no lugar original': ('restore_ui.py', 'show_restore'),
    'Restaurar arquivos marcados para pasta nova': ('restore_ui.py', 'show_restore'),
    'Incluir arquivos de Program Files/ProgramData ao colocar no lugar original':
        ('restore_ui.py', 'show_restore'),
    'Restaurar navegador': ('browser_recovery_ui.py', 'show_recovery'),
    # reinstalação guiada
    'Revisar preservação': INSTALL,
    'Diagnóstico dos discos': INSTALL,
    'Recuperação depois do Windows': INSTALL,
    '1. Exportar plano para usar depois': RECOVERY,
    '2. Abrir plano após reinstalar': RECOVERY,
    'Conferir discos e letras': AFTER,
    'Restaurar os arquivos': AFTER,
    'Reinstalar os programas': AFTER,
    'Religar os launchers de jogos': AFTER,
    'Navegador e senhas': AFTER,
    'Abrir': AFTER,
    'Feito': AFTER,
    'Pular': AFTER,
    # otimização
    '1  Diagnóstico': OPT_TABS,
    '4  Energia reversível': OPT_TABS,
    '6  BIOS e drivers': OPT_TABS,
    '7  Alterações feitas': OPT_TABS,
    '8  Ajustes seguros': OPT_TABS,
    '9  Ajustes avançados': OPT_TABS,
    'Analisar este PC': OPT_DIAG,
    'Check-up de segurança': OPT_DIAG,
    'Ver passo a passo': OPT_DIAG,
    'Medir ANTES (1 min)': OPT_DIAG,
    'Medir DEPOIS (1 min)': OPT_DIAG,
    'Medir uso parado (2 min)': OPT_DIAG,
    'Ver estado atual': ('optimization_ui.py', 'OptimizationPanel._build_tweaks'),
    'Aplicar ajustes seguros': ('optimization_ui.py', 'OptimizationPanel._build_tweaks'),
    'Desfazer tudo': ('optimization_ui.py', 'OptimizationPanel._build_changes'),
    'Conferir de novo': ('optimization_ui.py', 'OptimizationPanel._build_changes'),
    'Desfazer alteração antiga': ('optimization_ui.py', 'OptimizationPanel._build_power'),
}

# Nomes do próprio Windows citados no manual -> módulo cujo texto de tela os cita.
WINDOWS_NAMES = {
    'Executar como administrador': 'optimization_ui.py',
    'Gerenciamento de Disco': 'after_format.py',
}

# Páginas do notebook escondido (Hidden.TNotebook) sem item no menu: hoje só se chega
# a elas por _build_legacy_home, que nunca é chamada (FIX-P4-01-02).
HIDDEN_BUILDERS = {
    ('app.py', 'App._build'),            # rótulos das abas escondidas
    ('app.py', 'App._build_catalog'),    # "Seleção avançada"
    ('app.py', 'App._build_inventory'),  # "Arquivos pessoais"
    ('app.py', 'App._build_browsers'),   # "Navegadores"
    ('app.py', 'App._build_legacy_home'),
}
# App._build só põe os rótulos das abas escondidas; as páginas que ele monta seguem
# pelas próprias funções. As outras páginas escondidas não abrem nada visível.
BLOCKED_EDGES = HIDDEN_BUILDERS - {('app.py', 'App._build')}

# Lado negativo da reinstalação guiada: sujeito, verbos auxiliares opcionais e o verbo.
_APP_DOES = re.compile(
    r'\b(o app|o aplicativo|ele)((?: (?:vai|pode|irá|ira|consegue|deve|precisa|tenta|'
    r'costuma|chega a|começa a|passa a))*)(?: a)? '
    r'(formata|formatar|formatará|particiona|particionar|instala|instalar|instalará|'
    r'apaga|apagar|apagará)\b')

_LABEL_CALLS = {'_nav_entry', '_nav_action'}


def _norm(text):
    """Junta espaços seguidos num só (as abas usam dois espaços: "8  Ajustes seguros")."""
    return re.sub(r'\s+', ' ', text).strip()


def _str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Module:
    def __init__(self, root, filename):
        self.filename = filename
        self.tree = ast.parse((Path(root) / filename).read_text(encoding='utf-8'))
        self.funcs, self.top, self.methods, self.consts, self.imports = {}, {}, {}, {}, {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                target = node.module.replace('.', '/') + '.py'
                if (Path(root) / target).is_file():
                    for alias in node.names:
                        self.imports[alias.asname or alias.name] = (target, alias.name)
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.consts[target.id] = node.value
        self._collect(self.tree.body, '', False)
        self.skip = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and _str(body[0].value) is not None:
                    self.skip.add(id(body[0].value))

    def _collect(self, body, prefix, in_class):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + node.name
                self.funcs[qual] = node
                if not prefix:
                    self.top[node.name] = qual
                if in_class:
                    self.methods.setdefault(node.name, []).append(qual)
                self._collect(node.body, qual + '.', False)
            elif isinstance(node, ast.ClassDef):
                qual = prefix + node.name
                if not prefix:
                    self.top[node.name] = qual + '.__init__'
                self._collect(node.body, qual + '.', True)
            else:
                for field in ('body', 'orelse', 'finalbody', 'handlers'):
                    self._collect(getattr(node, field, None) or [], prefix, in_class)

    def own_nodes(self, qual):
        """Corpo da função sem entrar nas funções internas (cada uma é um nó próprio)."""
        stack = list(self.funcs[qual].body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield node
            stack.extend(ast.iter_child_nodes(node))


class _Project:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.mods = {}

    def mod(self, filename):
        if filename not in self.mods:
            self.mods[filename] = _Module(self.root, filename)
        return self.mods[filename]

    def _resolve(self, mod, qual, name):
        if qual + '.' + name in mod.funcs:
            return [(mod.filename, qual + '.' + name)]
        if name in mod.top and mod.top[name] in mod.funcs:
            return [(mod.filename, mod.top[name])]
        if name in mod.imports:
            target, orig = mod.imports[name]
            other = self.mod(target)
            found = other.top.get(orig)
            return [(target, found)] if found in other.funcs else []
        return []

    def edges(self, filename, qual):
        mod = self.mod(filename)
        out = []
        for node in mod.own_nodes(qual):
            if isinstance(node, ast.Name):
                out += self._resolve(mod, qual, node.id)
            elif isinstance(node, ast.Attribute):
                out += [(filename, q) for q in mod.methods.get(node.attr, [])]
        return out

    def reachable(self, roots=ROOTS, blocked=()):
        """Funções alcançáveis; as de ``blocked`` entram no conjunto, mas o que só
        elas abrem não (página escondida não leva a lugar nenhum visível)."""
        seen, stack = set(), list(roots)
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                if node not in blocked:
                    stack.extend(self.edges(*node))
        return seen

    def _const_labels(self, value):
        text = _str(value)
        if text is not None:
            return {_norm(text)}
        found = set()
        if isinstance(value, (ast.Tuple, ast.List)):
            for elt in value.elts:
                if _str(elt) is not None:
                    found.add(_norm(_str(elt)))
                elif isinstance(elt, ast.Dict):
                    for key, val in zip(elt.keys, elt.values):
                        if key is not None and _str(key) == 'title' and _str(val) is not None:
                            found.add(_norm(_str(val)))
        return found

    def _name_labels(self, mod, name):
        if name in mod.consts:
            return self._const_labels(mod.consts[name])
        if name in mod.imports:
            target, orig = mod.imports[name]
            other = self.mod(target)
            if orig in other.consts:
                return self._const_labels(other.consts[orig])
        return set()

    def _value_labels(self, mod, node):
        if id(node) in mod.skip:
            return set()
        if _str(node) is not None:
            return {_norm(_str(node))}
        if isinstance(node, ast.Name):
            return self._name_labels(mod, node.id)
        return set()

    def labels(self, filename, qual):
        """Rótulos montados pela própria função: text=, _nav_entry/_nav_action,
        tuplas/listas do corpo dela e a lista de etapas que ela percorre (for)."""
        mod = self.mod(filename)
        found = set()
        for node in mod.own_nodes(qual):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == 'text':
                        found |= self._value_labels(mod, kw.value)
                name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
                if name in _LABEL_CALLS:
                    for arg in node.args:
                        found |= self._value_labels(mod, arg)
            elif isinstance(node, (ast.Tuple, ast.List)):
                for elt in node.elts:
                    if _str(elt) is not None and id(elt) not in mod.skip:
                        found.add(_norm(_str(elt)))
                    elif isinstance(elt, ast.Name) and _str(mod.consts.get(elt.id)) is not None:
                        found.add(_norm(_str(mod.consts[elt.id])))
            elif isinstance(node, ast.For):
                it = node.iter
                names = [it] if isinstance(it, ast.Name) else (
                    [a for a in it.args if isinstance(a, ast.Name)] if isinstance(it, ast.Call) else [])
                for name_node in names:
                    found |= self._name_labels(mod, name_node.id)
        return found

    def screen_strings(self, filename):
        mod = self.mod(filename)
        return [_norm(n.value) for n in ast.walk(mod.tree)
                if _str(n) is not None and id(n) not in mod.skip]


def _manual_text():
    return MANUAL.read_text(encoding='utf-8')


def _sections(text):
    """Devolve {título: corpo} das seções de nível ##."""
    found, current = {}, None
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return {title: '\n'.join(body) for title, body in found.items()}


def _section(text, start):
    for title, body in _sections(text).items():
        if title.startswith(start):
            return body
    raise AssertionError(f'seção "{start}" não encontrada')


def _paragraphs(text):
    return [p for p in re.split(r'\n\s*\n', text) if p.strip()]


def _quoted_names(text):
    """Nomes entre aspas retas "..." ou curvas “...”."""
    found = set()
    for straight, curly in re.findall(r'"([^"\n]+)"|“([^”\n]+)”', text):
        found.add(_norm(straight or curly))
    return found


class ScreenAnalyzerTests(unittest.TestCase):
    """O analisador, com um módulo sintético (nada do app real é tocado)."""

    SOURCE = (
        '"""Botão Só Na Docstring."""\n'
        '# Botão Só No Comentário\n'
        'AVISO = "Use o Botão Só No Meio do texto."\n'
        'ABA_LABEL = "Aba  Constante"\n'
        'ETAPAS = ({"id": "a", "title": "Etapa Da Lista"},)\n'
        'class App:\n'
        '    def __init__(self):\n'
        '        self._build_tela()\n'
        '    def _build_tela(self):\n'
        '        """Botão Só Na Docstring Da Função."""\n'
        '        ttk.Button(frame, text="Botão De Verdade")\n'
        '        for f, n in ((frame, "Aba  Da Tupla"), (frame, ABA_LABEL)):\n'
        '            pass\n'
        '        for numero, etapa in enumerate(ETAPAS, 1):\n'
        '            pass\n'
        '        def janela():\n'
        '            ttk.Button(frame, text="Botão Da Janela")\n'
        '        ttk.Button(frame, text="Abrir janela", command=janela)\n'
        '        def nunca_usada():\n'
        '            ttk.Button(frame, text="Botão Interno Morto")\n'
        '        self._build_escondida()\n'
        '    def _build_escondida(self):\n'
        '        def janela_escondida():\n'
        '            ttk.Button(frame, text="Botão Da Janela Escondida")\n'
        '        ttk.Button(frame, text="Abrir", command=janela_escondida)\n'
        '        ttk.Button(frame, text="Outra", command=lambda: so_da_escondida())\n'
        '    def _build_morta(self):\n'
        '        ttk.Button(frame, text="Botão Morto")\n'
        'def solta():\n'
        '    ttk.Button(frame, text="Botão Solto Morto")\n'
        'def so_da_escondida():\n'
        '    ttk.Button(frame, text="Botão Só Da Página Escondida")\n'
        'SOLTOS = ("Texto Numa Tupla Do Módulo",)\n')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, 'tela.py').write_text(self.SOURCE, encoding='utf-8')
        self.project = _Project(self.tmp.name)
        self.reach = self.project.reachable((('tela.py', 'App.__init__'),))

    def tearDown(self):
        self.tmp.cleanup()

    def test_labels_inside_the_function(self):
        labels = self.project.labels('tela.py', 'App._build_tela')
        for name in ('Botão De Verdade', 'Aba Da Tupla', 'Aba Constante', 'Etapa Da Lista',
                     'Abrir janela'):
            self.assertIn(name, labels)
        for name in ('Botão Só Na Docstring.', 'Botão Só No Comentário', 'Botão Só No Meio',
                     'Botão Só Na Docstring Da Função.', 'Botão Da Janela',
                     'Texto Numa Tupla Do Módulo', 'Botão Morto'):
            self.assertNotIn(name, labels)

    def test_only_called_functions_are_reachable(self):
        self.assertIn(('tela.py', 'App._build_tela'), self.reach)
        self.assertIn(('tela.py', 'App._build_tela.janela'), self.reach)
        for dead in ('App._build_morta', 'solta', 'App._build_tela.nunca_usada'):
            self.assertNotIn(('tela.py', dead), self.reach)

    def test_label_in_never_called_function_does_not_count(self):
        hits = {lab for node in self.reach for lab in self.project.labels(*node)}
        self.assertIn('Botão Da Janela', hits)
        for dead in ('Botão Morto', 'Botão Solto Morto', 'Botão Interno Morto'):
            self.assertNotIn(dead, hits)

    def test_window_opened_only_by_hidden_page_does_not_count(self):
        hidden = ('tela.py', 'App._build_escondida')
        reach = self.project.reachable((('tela.py', 'App.__init__'),), blocked={hidden})
        self.assertIn(hidden, reach)
        self.assertNotIn(('tela.py', 'App._build_escondida.janela_escondida'), reach)
        self.assertNotIn(('tela.py', 'so_da_escondida'), reach)
        hits = {lab for node in reach for lab in self.project.labels(*node)}
        self.assertNotIn('Botão Da Janela Escondida', hits)
        self.assertNotIn('Botão Só Da Página Escondida', hits)
        # Sem o bloqueio, a janela seria alcançável: o bloqueio é que a tira.
        self.assertIn(('tela.py', 'so_da_escondida'), self.reach)

    def test_app_does_regex_catches_auxiliary_verbs(self):
        for bad in ('o app formata o disco', 'O app vai formatar o C:', 'o app pode apagar',
                    'ele irá instalar o Windows', 'o aplicativo consegue particionar',
                    'o app vai a apagar'):
            self.assertIsNotNone(_APP_DOES.search(bad.lower()), bad)
        for ok in ('o app não formata', 'o app nunca apaga', 'ele só orienta',
                   'o app guarda o antigo'):
            self.assertIsNone(_APP_DOES.search(ok), ok)

    def test_curly_quotes_are_extracted(self):
        self.assertEqual(_quoted_names('clique em “Abrir” e em "Feito"'), {'Abrir', 'Feito'})


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = _Project()
        cls.reach = cls.project.reachable(blocked=BLOCKED_EDGES)

    def test_manual_exists_and_is_short(self):
        self.assertTrue(MANUAL.is_file())
        self.assertLessEqual(len(_manual_text().splitlines()), 260)

    def test_every_quoted_ui_name_exists_in_code(self):
        quoted = _quoted_names(_manual_text())
        self.assertGreater(len(quoted), 20)
        known = {_norm(k) for k in UI_LABELS} | {_norm(k) for k in WINDOWS_NAMES}
        self.assertEqual(sorted(quoted - known), [],
                         'nome entre aspas no manual sem tela no mapa do teste')
        for name, screen in UI_LABELS.items():
            if _norm(name) not in quoted:
                continue
            with self.subTest(name=name, screen=screen):
                self.assertNotIn(screen, HIDDEN_BUILDERS)
                self.assertIn(screen, self.reach, f'{screen} não é alcançável')
                self.assertIn(_norm(name), self.project.labels(*screen),
                              f'"{name}" não é rótulo da tela {screen}')
        for name, filename in WINDOWS_NAMES.items():
            if _norm(name) not in quoted:
                continue
            with self.subTest(name=name, file=filename):
                self.assertTrue(any(_norm(name) in s for s in self.project.screen_strings(filename)),
                                f'"{name}" não aparece nos textos de tela de {filename}')

    def test_hidden_pages_are_really_unreachable_or_hidden(self):
        # Se o FIX-P4-01-02 ligar essas páginas ao menu, este teste avisa para rever o manual.
        self.assertNotIn(('app.py', 'App._build_legacy_home'), self.reach)
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("self.style.layout('Hidden.TNotebook.Tab', [])", app_source)
        sidebar = self.project.labels(*SIDEBAR)
        for page in ('Seleção avançada', 'Arquivos pessoais', 'Navegadores'):
            self.assertNotIn(page, sidebar)
            self.assertNotIn(page, _quoted_names(_manual_text()))

    def test_undo_without_admin_mentions_machine_wide_exception(self):
        # R-60: "Desfazer tudo ... sem administrador" precisa trazer a exceção no mesmo trecho.
        text = _manual_text()
        hits = [p for p in _paragraphs(text) if 'Desfazer tudo' in p and 'sem administrador' in p]
        self.assertTrue(hits, 'o manual deveria explicar quando "Desfazer tudo" pede administrador')
        for paragraph in hits:
            flat = _norm(paragraph)
            with self.subTest(paragraph=flat[:60]):
                self.assertIn('9 Ajustes avançados', flat)
                self.assertIn('computador todo', flat)
                self.assertIn('como administrador', flat)
                self.assertIn('reiniciar', flat)
        undo = _norm(_section(text, 'Desfazer'))
        self.assertIn('para nesse item', undo)
        self.assertIn('Desfazer alteração antiga', undo)
        self.assertNotIn('tudo pode ser desfeito', _norm(text).lower())

    def test_has_required_sections(self):
        titles = list(_sections(_manual_text()))
        for wanted in REQUIRED_SECTIONS:
            with self.subTest(section=wanted):
                self.assertTrue(any(t.startswith(wanted) for t in titles),
                                f'falta a seção "## {wanted}"')
        self.assertEqual(len(titles), len(REQUIRED_SECTIONS))

    def test_no_user_paths_or_personal_data(self):
        text = _manual_text()
        lowered = text.lower()
        self.assertIsNone(re.search(r'[a-z]:\\users\\', lowered))
        self.assertIsNone(re.search(r'[a-z]:/users/', lowered))
        self.assertNotIn('/home/', lowered)
        self.assertNotIn('preferencias-v05.json', lowered)
        self.assertNotIn('raphael', lowered)
        self.assertIsNone(re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text))
        for word in ('token', 'senha:', 'password', 'ghp_', 'sk-'):
            self.assertNotIn(word, lowered)

    def test_never_section_lists_forbidden_actions(self):
        body = _section(_manual_text(), 'O que o app NUNCA faz').lower()
        for word in ('formata', 'particiona', 'apaga', 'efi', 'bcd', 'instala o windows',
                     'defender', 'windows update', 'debloat', 'bios'):
            with self.subTest(word=word):
                self.assertIn(word, body)

    def test_reinstall_is_guided(self):
        text = _manual_text()
        body = _section(text, 'Reinstalação guiada')
        self.assertIn('instalador oficial', body)
        self.assertIn('Microsoft', body)
        # Lado negativo: fora da seção NUNCA, nenhuma frase diz que o app formata ou instala.
        never = _section(text, 'O que o app NUNCA faz')
        rest = _norm(text.replace(never, '').replace('*', '')).lower()
        self.assertIsNone(_APP_DOES.search(rest), _APP_DOES.search(rest) and
                          rest[max(0, _APP_DOES.search(rest).start() - 40):][:120])

    def test_backup_confirmation_matches_the_app(self):
        # R-31/R-63: begin_backup faz uma pergunta só; o botão liga depois do passo 1.
        flat = _norm(_manual_text()).lower()
        for wrong in ('pergunta duas vezes', 'duas perguntas', 'pergunta 2 vezes'):
            self.assertNotIn(wrong, flat)
        backup = _norm(_section(_manual_text(), 'Backup'))
        self.assertIn('só liga depois desse passo 1', backup)
        self.assertIn('pergunta se pode começar', backup)
        resume = [p for p in re.split(r'\n(?=\d\. )', _section(_manual_text(), 'Backup'))
                  if 'Retomar backup interrompido' in p]
        self.assertTrue(resume)
        for item in resume:
            self.assertIn('1. Recalcular plano e espaço', _norm(item))

    def test_browser_restore_states_its_limits(self):
        # R-64: o assistente só aceita o cofre do app e só orienta Opera / Opera GX.
        blocks = [_norm(b) for b in re.split(r'\n\s*\n|\n(?=\d\. )', _manual_text())]
        hits = [b for b in blocks if 'Restaurar navegador' in b]
        self.assertTrue(hits)
        for block in hits:
            with self.subTest(block=block[:60]):
                for needed in ('Opera', 'Opera GX', '.pcbrowser', 'CONFERIR-NAVEGADOR',
                               'sincronização', 'apague o CSV'):
                    self.assertIn(needed, block)
        self.assertNotIn('ajuda a trazer favoritos e senhas', _norm(_manual_text()))

    def test_backup_copies_only_the_windows_disk(self):
        backup = _norm(_section(_manual_text(), 'Backup'))
        self.assertIn('só o que você marcar no disco do Windows (C:)', backup)
        self.assertIn('Os outros discos ficam onde estão', backup)

    def test_install_disk_check_uses_what_the_installer_shows(self):
        # R-63: o instalador mostra número do disco e GB, nunca o modelo; o app mostra bytes.
        body = _section(_manual_text(), 'Reinstalação guiada')
        items = [_norm(p) for p in re.split(r'\n(?=- )|\n\s*\n', body)]
        compare = [p for p in items if 'instalador' in p and ('anote' in p or 'confira' in p.lower()
                                                               or 'comparar' in p)]
        self.assertTrue(compare)
        for item in compare:
            self.assertNotIn('modelo', item.lower())
        flat = _norm(body)
        for needed in ('bytes', '1.073.741.824', 'GB', 'não é garantido', 'desconecte o disco do backup',
                       'fora da tomada', 'cancele a instalação', 'Boot=True', 'System=True',
                       'abrir o gabinete', 'Conferir discos e letras',
                       'param de achar os arquivos', 'troque de novo para a letra antiga'):
            self.assertIn(needed, flat)

    def test_protected_copy_not_presented_as_ready(self):
        paragraphs = [_norm(p) for p in _paragraphs(_manual_text())
                      if 'Cópia protegida para outro disco' in p]
        self.assertTrue(paragraphs)
        for paragraph in paragraphs:
            with self.subTest(paragraph=paragraph[:60]):
                self.assertIn('ainda em teste', paragraph)

    def test_readme_links_manual(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('docs/MANUAL.md', readme)


if __name__ == '__main__':
    unittest.main()
