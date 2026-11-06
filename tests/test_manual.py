"""P4-01: confere o manual curto (docs/MANUAL.md).

Só lê arquivos do repositório: sem disco real, sem Tk e sem rodar o app.

R-61: um nome citado entre aspas no manual precisa existir como rótulo (texto
de botão, aba, menu ou título de etapa) no módulo da tela citada, nunca só como
pedaço de texto em qualquer .py. Os rótulos são lidos com ``ast``, então
comentários e docstrings não contam.
"""
import ast
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / 'docs' / 'MANUAL.md'

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

# Nome da tela do app citado no manual -> módulo onde ele é rótulo.
UI_LABELS = {
    # menu lateral e páginas
    'Visão geral': 'app.py',
    'Meu computador': 'app.py',
    'Preservação': 'app.py',
    'Instalar Windows': 'app.py',
    'Recuperação': 'app.py',
    'Depois de formatar': 'app.py',
    'Central de recuperação': 'app.py',
    'Cópia protegida para outro disco': 'app.py',
    'Otimização': 'app.py',
    'Diagnóstico': 'app.py',
    'Histórico e relatórios': 'app.py',
    'Seleção avançada': 'app.py',
    'Arquivos pessoais': 'app.py',
    'Navegadores': 'app.py',
    # Diagnóstico
    'Analisar computador e discos': 'app.py',
    'Simular destino de backup (somente leitura)': 'app.py',
    'Conferir origens e destinos (somente leitura)': 'app.py',
    'Exportar relatório JSON': 'app.py',
    # backup
    'Examinar unidades marcadas': 'deep_discovery_ui.py',
    'Manter selecionados': 'deep_discovery_ui.py',
    'Não preservar': 'deep_discovery_ui.py',
    'Começar pela detecção  →': 'app.py',
    'Manter': 'app.py',
    'Não incluir no backup': 'app.py',
    'Pendente': 'app.py',
    'Retirar do backup (não apaga)': 'workflow_ui.py',
    'Criar backup protegido do navegador': 'app.py',
    'Revisar o plano': 'app.py',
    'Escolher destino': 'app.py',
    '1. Recalcular plano e espaço': 'app.py',
    '2. Iniciar backup (confirmação dupla)': 'app.py',
    'Retomar backup interrompido': 'app.py',
    # testar e restaurar
    'Testar restauração de arquivo pequeno': 'app.py',
    '5. Conferir TODO o backup (SHA-256)': 'app.py',
    'Cancelar auditoria': 'app.py',
    'Salvar relatório de auditoria': 'app.py',
    'Restaurar navegador — assistente': 'app.py',
    'Escolher arquivo para testar': 'app.py',
    'Colocar no lugar original': 'restore_ui.py',
    # reinstalação guiada
    'Revisar preservação': 'workflow_ui.py',
    'Diagnóstico dos discos': 'workflow_ui.py',
    'Recuperação depois do Windows': 'workflow_ui.py',
    '1. Exportar plano para usar depois': 'app.py',
    'Conferir discos e letras': 'after_format.py',
    'Restaurar os arquivos': 'after_format.py',
    'Reinstalar os programas': 'after_format.py',
    'Religar os launchers de jogos': 'after_format.py',
    'Navegador e senhas': 'after_format.py',
    'Abrir': 'after_format_ui.py',
    'Feito': 'after_format_ui.py',
    'Pular': 'after_format_ui.py',
    # otimização
    '1  Diagnóstico': 'optimization_ui.py',
    '4  Energia reversível': 'optimization_ui.py',
    '6  BIOS e drivers': 'optimization_ui.py',
    '7  Alterações feitas': 'optimization_ui.py',
    '8  Ajustes seguros': 'optimization_ui.py',
    '9  Ajustes avançados': 'optimization_ui.py',
    'Analisar este PC': 'optimization_ui.py',
    'Check-up de segurança': 'optimization_ui.py',
    'Ver passo a passo': 'optimization_ui.py',
    'Ver estado atual': 'optimization_ui.py',
    'Aplicar ajustes seguros': 'optimization_ui.py',
    'Medir ANTES (1 min)': 'optimization_ui.py',
    'Medir DEPOIS (1 min)': 'optimization_ui.py',
    'Medir uso parado (2 min)': 'optimization_ui.py',
    'Desfazer tudo': 'optimization_ui.py',
    'Conferir de novo': 'optimization_ui.py',
    'Desfazer alteração antiga': 'optimization_ui.py',
}

# Nomes do próprio Windows citados no manual -> módulo cujo texto de tela os cita.
WINDOWS_NAMES = {
    'Executar como administrador': 'optimization_ui.py',
    'Gerenciamento de Disco': 'after_format.py',
}

# Rótulos guardados em constante: só contam nomes com estes finais.
_LABEL_NAME_ENDS = ('_LABEL', '_TEXT', '_TITLE')
_NAV_CALLS = {'_nav_entry', '_nav_action'}


def _norm(text):
    """Junta espaços seguidos num só (as abas usam dois espaços: "8  Ajustes seguros")."""
    return re.sub(r'\s+', ' ', text).strip()


def _manual_text():
    return MANUAL.read_text(encoding='utf-8')


def _sections(text):
    """Devolve {título: corpo} das seções de nível ##."""
    found = {}
    current = None
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


def _str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _docstring_nodes(tree):
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and _str(body[0].value) is not None:
                skip.add(id(body[0].value))
    return skip


def _labels(filename, root=ROOT):
    """Rótulos de tela de um módulo: text='...', tuplas/listas de rótulos,
    _nav_entry/_nav_action, 'title' de etapas e constantes *_LABEL/*_TEXT/*_TITLE."""
    tree = ast.parse((Path(root) / filename).read_text(encoding='utf-8'))
    skip = _docstring_nodes(tree)
    found = set()

    def add(node):
        value = _str(node)
        if value is not None and id(node) not in skip:
            found.add(_norm(value))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'text':
                    add(kw.value)
            func = node.func
            name = getattr(func, 'attr', None) or getattr(func, 'id', None)
            if name in _NAV_CALLS:
                for arg in node.args:
                    add(arg)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                add(elt)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is not None and _str(key) == 'title':
                    add(value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith(_LABEL_NAME_ENDS):
                    add(node.value)
    return found


def _screen_strings(filename):
    """Todos os textos de um módulo, sem docstrings (comentários não entram no ast)."""
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    skip = _docstring_nodes(tree)
    return [_norm(n.value) for n in ast.walk(tree)
            if _str(n) is not None and id(n) not in skip]


def _quoted_names(text):
    return {_norm(q) for q in re.findall(r'"([^"\n]+)"', text)}


class ManualTests(unittest.TestCase):
    def test_manual_exists_and_is_short(self):
        self.assertTrue(MANUAL.is_file())
        self.assertLessEqual(len(_manual_text().splitlines()), 260)

    def test_every_quoted_ui_name_exists_in_code(self):
        quoted = _quoted_names(_manual_text())
        self.assertGreater(len(quoted), 20)
        known = {_norm(k) for k in UI_LABELS} | {_norm(k) for k in WINDOWS_NAMES}
        self.assertEqual(sorted(quoted - known), [],
                         'nome entre aspas no manual sem módulo de tela no mapa do teste')
        cache = {}
        for name, filename in UI_LABELS.items():
            if _norm(name) not in quoted:
                continue
            labels = cache.setdefault(filename, _labels(filename))
            with self.subTest(name=name, file=filename):
                self.assertIn(_norm(name), labels,
                              f'"{name}" não é rótulo de tela em {filename}')
        for name, filename in WINDOWS_NAMES.items():
            if _norm(name) not in quoted:
                continue
            with self.subTest(name=name, file=filename):
                self.assertTrue(any(_norm(name) in s for s in _screen_strings(filename)),
                                f'"{name}" não aparece nos textos de tela de {filename}')

    def test_label_check_ignores_comments_docstrings_and_fragments(self):
        # Trava da R-61, com um módulo sintético (nada do app real é mudado).
        source = (
            '"""Botão Só Na Docstring."""\n'
            '# Botão Só No Comentário\n'
            'AVISO = "Use o Botão Só No Meio do texto."\n'
            'X_LABEL = "Aba  Constante"\n'
            'def build(ttk, frame):\n'
            '    """Botão Só Na Docstring Da Função."""\n'
            '    ttk.Button(frame, text="Botão De Verdade")\n'
            '    for f, n in ((frame, "Aba  Da Tupla"),):\n'
            '        pass\n')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'tela.py').write_text(source, encoding='utf-8')
            labels = _labels('tela.py', root=tmp)
        for name in ('Botão De Verdade', 'Aba Constante', 'Aba Da Tupla'):
            self.assertIn(name, labels)
        for name in ('Botão Só Na Docstring.', 'Botão Só No Comentário', 'Botão Só No Meio',
                     'Botão Só Na Docstring Da Função.'):
            self.assertNotIn(name, labels)
        # E um nome de tela conferido no arquivo errado não passa.
        self.assertNotIn('Manter selecionados', _labels('app.py'))

    def test_undo_without_admin_mentions_machine_wide_exception(self):
        # R-60: "Desfazer tudo ... sem administrador" precisa trazer a exceção no mesmo trecho.
        text = _manual_text()
        hits = [p for p in _paragraphs(text)
                if 'Desfazer tudo' in p and 'sem administrador' in p]
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
        self.assertIsNone(
            re.search(r'\b(o app|ele) (formata|particiona|instala|apaga)\b', rest))

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
