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
}

# "Executar como administrador" não é botão do app: é o item do menu do botão
# direito do Windows no atalho do programa. Por isso é conferido como frase nos
# textos de tela de optimization_ui.py (recusa por conta, R-55/R-60), e não como
# rótulo de um botão numa função que monta a tela (R-62).
WINDOWS_LABELS = {
    'Executar como administrador': 'optimization_ui.py',
}


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
        self.assertIn(
            'para tentar outra vez, clique em "Fechar" e abra de novo o '
            '"Primeiro uso guiado" (no menu da esquerda ou na "Visão geral").',
            fu.FIRST_USE_LOAD_ERROR_TEXT,
        )
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
            'Acesso negado para usuario_secreto',
            r'C:\Users\usuario_secreto\AppData\Local\PC-Restore-Optimizer\primeiro-uso-progresso.json',
        )
        msg = fu.first_use_error_text(exc)
        self.assertIn('primeiro-uso-progresso.json', msg)
        self.assertIn('PermissionError', msg)
        self.assertIn('não pôde ser gravado', msg)
        self.assertIn('ele foi deixado como está', msg)
        for secret in ('usuario_secreto', 'Users', 'AppData', 'Acesso negado'):
            self.assertNotIn(secret, msg)

    def test_error_text_without_filename_uses_saver_path_name_only(self):
        exc = OSError('falha em /home/usuario_secreto/pasta')
        path = self.base / 'usuario_secreto' / fu.PROGRESS_FILENAME
        msg = fu.first_use_error_text(exc, path)
        self.assertIn(f'o arquivo de progresso "{fu.PROGRESS_FILENAME}" não pôde ser gravado (OSError)', msg)
        self.assertIn('ele foi deixado como está', msg)
        self.assertNotIn('usuario_secreto', msg)
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
            PermissionError(13, 'segredo', r'C:\Users\segredo\primeiro-uso-progresso.json'),
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
        self.assertNotIn('segredo', err)
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
