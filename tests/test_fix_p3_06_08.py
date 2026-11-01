"""FIX-P3-06-08: `_save_choices` grava com temporário de nome único, o
histórico de benchmarks usa uma trava (duas janelas não perdem registros) e a
tela de otimização mostra erros sem caminhos pessoais. Só arquivos sintéticos
em TemporaryDirectory; nenhuma ferramenta real é chamada."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import atomic_write
import optimization_bench
from atomic_write import exclusive_lock

ROOT = Path(__file__).resolve().parent.parent


def _leftovers(folder: Path, suffix: str):
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(suffix))


def _lock_path(path: Path) -> Path:
    return path.with_name('.' + path.name + '.lock')


class SaveChoicesSourceTests(unittest.TestCase):
    """Funciona mesmo sem Tk: `_save_choices` não monta mais o temporário fixo."""

    def test_save_choices_uses_atomic_write_text(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        start = source.index('def _save_choices(self):')
        body = source[start:source.index('\n    def ', start + 1)]
        self.assertIn('atomic_write_text(self.local_state', body)
        self.assertNotIn("with_suffix('.json.tmp')", body)
        self.assertIn('except OSError:pass', body)


class SaveChoicesTests(unittest.TestCase):
    def setUp(self):
        try:
            import app
        except ImportError as exc:  # nuvem Linux sem Tk
            self.skipTest(f'Tk indisponível: {exc}')
        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _fake(self):
        app = self.app
        return SimpleNamespace(
            local_state=self.folder / 'preferencias.json',
            choices={'C:/Jogos': 'keep'},
            format_vars={d: SimpleNamespace(get=lambda: False) for d in app.DISKS},
            dest=SimpleNamespace(get=lambda: 'D:'), catalog_choices={},
            auto_save_paths=set(), approved_catalog_paths={}, personal_paths=set(),
            browser_keep_paths=set(), browser_vaults={}, retained_discoveries={},
            cleanup_candidates=set(), catalog_items={})

    def test_unique_tmp_and_foreign_tmp_untouched(self):
        fake = self._fake()
        foreign = fake.local_state.with_suffix('.json.tmp')
        foreign.write_text('alheio', encoding='utf-8')
        self.app.App._save_choices(fake)
        doc = json.loads(fake.local_state.read_text(encoding='utf-8'))
        self.assertEqual(doc['choices'], {'C:/Jogos': 'keep'})
        self.assertEqual(foreign.read_text(encoding='utf-8'), 'alheio')
        self.assertEqual(_leftovers(self.folder, '.tmp'), [foreign.name])

    def test_replace_failure_keeps_old_file_without_tmp_or_error(self):
        fake = self._fake()
        fake.local_state.write_text('antigo', encoding='utf-8')
        with mock.patch.object(atomic_write.os, 'replace', side_effect=OSError('falha')):
            self.app.App._save_choices(fake)  # sem erro: except OSError continua
        self.assertEqual(fake.local_state.read_text(encoding='utf-8'), 'antigo')
        self.assertEqual(_leftovers(self.folder, '.tmp'), [])


class ExclusiveLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.target = self.folder / 'bench.json'
        self.lock = _lock_path(self.target)

    def tearDown(self):
        self._tmp.cleanup()

    def test_lock_created_and_released_on_success(self):
        with exclusive_lock(self.target):
            self.assertTrue(self.lock.exists())
        self.assertFalse(self.lock.exists())

    def test_lock_released_on_failure(self):
        with self.assertRaises(RuntimeError):
            with exclusive_lock(self.target):
                raise RuntimeError('falha simulada')
        self.assertFalse(self.lock.exists())

    def test_recent_foreign_lock_times_out_and_is_kept(self):
        self.lock.write_text('outra janela', encoding='utf-8')
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            with exclusive_lock(self.target, timeout=0.2):
                self.fail('não devia entrar')
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(self.lock.read_text(encoding='utf-8'), 'outra janela')

    def test_stale_lock_is_taken_over(self):
        self.lock.write_text('sobra velha', encoding='utf-8')
        old = time.time() - 600
        os.utime(self.lock, (old, old))
        with exclusive_lock(self.target, timeout=0.2):
            self.assertNotEqual(self.lock.read_text(encoding='utf-8'), 'sobra velha')
        self.assertFalse(self.lock.exists())

    def test_does_not_remove_lock_replaced_by_someone_else(self):
        with exclusive_lock(self.target):
            # outra janela tomou a trava (ex.: achou que estava velha)
            self.lock.unlink()
            self.lock.write_text('de outra janela', encoding='utf-8')
        self.assertEqual(self.lock.read_text(encoding='utf-8'), 'de outra janela')


class BenchLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.journal = self.folder / 'bench.json'
        self.lock = _lock_path(self.journal)

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_threads_twenty_runs_each_keep_all_forty(self):
        errors = []

        def worker(phase):
            for n in range(20):
                try:
                    optimization_bench.insert_run(self.journal, 'Jogo', phase, {'avg_fps': n})
                except Exception as exc:  # pragma: no cover - aparece no assert
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(p,)) for p in ('antes', 'depois')]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        data = json.loads(self.journal.read_text(encoding='utf-8'))
        self.assertEqual(len(data['runs']), 40)
        self.assertEqual(_leftovers(self.folder, '.lock'), [])
        self.assertEqual(_leftovers(self.folder, '.tmp'), [])

    def test_recent_lock_gives_app_error_and_journal_unchanged(self):
        optimization_bench.insert_run(self.journal, 'Jogo', 'antes', {'avg_fps': 60})
        before = self.journal.read_bytes()
        self.lock.write_text('outra janela', encoding='utf-8')
        real = optimization_bench.exclusive_lock
        with mock.patch.object(optimization_bench, 'exclusive_lock',
                               lambda path: real(path, timeout=0.2)):
            with self.assertRaises(ValueError) as ctx:
                optimization_bench.insert_run(self.journal, 'Jogo', 'depois', {'avg_fps': 70})
        self.assertEqual(str(ctx.exception),
                         'Histórico de benchmarks em uso por outra janela; nenhuma alteração.')
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertTrue(self.lock.exists())

    def test_stale_lock_is_taken_and_run_saved(self):
        self.lock.write_text('sobra velha', encoding='utf-8')
        old = time.time() - 600
        os.utime(self.lock, (old, old))
        optimization_bench.insert_run(self.journal, 'Jogo', 'antes', {'avg_fps': 60})
        data = json.loads(self.journal.read_text(encoding='utf-8'))
        self.assertEqual(len(data['runs']), 1)
        self.assertFalse(self.lock.exists())

    def test_invalid_scenario_rejected_before_lock(self):
        with mock.patch.object(optimization_bench, 'exclusive_lock') as lock:
            with self.assertRaises(ValueError):
                optimization_bench.insert_run(self.journal, '  ', 'antes', {})
            with self.assertRaises(ValueError):
                optimization_bench.insert_run(self.journal, 'Jogo', 'meio', {})
        lock.assert_not_called()

    def test_lock_released_when_write_fails(self):
        with mock.patch.object(atomic_write.os, 'replace', side_effect=OSError('falha')):
            with self.assertRaises(OSError):
                optimization_bench.insert_run(self.journal, 'Jogo', 'antes', {'avg_fps': 60})
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.journal.exists())

    def test_unreadable_journal_releases_lock(self):
        self.journal.write_text('{quebrado', encoding='utf-8')
        with self.assertRaises(ValueError):
            optimization_bench.insert_run(self.journal, 'Jogo', 'antes', {'avg_fps': 60})
        self.assertFalse(self.lock.exists())
        self.assertEqual(self.journal.read_text(encoding='utf-8'), '{quebrado')


class ErrorTextTests(unittest.TestCase):
    """`_error_text` é função pura, testada sem Tk (fonte lida e executada à parte
    quando o módulo da tela não pode ser importado)."""

    def setUp(self):
        try:
            import optimization_ui
            self.error_text = optimization_ui._error_text
        except ImportError:
            source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
            start = source.index('def _error_text(')
            end = source.index('\n\n\n', start)
            import ntpath
            namespace = {'Path': Path, 'ntpath': ntpath}
            exec(source[start:end], namespace)
            self.error_text = namespace['_error_text']

    def test_oserror_shows_only_file_name_and_type(self):
        exc = PermissionError(13, 'Acesso negado', 'C:/Users/fulano/x.json')
        text = self.error_text(exc)
        self.assertIn('x.json', text)
        self.assertIn('PermissionError', text)
        self.assertNotIn('fulano', text)
        self.assertNotIn('Users', text)

    def test_oserror_with_windows_path(self):
        exc = FileNotFoundError(2, 'x', r'C:\Users\fulano\bench.json')
        text = self.error_text(exc)
        self.assertIn('bench.json', text)
        self.assertNotIn('fulano', text)

    def test_oserror_without_filename(self):
        self.assertEqual(self.error_text(OSError('C:/Users/fulano')), 'arquivo: OSError')

    def test_value_error_keeps_app_text(self):
        msg = 'Histórico de benchmarks em uso por outra janela; nenhuma alteração.'
        self.assertEqual(self.error_text(ValueError(msg)), msg)

    def test_other_errors_show_only_type(self):
        self.assertEqual(self.error_text(KeyError('C:/Users/fulano')), 'KeyError')

    def test_ui_uses_helper_at_both_places(self):
        source = (ROOT / 'optimization_ui.py').read_text(encoding='utf-8')
        self.assertIn("'Falha ao registrar: '+_error_text(exc)", source)
        self.assertIn("messagebox.showerror('Importar benchmark',_error_text(exc))", source)


if __name__ == '__main__':
    unittest.main()
