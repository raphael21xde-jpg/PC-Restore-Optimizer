"""FIX-P3-06-07: a tela de otimização e o bench gravam num temporário de nome
único na mesma pasta do destino (ajudante `atomic_write_text`) e o apagam se a
gravação falhar. Só arquivos sintéticos em TemporaryDirectory."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import atomic_write
import optimization_bench
from atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parent.parent


def _leftover_tmps(folder: Path):
    return sorted(p.name for p in folder.iterdir() if p.name.endswith('.tmp'))


class AtomicWriteTextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.target = self.folder / 'historico.json'

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_text_with_accents_and_leaves_no_tmp(self):
        atomic_write_text(self.target, 'ação reversível')
        self.assertEqual(self.target.read_text(encoding='utf-8'), 'ação reversível')
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_replace_failure_propagates_keeps_target_and_removes_tmp(self):
        self.target.write_text('antigo', encoding='utf-8')
        with mock.patch.object(atomic_write.os, 'replace',
                               side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError) as ctx:
                atomic_write_text(self.target, 'novo')
        self.assertEqual(str(ctx.exception), 'falha simulada')
        self.assertEqual(self.target.read_text(encoding='utf-8'), 'antigo')
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_fsync_failure_propagates_and_removes_tmp(self):
        with mock.patch.object(atomic_write.os, 'fsync',
                               side_effect=OSError('disco cheio simulado')):
            with self.assertRaises(OSError):
                atomic_write_text(self.target, 'novo')
        self.assertFalse(self.target.exists())
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_each_write_uses_unique_tmp_in_target_folder(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src))
            return real_replace(src, dst)

        with mock.patch.object(atomic_write.os, 'replace', side_effect=spy):
            atomic_write_text(self.target, '1')
            atomic_write_text(self.target, '2')
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0].name, seen[1].name)
        for temp in seen:
            self.assertNotEqual(temp.name, self.target.with_suffix('.tmp').name)
            self.assertEqual(temp.parent.resolve(), self.folder.resolve())
        self.assertEqual(self.target.read_text(encoding='utf-8'), '2')

    def test_foreign_stale_tmp_is_left_alone(self):
        stale = self.target.with_suffix('.tmp')
        stale.write_text('sobra antiga', encoding='utf-8')
        atomic_write_text(self.target, 'ok')
        with mock.patch.object(atomic_write.os, 'replace', side_effect=OSError('x')):
            with self.assertRaises(OSError):
                atomic_write_text(self.target, 'novo')
        self.assertEqual(stale.read_text(encoding='utf-8'), 'sobra antiga')
        self.assertEqual(_leftover_tmps(self.folder), [stale.name])


class BenchInsertRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.journal = self.folder / 'bench.json'

    def tearDown(self):
        self._tmp.cleanup()

    def test_insert_run_uses_unique_tmp_and_keeps_foreign_tmp(self):
        stale = self.journal.with_suffix('.tmp')
        stale.write_text('sobra antiga', encoding='utf-8')
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src))
            return real_replace(src, dst)

        with mock.patch.object(atomic_write.os, 'replace', side_effect=spy):
            optimization_bench.insert_run(self.journal, 'Jogo cenário', 'antes', {'avg_fps': 60})
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0].name, stale.name)
        data = json.loads(self.journal.read_text(encoding='utf-8'))
        self.assertEqual(data['runs'][0]['scenario'], 'Jogo cenário')
        self.assertEqual(stale.read_text(encoding='utf-8'), 'sobra antiga')
        self.assertEqual(_leftover_tmps(self.folder), [stale.name])

    def test_insert_run_failure_keeps_old_journal_and_removes_tmp(self):
        optimization_bench.insert_run(self.journal, 'Jogo', 'antes', {'avg_fps': 60})
        before = self.journal.read_text(encoding='utf-8')
        with mock.patch.object(atomic_write.os, 'replace',
                               side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError) as ctx:
                optimization_bench.insert_run(self.journal, 'Jogo', 'depois', {'avg_fps': 70})
        self.assertEqual(str(ctx.exception), 'falha simulada')
        self.assertEqual(self.journal.read_text(encoding='utf-8'), before)
        self.assertEqual(_leftover_tmps(self.folder), [])


class NoFixedTmpNameInSourceTests(unittest.TestCase):
    """Funciona mesmo sem Tk: confere que nenhum dos dois arquivos monta mais
    o temporário de nome fixo."""

    def test_ui_and_bench_do_not_use_fixed_tmp_name(self):
        # FIX-P3-06-08: app.py (`_save_choices`) também entra na conferência.
        for name in ('optimization_ui.py', 'optimization_bench.py', 'app.py'):
            source = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotIn("with_suffix('.tmp')", source, name)
            self.assertNotIn("with_suffix('.json.tmp')", source, name)
            # FIX-P3-06-09: app.py grava via choices_store (que usa atomic_write_text).
            self.assertIn('choices_store' if name == 'app.py' else 'atomic_write_text', source, name)


class UiSaveMonitorSourceTests(unittest.TestCase):
    def setUp(self):
        try:
            import optimization_ui
        except ImportError as exc:  # nuvem Linux sem Tk
            self.skipTest(f'Tk indisponível: {exc}')
        self.ui = optimization_ui
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / 'estado'

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _fake(self, value):
        return SimpleNamespace(state_dir=self.folder,
                               afterburner_config=self.folder / 'afterburner-fonte.json',
                               afterburner_path=SimpleNamespace(get=lambda: value))

    def test_save_monitor_source_writes_atomically_and_keeps_foreign_tmp(self):
        fake = self._fake('C:/logs/HardwareMonitoring.hml')
        self.folder.mkdir()
        stale = fake.afterburner_config.with_suffix('.tmp')
        stale.write_text('sobra antiga', encoding='utf-8')
        self.ui.OptimizationPanel._save_monitor_source(fake)
        self.assertEqual(json.loads(fake.afterburner_config.read_text(encoding='utf-8')),
                         {'hml': 'C:/logs/HardwareMonitoring.hml'})
        self.assertEqual(stale.read_text(encoding='utf-8'), 'sobra antiga')
        self.assertEqual(_leftover_tmps(self.folder), [stale.name])

    def test_save_monitor_source_failure_removes_own_tmp(self):
        fake = self._fake('C:/logs/x.hml')
        with mock.patch.object(atomic_write.os, 'replace', side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError):
                self.ui.OptimizationPanel._save_monitor_source(fake)
        self.assertFalse(fake.afterburner_config.exists())
        self.assertEqual(_leftover_tmps(self.folder), [])


if __name__ == '__main__':
    unittest.main()
