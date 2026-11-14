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

# Mapa dos rótulos entre aspas citados em first_use.py -> (módulo, função que monta a tela)
EXPECTED_STEP_LABELS = {
    'Abrir': ('after_format_ui.py', 'show_after_format'),
    'Diagnóstico': ('app.py', 'App._build_sidebar'),
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
    '8  Ajustes seguros': ('optimization_ui.py', 'OptimizationPanel._build'),
    '9  Ajustes avançados': ('optimization_ui.py', 'OptimizationPanel._build'),
}

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
            self.assertIn('não apaga nenhum arquivo', intro)
            self.assertIn(f'o que não for copiado do {drive} não entra no backup', intro)
            self.assertIn(f'se perde quando o instalador formatar o {drive}', intro)

            by_id = {s['id']: s for s in steps}
            self.assertIn('não apaga nenhum arquivo', by_id['explorar']['text'])
            self.assertIn(
                f'se perde quando o instalador formatar o {drive}',
                by_id['explorar']['text'],
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
                if drive == 'W:':
                    self.assertNotIn('C:', text)

    def test_default_drive_uses_workflow_texts_system_drive(self):
        with mock.patch.object(fu, 'system_drive', return_value='Z:'):
            self.assertIn('Z:', fu.FIRST_USE_INTRO_TEXT())
            steps = fu.FIRST_USE_STEPS()
            self.assertTrue(any('Z:' in s['text'] for s in steps))

    def test_every_quoted_label_exists_in_reachable_screen_builder(self):
        project = _Project(ROOT)
        reach = project.reachable(blocked=BLOCKED_EDGES)
        texts = [fu.FIRST_USE_INTRO_TEXT('C:'), fu.FIRST_USE_MODE_NOTE] + [
            step['text'] for step in fu.FIRST_USE_STEPS('C:')
        ]
        quoted = set()
        for text in texts:
            quoted |= _quoted_names(text)

        known = {_norm(k) for k in EXPECTED_STEP_LABELS} | {_norm(k) for k in WINDOWS_LABELS}
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
        fu.save_first_use_progress(loaded['path'], updated)
        again = fu.load_first_use_progress(self.base)
        self.assertEqual(again['steps'], updated)
        self.assertEqual(again['path'], loaded['path'])
        self.assertEqual(again['warnings'], [])

    def test_invalid_step_or_status_raises_value_error(self):
        path = self.base / fu.PROGRESS_FILENAME
        with self.assertRaises(ValueError):
            fu.validate_first_use_steps('invalido')
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'inexistente': fu.DONE})
        with self.assertRaises(ValueError):
            fu.save_first_use_progress(path, {'diagnostico': 'talvez'})
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
            self.assertTrue(any('atalho (link)' in w for w in loaded['warnings']))
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
        for secret in ('usuario_secreto', 'Users', 'AppData', 'Acesso negado'):
            self.assertNotIn(secret, msg)

    def test_failed_replace_keeps_partial_without_deleting(self):
        path = self.base / fu.PROGRESS_FILENAME
        fu.save_first_use_progress(path, {'diagnostico': fu.DONE})
        before = path.read_bytes()
        with mock.patch.object(fu.os, 'replace', side_effect=OSError('falha')):
            with self.assertRaises(OSError):
                fu.save_first_use_progress(path, {'diagnostico': fu.SKIPPED})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self._partials(path)), 1)

    def test_concurrent_instance_save_preserves_other_instance_entry(self):
        path = self.base / fu.PROGRESS_FILENAME
        base_steps = fu.empty_first_use_steps()
        fu.save_first_use_progress(path, base_steps)

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

    def test_latest_request_wins_and_coalesces_intermediate(self):
        release = threading.Event()
        started = threading.Event()
        calls = []

        def fake_save(path, steps):
            started.set()
            self.assertTrue(release.wait(5))
            calls.append((path, dict(steps)))
            return steps

        saver = self._make_saver(save=fake_save)
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

        self.assertLessEqual(len(calls), 2)
        self.assertEqual(calls[-1], (self.path, third))
        self.assertNotIn(second, [c[1] for c in calls])
        self.assertIsNone(saver.pending_steps())
        self.assertIsNone(saver.poll_error())

    def test_save_error_is_sanitized_and_cleared_on_next_success(self):
        outcomes = [
            PermissionError(13, 'segredo', r'C:\Users\segredo\primeiro-uso-progresso.json'),
            None,
        ]

        def fake_save(path, steps):
            item = outcomes.pop(0)
            if item is not None:
                raise item
            return fu.save_first_use_progress(path, steps)

        saver = self._make_saver(save=fake_save)
        saver.request({'diagnostico': fu.DONE})
        self.assertTrue(saver.join(5))
        err = saver.poll_error()
        self.assertIsNotNone(err)
        self.assertNotIn('segredo', err)
        self.assertEqual(fu.first_use_warning_text('aviso base', err), err)

        saver.request({'diagnostico': fu.SKIPPED})
        self.assertTrue(saver.join(5))
        self.assertIsNone(saver.poll_error())
        self.assertEqual(fu.first_use_warning_text('aviso base', saver.poll_error()), 'aviso base')
        loaded = fu.load_first_use_progress(self.path.parent)
        self.assertEqual(loaded['steps']['diagnostico'], fu.SKIPPED)

    def test_load_with_pending_reads_pending_before_disk(self):
        fu.save_first_use_progress(self.path, {'diagnostico': fu.PENDING})
        release = threading.Event()
        saver = self._make_saver(
            save=lambda p, st: (release.wait(5), fu.save_first_use_progress(p, st))[1]
        )
        newer = dict(fu.empty_first_use_steps(), diagnostico=fu.DONE)
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


if __name__ == '__main__':
    unittest.main()
