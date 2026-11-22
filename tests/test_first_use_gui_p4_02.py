"""P4-02 (Fatia 2): testes da janela "Primeiro uso guiado" (`first_use_ui.py`).

Duas partes:
1. Sem Tk (objetos falsos): a lógica `FirstUseFlow` e a reabertura da mesma
   janela. Rodam também num subprocesso com `sys.modules['tkinter'] = None`
   (R-87: nada é trocado em `sys.modules` neste processo).
2. Com Tk real (`track_tk_root`), ignorados quando não há tkinter ou display.

Tudo em `TemporaryDirectory`; nenhum disco real, nenhuma varredura, cópia,
restauração ou diagnóstico. Os gravadores são esperados (`join`) antes de a
pasta temporária ser removida (R-29).
"""
from __future__ import annotations

import ast
import os
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
import first_use_ui as fui
from tests.test_manual import BLOCKED_EDGES, _Project, _norm
from tests.tk_helpers import track_tk_root

try:  # pragma: no cover - depende do Python instalado
    import tkinter as tk
except ImportError:  # pragma: no cover - servidor Linux sem tkinter
    tk = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'first_use_ui.py').read_text(encoding='utf-8')
NO_TK_CHILD_ENV = 'PCRO_FIRST_USE_GUI_NO_TK_CHILD'
PAGES = ('diagnostic', 'home', 'preservation', 'review', 'history', 'installation')
WINDOW_LABELS = ('Abrir', 'Feito', 'Pular', 'Recomeçar marcações', 'Fechar')
FORBIDDEN_R88 = ('não mexe', 'nao mexe', 'intact', 'só grava', 'so grava', 'só lê',
                 'so le', 'só leitura')


def _all(**changes) -> dict[str, str]:
    return dict(fu.empty_first_use_steps(), **changes)


class FakeApp:
    """App falso: só as páginas e `navigate`; qualquer outra coisa falha."""

    _ALLOWED = {'navigate', 'first_use_saver', 'first_use_dialog', 'calls'} | set(PAGES)

    def __init__(self):
        object.__setattr__(self, 'calls', [])
        for name in PAGES:
            object.__setattr__(self, name, f'pagina:{name}')
        object.__setattr__(self, 'first_use_saver', None)
        object.__setattr__(self, 'first_use_dialog', None)

    def navigate(self, page):
        self.calls.append(('navigate', page))

    def __getattr__(self, name):  # só é chamado para atributo que não existe
        raise AssertionError(f'a janela usou app.{name}, que não é navegação')

    def __setattr__(self, name, value):
        if name not in self._ALLOWED:
            raise AssertionError(f'a janela mudou app.{name}')
        object.__setattr__(self, name, value)


class FakeView:
    def __init__(self):
        self.status = {}
        self.warning = None
        self.ready = None
        self.timers = []
        self.events = []
        self.destroyed = False

    def set_status(self, step_id, text):
        self.status[step_id] = text

    def set_warning(self, text):
        self.warning = text

    def set_ready(self, ready):
        self.ready = ready
        self.events.append(('ready', ready))

    def after(self, ms, callback):
        self.timers.append(callback)

    def destroy(self):
        self.destroyed = True
        self.events.append(('destroy',))

    def warn(self, text):
        self.events.append(('warn', text))

    def pump(self, rounds=1):
        for _ in range(rounds):
            current, self.timers = self.timers, []
            for callback in current:
                callback()


class FakeJob:
    """Job falso: guarda o trabalho; o teste decide quando ele termina."""

    def __init__(self, work):
        self.work = work
        self.cancelled = threading.Event()
        self.result = None

    def finish(self):
        try:
            self.result = ('done', self.work(self.cancelled, lambda *a: None))
        except Exception as exc:  # noqa: BLE001
            self.result = ('error', str(exc))

    def poll(self):
        return self.result


class FakeSaver:
    def __init__(self, path, *, pending=None, busy=False, error=None):
        self.path = Path(path)
        self.closed = False
        self.requests = []
        self._pending = pending
        self._busy = busy
        self._error = error

    def request(self, steps):
        fu.validate_complete_first_use_steps(steps)
        self.requests.append(dict(steps))

    def pending(self):
        return self._pending

    def busy(self):
        return self._busy

    def poll_error(self):
        return self._error

    def join(self, timeout=None):  # pragma: no cover - a janela nunca espera
        raise AssertionError('a janela não pode esperar a gravação')


class FlowTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / 'dados-do-app'
        self.path = self.base / fu.PROGRESS_FILENAME
        self._savers = []
        self.addCleanup(self._join_savers)  # R-29: roda antes de apagar a pasta
        self.app = FakeApp()
        self.view = FakeView()
        self.jobs = []

    def _join_savers(self):
        for saver in self._savers + [self.app.first_use_saver]:
            if isinstance(saver, fu.FirstUseProgressSaver):
                self.assertTrue(saver.join(5))

    def job_factory(self, work):
        job = FakeJob(work)
        self.jobs.append(job)
        return job

    def make_flow(self, **kwargs):
        return fui.FirstUseFlow(self.app, self.view, base=self.base,
                                steps=fu.FIRST_USE_STEPS('W:'),
                                job_factory=self.job_factory, **kwargs)

    def loaded_flow(self):
        flow = self.make_flow()
        flow.start()
        self.jobs[-1].finish()
        self.view.pump()
        self.assertTrue(flow.ready)
        return flow


class FlowLoadingTests(FlowTestBase):
    def test_reading_waits_for_job_and_buttons_start_disabled(self):
        flow = self.make_flow()
        flow.start()
        self.assertEqual(set(self.view.status.values()), {'Carregando...'})
        self.assertIs(self.view.ready, False)
        self.assertEqual(len(self.jobs), 1)
        # a leitura ainda não aconteceu: nada vem do disco antes do Job
        flow.mark('diagnostico', fu.DONE)
        flow.reset()
        self.view.pump()
        self.assertEqual(set(self.view.status.values()), {'Carregando...'})
        self.assertIsNone(self.app.first_use_saver)
        self.jobs[0].finish()
        self.view.pump()
        self.assertIs(self.view.ready, True)
        self.assertEqual(set(self.view.status.values()), {'Pendente'})
        self.assertEqual(self.app.first_use_saver.path, self.path)

    def test_default_reading_runs_in_job_thread_not_tk_thread(self):
        threads = []

        def spy_load(base, saver):
            threads.append(threading.current_thread())
            return fu.load_first_use_progress(base)

        flow = fui.FirstUseFlow(self.app, self.view, base=self.base,
                                steps=fu.FIRST_USE_STEPS('W:'))
        self.assertIs(flow.job_factory, fui.Job)
        with mock.patch.object(fui, 'load_first_use_with_pending', side_effect=spy_load):
            flow.start()
            deadline = time.monotonic() + 5
            while not flow.ready and time.monotonic() < deadline:
                self.view.pump()
                time.sleep(0.01)
        self.assertTrue(flow.ready)
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())

    def test_saved_marks_are_shown_after_loading(self):
        fu.save_first_use_progress(self.path, _all(backup=fu.DONE, testar=fu.SKIPPED))
        self.loaded_flow()
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(self.view.status['testar'], 'Pulado')
        self.assertEqual(self.view.status['diagnostico'], 'Pendente')
        self.assertEqual(self.view.warning, '')

    def test_corrupt_file_warning_has_only_file_name(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{ quebrado', encoding='utf-8')
        self.loaded_flow()
        self.assertIn(f'"{fu.PROGRESS_FILENAME}"', self.view.warning)
        self.assertIn('foi deixado como está', self.view.warning)
        self.assertEqual(self.app.first_use_saver.path, self.base / 'primeiro-uso-progresso-2.json')
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{ quebrado')

    def test_symlink_warning_has_only_file_name(self):
        target = self.base.parent / 'alvo.json'
        target.write_text('{}', encoding='utf-8')
        self.base.mkdir(parents=True)
        try:
            os.symlink(target, self.path)
        except OSError as exc:
            self.skipTest(f'sem permissão de symlink: {exc}')
        self.loaded_flow()
        self.assertIn('é um link ou um arquivo especial do Windows', self.view.warning)
        self.assertIn(fu.PROGRESS_FILENAME, self.view.warning)
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertEqual(target.read_text(encoding='utf-8'), '{}')

    def test_job_error_becomes_fixed_text_without_path(self):
        flow = self.make_flow()
        with mock.patch.object(fui, 'load_first_use_with_pending',
                               side_effect=OSError(f'falha em {self.base}')):
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        self.assertEqual(self.view.warning, fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertIsNone(flow.saver)
        flow.mark('backup', fu.DONE)  # marca em memória, sem gravar
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertFalse(self.path.exists())
        flow.close()  # FIX-P4-02-03: avisa que nada desta janela foi salvo
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT)])
        self.assertFalse(self.path.exists())

    def test_reopen_reuses_saver_of_same_file_and_reads_its_pending(self):
        old = FakeSaver(self.path, pending=_all(explorar=fu.DONE), busy=True)
        self.app.first_use_saver = old
        flow = self.loaded_flow()
        self.assertIs(flow.saver, old)
        self.assertEqual(self.view.status['explorar'], 'Feito')
        flow.mark('backup', fu.DONE)
        self.assertEqual(old.requests, [_all(explorar=fu.DONE, backup=fu.DONE)])


class FlowMarkTests(FlowTestBase):
    def setUp(self):
        super().setUp()
        self.saver = FakeSaver(self.path)
        self.app.first_use_saver = self.saver

    def test_done_and_skip_change_label_at_once_and_toggle_back(self):
        flow = self.loaded_flow()
        flow.mark('diagnostico', fu.DONE)
        self.assertEqual(self.view.status['diagnostico'], 'Feito')
        flow.mark('explorar', fu.SKIPPED)
        self.assertEqual(self.view.status['explorar'], 'Pulado')
        flow.mark('diagnostico', fu.DONE)  # clicar de novo volta a Pendente
        self.assertEqual(self.view.status['diagnostico'], 'Pendente')
        flow.mark('explorar', fu.SKIPPED)
        self.assertEqual(self.view.status['explorar'], 'Pendente')
        flow.mark('backup', fu.SKIPPED)
        flow.mark('backup', fu.DONE)  # trocar de Pulado para Feito
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(self.saver.requests, [
            _all(diagnostico=fu.DONE),
            _all(diagnostico=fu.DONE, explorar=fu.SKIPPED),
            _all(explorar=fu.SKIPPED),
            _all(),
            _all(backup=fu.SKIPPED),
            _all(backup=fu.DONE),
        ])
        for steps in self.saver.requests:
            self.assertEqual(tuple(steps), fu.STEP_IDS)

    def test_reset_brings_all_six_back_to_pending(self):
        flow = self.loaded_flow()
        for step_id in fu.STEP_IDS:
            flow.mark(step_id, fu.DONE)
        flow.reset()
        self.assertEqual(set(self.view.status.values()), {'Pendente'})
        self.assertEqual(self.saver.requests[-1], fu.empty_first_use_steps())
        self.assertEqual(len(self.saver.requests[-1]), 6)

    def test_marks_never_write_on_the_tk_thread(self):
        threads = []

        def spy_save(path, steps):
            threads.append(threading.current_thread())
            fu.save_first_use_progress(path, steps)

        real = fu.FirstUseProgressSaver(self.path, save=spy_save)
        self._savers.append(real)
        self.app.first_use_saver = real
        flow = self.loaded_flow()
        flow.mark('diagnostico', fu.DONE)
        flow.reset()
        self.assertTrue(real.join(5))
        self.assertTrue(threads)
        for thread in threads:
            self.assertIsNot(thread, threading.current_thread())
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], _all())

    def test_save_error_shows_in_warning_line(self):
        self.saver._error = fu.first_use_error_text(OSError('x'), self.path)
        flow = self.loaded_flow()
        flow.mark('diagnostico', fu.DONE)
        self.view.pump()
        self.assertEqual(self.view.warning, self.saver._error)
        self.assertNotIn(str(self.base), self.view.warning)

    def test_open_only_navigates_to_existing_pages(self):
        flow = self.loaded_flow()
        for step in fu.FIRST_USE_STEPS('W:'):
            flow.open_step(step['id'])
        self.assertEqual(self.app.calls,
                         [('navigate', f'pagina:{page}') for page in PAGES])
        self.assertEqual(self.saver.requests, [])  # "Abrir" não mexe nas marcações
        self.assertEqual(set(self.view.status.values()), {'Pendente'})

    def test_open_refuses_page_outside_list(self):
        steps = list(fu.FIRST_USE_STEPS('W:'))
        steps[0] = dict(steps[0], page='optimization')
        flow = fui.FirstUseFlow(self.app, self.view, base=self.base, steps=steps,
                                job_factory=self.job_factory)
        with self.assertRaises(ValueError):
            flow.open_step(steps[0]['id'])
        self.assertEqual(self.app.calls, [])


class FlowCloseTests(FlowTestBase):
    def _flow_with(self, saver):
        self.app.first_use_saver = saver
        return self.loaded_flow()

    def test_close_without_pending_just_closes(self):
        flow = self._flow_with(FakeSaver(self.path))
        flow.close()
        self.assertEqual(self.view.events[-1], ('destroy',))
        self.assertTrue(flow.closed)

    def test_close_while_saving_warns_fixed_text_after_closing(self):
        saver = FakeSaver(self.path, pending=_all(backup=fu.DONE), busy=True)
        flow = self._flow_with(saver)
        flow.close()
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.FIRST_USE_CLOSE_SAVING_TEXT)])
        self.assertFalse(saver.closed)  # a gravação continua depois de fechar

    def test_close_after_failed_save_warns_saver_error(self):
        error = fu.first_use_error_text(PermissionError(13, 'x', str(self.path)), self.path)
        saver = FakeSaver(self.path, pending=_all(backup=fu.DONE), busy=False, error=error)
        flow = self._flow_with(saver)
        flow.close()
        self.assertEqual(self.view.events[-1], ('warn', error))
        self.assertNotIn(str(self.base), error)

    def test_failed_save_after_close_shows_error_when_guide_reopens(self):
        # R-86: o caminho que FIRST_USE_CLOSE_SAVING_TEXT promete, com o
        # gravador REAL: a gravação ainda está em curso ao fechar, falha depois,
        # e o aviso de erro aparece ao reabrir, sem nenhum clique novo.
        started = threading.Event()
        release = threading.Event()
        waited = []

        def failing_save(path, steps):
            started.set()
            waited.append(release.wait(5))
            raise PermissionError(13, 'acesso negado', str(path))

        saver = fu.FirstUseProgressSaver(self.path, save=failing_save)
        self._savers.append(saver)
        self.addCleanup(release.set)  # registrado depois: roda antes do join (R-29)
        flow = self._flow_with(saver)
        flow.mark('backup', fu.DONE)
        self.assertTrue(started.wait(5))
        flow.close()
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.FIRST_USE_CLOSE_SAVING_TEXT)])
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(waited, [True])
        expected = fu.first_use_error_text(PermissionError(13, 'x'), self.path)
        self.assertEqual(saver.poll_error(), expected)
        self.assertFalse(self.path.exists())

        # reabre com o MESMO app, sem marcar nada
        self.view = FakeView()
        again = self.loaded_flow()
        self.assertIs(again.saver, saver)
        self.assertEqual(self.view.warning, expected)
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(again.steps, _all(backup=fu.DONE))
        self.assertFalse(saver.busy())  # nenhuma gravação nova foi pedida

    def test_close_cancels_reading_and_stops_polling(self):
        flow = self.make_flow()
        flow.start()
        job = self.jobs[0]
        flow.close()
        self.assertTrue(job.cancelled.is_set())
        job.finish()
        self.view.pump()
        self.assertFalse(flow.ready)
        flow.mark('backup', fu.DONE)
        self.assertNotIn('Feito', self.view.status.values())

    def test_close_with_real_saver_does_not_wait_for_write(self):
        started = threading.Event()
        release = threading.Event()
        waited = []

        def slow_save(path, steps):
            started.set()
            waited.append(release.wait(5))
            fu.save_first_use_progress(path, steps)

        saver = fu.FirstUseProgressSaver(self.path, save=slow_save)
        self._savers.append(saver)
        flow = self._flow_with(saver)
        self.addCleanup(release.set)  # roda antes do join (R-29)
        flow.mark('preservacao', fu.DONE)
        self.assertTrue(started.wait(5))
        began = time.monotonic()
        flow.close()
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(self.view.events[-1], ('warn', fu.FIRST_USE_CLOSE_SAVING_TEXT))
        release.set()
        self.assertTrue(saver.join(5))
        self.assertEqual(waited, [True])
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'],
                         _all(preservacao=fu.DONE))


class PreviousSaverTests(FlowTestBase):
    """FIX-P4-02-01: a janela reabre e escolhe entre o gravador antigo do app e
    um novo; o erro e as marcações pendentes do antigo continuam visíveis ou
    passam ao novo (leitura falhando, arquivo trocado e fechar carregando)."""

    def _error(self):
        return fu.first_use_error_text(PermissionError(13, 'x', str(self.path)), self.path)

    def _failing_load(self):
        return mock.patch.object(fui, 'load_first_use_with_pending',
                                 side_effect=OSError(f'falha em {self.base}'))

    # item 1: gravação falhou e, ao reabrir, a leitura também falha
    def test_load_error_keeps_failed_pending_and_error_of_old_saver(self):
        error = self._error()
        old = FakeSaver(self.path, pending=_all(backup=fu.DONE), error=error)
        self.app.first_use_saver = old
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        self.assertTrue(flow.ready)
        self.assertIsNone(flow.saver)  # nesta janela nada é gravado
        self.assertIs(self.app.first_use_saver, old)  # o antigo não é largado
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(flow.steps, _all(backup=fu.DONE))
        self.assertEqual(self.view.warning, fu.first_use_load_error_text(True, True))
        self.assertIn(fu.FIRST_USE_PREVIOUS_FAILED_TEXT, self.view.warning)
        self.assertNotIn(str(self.base), self.view.warning)
        flow.mark('explorar', fu.DONE)
        self.assertEqual(old.requests, [])
        flow.close()  # FIX-P4-02-03: aviso próprio, sem o erro que promete nova tentativa
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.first_use_close_load_failed_text(False, True))])
        self.assertNotIn(error, self.view.events[-1][1])

    def test_load_error_with_real_failing_saver_shows_its_marks_and_error(self):
        def failing_save(path, steps):
            raise PermissionError(13, 'acesso negado', str(path))

        saver = fu.FirstUseProgressSaver(self.path, save=failing_save)
        self._savers.append(saver)
        self.app.first_use_saver = saver
        flow = self.loaded_flow()
        flow.mark('backup', fu.DONE)
        self.assertTrue(saver.join(5))
        self.assertIsNotNone(saver.poll_error())
        flow.close()

        self.view = FakeView()
        again = self.make_flow()
        with self._failing_load():
            again.start()
            self.jobs[-1].finish()
        self.view.pump()
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(self.view.warning, fu.first_use_load_error_text(True, True))
        self.assertEqual(saver.pending(), _all(backup=fu.DONE))
        self.assertFalse(self.path.exists())

    # FIX-P4-02-04 (item 4): os dois testes abaixo começam iguais (leitura
    # falha com o gravador antigo ainda gravando) e diferem no que acontece
    # antes do "Fechar"; os nomes dizem qual variante do aviso cada um confere.
    def test_load_error_old_saver_fails_while_window_open_close_warns_failed(self):
        # a gravação antiga falha com a janela aberta: a linha de aviso muda
        # na hora e o "Fechar" usa a variante "também não foram salvas"
        old = FakeSaver(self.path, pending=_all(backup=fu.DONE), busy=True)
        self.app.first_use_saver = old
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        self.assertEqual(self.view.warning, fu.first_use_load_error_text(True, False))
        self.assertTrue(flow.watching)  # olha o antigo enquanto ele grava
        old._busy = False
        old._error = self._error()
        self.view.pump()
        self.assertEqual(self.view.warning, fu.first_use_load_error_text(True, True))
        self.assertFalse(flow.watching)
        flow.close()
        self.assertEqual(self.view.events[-1],
                         ('warn', fu.first_use_close_load_failed_text(False, True)))

    def test_load_error_close_while_old_saver_busy_warns_still_saving(self):
        # fecha com o gravador antigo ainda gravando: variante "ainda está
        # salvando" (o caminho inteiro, com o gravador real, está no teste
        # test_close_while_old_saver_writes_then_fails_error_shows_on_reopen)
        old = FakeSaver(self.path, pending=_all(backup=fu.DONE), busy=True)
        self.app.first_use_saver = old
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        flow.close()
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.first_use_close_load_failed_text(True, False))])

    def _close_failed_read_while_real_saver_writes(self):
        """FIX-P4-02-04 (item 1, R-86/R-101): o caminho que
        FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT promete, com o gravador REAL.
        Marca na 1ª janela; a gravação fica presa; a 2ª janela abre com a
        leitura falhando; "Fechar" mostra a variante "ainda está salvando";
        só depois a gravação falha. Devolve o gravador e o erro esperado."""
        started = threading.Event()
        release = threading.Event()
        waited = []

        def failing_save(path, steps):
            started.set()
            waited.append(release.wait(5))
            raise PermissionError(13, 'acesso negado', str(path))

        saver = fu.FirstUseProgressSaver(self.path, save=failing_save)
        self._savers.append(saver)
        self.addCleanup(release.set)  # registrado depois: roda antes do join (R-29)
        self.app.first_use_saver = saver
        first = self.loaded_flow()
        first.mark('backup', fu.DONE)
        self.assertTrue(started.wait(5))
        first.close()

        self.view = FakeView()
        failed = self.make_flow()
        with self._failing_load():
            failed.start()
            self.jobs[-1].finish()
        self.view.pump()
        self.assertIsNone(failed.saver)
        self.assertIs(failed.previous, saver)
        self.assertTrue(saver.busy())  # a gravação antiga ainda está presa
        failed.close()
        close_text = fu.first_use_close_load_failed_text(True, False)
        self.assertEqual(self.view.events[-2:], [('destroy',), ('warn', close_text)])
        self.assertIn(fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT, close_text)

        release.set()  # agora a gravação falha, com a janela já fechada
        self.assertTrue(saver.join(5))
        self.assertEqual(waited, [True])
        expected = fu.first_use_error_text(PermissionError(13, 'x'), self.path)
        self.assertEqual(saver.poll_error(), expected)
        self.assertFalse(self.path.exists())
        return saver, expected

    def test_close_while_old_saver_writes_then_fails_error_shows_on_reopen(self):
        saver, expected = self._close_failed_read_while_real_saver_writes()
        # reabre com o MESMO app e a leitura dando certo, sem marcar nada
        self.view = FakeView()
        again = self.loaded_flow()
        self.assertIs(again.saver, saver)
        self.assertEqual(self.view.warning, expected)  # o erro na linha de aviso
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(again.steps, _all(backup=fu.DONE))
        self.assertFalse(saver.busy())  # nenhuma gravação nova foi pedida

    def test_close_while_old_saver_writes_then_fails_reopen_failing_read_warns(self):
        saver, _ = self._close_failed_read_while_real_saver_writes()
        # reabre e a leitura falha de novo: o aviso diz que a gravação falhou
        self.view = FakeView()
        again = self.make_flow()
        with self._failing_load():
            again.start()
            self.jobs[-1].finish()
        self.view.pump()
        self.assertEqual(self.view.warning, fu.first_use_load_error_text(True, True))
        self.assertIn(fu.FIRST_USE_PREVIOUS_FAILED_TEXT, self.view.warning)
        self.assertNotIn(str(self.base), self.view.warning)
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertEqual(saver.pending(), _all(backup=fu.DONE))
        self.assertFalse(self.path.exists())

    def test_load_error_without_old_pending_starts_from_zero(self):
        self.app.first_use_saver = FakeSaver(self.path)
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        self.assertEqual(self.view.warning, fu.FIRST_USE_LOAD_ERROR_TEXT)
        self.assertEqual(flow.steps, fu.empty_first_use_steps())
        flow.close()
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT)])

    # FIX-P4-02-03: fechar depois de uma leitura que falhou nesta janela
    def test_close_after_failed_read_warns_once_and_saves_nothing(self):
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        flow.mark('backup', fu.DONE)
        flow.reset()
        flow.mark('explorar', fu.SKIPPED)
        self.assertIsNone(self.app.first_use_saver)  # nenhum gravador criado
        flow.close()
        flow.close()  # "Fechar" e "X" no mesmo caminho: um aviso só
        warns = [e for e in self.view.events if e[0] == 'warn']
        self.assertEqual(warns, [('warn', fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT)])
        self.assertNotIn(str(self.base), warns[0][1])
        self.assertFalse(self.base.exists())

    def test_reopen_after_failed_read_saves_again(self):
        # o caminho que FIRST_USE_CLOSE_LOAD_FAILED_TEXT manda seguir
        flow = self.make_flow()
        with self._failing_load():
            flow.start()
            self.jobs[0].finish()
        self.view.pump()
        flow.mark('backup', fu.DONE)
        flow.close()
        self.assertFalse(self.path.exists())

        self.view = FakeView()
        again = self.loaded_flow()
        self.assertIsInstance(again.saver, fu.FirstUseProgressSaver)
        self.assertEqual(again.steps, fu.empty_first_use_steps())  # nada foi salvo
        again.mark('explorar', fu.DONE)
        self.assertTrue(again.saver.join(5))
        self.assertIsNone(again.saver.poll_error())
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'],
                         _all(explorar=fu.DONE))
        again.close()
        self.assertEqual(self.view.events[-1], ('destroy',))  # leitura deu certo

    def test_previous_failed_marks_reappear_when_guide_reopens(self):
        # o caminho que FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT promete
        def failing_save(path, steps):
            raise PermissionError(13, 'acesso negado', str(path))

        saver = fu.FirstUseProgressSaver(self.path, save=failing_save)
        self._savers.append(saver)
        self.app.first_use_saver = saver
        first = self.loaded_flow()
        first.mark('backup', fu.DONE)
        self.assertTrue(saver.join(5))
        first.close()

        self.view = FakeView()
        failed = self.make_flow()
        with self._failing_load():
            failed.start()
            self.jobs[-1].finish()
        self.view.pump()
        failed.close()
        self.assertEqual(self.view.events[-1],
                         ('warn', fu.first_use_close_load_failed_text(False, True)))

        self.view = FakeView()
        again = self.loaded_flow()
        self.assertIs(again.saver, saver)
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertFalse(self.path.exists())

    # item 2: a leitura cai no arquivo -2
    def test_reading_moved_to_second_file_passes_pending_to_new_saver(self):
        self.base.mkdir(parents=True)
        self.path.write_text('{estragado', encoding='utf-8')
        error = self._error()
        old = FakeSaver(self.path, pending=_all(backup=fu.DONE), error=error)
        self.app.first_use_saver = old
        flow = self.loaded_flow()
        second = self.base / 'primeiro-uso-progresso-2.json'
        self.assertEqual(flow.path, second)
        self.assertIsInstance(flow.saver, fu.FirstUseProgressSaver)
        self.assertIs(self.app.first_use_saver, flow.saver)
        self.assertIsNone(flow.previous)
        self.assertEqual(self.view.status['backup'], 'Feito')
        self.assertTrue(flow.saver.join(5))
        self.assertIsNone(flow.saver.poll_error())
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], _all(backup=fu.DONE))
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{estragado')
        self.assertEqual(old.requests, [])

    def test_reading_moved_to_second_file_without_pending_writes_nothing(self):
        self.base.mkdir(parents=True)
        self.path.write_text('{estragado', encoding='utf-8')
        self.app.first_use_saver = FakeSaver(self.path)
        flow = self.loaded_flow()
        self.assertFalse(flow.saver.busy())
        self.assertFalse((self.base / 'primeiro-uso-progresso-2.json').exists())

    # item 3: fechar durante "Carregando..."
    def test_close_while_loading_warns_pending_of_app_saver(self):
        old = FakeSaver(self.path, pending=_all(backup=fu.DONE), busy=True)
        self.app.first_use_saver = old
        flow = self.make_flow()
        flow.start()
        self.assertFalse(flow.ready)
        flow.close()
        self.assertTrue(self.jobs[0].cancelled.is_set())
        self.assertEqual(self.view.events[-2:], [
            ('destroy',), ('warn', fu.FIRST_USE_CLOSE_SAVING_TEXT)])

    def test_close_while_loading_after_failed_save_warns_error(self):
        error = self._error()
        self.app.first_use_saver = FakeSaver(self.path, pending=_all(backup=fu.DONE),
                                             error=error)
        flow = self.make_flow()
        flow.start()
        flow.close()
        self.assertEqual(self.view.events[-1], ('warn', error))

    def test_close_while_loading_without_pending_does_not_warn(self):
        self.app.first_use_saver = FakeSaver(self.path)
        flow = self.make_flow()
        flow.start()
        flow.close()
        self.assertEqual(self.view.events[-1], ('destroy',))
        flow = self.make_flow()  # sem gravador no app
        self.app.first_use_saver = None
        flow.start()
        flow.close()
        self.assertEqual(self.view.events[-1], ('destroy',))


class SingleWindowNoTkTests(unittest.TestCase):
    def test_second_open_reuses_window_without_tkinter(self):
        class FakeDialog:
            def __init__(self):
                self.calls = []

            def winfo_exists(self):
                return True

            def deiconify(self):
                self.calls.append('deiconify')

            def lift(self):
                self.calls.append('lift')

        app = FakeApp()
        dialog = FakeDialog()
        app.first_use_dialog = dialog
        self.assertIs(fui.show_first_use(app), dialog)
        self.assertEqual(dialog.calls, ['deiconify', 'lift'])
        self.assertEqual(app.calls, [])


class FirstUseUiSourceTests(unittest.TestCase):
    def test_window_labels_are_in_show_first_use_and_reachable(self):
        project = _Project(ROOT)
        reach = project.reachable(blocked=BLOCKED_EDGES)
        screen = ('first_use_ui.py', 'show_first_use')
        self.assertIn(screen, reach)
        labels = project.labels(*screen)
        for label in WINDOW_LABELS + (fui.TITLE,):
            with self.subTest(label=label):
                self.assertIn(_norm(label), labels)
        self.assertIn('Primeiro uso guiado', project.labels('app.py', 'App._build_sidebar'))

    def test_app_wires_overview_button_and_sidebar_action(self):
        # Revisão da PR #293: o botão é conferido com ast dentro da função que
        # monta a "Visão geral" (App._build chama build_overview(self) e põe os
        # botões em self.overview), e não por busca de texto no app.py inteiro.
        project = _Project(ROOT)
        mod = project.mod('app.py')
        self.assertIn('build_overview', mod.imports)
        found = []
        builds_overview = False
        for node in mod.own_nodes('App._build'):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, 'id', None) == 'build_overview':
                builds_overview = True
            texts = [kw.value.value for kw in node.keywords if kw.arg == 'text'
                     and isinstance(kw.value, ast.Constant)]
            if texts != ['Primeiro uso guiado  →']:
                continue
            parent = node.args[0] if node.args else None
            command = next((kw.value for kw in node.keywords if kw.arg == 'command'), None)
            found.append((
                isinstance(parent, ast.Attribute) and parent.attr == 'overview',
                isinstance(command, ast.Attribute) and command.attr == 'open_first_use',
            ))
        self.assertTrue(builds_overview)
        self.assertEqual(found, [(True, True)])
        self.assertIn('Primeiro uso guiado', project.labels('app.py', 'App._build_sidebar'))
        sidebar_actions = [
            node for node in mod.own_nodes('App._build_sidebar')
            if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == '_nav_action'
            and len(node.args) == 3 and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == 'Primeiro uso guiado']
        self.assertEqual(len(sidebar_actions), 1)
        self.assertEqual(getattr(sidebar_actions[0].args[2], 'attr', None), 'open_first_use')
        reach = project.reachable(blocked=BLOCKED_EDGES)
        self.assertIn(('app.py', 'App.open_first_use'), reach)
        self.assertIn(('first_use_ui.py', 'show_first_use'),
                      project.edges('app.py', 'App.open_first_use'))

    def test_close_button_and_window_x_share_the_same_handler(self):
        self.assertIn("close_btn.configure(command=flow.close)", SOURCE)
        self.assertIn("dlg.protocol('WM_DELETE_WINDOW', flow.close)", SOURCE)

    def test_open_step_calls_nothing_but_navigate_on_app(self):
        tree = ast.parse(SOURCE)
        flow = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                    and n.name == 'FirstUseFlow')
        app_calls = set()
        for node in ast.walk(flow):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == 'app'):
                app_calls.add(node.func.attr)
        self.assertEqual(app_calls, {'navigate'})
        self.assertEqual(fui.OPEN_PAGES, frozenset(PAGES))
        self.assertEqual({s['page'] for s in fu.FIRST_USE_STEPS('W:')}, set(PAGES))
        for word in ('subprocess', 'os.system', 'unlink', 'rmtree', 'remove(',
                     'save_first_use_progress', 'begin_backup', 'show_restore',
                     'show_deep_discovery', 'disk_inventory', 'build_plan'):
            with self.subTest(word=word):
                self.assertNotIn(word, SOURCE)

    def test_texts_follow_r88_and_have_no_fixed_drive(self):
        tree = ast.parse(SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn('C:', node.value)
        for text in (fu.FIRST_USE_CLOSE_SAVING_TEXT, fu.FIRST_USE_LOAD_ERROR_TEXT,
                     fu.FIRST_USE_LOAD_ERROR_KEPT_TEXT, fu.FIRST_USE_PREVIOUS_FAILED_TEXT,
                     fu.FIRST_USE_CLOSE_LOAD_FAILED_TEXT,
                     fu.FIRST_USE_CLOSE_PREVIOUS_SAVING_TEXT,
                     fu.FIRST_USE_CLOSE_PREVIOUS_FAILED_TEXT,
                     fui.LOADING_TEXT, fui.TITLE):
            for bad in FORBIDDEN_R88:
                self.assertNotIn(bad, text.lower())
        self.assertIn('workflow_texts.system_drive()', SOURCE)

    def test_whole_module_passes_in_subprocess_without_tkinter(self):
        if os.environ.get(NO_TK_CHILD_ENV) == '1':
            self.skipTest('já está rodando no subprocesso sem tkinter')
        env = dict(os.environ, **{NO_TK_CHILD_ENV: '1'})
        proc = subprocess.run(
            [sys.executable, '-c', (
                "import sys, unittest; sys.modules['tkinter'] = None; "
                "suite = unittest.defaultTestLoader.loadTestsFromName("
                "'tests.test_first_use_gui_p4_02'); "
                "result = unittest.TextTestRunner(verbosity=0).run(suite); "
                "assert result.testsRun >= 25, result.testsRun; "
                "sys.exit(0 if result.wasSuccessful() else 1)")],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-4000:])


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


class FirstUseWindowTkTests(unittest.TestCase):
    """Janela Tk real (ignorados sem tkinter ou sem display)."""

    def setUp(self):
        if tk is None:
            self.skipTest('tkinter indisponível neste ambiente')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / 'dados-do-app'
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'display Tk indisponível: {exc}')
        root.withdraw()
        self.root = track_tk_root(self, root)
        self.navigated = []
        root.navigate = self.navigated.append
        for name in PAGES:
            setattr(root, name, f'pagina:{name}')
        self.addCleanup(self._join_saver)  # R-29: antes de fechar o Tk e a pasta

    def _join_saver(self):
        saver = getattr(self.root, 'first_use_saver', None) if self.root is not None else None
        if saver is not None:
            self.assertTrue(saver.join(5))

    def _open(self):
        dlg = fui.show_first_use(self.root, base=self.base)
        return dlg

    def _wait_ready(self, dlg):
        deadline = time.monotonic() + 5
        while not dlg.first_use_flow.ready and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(dlg.first_use_flow.ready)

    def _state(self, button):
        return 'disabled' in button.state()

    def test_loading_then_buttons_enable_and_labels_exist(self):
        dlg = self._open()
        self.assertEqual({v.get() for v in dlg.first_use_status.values()}, {'Carregando...'})
        for own in dlg.first_use_buttons.values():
            for button in own.values():
                self.assertTrue(self._state(button))
        self.assertTrue(self._state(dlg.first_use_reset))
        self.assertFalse(self._state(dlg.first_use_close))
        self._wait_ready(dlg)
        self.assertEqual({v.get() for v in dlg.first_use_status.values()}, {'Pendente'})
        for own in dlg.first_use_buttons.values():
            for button in own.values():
                self.assertFalse(self._state(button))
        texts = {str(w.cget('text')) for w in _walk(dlg)
                 if w.winfo_class() in ('TButton', 'TLabel')}
        for label in WINDOW_LABELS + (fui.TITLE,):
            self.assertIn(label, texts)
        self.assertEqual(dlg.title(), 'Primeiro uso guiado')

    def test_buttons_mark_toggle_reset_and_save_in_background(self):
        dlg = self._open()
        self._wait_ready(dlg)
        buttons = dlg.first_use_buttons
        status = dlg.first_use_status
        buttons['diagnostico']['Feito'].invoke()
        self.assertEqual(status['diagnostico'].get(), 'Feito')
        buttons['explorar']['Pular'].invoke()
        self.assertEqual(status['explorar'].get(), 'Pulado')
        buttons['explorar']['Pular'].invoke()
        self.assertEqual(status['explorar'].get(), 'Pendente')
        self.assertTrue(self.root.first_use_saver.join(5))
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'],
                         _all(diagnostico=fu.DONE))
        for step_id in fu.STEP_IDS:
            buttons[step_id]['Feito'].invoke()
        dlg.first_use_reset.invoke()
        self.assertEqual({v.get() for v in status.values()}, {'Pendente'})
        self.assertTrue(self.root.first_use_saver.join(5))
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'], _all())

    def test_open_buttons_only_navigate(self):
        dlg = self._open()
        self._wait_ready(dlg)
        for step_id in fu.STEP_IDS:
            dlg.first_use_buttons[step_id]['Abrir'].invoke()
        self.assertEqual(self.navigated, [f'pagina:{p}' for p in PAGES])
        self.assertFalse(self.base.exists())  # nada foi gravado por "Abrir"

    def test_second_open_reuses_window(self):
        dlg = self._open()
        with mock.patch.object(dlg, 'deiconify') as deiconify, \
                mock.patch.object(dlg, 'lift') as lift:
            again = self._open()
        self.assertIs(again, dlg)
        deiconify.assert_called_once_with()
        lift.assert_called_once_with()
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(tops, [dlg])
        self._wait_ready(dlg)

    def test_close_with_pending_warns_and_cancels_timers(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def slow_save(path, steps):
            started.set()
            release.wait(5)
            fu.save_first_use_progress(path, steps)

        self.root.first_use_saver = fu.FirstUseProgressSaver(
            fu.first_use_progress_path(self.base), save=slow_save)
        dlg = self._open()
        self._wait_ready(dlg)
        timers = dlg.first_use_timers
        dlg.first_use_buttons['backup']['Feito'].invoke()
        self.assertTrue(started.wait(5))
        self.assertTrue(timers.pending)
        with mock.patch.object(fui, '_show_close_warning') as warn:
            dlg.first_use_close.invoke()
        warn.assert_called_once_with(self.root, fu.FIRST_USE_CLOSE_SAVING_TEXT)
        self.assertFalse(dlg.winfo_exists())
        self.assertIsNone(self.root.first_use_dialog)
        self.assertTrue(timers.closed)
        self.assertEqual(timers.pending, set())
        release.set()
        self.assertTrue(self.root.first_use_saver.join(5))
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'],
                         _all(backup=fu.DONE))
        # reabrir depois de fechar cria uma janela nova, com a marcação salva
        dlg2 = self._open()
        self.assertIsNot(dlg2, dlg)
        self._wait_ready(dlg2)
        self.assertEqual(dlg2.first_use_status['backup'].get(), 'Feito')

    def test_window_x_uses_same_path_as_close_button(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def slow_save(path, steps):
            started.set()
            release.wait(5)
            fu.save_first_use_progress(path, steps)

        self.root.first_use_saver = fu.FirstUseProgressSaver(
            fu.first_use_progress_path(self.base), save=slow_save)
        dlg = self._open()
        self._wait_ready(dlg)
        timers = dlg.first_use_timers
        dlg.first_use_buttons['testar']['Pular'].invoke()
        self.assertTrue(started.wait(5))
        command = dlg.protocol('WM_DELETE_WINDOW')
        self.assertTrue(command)
        with mock.patch.object(fui, '_show_close_warning') as warn:
            dlg.tk.call(command)  # o mesmo que clicar no "X" da janela
        warn.assert_called_once_with(self.root, fu.FIRST_USE_CLOSE_SAVING_TEXT)
        self.assertFalse(dlg.winfo_exists())
        self.assertIsNone(self.root.first_use_dialog)
        self.assertTrue(timers.closed)
        self.assertTrue(dlg.first_use_flow.closed)
        release.set()
        self.assertTrue(self.root.first_use_saver.join(5))
        self.assertEqual(fu.load_first_use_progress(self.base)['steps'],
                         _all(testar=fu.SKIPPED))

    def test_close_without_pending_does_not_warn(self):
        dlg = self._open()
        self._wait_ready(dlg)
        with mock.patch.object(fui, '_show_close_warning') as warn:
            dlg.first_use_close.invoke()
        warn.assert_not_called()
        self.assertFalse(dlg.winfo_exists())

    def test_corrupt_file_warning_line_has_only_file_name(self):
        path = fu.first_use_progress_path(self.base)
        path.parent.mkdir(parents=True)
        path.write_text('{ quebrado', encoding='utf-8')
        dlg = self._open()
        self._wait_ready(dlg)
        warning = dlg.first_use_warning.get()
        self.assertIn(f'"{fu.PROGRESS_FILENAME}"', warning)
        self.assertNotIn(str(self.base), warning)
        self.assertEqual(path.read_text(encoding='utf-8'), '{ quebrado')


if __name__ == '__main__':
    unittest.main()
