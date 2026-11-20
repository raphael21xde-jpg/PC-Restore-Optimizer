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
}

# Rótulos da própria janela do Primeiro uso guiado (Fatia 2: first_use_ui.py, show_first_use).
SLICE_2_WINDOW_LABELS = {'Abrir'}

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
                'O app não apaga nenhum arquivo: grava a cópia no destino de backup que você escolher e, na restauração, nas pastas que você indicar (um arquivo que já existia é renomeado para .antes-pcro-AAAAMMDD, nunca apagado)',
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
            self.assertIn('pasta que você escolher', by_id['diagnostico']['text'])
            self.assertIn(
                f'o que não for copiado do {drive} não entra no backup e se perde '
                f'quando o instalador formatar o {drive}',
                by_id['diagnostico']['text'],
            )
            self.assertIn(
                'o app não apaga nenhum arquivo: grava a cópia no destino de backup '
                'que você escolher e, na restauração, nas pastas que você indicar, '
                'onde um arquivo que já existia é renomeado para .antes-pcro-AAAAMMDD, '
                'nunca apagado',
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
                f'O que ficar desmarcado ou pendente no {drive} não entra no backup '
                f'e se perde quando o instalador formatar o {drive}.',
                by_id['preservacao']['text'],
            )

            all_texts = [intro, fu.FIRST_USE_MODE_NOTE] + [
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
        texts = [fu.FIRST_USE_INTRO_TEXT('C:'), fu.FIRST_USE_MODE_NOTE] + [
            step['text'] for step in fu.FIRST_USE_STEPS('C:')
        ]
        quoted = set()
        for text in texts:
            quoted |= _quoted_names(text)

        known = (
            {_norm(k) for k in EXPECTED_STEP_LABELS}
            | {_norm(k) for k in SLICE_2_WINDOW_LABELS}
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
        fu.save_first_use_progress(loaded['path'], updated, base_steps=loaded['steps'])
        again = fu.load_first_use_progress(self.base)
        self.assertEqual(again['steps'], updated)
        self.assertEqual(again['path'], loaded['path'])
        self.assertEqual(again['warnings'], [])

    def test_invalid_step_or_status_or_missing_base_raises_value_error(self):
        path = self.base / fu.PROGRESS_FILENAME
        empty = fu.empty_first_use_steps()
        with self.assertRaises(ValueError):
            fu.validate_first_use_steps('invalido')
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'inexistente': fu.DONE}, base_steps=empty)
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'diagnostico': 'talvez'}, base_steps=empty)
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, empty)
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'xyz': 'talvez'}, reset=True)
        self.assertFalse(path.exists())

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

        fu.save_first_use_progress(
            loaded['path'],
            dict(loaded['steps'], diagnostico=fu.DONE),
            base_steps=loaded['steps'],
        )
        self.assertEqual(first.read_bytes(), before)
        again = fu.load_first_use_progress(self.base)
        self.assertEqual(again['steps']['diagnostico'], fu.DONE)
        self.assertEqual(again['path'], loaded['path'])

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
                fu.save_first_use_progress(
                    first,
                    fu.empty_first_use_steps(),
                    base_steps=fu.empty_first_use_steps(),
                )

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
        # Ressalva A: erro sem nome de arquivo (ex.: trava ocupada) mostra o
        # nome do arquivo de progresso e um motivo fixo, nunca a pasta.
        exc = OSError('falha em /home/usuario_secreto/pasta')
        path = self.base / 'usuario_secreto' / fu.PROGRESS_FILENAME
        msg = fu.first_use_error_text(exc, path)
        self.assertIn(f'o arquivo de progresso "{fu.PROGRESS_FILENAME}" não pôde ser gravado (OSError)', msg)
        self.assertIn('ele foi deixado como está', msg)
        self.assertNotIn('usuario_secreto', msg)
        self.assertNotIn(str(self.base), msg)
        self.assertNotIn('Não deu para salvar o progresso (OSError)', msg)

    def test_bad_progress_file_error_uses_fixed_reason_and_filename(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.mkdir(parents=True)
        with self.assertRaises(fu.FirstUseBadProgressFileError) as ctx:
            fu.save_first_use_progress(
                first,
                fu.empty_first_use_steps(),
                base_steps=fu.empty_first_use_steps(),
            )
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn(fu.PROGRESS_FILENAME, msg)
        self.assertIn(
            'o arquivo de progresso',
            msg,
        )
        self.assertIn(
            'não é um arquivo comum ou não pôde ser lido; ele foi deixado como está',
            msg,
        )
        self.assertNotIn(str(self.base), msg)

    def test_failed_replace_keeps_partial_without_deleting(self):
        path = self.base / fu.PROGRESS_FILENAME
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, {'diagnostico': fu.DONE}, base_steps=empty)
        before = path.read_bytes()
        with mock.patch.object(fu.os, 'replace', side_effect=OSError('falha')):
            with self.assertRaises(OSError):
                fu.save_first_use_progress(
                    path,
                    {'diagnostico': fu.SKIPPED},
                    base_steps=dict(empty, diagnostico=fu.DONE),
                )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self._partials(path)), 1)

    def test_concurrent_instance_save_preserves_other_instance_entry(self):
        path = self.base / fu.PROGRESS_FILENAME
        base_steps = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, base_steps, base_steps=base_steps)

        # Outra instância grava 'explorar = feito' no disco
        other_steps = dict(base_steps, explorar=fu.DONE)
        fu.save_first_use_progress(path, other_steps, base_steps=base_steps)

        # Esta instância ainda tinha 'explorar = pendente' na memória e marca 'diagnostico = feito'
        my_steps = dict(base_steps, diagnostico=fu.DONE)
        merged = fu.save_first_use_progress(path, my_steps, base_steps=base_steps)
        self.assertEqual(merged['diagnostico'], fu.DONE)
        self.assertEqual(merged['explorar'], fu.DONE)

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['steps']['diagnostico'], fu.DONE)
        self.assertEqual(loaded['steps']['explorar'], fu.DONE)

    def test_full_memory_dict_without_base_is_refused_and_keeps_other_window_mark(self):
        # Ponto 2 do revisor (reprodução): tudo pendente; outra janela grava
        # explorar=feito; gravar o dicionário completo da memória SEM base
        # apagaria explorar. Agora levanta ValueError e o disco fica igual.
        path = self.base / fu.PROGRESS_FILENAME
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, empty, base_steps=empty)
        fu.save_first_use_progress(path, {'explorar': fu.DONE}, base_steps=empty)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, dict(empty, diagnostico=fu.DONE))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self._partials(path), [])
        self.assertEqual(
            fu.load_first_use_progress(self.base)['steps']['explorar'], fu.DONE
        )
        # Com a base certa, a mesma gravação junta as duas marcações.
        merged = fu.save_first_use_progress(
            path, dict(empty, diagnostico=fu.DONE), base_steps=empty
        )
        self.assertEqual(merged, dict(empty, diagnostico=fu.DONE, explorar=fu.DONE))

    def test_reset_with_invalid_step_raises_and_does_not_touch_disk(self):
        # Ponto 3a: reset=True valida o dicionário e não grava nada se falhar.
        path = self.base / fu.PROGRESS_FILENAME
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, {'explorar': fu.DONE}, base_steps=empty)
        before = path.read_bytes()
        for bad in ({'xyz': 'talvez'}, {'diagnostico': 'talvez'}, 'invalido'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    fu.save_first_use_progress(path, bad, reset=True)
                self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self._partials(path), [])

    def test_can_revert_step_to_pending_and_reset_all_with_base_or_reset(self):
        path = self.base / fu.PROGRESS_FILENAME
        base = fu.empty_first_use_steps()
        done_steps = dict(base, diagnostico=fu.DONE, explorar=fu.SKIPPED)
        fu.save_first_use_progress(path, done_steps, base_steps=base)

        # Com base_steps: voltar para pendente e recomeçar tudo gravam no disco
        fu.save_first_use_progress(
            path,
            dict(done_steps, explorar=fu.PENDING),
            base_steps=done_steps,
        )
        self.assertEqual(
            fu.load_first_use_progress(self.base)['steps'],
            dict(base, diagnostico=fu.DONE),
        )
        fu.save_first_use_progress(
            path,
            fu.empty_first_use_steps(),
            base_steps=dict(base, diagnostico=fu.DONE),
        )
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], base)

        # Com reset=True: recomeçar todas as marcações sem base_steps grava tudo pendente
        fu.save_first_use_progress(path, done_steps, base_steps=base)
        fu.save_first_use_progress(path, fu.empty_first_use_steps(), reset=True)
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], base)

    def test_permission_error_is_not_called_corrupt_and_retries(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text(json.dumps({'schema': fu.SCHEMA, 'steps': {}}), encoding='utf-8')
        with mock.patch.object(fu, '_read_bytes_with_retry', side_effect=PermissionError(13, 'ocupado')):
            loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('não pôde ser lido' in w for w in loaded['warnings']))
        self.assertFalse(any('estragado' in w for w in loaded['warnings']))

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
        saved = dict(fu.empty_first_use_steps(), backup=fu.DONE)
        fu.save_first_use_progress(second, saved, base_steps=fu.empty_first_use_steps())

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], second)
        self.assertEqual(loaded['steps'], saved)
        self.assertEqual(len(loaded['warnings']), 1)
        self.assertNotIn('começou do zero', loaded['warnings'][0])
        self.assertIn('primeiro-uso-progresso-2.json', loaded['warnings'][0])

    def test_real_symlink_is_not_followed_and_target_remains_unchanged(self):
        target = self.tmp / 'alvo-real.json'
        target_bytes = json.dumps(
            {'schema': fu.SCHEMA, 'steps': dict(fu.empty_first_use_steps(), diagnostico=fu.DONE)}
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
            fu.save_first_use_progress(
                first,
                fu.empty_first_use_steps(),
                base_steps=fu.empty_first_use_steps(),
            )
        self.assertEqual(target.read_bytes(), target_bytes)

    def test_directory_in_place_of_file_is_untouched_and_refused(self):
        first = self.base / fu.PROGRESS_FILENAME
        first.mkdir(parents=True)
        marker = first / 'conteudo.txt'
        marker.write_text('nao apagar', encoding='utf-8')

        loaded = fu.load_first_use_progress(self.base)
        self.assertEqual(loaded['path'], self.base / 'primeiro-uso-progresso-2.json')
        self.assertTrue(any('não é um arquivo comum' in w for w in loaded['warnings']))
        with self.assertRaises(OSError):
            fu.save_first_use_progress(
                first,
                fu.empty_first_use_steps(),
                base_steps=fu.empty_first_use_steps(),
            )
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
                fu.save_first_use_progress(
                    path,
                    fu.empty_first_use_steps(),
                    base_steps=fu.empty_first_use_steps(),
                )
        msg = fu.first_use_error_text(ctx.exception)
        self.assertIn('TimeoutError', msg)
        self.assertNotIn(str(self.base), msg)

    def test_partial_request_with_base_steps_preserves_other_window_entry(self):
        path = self.base / fu.PROGRESS_FILENAME
        initial = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, initial, base_steps=initial)

        # Outra janela grava explorar=feito
        fu.save_first_use_progress(path, {'explorar': fu.DONE}, base_steps=initial)

        # Pedido parcial com base_steps onde explorar estava feito na base local:
        # etapas que não vieram no pedido não podem virar pendente e apagar o disco.
        local_base = dict(initial, explorar=fu.DONE)
        merged = fu.save_first_use_progress(
            path,
            {'diagnostico': fu.DONE},
            base_steps=local_base,
        )
        self.assertEqual(merged['diagnostico'], fu.DONE)
        self.assertEqual(merged['explorar'], fu.DONE)
        self.assertEqual(
            fu.load_first_use_progress(self.base)['steps']['explorar'],
            fu.DONE,
        )

    def test_reset_flag_overwrites_other_window_entry_and_still_refuses_bad_file(self):
        path = self.base / fu.PROGRESS_FILENAME
        base = fu.empty_first_use_steps()
        fu.save_first_use_progress(
            path,
            dict(base, diagnostico=fu.DONE, explorar=fu.DONE),
            base_steps=base,
        )

        reset_result = fu.save_first_use_progress(
            path,
            dict(base, backup=fu.SKIPPED),
            base_steps=dict(base, diagnostico=fu.DONE),
            reset=True,
        )
        expected = dict(base, backup=fu.SKIPPED)
        self.assertEqual(reset_result, expected)
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], expected)

        corrupt = self.base / 'primeiro-uso-progresso-2.json'
        corrupt.write_text('{ quebrado', encoding='utf-8')
        with self.assertRaises(OSError):
            fu.save_first_use_progress(corrupt, fu.empty_first_use_steps(), reset=True)

    def test_concurrent_threads_race_with_exclusive_lock_preserves_both(self):
        path = self.base / fu.PROGRESS_FILENAME
        base = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, base, base_steps=base)

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
                fu.save_first_use_progress(
                    path,
                    dict(base, diagnostico=fu.DONE),
                    base_steps=base,
                )
            except Exception as exc:  # pragma: no cover - falha do teste
                errors.append(exc)

        def writer_b():
            nonlocal thread_b_id
            thread_b_id = threading.get_ident()
            try:
                fu.save_first_use_progress(
                    path,
                    dict(base, explorar=fu.DONE),
                    base_steps=base,
                )
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
            # B está bloqueada na trava exclusiva enquanto A não termina
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
        self.assertEqual(loaded['steps']['diagnostico'], fu.DONE)
        self.assertEqual(loaded['steps']['explorar'], fu.DONE)


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

    def test_initial_steps_is_required(self):
        with self.assertRaises(TypeError):
            fu.FirstUseProgressSaver(self.path)

    def test_latest_request_wins_and_coalesces_intermediate(self):
        release = threading.Event()
        started = threading.Event()
        calls = []
        wait_results = []

        def fake_save(path, steps, **kwargs):
            started.set()
            wait_results.append(release.wait(5))
            calls.append((path, dict(steps), kwargs))
            return steps

        saver = self._make_saver(initial_steps=fu.empty_first_use_steps(), save=fake_save)
        first = dict(fu.empty_first_use_steps(), diagnostico=fu.DONE)
        second = dict(first, explorar=fu.SKIPPED)
        third = dict(second, preservacao=fu.DONE)

        saver.request(first)
        self.assertTrue(started.wait(5))
        saver.request(second)
        saver.request(third)
        self.assertEqual(saver.pending_steps(), third)
        release.set()
        self.assertTrue(saver.join(5))

        self.assertEqual(wait_results, [True, True])
        self.assertEqual([c[1] for c in calls], [first, third])
        self.assertIsNone(saver.pending_steps())
        self.assertIsNone(saver.poll_error())

    def test_real_saver_preserves_other_instance_and_can_revert_to_pending(self):
        initial = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, initial, base_steps=initial)
        saver = self._make_saver(initial_steps=initial)

        # Marca diagnostico=feito pelo gravador real
        step1 = dict(initial, diagnostico=fu.DONE)
        saver.request(step1)
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())

        # Outra instância grava explorar=feito entre dois pedidos
        fu.save_first_use_progress(
            self.path,
            dict(initial, explorar=fu.DONE),
            base_steps=initial,
        )

        # Esta janela volta diagnostico para pendente (feito -> clicar de novo -> pendente)
        step2 = dict(initial, diagnostico=fu.PENDING)
        saver.request(step2)
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        merged = saver.poll_merged()
        self.assertEqual(merged['diagnostico'], fu.PENDING)
        self.assertEqual(merged['explorar'], fu.DONE)
        self.assertEqual(
            fu.load_first_use_progress(self.path.parent)['steps'],
            merged,
        )

        # Recomeçar marcações com reset=True: volta todas as etapas (inclusive
        # nova marcação gravada por outra janela) para pendente
        fu.save_first_use_progress(
            self.path,
            dict(initial, backup=fu.DONE),
            base_steps=merged,
        )
        reset = fu.empty_first_use_steps()
        saver.request(reset, reset=True)
        self.assertTrue(saver.join(5))
        self.assertEqual(fu.load_first_use_progress(self.path.parent)['steps'], reset)

    def test_saver_partial_request_preserves_other_window_entry(self):
        initial = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, initial, base_steps=initial)
        saver = self._make_saver(initial_steps=initial)

        # Outra janela grava explorar=feito no disco
        fu.save_first_use_progress(self.path, {'explorar': fu.DONE}, base_steps=initial)

        # Esta janela envia apenas diagnostico=feito (pedido parcial)
        saver.request({'diagnostico': fu.DONE})
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        merged = saver.poll_merged()
        self.assertEqual(merged['diagnostico'], fu.DONE)
        self.assertEqual(merged['explorar'], fu.DONE)
        self.assertEqual(
            fu.load_first_use_progress(self.path.parent)['steps'],
            merged,
        )

    def test_saver_ignores_requests_after_close(self):
        saver = self._make_saver(
            initial_steps=fu.empty_first_use_steps(),
        )
        saver.close()
        saver.request({'diagnostico': fu.DONE})
        self.assertFalse(saver.busy())
        self.assertIsNone(saver.pending_steps())

    def test_saver_accepts_none_path(self):
        no_path_saver = fu.FirstUseProgressSaver(
            None,
            initial_steps=fu.empty_first_use_steps(),
        )
        self._savers.append(no_path_saver)
        no_path_saver.request({'diagnostico': fu.DONE})
        self.assertFalse(no_path_saver.busy())
        self.assertIsNone(no_path_saver.pending_steps())
        self.assertTrue(no_path_saver.join(1))

    def test_saver_coalesces_reset_then_normal_preserving_reset_true(self):
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, empty, base_steps=empty)
        started = threading.Event()
        release = threading.Event()
        seen_calls: list[tuple[dict[str, str], dict]] = []

        release_results: list[bool] = []

        def fake_save(path, steps, **kwargs):
            seen_calls.append((dict(steps), dict(kwargs)))
            if len(seen_calls) == 1:
                started.set()
                # Conferido depois do join, na thread do teste.
                release_results.append(release.wait(5))
            return fu.save_first_use_progress(path, steps, **kwargs)

        saver = self._make_saver(initial_steps=empty, save=fake_save)
        saver.request(dict(empty, preservacao=fu.DONE))
        self.assertTrue(started.wait(5))

        # Outra janela grava explorar=feito enquanto o primeiro pedido está pausado
        fu.save_first_use_progress(
            self.path,
            dict(empty, explorar=fu.DONE),
            base_steps=empty,
        )
        # Recomeçar seguido de um Feito rápido: o segundo pedido herda reset=True
        saver.request(empty, reset=True)
        saver.request(dict(empty, diagnostico=fu.DONE))
        self.assertTrue(saver.pending_is_reset())
        release.set()
        self.assertTrue(saver.join(5))

        self.assertEqual(release_results, [True])
        self.assertEqual(len(seen_calls), 2)
        self.assertFalse(seen_calls[0][1]['reset'])
        self.assertTrue(seen_calls[1][1]['reset'])
        self.assertEqual(seen_calls[1][0], dict(empty, diagnostico=fu.DONE))
        self.assertIn('base_steps', seen_calls[1][1])
        loaded = fu.load_first_use_progress(self.path.parent)['steps']
        self.assertEqual(loaded['diagnostico'], fu.DONE)
        self.assertEqual(loaded['explorar'], fu.PENDING)

    def test_save_error_is_sanitized_and_cleared_on_next_success(self):
        outcomes = [
            PermissionError(13, 'segredo', r'C:\Users\segredo\primeiro-uso-progresso.json'),
            None,
        ]

        def fake_save(path, steps, **kwargs):
            item = outcomes.pop(0)
            if item is not None:
                raise item
            return fu.save_first_use_progress(path, steps, **kwargs)

        saver = self._make_saver(initial_steps=fu.empty_first_use_steps(), save=fake_save)
        saver.request({'diagnostico': fu.DONE})
        self.assertTrue(saver.join(5))
        err = saver.poll_error()
        self.assertIsNotNone(err)
        self.assertNotIn('segredo', err)
        self.assertIn(f'"{fu.PROGRESS_FILENAME}"', err)
        self.assertNotIn(str(self.tmp), err)
        self.assertEqual(fu.first_use_warning_text('aviso base', err), err)

        saver.request({'diagnostico': fu.SKIPPED})
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        self.assertEqual(fu.first_use_warning_text('aviso base', saver.poll_error()), 'aviso base')
        loaded = fu.load_first_use_progress(self.path.parent)
        self.assertEqual(loaded['steps']['diagnostico'], fu.SKIPPED)

    def test_load_with_pending_reads_pending_before_disk(self):
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, {'diagnostico': fu.PENDING}, base_steps=empty)
        release = threading.Event()
        saver = self._make_saver(
            initial_steps=empty,
            save=lambda p, st, **kw: (release.wait(5), fu.save_first_use_progress(p, st, **kw))[1],
        )
        newer = dict(empty, diagnostico=fu.DONE)
        saver.request(newer)
        order = []

        def fake_load(base):
            order.append('disk')
            release.set()
            self.assertTrue(saver.join(5))
            return fu.load_first_use_progress(base)

        real_pending = saver.pending_steps

        def spy_pending():
            order.append('pending')
            return real_pending()

        saver.pending_steps = spy_pending
        result = fu.load_first_use_with_pending(self.path.parent, saver, load=fake_load)
        self.assertEqual(order, ['pending', 'disk'])
        self.assertEqual(result['steps']['diagnostico'], fu.DONE)

    def test_load_with_pending_merges_partial_pending_over_disk(self):
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, dict(empty, explorar=fu.DONE), base_steps=empty)
        started = threading.Event()
        release = threading.Event()
        saver = self._make_saver(
            initial_steps=empty,
            save=lambda p, st, **kw: (started.set(), release.wait(5), fu.save_first_use_progress(p, st, **kw))[2],
        )
        saver.request({'diagnostico': fu.DONE})
        self.assertTrue(started.wait(5))
        try:
            loaded = fu.load_first_use_with_pending(self.path.parent, saver)
            self.assertEqual(set(loaded['steps'].keys()), set(fu.STEP_IDS))
            self.assertEqual(loaded['steps']['diagnostico'], fu.DONE)
            self.assertEqual(loaded['steps']['explorar'], fu.DONE)
        finally:
            release.set()

    def test_load_with_pending_reset_ignores_disk_and_returns_full_dict(self):
        empty = fu.empty_first_use_steps()
        fu.save_first_use_progress(self.path, dict(empty, explorar=fu.DONE), base_steps=empty)
        started = threading.Event()
        release = threading.Event()
        saver = self._make_saver(
            initial_steps=empty,
            save=lambda p, st, **kw: (started.set(), release.wait(5), fu.save_first_use_progress(p, st, **kw))[2],
        )
        saver.request({'diagnostico': fu.DONE}, reset=True)
        self.assertTrue(started.wait(5))
        try:
            loaded = fu.load_first_use_with_pending(self.path.parent, saver)
            self.assertEqual(set(loaded['steps'].keys()), set(fu.STEP_IDS))
            self.assertEqual(loaded['steps']['diagnostico'], fu.DONE)
            self.assertEqual(loaded['steps']['explorar'], fu.PENDING)
        finally:
            release.set()


if __name__ == '__main__':
    unittest.main()
