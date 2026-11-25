"""P4-02 (Fatia 1): testes do módulo puro `first_use.py` (100% sem tkinter).

Confere:
1. Importação e execução sem `tkinter`.
2. Textos conforme R-88 (sem "C:" fixo no código, sem "não mexe", "intactos" ou
   "só grava", e com o aviso de que o app não apaga nenhum arquivo e de que o
   que não for copiado do disco do Windows se perde na formatação).
3. Todos os nomes de telas, abas e botões citados entre aspas existem de verdade
   nas funções que montam essas telas (conferidos com `ast`, R-62 / R-74).
4. Persistência segura das marcações (`pendente`, `feito`, `pulado`) em
   `TemporaryDirectory`, incluindo arquivo corrompido, grande demais, link/atalho,
   mensagens sem caminho completo (R-07) e `FirstUseProgressSaver` em segundo
   plano com espera via `addCleanup` antes de remover a pasta temporária (R-29).
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_use as fu
from tests.test_manual import BLOCKED_EDGES, _Project, _norm, _quoted_names

ROOT = Path(__file__).resolve().parents[1]
NO_TK_CHILD_ENV = 'PCRO_FIRST_USE_NO_TK_CHILD'

FORBIDDEN_R88 = (
    'não mexe',
    'nao mexe',
    'intactos',
    'intacto',
    'intactas',
    'intacta',
    'só grava',
    'so grava',
)

OLD_TEXTS = (
    'Conhecer os discos (só leitura)',
    'Conhecer os discos (a análise só lê)',
    'O guia só orienta',
    # R-88: a restauração não grava "nas pastas que você indicar"; o .antes-pcro
    # é do "Colocar no lugar original" (revisão da PR #284 @524c34f135fe).
    'na restauração, nas pastas que você indicar',
    # Revisão da PR #293 @9936711e5d86: a janela não tem "feche e abra o guia";
    # o gravador continua no app, então o que se perde é ao fechar o app; e o
    # aviso de fechar não promete que a gravação deu certo.
    'se você fechar a janela antes disso',
    'feche e abra o guia',
    'termina de salvar',
    # Revisão da PR #293 @fd406e7977f4: o aviso de fechar diz o que acontece agora.
    'continua tentando',
)

# Mapa dos rótulos entre aspas citados em first_use.py -> (módulo, função que monta a tela)
EXPECTED_STEP_LABELS = {
    'Diagnóstico': ('app.py', 'App._build_sidebar'),
    'Exportar relatório JSON': ('app.py', 'App._build_diagnostic'),
    'Meu computador': ('app.py', 'App._build_sidebar'),
    'Manter selecionados': ('deep_discovery_ui.py', 'show_deep_discovery'),
    'Não preservar': ('deep_discovery_ui.py', 'show_deep_discovery'),
    'Seleção avançada': ('app.py', 'App._build_sidebar'),
    'Preservação': ('app.py', 'App._build_sidebar'),
    'Próximo: revisar backup dos arquivos escolhidos →': (
        'workflow_ui.py',
        'build_preservation',
    ),
    'Escolher destino': ('app.py', 'App._build_review'),
    '1. Recalcular plano e espaço': ('app.py', 'App._build_review'),
    '2. Iniciar backup (confirmação dupla)': ('app.py', 'App._build_review'),
    'Histórico e relatórios': ('app.py', 'App._build_sidebar'),
    'Testar restauração de arquivo pequeno': ('app.py', 'App._build_history'),
    'Instalar Windows': ('app.py', 'App._build_sidebar'),
    'Depois de formatar': ('app.py', 'App._build_sidebar'),
    'Otimização': ('app.py', 'App._build_sidebar'),
    '4  Energia reversível': ('optimization_ui.py', 'OptimizationPanel._build'),
    '7  Alterações feitas': ('optimization_ui.py', 'OptimizationPanel._build'),
    '8  Ajustes seguros': ('optimization_ui.py', 'OptimizationPanel._build'),
    '9  Ajustes avançados': ('optimization_ui.py', 'OptimizationPanel._build'),
    'Desfazer tudo': ('optimization_ui.py', 'OptimizationPanel._build_changes'),
    'Colocar no lugar original': ('restore_ui.py', 'show_restore'),
    # Fatia 2: botão da própria janela do Primeiro uso guiado (R-62/R-74).
    'Abrir': ('first_use_ui.py', 'show_first_use'),
    'Fechar': ('first_use_ui.py', 'show_first_use'),
    'Primeiro uso guiado': ('app.py', 'App._build_sidebar'),
    'Visão geral': ('app.py', 'App._build_sidebar'),
    # FIX-P4-02-01: o botão da "Visão geral" é citado com a seta, igual ao rótulo.
    'Primeiro uso guiado  →': ('app.py', 'App._build'),
}

# "Executar como administrador" não é botão do app: é o item do menu do botão
# direito do Windows no atalho do programa. Por isso é conferido como frase nos
# textos de tela de optimization_ui.py (recusa por conta, R-55/R-60), e não como
# rótulo de um botão numa função que monta a tela (R-62).
WINDOWS_LABELS = {
    'Executar como administrador': 'optimization_ui.py',
}


def _is_ttk_button_call(call: ast.Call) -> bool:
    """FIX-P4-02-06 (R-103): a chamada é exatamente ``ttk.Button(...)``.

    Confere o módulo (o nome ``ttk``) e a classe (o atributo ``Button``);
    ``tk.Button``, ``Button`` solto ou ``self.ttk.Button`` são recusados.
    """
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr == 'Button'
            and isinstance(func.value, ast.Name) and func.value.id == 'ttk')


def _scope_binds_name(stmts, name: str) -> bool:
    """FIX-P4-02-07 (item 1): algum comando deste escopo dá outro valor a
    ``name``: atribuição (``=``, ``+=``, anotação, ``:=``), ``for``/``with``/
    ``except ... as``, ``def``/``class`` com esse nome, ``import``, ``del``,
    ``global``/``nonlocal`` ou ``case``. Desce em ``if``/``for``/``try``/``with``,
    mas não no corpo de funções e classes de dentro (outro escopo); o nome delas
    conta."""
    pending = list(stmts)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
            # decoradores, argumentos padrão e bases rodam neste escopo
            pending.extend(node.decorator_list)
            if isinstance(node, ast.ClassDef):
                pending.extend(node.bases)
                pending.extend(k.value for k in node.keywords)
            else:
                pending.extend(node.args.defaults)
                pending.extend(d for d in node.args.kw_defaults if d is not None)
            continue
        if isinstance(node, ast.Lambda):
            # FIX-P4-02-08: como no def, os padrões só-nome também rodam aqui
            pending.extend(node.args.defaults)
            pending.extend(d for d in node.args.kw_defaults if d is not None)
            continue
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                (a.asname or a.name.split('.')[0]) == name for a in node.names):
            return True
        if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return True
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            return True
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name:
            return True
        if isinstance(node, ast.MatchMapping) and node.rest == name:
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


def _imports_ttk_from_tkinter(tree: ast.Module, build=None) -> bool:
    """FIX-P4-02-06 (R-103): no módulo, ``ttk`` vem de ``from tkinter import ttk``
    (sem apelido) e nunca recebe outro valor no nível do módulo.

    FIX-P4-02-07 (item 1): também recusa ``def ttk``, ``class ttk``,
    ``for ttk in ...`` e qualquer outra forma de dar valor a ``ttk`` no módulo
    (inclusive dentro de ``if``/``try``), e, se ``build`` (a função que monta a
    tela, ex.: ``App._build``) for passada, um ``ttk = ...`` local nela."""
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'tkinter'
               and any(a.name == 'ttk' and a.asname is None for a in n.names)]
    if len(imports) != 1:
        return False
    others = [n for n in tree.body if n is not imports[0]]
    if _scope_binds_name(others, 'ttk'):
        return False
    # ``global ttk`` em qualquer função deixa ela trocar o ``ttk`` do módulo
    if any(isinstance(n, ast.Global) and 'ttk' in n.names for n in ast.walk(tree)):
        return False
    if build is not None and _scope_binds_name(build.body, 'ttk'):
        return False
    if build is not None and any(a.arg == 'ttk' for a in ast.walk(build.args)
                                 if isinstance(a, ast.arg)):
        return False
    return True


def _pair_reaches_tabs_add(func: ast.AST, pair: ast.Tuple) -> bool:
    """FIX-P4-02-06 (item 2): a tupla ``(página, rótulo)`` está na lista de um
    laço ``for page, label in (...)`` cujo corpo chama
    ``self.tabs.add(page, text=label)``."""
    for loop in ast.walk(func):
        if not (isinstance(loop, ast.For) and isinstance(loop.iter, (ast.Tuple, ast.List))
                and any(elt is pair for elt in loop.iter.elts)
                and isinstance(loop.target, ast.Tuple) and len(loop.target.elts) == 2
                and all(isinstance(t, ast.Name) for t in loop.target.elts)):
            continue
        page, label = (t.id for t in loop.target.elts)
        for call in (n for stmt in loop.body for n in ast.walk(stmt)):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == 'add'):
                continue
            owner = call.func.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == 'tabs'
                    and isinstance(owner.value, ast.Name) and owner.value.id == 'self'):
                continue
            if (call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == page
                    and any(k.arg == 'text' and isinstance(k.value, ast.Name)
                            and k.value.id == label for k in call.keywords)):
                return True
    return False


class FirstUseTextsAndAstTests(unittest.TestCase):
    def test_module_has_no_tkinter_or_destructive_calls(self):
        source = (ROOT / 'first_use.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn('tkinter', alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn('tkinter', node.module or '')
        for forbidden in ('unlink', 'os.remove', 'rmtree', 'rmdir', 'subprocess', 'os.system'):
            self.assertNotIn(forbidden, source)

    def test_whole_test_module_passes_in_subprocess_without_tkinter(self):
        # Critério 1: todos os testes deste arquivo passam com tkinter=None,
        # num processo separado (R-87: nada é trocado em sys.modules aqui).
        if os.environ.get(NO_TK_CHILD_ENV) == '1':
            self.skipTest('já está rodando no subprocesso sem tkinter')
        env = dict(os.environ, **{NO_TK_CHILD_ENV: '1'})
        proc = subprocess.run(
            [
                sys.executable,
                '-c',
                (
                    "import sys, unittest; sys.modules['tkinter'] = None; "
                    "suite = unittest.defaultTestLoader.loadTestsFromName("
                    "'tests.test_first_use_p4_02'); "
                    "result = unittest.TextTestRunner(verbosity=0).run(suite); "
                    "assert result.testsRun >= 30, result.testsRun; "
                    "sys.exit(0 if result.wasSuccessful() else 1)"
                ),
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-4000:])

    def test_imports_and_runs_in_subprocess_without_tkinter(self):
        proc = subprocess.run(
            [
                sys.executable,
                '-c',
                (
                    "import sys; sys.modules['tkinter'] = None; "
                    "import first_use as fu; "
                    "assert len(fu.FIRST_USE_STEPS('C:')) == 6"
                ),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_hardcoded_c_drive_in_first_use_source(self):
        source = (ROOT / 'first_use.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn('C:', node.value)

    def test_texts_follow_r88_and_adapt_to_system_drive(self):
        for drive in ('C:', 'W:'):
            intro = fu.FIRST_USE_INTRO_TEXT(drive)
            steps = fu.FIRST_USE_STEPS(drive)
            self.assertEqual(len(steps), 6)
            self.assertEqual(tuple(s['id'] for s in steps), fu.STEP_IDS)
            self.assertIn(
                'O guia orienta e abre cada tela para você',
                intro,
            )
            self.assertIn(
                f'guarda apenas as suas marcações (Feito/Pulado) no arquivo {fu.PROGRESS_FILENAME} na pasta de dados do app',
                intro,
            )
            self.assertIn(
                'O app não apaga nenhum arquivo: grava a cópia no destino de backup '
                'que você escolher; na restauração, numa pasta nova dentro da pasta '
                'que você escolher; e, se você usar "Colocar no lugar original", no '
                'lugar original de cada arquivo, depois de mostrar uma prévia (um '
                'arquivo diferente que já existia é renomeado para .antes-pcro-AAAAMMDD, '
                'nunca apagado)',
                intro,
            )
            self.assertIn(f'o que não for copiado do {drive} não entra no backup', intro)
            self.assertIn(f'se perde quando o instalador formatar o {drive}', intro)

            by_id = {s['id']: s for s in steps}
            self.assertEqual(by_id['diagnostico']['title'], 'Conhecer os discos')
            self.assertNotIn('só lê', by_id['diagnostico']['title'].lower())
            self.assertNotIn('só leitura', by_id['diagnostico']['title'].lower())
            self.assertIn('não apaga nenhum arquivo', by_id['diagnostico']['text'])
            self.assertIn(
                'grava um relatório apenas se você clicar em "Exportar relatório JSON"',
                by_id['diagnostico']['text'],
            )
            # "Exportar relatório JSON" abre um "Salvar como" (arquivo, não pasta).
            self.assertIn('(no arquivo que você escolher)', by_id['diagnostico']['text'])
            self.assertNotIn('pasta que você escolher', by_id['diagnostico']['text'])
            self.assertIn(
                'as suas escolhas ficam guardadas na pasta de dados do app',
                by_id['explorar']['text'],
            )
            self.assertIn(
                f'o que não for copiado do {drive} não entra no backup e se perde '
                f'quando o instalador formatar o {drive}',
                by_id['diagnostico']['text'],
            )
            self.assertIn(
                'o app não apaga nenhum arquivo: grava a cópia no destino de backup '
                'que você escolher; na restauração, numa pasta nova dentro da pasta '
                'que você escolher; e, se você usar "Colocar no lugar original", no '
                'lugar original de cada arquivo, depois de mostrar uma prévia (um '
                'arquivo diferente que já existia é renomeado para .antes-pcro-AAAAMMDD, '
                'nunca apagado)',
                by_id['explorar']['text'],
            )
            self.assertIn(
                f'se perde quando o instalador formatar o {drive}',
                by_id['explorar']['text'],
            )
            self.assertIn(
                'o app grava a cópia de teste numa pasta nova, dentro da pasta que '
                'você escolher, e não apaga nenhum arquivo',
                by_id['testar']['text'],
            )
            self.assertIn(
                f'O que não for copiado do {drive} não entra no backup e se perde '
                f'quando o instalador formatar o {drive}.',
                by_id['testar']['text'],
            )
            for step_id in ('backup', 'proximos'):
                with self.subTest(step=step_id, drive=drive):
                    self.assertIn(
                        f'o que não for copiado do {drive} não entra no backup e se '
                        f'perde quando o instalador formatar o {drive}.',
                        by_id[step_id]['text'],
                    )
            self.assertIn(
                'O app grava a cópia no destino que você escolher e não apaga '
                'nenhum arquivo',
                by_id['backup']['text'],
            )
            self.assertIn(
                f'O que ficar desmarcado ou pendente no {drive} não entra no backup '
                f'e se perde quando o instalador formatar o {drive}.',
                by_id['preservacao']['text'],
            )

            all_texts = [
                intro,
                fu.FIRST_USE_MODE_NOTE,
                fu.FIRST_USE_CLOSE_SAVING_TEXT,
                fu.FIRST_USE_LOAD_ERROR_TEXT,
                fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT,
                fu.FIRST_USE_PREVIOUS_FAILED_TEXT,
                fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT,
                fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT,
                fu.FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT,
            ] + [
                s['title'] + ' ' + s['text'] for s in steps
            ]
            for text in all_texts:
                lower = text.lower()
                for bad in FORBIDDEN_R88:
                    self.assertNotIn(bad, lower, text)
                for old in OLD_TEXTS:
                    self.assertNotIn(old.lower(), lower, text)
                if drive == 'W:':
                    self.assertNotIn('C:', text)

    def test_window_texts_name_real_buttons_and_promise_nothing(self):
        # Revisão da PR #293: o caminho para tentar de novo usa botões que existem.
        try_again = (
            'para tentar outra vez, clique em "Fechar" e abra o guia de novo, no menu '
            'da esquerda (botão "Primeiro uso guiado") ou na página "Visão geral" '
            '(botão "Primeiro uso guiado  →").'
        )
        self.assertIn(try_again, fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertIn(try_again, fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT)
        self.assertIn(
            'O app ainda está salvando as marcações no arquivo '
            f'{fu.PROGRESS_FILENAME}, na pasta de dados do app; se não der, o aviso '
            'aparece quando você abrir o guia de novo (se você fechar o app antes '
            'disso, essas marcações podem se perder).',
            fu.FIRST_USE_CLOSE_SAVING_TEXT,
        )
        project = _Project(ROOT)
        reach = project.reachable(blocked=BLOCKED_EDGES)
        for label, screen in (
            ('Fechar', ('first_use_ui.py', 'show_first_use')),
            ('Primeiro uso guiado', ('app.py', 'App._build_sidebar')),
            ('Visão geral', ('app.py', 'App._build_sidebar')),
        ):
            with self.subTest(label=label):
                self.assertIn(screen, reach)
                self.assertIn(_norm(label), project.labels(*screen))
        for exc in (ValueError('x'), OSError('x'),
                    fu.FirstUseBadProgressFileError(fu.PROGRESS_FILENAME, 'x'),
                    fu.FirstUseTooManyPartialsError(fu.PROGRESS_FILENAME, 21)):
            msg = fu.first_use_error_text(exc)
            with self.subTest(exc=type(exc).__name__):
                self.assertIn('se você fechar o app antes disso, estas marcações se perdem.', msg)
                for old in OLD_TEXTS:
                    self.assertNotIn(old.lower(), msg.lower())

    def test_load_error_cites_exact_labels_of_the_buttons_in_app(self):
        # FIX-P4-02-01 (item 4): o aviso cita o rótulo EXATO de cada botão que
        # abre o guia, lido com ast no app.py (o da "Visão geral" tem a seta).
        # FIX-P4-02-04 (item 2, R-81): cada rótulo é procurado só na função que
        # monta a tela dele, nunca no app.py inteiro: o menu da esquerda (com a
        # entrada "Visão geral") em App._build_sidebar; o botão com a seta em
        # App._build, logo depois de build_overview (que monta a "Visão geral").
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        app_class = next(n for n in tree.body
                         if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = {n.name: n for n in app_class.body if isinstance(n, ast.FunctionDef)}

        def calls(name):
            return [n for n in ast.walk(methods[name]) if isinstance(n, ast.Call)]

        def opens_guide(node):
            return getattr(node, 'attr', None) == 'open_first_use'

        sidebar = [c.args[1].value for c in calls('_build_sidebar')
                   if getattr(c.func, 'attr', None) == '_nav_action'
                   and len(c.args) == 3 and opens_guide(c.args[2])]
        nav_entries = [c.args[2].value for c in calls('_build_sidebar')
                       if getattr(c.func, 'attr', None) == '_nav_entry'
                       and len(c.args) == 3 and isinstance(c.args[2], ast.Constant)]
        build_calls = calls('_build')
        self.assertIn('build_overview',
                      [getattr(c.func, 'id', None) for c in build_calls])

        def is_self_attr(node, attr):
            return (isinstance(node, ast.Attribute) and node.attr == attr
                    and isinstance(node.value, ast.Name) and node.value.id == 'self')

        # FIX-P4-02-05 (item 3, R-62, R-102): as duas funções que montam as
        # telas são chamadas (App.__init__ chama _build, que chama
        # _build_sidebar), e a página "Visão geral" é self.overview.
        self.assertTrue(any(is_self_attr(c.func, '_build') for c in calls('__init__')))
        self.assertTrue(any(is_self_attr(c.func, '_build_sidebar') for c in build_calls))
        # FIX-P4-02-07 (item 4): a tupla é procurada pelo rótulo "Visão geral",
        # em qualquer posição da lista de abas (não supõe que é a primeira), e
        # só depois se confere que a página dela é self.overview.
        tab_pairs = [n for n in ast.walk(methods['_build']) if isinstance(n, ast.Tuple)
                     and len(n.elts) == 2 and isinstance(n.elts[1], ast.Constant)
                     and n.elts[1].value == 'Visão geral']
        self.assertEqual(len(tab_pairs), 1)
        overview_pair = tab_pairs[0]
        self.assertTrue(is_self_attr(overview_pair.elts[0], 'overview'))
        guide_buttons = [c for c in build_calls
                         if any(k.arg == 'command' and opens_guide(k.value)
                                for k in c.keywords)]
        self.assertEqual(len(guide_buttons), 1)
        # FIX-P4-02-06 (item 2): a tupla (self.overview, "Visão geral") chega
        # mesmo a uma chamada self.tabs.add (vira a aba da página).
        self.assertTrue(_pair_reaches_tabs_add(methods['_build'], overview_pair))
        # o botão com a seta é criado DENTRO da página "Visão geral": o
        # primeiro argumento do ttk.Button é self.overview
        # FIX-P4-02-06 (item 1, R-103): confere módulo E classe (ttk.Button,
        # com ttk vindo de tkinter), não só o nome Button.
        self.assertTrue(_imports_ttk_from_tkinter(tree, build=methods['_build']))
        self.assertTrue(_is_ttk_button_call(guide_buttons[0]))
        self.assertTrue(guide_buttons[0].args
                        and is_self_attr(guide_buttons[0].args[0], 'overview'))
        overview = [kw.value.value for c in guide_buttons for kw in c.keywords
                    if kw.arg == 'text' and isinstance(kw.value, ast.Constant)]
        self.assertEqual(overview, [fu.FIRST_USE_OVERVIEW_BUTTON_LABEL])
        self.assertEqual(sidebar, [fu.FIRST_USE_SIDEBAR_LABEL])
        self.assertIn('Visão geral', nav_entries)
        # fora dessas duas funções, nenhum outro botão do app.py abre o guia
        others = [c for name, method in methods.items()
                  if name not in ('_build', '_build_sidebar')
                  for c in ast.walk(method) if isinstance(c, ast.Call)
                  and (any(opens_guide(a) for a in c.args)
                       or any(opens_guide(k.value) for k in c.keywords))]
        self.assertEqual(others, [])
        self.assertEqual(fu.FIRST_USE_OVERVIEW_BUTTON_LABEL, 'Primeiro uso guiado  →')
        for text in (fu.FIRST_USE_LOAD_ERROR_TEXT, fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT,
                     fu.first_use_load_error_text(True, True),
                     fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT,
                     fu.first_use_close_load_failed_text(True, False),
                     fu.first_use_close_load_failed_text(False, True)):
            with self.subTest(text=text[:40]):
                self.assertIn(f'(botão "{overview[0]}")', text)
                self.assertIn(f'(botão "{sidebar[0]}")', text)
                # o nome sem a seta só aparece como o botão do menu da esquerda
                self.assertEqual(text.count('"Primeiro uso guiado"'), 1)

    def test_ttk_button_helper_checks_module_and_class(self):
        # FIX-P4-02-06 (item 1, R-103): o ajudante recusa tk.Button, Button
        # solto e ttk.Label; só aceita ttk.Button. Código sintético, sem Tk.
        def first_call(code):
            return next(n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call))

        self.assertTrue(_is_ttk_button_call(
            first_call("ttk.Button(self.overview, text='x', command=self.open_first_use)")))
        for code in ("tk.Button(self.overview, text='x', command=self.open_first_use)",
                     "Button(self.overview, text='x', command=self.open_first_use)",
                     "ttk.Label(self.overview, text='x')",
                     "tkinter.ttk.Button(self.overview, text='x')",
                     "self.ttk.Button(self.overview, text='x')"):
            with self.subTest(code=code):
                self.assertFalse(_is_ttk_button_call(first_call(code)))
        self.assertTrue(_imports_ttk_from_tkinter(ast.parse('from tkinter import ttk')))
        for code in ('import ttk', 'from tkinter import ttk as t',
                     'from tkinter import ttk\nttk = None',
                     'from other import ttk', 'import tkinter as tk'):
            with self.subTest(code=code):
                self.assertFalse(_imports_ttk_from_tkinter(ast.parse(code)))

    def test_ttk_import_helper_refuses_every_other_binding_of_ttk(self):
        # FIX-P4-02-07 (item 1): mutações sintéticas (código em string, sem Tk
        # e sem disco): qualquer outro valor para ttk no módulo, ou um ttk local
        # em _build, faz o ajudante recusar.
        head = 'from tkinter import ttk\n'
        build_ok = ('class App:\n'
                    '    def _build(self):\n'
                    '        ttk.Button(self.overview, text="x")\n')

        def check(code):
            tree = ast.parse(code)
            app = next((n for n in tree.body if isinstance(n, ast.ClassDef)
                        and n.name == 'App'), None)
            build = None if app is None else next(
                n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == '_build')
            return _imports_ttk_from_tkinter(tree, build=build)

        self.assertTrue(check(head + build_ok))
        self.assertTrue(check('from tkinter import ttk, filedialog\n' + build_ok))
        # nomes parecidos ou ttk só lido não contam como troca
        self.assertTrue(check(head + 'ttk_x = 1\nprint(ttk)\nx = ttk.Button\n' + build_ok))
        self.assertTrue(check(head + 'def helper(ttk_local=None):\n    ttk = 1\n' + build_ok))
        module_mutations = {
            'def ttk': 'def ttk():\n    pass\n',
            'async def ttk': 'async def ttk():\n    pass\n',
            'class ttk': 'class ttk:\n    pass\n',
            'for ttk in': 'for ttk in ():\n    pass\n',
            'ttk =': 'ttk = None\n',
            'ttk: tipo =': 'ttk: object = None\n',
            'ttk +=': 'ttk += 1\n',
            'a = ttk = ...': 'a = ttk = None\n',
            'desempacotar': 'ttk, b = (1, 2)\n',
            'with as ttk': 'with open("x") as ttk:\n    pass\n',
            'except as ttk': 'try:\n    pass\nexcept Exception as ttk:\n    pass\n',
            'walrus': 'if (ttk := None):\n    pass\n',
            'dentro de if': 'if True:\n    ttk = None\n',
            'dentro de try': 'try:\n    import ttk\nexcept ImportError:\n    pass\n',
            'del ttk': 'del ttk\n',
            'import de novo': 'import tkinter.ttk as ttk\n',
            'segundo from tkinter': 'from tkinter import ttk\n',
            'global ttk numa função': 'def f():\n    global ttk\n    ttk = None\n',
            # FIX-P4-02-08 (ressalva R1 da PR #306): lambda igual ao def
            'walrus no padrão da lambda': 'h = lambda a=(ttk := 1): 0\n',
            'walrus no padrão só-nome da lambda': 'h = lambda *, a=(ttk := 1): 0\n',
        }
        for name, code in module_mutations.items():
            for where in ('antes', 'depois'):
                text = (head + code + build_ok) if where == 'depois' else (code + head + build_ok)
                with self.subTest(name=name, where=where):
                    self.assertFalse(check(text))
        local_mutations = {
            'ttk = local': '        ttk = None\n',
            'ttk: tipo = local': '        ttk: object = None\n',
            'for ttk in local': '        for ttk in ():\n            pass\n',
            'def ttk local': '        def ttk():\n            pass\n',
            'class ttk local': '        class ttk:\n            pass\n',
            'import local': '        import ttk\n',
            'with as ttk local': '        with open("x") as ttk:\n            pass\n',
            'dentro de if local': '        if True:\n            ttk = None\n',
        }
        for name, line in local_mutations.items():
            code = head + build_ok.replace('    def _build(self):\n',
                                           '    def _build(self):\n' + line)
            with self.subTest(name=name):
                self.assertFalse(check(code))
        with self.subTest(name='argumento ttk em _build'):
            self.assertFalse(check(head + build_ok.replace('_build(self)', '_build(self, ttk=None)')))
        # sem _build passada, o ttk local nela não é conferido (só o módulo)
        local = head + build_ok.replace('    def _build(self):\n',
                                        '    def _build(self):\n        ttk = None\n')
        self.assertTrue(_imports_ttk_from_tkinter(ast.parse(local)))

    def test_tabs_add_helper_requires_the_pair_to_reach_tabs_add(self):
        # FIX-P4-02-06 (item 2): a tupla (self.overview, "Visão geral") só vale
        # se o laço que a percorre chama self.tabs.add(página, text=rótulo).
        def check(code):
            func = ast.parse(code).body[0]
            pair = next(n for n in ast.walk(func) if isinstance(n, ast.Tuple)
                        and len(n.elts) == 2 and isinstance(n.elts[1], ast.Constant)
                        and n.elts[1].value == 'Visão geral')
            return _pair_reaches_tabs_add(func, pair)

        ok = ("def _build(self):\n"
              "    for page, label in ((self.overview, 'Visão geral'), (self.home, 'M')):\n"
              "        self.tabs.add(page, text=label)\n")
        self.assertTrue(check(ok))
        bad = {
            'sem tabs.add': ok.replace('self.tabs.add(page, text=label)', 'print(page, label)'),
            'outro notebook': ok.replace('self.tabs.add', 'self.other.add'),
            'rótulo trocado': ok.replace('text=label', "text='x'"),
            'página trocada': ok.replace('add(page,', 'add(self.home,'),
            'fora do laço': ("def _build(self):\n"
                             "    pairs = ((self.overview, 'Visão geral'),)\n"
                             "    self.tabs.add(self.home, text='M')\n"),
        }
        for name, code in bad.items():
            with self.subTest(name=name):
                self.assertFalse(check(code))

    def test_load_error_text_variants(self):
        self.assertEqual(fu.first_use_load_error_text(False, False),
                         fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertEqual(fu.first_use_load_error_text(False, True),
                         fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertEqual(fu.first_use_load_error_text(True, False),
                         fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT)
        self.assertEqual(fu.first_use_load_error_text(True, True),
                         fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT + ' '
                         + fu.FIRST_USE_PREVIOUS_FAILED_TEXT)
        self.assertIn('começou do zero', fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertNotIn('começou do zero', fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT)
        for text in (fu.FIRST_USE_LOAD_ERROR_TEXT, fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT):
            self.assertIn('nenhum arquivo foi apagado', text)

    def test_close_after_failed_read_text_promises_no_saving(self):
        # FIX-P4-02-03: ao fechar depois de uma leitura que falhou, o aviso diz
        # que nada desta janela foi salvo e não promete nova tentativa.
        text = fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT
        self.assertIn('nenhuma marcação desta janela foi salva', text)
        self.assertIn('O progresso salvo não pôde ser lido.', text)
        self.assertIn('Nenhum arquivo foi apagado.', text)
        self.assertIn('se perde ao fechar', text)
        self.assertIn('abra o guia de novo', text)
        self.assertNotIn('"Fechar"', text)  # a janela já está fechando
        self.assertNotIn(fu.PROGRESS_FILENAME, text)
        self.assertNotIn(':\\', text)
        variants = (
            fu.first_use_close_load_failed_text(False, False),
            fu.first_use_close_load_failed_text(True, False),
            fu.first_use_close_load_failed_text(False, True),
            fu.first_use_close_load_failed_text(True, True),
        )
        self.assertEqual(variants[0], text)
        self.assertEqual(variants[1], f'{text} {fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT}')
        self.assertEqual(variants[2], f'{text} {fu.FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT}')
        self.assertEqual(variants[3], variants[1])  # ainda gravando vale mais
        for variant in variants:
            with self.subTest(variant=variant[-60:]):
                lower = variant.lower()
                self.assertNotIn('tenta salvar de novo', lower)
                self.assertNotIn('próxima marcação', lower)
        # FIX-P4-02-04 (item 3): frases curtas, com as mesmas promessas de antes
        self.assertEqual(
            fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT,
            'O app ainda está salvando as marcações que já estavam na tela quando o '
            'guia abriu. Se não der certo, o aviso aparece quando você abrir o guia de '
            'novo. Se você fechar o app antes disso, elas podem se perder.')
        self.assertEqual(
            fu.FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT,
            'As marcações que já estavam na tela quando o guia abriu também não foram '
            'salvas. O app ainda as guarda, e elas aparecem quando você abrir o guia de '
            'novo. Se você fechar o app antes disso, elas se perdem.')
        # a frase com os dois botões (igual à do erro de leitura) fica de fora
        open_again = f'Para tentar outra vez, {fu._FIRST_USE_OPEN_AGAIN}'
        for variant in variants:
            self.assertIn(open_again, variant)
            short = variant.replace(open_again, '')
            for sentence in re.split(r'(?<=\.)\s+', short.strip()):
                with self.subTest(sentence=sentence):
                    self.assertLessEqual(len(sentence.split()), 16)
                    for mark in (';', ':', '('):
                        self.assertNotIn(mark, sentence)

    def test_default_drive_uses_workflow_texts_system_drive(self):
        with mock.patch.object(fu, 'system_drive', return_value='Z:'):
            self.assertIn('Z:', fu.FIRST_USE_INTRO_TEXT())
            steps = fu.FIRST_USE_STEPS()
            self.assertTrue(any('Z:' in s['text'] for s in steps))

        self.assertIn('desfazer ajustes da aba "9  Ajustes avançados"', fu.FIRST_USE_MODE_NOTE)
        self.assertIn('"Desfazer tudo" da aba "7  Alterações feitas"', fu.FIRST_USE_MODE_NOTE)

    def test_every_quoted_label_exists_in_reachable_screen_builder(self):
        project = _Project(ROOT)
        reach = project.reachable(blocked=BLOCKED_EDGES)
        texts = [
            fu.FIRST_USE_INTRO_TEXT('C:'),
            fu.FIRST_USE_MODE_NOTE,
            fu.FIRST_USE_CLOSE_SAVING_TEXT,
            fu.FIRST_USE_LOAD_ERROR_TEXT,
            fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT,
            fu.FIRST_USE_PREVIOUS_FAILED_TEXT,
            fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT,
            fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT,
            fu.FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT,
        ] + [step['text'] for step in fu.FIRST_USE_STEPS('C:')]
        quoted = set()
        for text in texts:
            quoted |= _quoted_names(text)

        known = (
            {_norm(k) for k in EXPECTED_STEP_LABELS}
            | {_norm(k) for k in WINDOWS_LABELS}
        )
        self.assertEqual(sorted(quoted - known), [])

        for label, screen in EXPECTED_STEP_LABELS.items():
            with self.subTest(label=label, screen=screen):
                self.assertIn(_norm(label), quoted)
                self.assertIn(screen, reach)
                self.assertIn(_norm(label), project.labels(*screen))

        for label, filename in WINDOWS_LABELS.items():
            with self.subTest(label=label, filename=filename):
                self.assertIn(_norm(label), quoted)
                self.assertTrue(
                    any(_norm(label) in s for s in project.screen_strings(filename))
                )



def _all(**changes) -> dict[str, str]:
    """As 6 etapas (pendentes), com as mudanças pedidas."""
    return dict(fu.empty_first_use_steps(), **changes)


class FirstUseProgressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / 'appdata'

    def _partials(self, path: Path) -> list[str]:
        if not path.parent.exists():
            return []
        return sorted(
            p.name
            for p in path.parent.iterdir()
            if p.name.startswith(path.name + fu.PARTIAL_SUFFIX + '-')
        )

    def test_default_base_uses_localappdata(self):
        path = fu.first_use_progress_path(environ={'LOCALAPPDATA': str(self.tmp)})
        self.assertEqual(
            path,
            self.tmp / 'PC-Restore-Optimizer' / fu.PROGRESS_FILENAME,
        )

    def test_round_trip_and_validation(self):
        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['steps'], fu.empty_first_use_steps())
        self.assertEqual(loaded['warnings'], [])
        self.assertEqual(loaded['path'], self.base / fu.PROGRESS_FILENAME)

        updated = dict(loaded['steps'], diagnostico=fu.DONE, explorar=fu.SKIPPED)
        self.assertEqual(fu.save_first_use_progress(loaded['path'], updated), updated)
        again = fu.load_first_use_progress(self.base)
        self.assertEqual(again['steps'], updated)
        self.assertEqual(again['path'], loaded['path'])
        self.assertEqual(again['warnings'], [])

    def test_invalid_or_incomplete_steps_raise_value_error_before_touching_disk(self):
        path = self.base / fu.PROGRESS_FILENAME
        with self.assertRaises(ValueError):
            fu.validate_first_use_steps('invalido')
        for bad in (
            'invalido',
            _all(inexistente=fu.DONE),
            _all(diagnostico='talvez'),
            {'diagnostico': fu.DONE},  # incompleto: nunca completa com pendente
            {},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    fu.save_first_use_progress(path, bad)
                self.assertFalse(path.exists())
        self.assertEqual(self._partials(path), [])

    def test_incomplete_dict_never_unmarks_saved_step(self):
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, _all(explorar=fu.DONE))
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'diagnostico': fu.DONE})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self._partials(path), [])

    def test_one_window_model_has_no_merge_api(self):
        # Decisão de 20/11/2026: uma janela só; nada de base, reset ou adoção.
        params = inspect.signature(fu.save_first_use_progress).parameters
        self.assertEqual(list(params), ['path', 'steps'])
        self.assertEqual(
            list(inspect.signature(fu.FirstUseProgressSaver).parameters),
            ['path', 'save'],
        )
        for name in ('poll_merged', 'adopt', 'pending_is_reset', 'pending_steps'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(fu.FirstUseProgressSaver, name))
        self.assertFalse(hasattr(fu, '_stack_requests'))
        source = (ROOT / 'first_use.py').read_text(encoding='utf-8')
        for word in ('base_steps', 'reset=', 'merged', 'adopt'):
            with self.subTest(word=word):
                self.assertNotIn(word, source)

    def test_window_state_is_saved_as_is_including_back_to_pending(self):
        # O que a janela mostra é o que vale: voltar para Pendente e
        # "Recomeçar marcações" (tudo pendente) chegam ao disco.
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, _all(diagnostico=fu.DONE, explorar=fu.DONE))
        shown = fu.load_first_use_progress(self.base)['steps']
        self.assertEqual(shown['explorar'], fu.DONE)
        shown['explorar'] = fu.PENDING
        fu.save_first_use_progress(path, shown)
        self.assertEqual(
            fu.load_first_use_progress(self.base)['steps'], _all(diagnostico=fu.DONE)
        )
        fu.save_first_use_progress(path, fu.empty_first_use_steps())
        self.assertEqual(
            fu.load_first_use_progress(self.base)['steps'], fu.empty_first_use_steps()
        )

    def test_corrupt_json_is_untouched_and_advances_to_2(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text('{ corrompido', encoding='utf-8')
        before = first.read_bytes()

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['steps'], fu.empty_first_use_steps())
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertEqual(len(loaded['warnings']), 1)
        self.assertIn(fu.PROGRESS_FILENAME, loaded['warnings'][0])
        self.assertNotIn(str(self.base), loaded['warnings'][0])

        fu.save_first_use_progress(loaded['path'], dict(loaded['steps'], diagnostico=fu.DONE))
        self.assertEqual(first.read_bytes(), before)
        again = fu.load_first_use_progress(self.base)
        self.assertEqual(again['steps']['diagnostico'], fu.DONE)
        self.assertEqual(again['path'], loaded['path'])
        with self.assertRaises(fu.FirstUseBadProgressFileError):
            fu.save_first_use_progress(first, fu.empty_first_use_steps())
        self.assertEqual(first.read_bytes(), before)

    def test_too_large_file_is_untouched_and_advances_to_2(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b'x' * (fu.PROGRESS_LIMIT + 1))

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('grande demais' in w for w in loaded['warnings']))
        self.assertEqual(first.stat().st_size, fu.PROGRESS_LIMIT + 1)

    def test_unknown_schema_is_untouched_and_advances_to_2(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text(json.dumps({'schema': 'outro', 'steps': {}}), encoding='utf-8')

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('formato desconhecido' in w for w in loaded['warnings']))

    def test_symlink_or_reparse_point_is_refused(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text(
            json.dumps({'schema': fu.SCHEMA, 'steps': {'diagnostico': fu.DONE}}),
            encoding='utf-8',
        )
        reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)

        class FakeStat:
            st_mode = stat.S_IFREG | 0o600
            st_size = 40
            st_file_attributes = reparse_flag

        with mock.patch.object(fu.os, 'lstat', return_value=FakeStat()):
            loaded = fu.load_first_use_progress(self.base)
            self.assertIsNone(loaded['path'])
            self.assertTrue(
                any('é um link ou um arquivo especial do Windows' in w for w in loaded['warnings'])
            )
            with self.assertRaises(OSError):
                fu.save_first_use_progress(first, fu.empty_first_use_steps())

    def test_error_text_never_exposes_full_path_or_username(self):
        exc = PermissionError(
            13,
            'Acesso negado para Beltrano',
            r'C:\Users\Beltrano\AppData\Local\PC-Restore-Optimizer\primeiro-uso-progresso.json',
        )
        msg = fu.first_use_error_text(exc)
        self.assertIn('primeiro-uso-progresso.json', msg)
        self.assertIn('PermissionError', msg)
        self.assertIn('não pôde ser gravado', msg)
        self.assertIn('ele foi deixado como está', msg)
        for secret in ('Beltrano', 'Users', 'AppData', 'Acesso negado'):
            self.assertNotIn(secret, msg)

    def test_error_text_without_filename_uses_saver_path_name_only(self):
        exc = OSError('falha em /home/Beltrano/pasta')
        path = self.base / 'Beltrano' / fu.PROGRESS_FILENAME
        msg = fu.first_use_error_text(exc, path)
        self.assertIn(f'o arquivo de progresso "{fu.PROGRESS_FILENAME}" não pôde ser gravado (OSError)', msg)
        self.assertIn('ele foi deixado como está', msg)
        self.assertNotIn('Beltrano', msg)
        self.assertNotIn(str(self.base), msg)

    def test_bad_progress_file_error_uses_fixed_reason_and_filename(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.mkdir(parents=True)
        with self.assertRaises(fu.FirstUseBadProgressFileError) as ctx:
            fu.save_first_use_progress(first, fu.empty_first_use_steps())
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn(fu.PROGRESS_FILENAME, msg)
        self.assertIn(
            f'o arquivo de progresso "{fu.PROGRESS_FILENAME}" não pôde ser usado; '
            'ele foi deixado como está',
            msg,
        )
        self.assertNotIn(str(self.base), msg)

    def test_bad_progress_text_is_neutral_also_for_corrupt_json(self):
        # R-37: JSON estragado não é "arquivo não comum"; o texto vale para as duas causas.
        path = self.base / fu.PROGRESS_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{estragado', encoding='utf-8')
        with self.assertRaises(fu.FirstUseBadProgressFileError) as ctx:
            fu.save_first_use_progress(path, fu.empty_first_use_steps())
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn('não pôde ser usado; ele foi deixado como está', msg)
        self.assertNotIn('arquivo comum', msg)
        self.assertEqual(path.read_text(encoding='utf-8'), '{estragado')

    def test_too_many_leftover_partials_refuses_to_write_and_deletes_nothing(self):
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, _all(diagnostico=fu.DONE))
        before = path.read_bytes()
        leftovers = []
        for i in range(fu.MAX_PARTIAL_FILES):
            extra = path.with_name(f'{path.name}{fu.PARTIAL_SUFFIX}-{i:08x}')
            extra.write_text('sobra', encoding='utf-8')
            leftovers.append(extra)
        # Com exatamente o limite ainda grava (e não cria sobra nova).
        fu.save_first_use_progress(path, _all(diagnostico=fu.SKIPPED))
        self.assertEqual(len(self._partials(path)), fu.MAX_PARTIAL_FILES)
        before = path.read_bytes()
        extra = path.with_name(f'{path.name}{fu.PARTIAL_SUFFIX}-ffffffff')
        extra.write_text('sobra', encoding='utf-8')
        leftovers.append(extra)
        with self.assertRaises(fu.FirstUseTooManyPartialsError) as ctx:
            fu.save_first_use_progress(path, _all(diagnostico=fu.DONE))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self._partials(path)), fu.MAX_PARTIAL_FILES + 1)
        for item in leftovers:
            self.assertEqual(item.read_text(encoding='utf-8'), 'sobra')
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn('sobras de gravações que falharam', msg)
        self.assertIn('nada foi apagado', msg)
        self.assertNotIn(str(self.base), msg)

    def test_partials_of_other_progress_file_do_not_count(self):
        path = self.base / fu.PROGRESS_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        other = self.base / 'primeiro-uso-progresso-2.json'
        for i in range(fu.MAX_PARTIAL_FILES + 3):
            other.with_name(f'{other.name}{fu.PARTIAL_SUFFIX}-{i:08x}').write_text('x', encoding='utf-8')
        fu.save_first_use_progress(path, _all(backup=fu.DONE))
        self.assertEqual(fu.load_first_use_progress(self.base)['steps']['backup'], fu.DONE)

    def test_save_docstring_says_other_process_marks_can_be_replaced(self):
        doc = ' '.join((fu.save_first_use_progress.__doc__ or '').split())
        self.assertIn('outro processo do app', doc)
        self.assertIn('pode ser trocada pela desta janela', doc)

    def test_module_docstring_says_user_files_and_progress_are_never_deleted(self):
        doc = ' '.join((fu.__doc__ or '').split())
        self.assertIn('nunca apaga arquivos do usuário nem o arquivo de progresso', doc)
        self.assertNotIn('- nunca apaga arquivos;', doc)

    def test_failed_replace_keeps_partial_without_deleting(self):
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, _all(diagnostico=fu.DONE))
        before = path.read_bytes()
        with mock.patch.object(fu.os, 'replace', side_effect=OSError('falha')):
            with self.assertRaises(OSError):
                fu.save_first_use_progress(path, _all(diagnostico=fu.SKIPPED))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self._partials(path)), 1)

    def test_permission_error_is_not_called_corrupt_and_retries(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text(json.dumps({'schema': fu.SCHEMA, 'steps': {}}), encoding='utf-8')
        with mock.patch.object(fu, '_read_bytes_with_retry', side_effect=PermissionError(13, 'ocupado')):
            loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('não pôde ser lido' in w for w in loaded['warnings']))
        self.assertFalse(any('estragado' in w for w in loaded['warnings']))

    def test_read_retries_permission_error_then_succeeds(self):
        first = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(first, _all(backup=fu.DONE))
        real_open = open
        calls = []

        def flaky_open(path, mode='r', *args, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, 'ocupado')
            return real_open(path, mode, *args, **kwargs)

        sleeps: list[float] = []
        with mock.patch('builtins.open', side_effect=flaky_open):
            data = fu._read_bytes_with_retry(first, 1000, sleep=sleeps.append)
        self.assertEqual(len(sleeps), 1)
        self.assertIn(b'backup', data)

    def test_deep_json_recursion_error_is_untouched_and_advances_to_2(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        payload = ('[' * 50000).encode('utf-8')
        first.write_bytes(payload)

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertEqual(first.read_bytes(), payload)
        self.assertTrue(any('estragado' in w for w in loaded['warnings']))

    def test_bad_first_and_valid_second_warns_that_second_was_used(self):
        first = self.base / fu.PROGRESS_FILENAME
        second = self.base / 'primeiro-uso-progresso-2.json'
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text('{ quebrado', encoding='utf-8')
        saved = _all(backup=fu.DONE)
        fu.save_first_use_progress(second, saved)

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], second)
        self.assertEqual(loaded['steps'], saved)
        self.assertEqual(len(loaded['warnings']), 1)
        self.assertNotIn('começou do zero', loaded['warnings'][0])
        self.assertIn('primeiro-uso-progresso-2.json', loaded['warnings'][0])

    def test_real_symlink_is_not_followed_and_target_remains_unchanged(self):
        target = self.tmp / 'alvo-real.json'
        target_bytes = json.dumps(
            {'schema': fu.SCHEMA, 'steps': _all(diagnostico=fu.DONE)}
        ).encode('utf-8')
        target.write_bytes(target_bytes)
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, first)
        except OSError as exc:
            self.skipTest(f'sem permissão de symlink: {exc}')

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(
            any('é um link ou um arquivo especial do Windows' in w for w in loaded['warnings'])
        )
        with self.assertRaises(OSError):
            fu.save_first_use_progress(first, fu.empty_first_use_steps())
        self.assertEqual(target.read_bytes(), target_bytes)
        self.assertTrue(first.is_symlink())

    def test_directory_in_place_of_file_is_untouched_and_refused(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.mkdir(parents=True)
        marker = first / 'conteudo.txt'
        marker.write_text('nao apagar', encoding='utf-8')

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('não é um arquivo comum' in w for w in loaded['warnings']))
        with self.assertRaises(OSError):
            fu.save_first_use_progress(first, fu.empty_first_use_steps())
        self.assertTrue(first.is_dir())
        self.assertEqual(marker.read_text(encoding='utf-8'), 'nao apagar')

    def test_exclusive_lock_timeout_becomes_sanitized_error_text(self):
        path = self.base / fu.PROGRESS_FILENAME
        with mock.patch.object(
            fu,
            'exclusive_lock',
            side_effect=TimeoutError('trava ocupada: .primeiro-uso-progresso.json.lock'),
        ):
            with self.assertRaises(TimeoutError) as ctx:
                fu.save_first_use_progress(path, fu.empty_first_use_steps())
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn('TimeoutError', msg)
        self.assertNotIn(str(self.base), msg)
        self.assertFalse(path.exists())

    def test_two_app_processes_are_serialized_by_exclusive_lock(self):
        # Trava contra dois processos do app gravando ao mesmo tempo: a segunda
        # gravação espera a primeira terminar; o arquivo fica sempre inteiro e
        # vale o último a gravar (sem juntar, modelo de uma janela só).
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, fu.empty_first_use_steps())

        a_paused = threading.Event()
        release_a = threading.Event()
        b_entering_lock = threading.Event()
        b_acquired_lock = threading.Event()
        real_replace = fu._replace_with_retry
        real_lock = fu.exclusive_lock
        thread_a_id = None
        thread_b_id = None
        events: list[str] = []
        errors = []

        from contextlib import contextmanager

        @contextmanager
        def spy_exclusive_lock(lock_target):
            tid = threading.get_ident()
            if tid == thread_b_id:
                events.append('b_waiting')
                b_entering_lock.set()
            with real_lock(lock_target):
                if tid == thread_a_id:
                    events.append('a_acquired')
                elif tid == thread_b_id:
                    events.append('b_acquired')
                    b_acquired_lock.set()
                yield
                if tid == thread_a_id:
                    events.append('a_releasing')

        def paused_replace(partial, dst, sleep=None):
            if threading.get_ident() == thread_a_id:
                a_paused.set()
                if not release_a.wait(5):
                    raise TimeoutError('A não foi liberada a tempo')
            return real_replace(partial, dst, sleep=sleep)

        def writer_a():
            nonlocal thread_a_id
            thread_a_id = threading.get_ident()
            try:
                fu.save_first_use_progress(path, _all(diagnostico=fu.DONE))
            except Exception as exc:  # pragma: no cover - falha do teste
                errors.append(exc)

        def writer_b():
            nonlocal thread_b_id
            thread_b_id = threading.get_ident()
            try:
                fu.save_first_use_progress(path, _all(explorar=fu.DONE))
            except Exception as exc:  # pragma: no cover - falha do teste
                errors.append(exc)

        with (
            mock.patch.object(fu, '_replace_with_retry', side_effect=paused_replace),
            mock.patch.object(fu, 'exclusive_lock', side_effect=spy_exclusive_lock),
        ):
            ta = threading.Thread(target=writer_a)
            ta.start()
            self.assertTrue(a_paused.wait(5))

            tb = threading.Thread(target=writer_b)
            tb.start()
            self.assertTrue(b_entering_lock.wait(5))
            self.assertFalse(b_acquired_lock.wait(0.05))
            release_a.set()

            self.assertTrue(b_acquired_lock.wait(5))
            ta.join(timeout=5)
            tb.join(timeout=5)
            self.assertFalse(ta.is_alive())
            self.assertFalse(tb.is_alive())

        self.assertEqual(errors, [])
        self.assertEqual(events, ['a_acquired', 'b_waiting', 'a_releasing', 'b_acquired'])
        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['warnings'], [])
        self.assertEqual(loaded['steps'], _all(explorar=fu.DONE))
        self.assertEqual(self._partials(path), [])


class FirstUseProgressSaverTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.path = self.tmp / 'progresso' / fu.PROGRESS_FILENAME
        self._savers: list[fu.FirstUseProgressSaver] = []
        # R-29: registrado depois do cleanup da pasta para rodar ANTES dele
        self.addCleanup(self._join_all_savers)

    def _join_all_savers(self):
        for saver in self._savers:
            self.assertTrue(saver.join(5))

    def _make_saver(self, **kwargs) -> fu.FirstUseProgressSaver:
        saver = fu.FirstUseProgressSaver(self.path, **kwargs)
        self._savers.append(saver)
        return saver

    def _disk(self) -> dict[str, str]:
        return fu.load_first_use_progress(self.path.parent)['steps']

    def test_latest_request_wins_and_coalesces_intermediate(self):
        release = threading.Event()
        started = threading.Event()
        calls = []
        wait_results = []

        def fake_save(path, steps):
            started.set()
            wait_results.append(release.wait(5))
            calls.append((path, dict(steps)))

        saver = self._make_saver(save=fake_save)
        first = _all(diagnostico=fu.DONE)
        second = dict(first, explorar=fu.SKIPPED)
        third = dict(second, preservacao=fu.DONE)

        saver.request(first)
        self.assertTrue(started.wait(5))
        saver.request(second)
        saver.request(third)
        self.assertEqual(saver.pending(), third)
        release.set()
        self.assertTrue(saver.join(5))

        self.assertEqual(wait_results, [True, True])
        self.assertEqual([c[1] for c in calls], [first, third])
        self.assertEqual([c[0] for c in calls], [self.path, self.path])
        self.assertIsNone(saver.pending())
        self.assertIsNone(saver.poll_error())

    def test_real_saver_writes_window_state_including_revert_and_restart(self):
        saver = self._make_saver()
        saver.request(_all(diagnostico=fu.DONE, explorar=fu.DONE))
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE, explorar=fu.DONE))

        # Clicar de novo em "Feito": volta para Pendente, e isso chega ao disco.
        saver.request(_all(diagnostico=fu.DONE))
        self.assertTrue(saver.join(5))
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE))

        # "Recomeçar marcações": tudo pendente.
        saver.request(fu.empty_first_use_steps())
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        self.assertEqual(self._disk(), fu.empty_first_use_steps())

    def test_invalid_or_incomplete_request_is_refused_at_once(self):
        started = threading.Event()
        release = threading.Event()
        wait_results: list[bool] = []
        calls: list[dict] = []

        def paused_save(path, steps):
            calls.append(dict(steps))
            if len(calls) == 1:
                started.set()
                wait_results.append(release.wait(5))
            fu.save_first_use_progress(path, steps)

        saver = self._make_saver(save=paused_save)
        saver.request(_all(diagnostico=fu.DONE))
        self.assertTrue(started.wait(5))
        saver.request(_all(diagnostico=fu.DONE, explorar=fu.DONE))
        for bad in (_all(xyz=fu.DONE), _all(testar='talvez'), 'invalido', {'backup': fu.DONE}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    saver.request(bad)
        self.assertEqual(saver.pending(), _all(diagnostico=fu.DONE, explorar=fu.DONE))
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(wait_results, [True])
        self.assertEqual(
            calls, [_all(diagnostico=fu.DONE), _all(diagnostico=fu.DONE, explorar=fu.DONE)]
        )
        self.assertIsNone(saver.poll_error())
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE, explorar=fu.DONE))

    def test_failed_save_is_kept_in_pending_and_retried_on_next_request(self):
        calls: list[dict] = []

        def flaky_save(path, steps):
            calls.append(dict(steps))
            if len(calls) == 1:
                raise TimeoutError('trava ocupada')
            fu.save_first_use_progress(path, steps)

        saver = self._make_saver(save=flaky_save)
        saver.request(_all(diagnostico=fu.DONE))
        self.assertTrue(saver.join(5))
        err = saver.poll_error()
        self.assertIsNotNone(err)
        self.assertIn('TimeoutError', err)
        # Não tenta de novo sozinho: espera o próximo pedido.
        self.assertFalse(saver.busy())
        self.assertEqual(len(calls), 1)
        self.assertEqual(saver.pending(), _all(diagnostico=fu.DONE))
        self.assertFalse(self.path.exists())

        saver.request(_all(diagnostico=fu.DONE, explorar=fu.DONE))
        self.assertTrue(saver.join(5))
        self.assertEqual(calls[1], _all(diagnostico=fu.DONE, explorar=fu.DONE))
        self.assertIsNone(saver.poll_error())
        self.assertIsNone(saver.pending())
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE, explorar=fu.DONE))

    def test_failure_with_newer_waiting_request_writes_the_newer(self):
        started = threading.Event()
        release = threading.Event()
        wait_results: list[bool] = []
        calls: list[dict] = []

        def save(path, steps):
            calls.append(dict(steps))
            if len(calls) == 1:
                started.set()
                wait_results.append(release.wait(5))
                raise TimeoutError('trava ocupada')
            fu.save_first_use_progress(path, steps)

        saver = self._make_saver(save=save)
        saver.request(_all(diagnostico=fu.DONE, explorar=fu.DONE))
        self.assertTrue(started.wait(5))
        saver.request(_all(diagnostico=fu.DONE, explorar=fu.SKIPPED))
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(wait_results, [True])
        self.assertEqual(calls[1], _all(diagnostico=fu.DONE, explorar=fu.SKIPPED))
        self.assertIsNone(saver.poll_error())
        self.assertIsNone(saver.pending())
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE, explorar=fu.SKIPPED))

    def test_value_error_text_blames_the_marks_not_the_file(self):
        msg = fu.first_use_error_text(ValueError('Etapa desconhecida'), self.path)
        self.assertIn('as marcações não puderam ser salvas (ValueError)', msg)
        self.assertNotIn('não pôde ser gravado', msg)
        self.assertNotIn('Etapa desconhecida', msg)

    def test_saver_ignores_requests_after_close(self):
        saver = self._make_saver()
        saver.close()
        saver.request(_all(diagnostico=fu.DONE))
        self.assertFalse(saver.busy())
        self.assertIsNone(saver.pending())
        self.assertFalse(self.path.exists())

    def test_saver_accepts_none_path(self):
        no_path_saver = fu.FirstUseProgressSaver(None)
        self._savers.append(no_path_saver)
        no_path_saver.request(_all(diagnostico=fu.DONE))
        self.assertFalse(no_path_saver.busy())
        self.assertIsNone(no_path_saver.pending())
        self.assertTrue(no_path_saver.join(1))

    def test_save_error_is_sanitized_and_cleared_on_next_success(self):
        outcomes = [
            PermissionError(13, 'Beltrano', r'C:\Users\Beltrano\primeiro-uso-progresso.json'),
            None,
        ]

        def fake_save(path, steps):
            item = outcomes.pop(0)
            if item is not None:
                raise item
            fu.save_first_use_progress(path, steps)

        saver = self._make_saver(save=fake_save)
        saver.request(_all(diagnostico=fu.DONE))
        self.assertTrue(saver.join(5))
        err = saver.poll_error()
        self.assertIsNotNone(err)
        self.assertNotIn('Beltrano', err)
        self.assertIn(f'"{fu.PROGRESS_FILENAME}"', err)
        self.assertNotIn(str(self.tmp), err)
        self.assertEqual(fu.first_use_warning_text('aviso base', err), err)

        saver.request(_all(diagnostico=fu.SKIPPED))
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        self.assertEqual(fu.first_use_warning_text('aviso base', saver.poll_error()), 'aviso base')
        self.assertEqual(self._disk()['diagnostico'], fu.SKIPPED)

    def test_load_with_pending_reads_pending_before_disk(self):
        fu.save_first_use_progress(self.path, fu.empty_first_use_steps())
        release = threading.Event()
        saver = self._make_saver(
            save=lambda p, st: (release.wait(5), fu.save_first_use_progress(p, st)),
        )
        newer = _all(diagnostico=fu.DONE)
        saver.request(newer)
        order = []

        def fake_load(base):
            order.append('disk')
            release.set()
            self.assertTrue(saver.join(5))
            return fu.load_first_use_progress(base)

        real_pending = saver.pending

        def spy_pending():
            order.append('pending')
            return real_pending()

        saver.pending = spy_pending
        result = fu.load_first_use_with_pending(self.path.parent, saver, load=fake_load)
        self.assertEqual(order, ['pending', 'disk'])
        self.assertEqual(result['steps'], newer)

    def test_load_with_pending_uses_whole_pending_dict_over_disk(self):
        # Reabrir a janela durante uma gravação: vale o que a janela pediu
        # por inteiro (inclusive o que voltou para Pendente).
        fu.save_first_use_progress(self.path, _all(explorar=fu.DONE))
        started = threading.Event()
        release = threading.Event()
        saver = self._make_saver(
            save=lambda p, st: (started.set(), release.wait(5), fu.save_first_use_progress(p, st)),
        )
        saver.request(_all(diagnostico=fu.DONE))
        self.assertTrue(started.wait(5))
        try:
            loaded = fu.load_first_use_with_pending(self.path.parent, saver)
            self.assertEqual(loaded['steps'], _all(diagnostico=fu.DONE))
            self.assertEqual(loaded['warnings'], [])
        finally:
            release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(self._disk(), _all(diagnostico=fu.DONE))

    def test_load_with_pending_without_saver_or_pending_reads_disk(self):
        fu.save_first_use_progress(self.path, _all(testar=fu.SKIPPED))
        self.assertEqual(
            fu.load_first_use_with_pending(self.path.parent)['steps'],
            _all(testar=fu.SKIPPED),
        )
        saver = self._make_saver()
        self.assertEqual(
            fu.load_first_use_with_pending(self.path.parent, saver)['steps'],
            _all(testar=fu.SKIPPED),
        )

    def test_saver_docstrings_tell_screen_to_close_by_pending(self):
        for func in (fu.FirstUseProgressSaver.close, fu.FirstUseProgressSaver.busy):
            with self.subTest(func=func.__name__):
                self.assertIn('pending()', func.__doc__)
        self.assertIn('uma janela só', fu.save_first_use_progress.__doc__.lower())

    def test_error_texts_say_app_retries_on_next_mark(self):
        retry = (
            'O app tenta salvar de novo na próxima marcação; se você fechar o '
            'app antes disso, estas marcações se perdem.'
        )
        excs = (
            ValueError('x'),
            fu.FirstUseBadProgressFileError(fu.PROGRESS_FILENAME, 'x'),
            OSError('x'),
        )
        for exc in excs:
            with self.subTest(exc=type(exc).__name__):
                msg = fu.first_use_error_text(exc, self.path)
                self.assertTrue(msg.endswith(retry), msg)
                self.assertNotIn('valem só até fechar', msg)


if __name__ == '__main__':
    unittest.main()
