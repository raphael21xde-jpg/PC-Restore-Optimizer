"""FIX-P3-06-06: `_atomic_json` grava num temporário de nome único na mesma
pasta do destino e o apaga se a gravação falhar. Só arquivos sintéticos em
TemporaryDirectory."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import optimization_engine
from optimization_engine import _atomic_json


def _leftover_tmps(folder: Path):
    return sorted(p.name for p in folder.iterdir() if p.name.endswith('.tmp'))


class AtomicJsonTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.target = self.folder / 'diario.json'

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_content_with_accents(self):
        data = {'mensagem': 'Plano de energia alterado; ação reversível', 'n': 1}
        _atomic_json(self.target, data)
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8')), data)
        self.assertIn('ação', self.target.read_text(encoding='utf-8'))

    def test_no_tmp_left_after_success(self):
        _atomic_json(self.target, {'a': 1})
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_unserializable_value_keeps_old_target_and_removes_tmp(self):
        self.target.write_text('{"antigo": true}', encoding='utf-8')
        with self.assertRaises(TypeError):
            _atomic_json(self.target, {'ruim': object()})
        self.assertEqual(self.target.read_text(encoding='utf-8'), '{"antigo": true}')
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_replace_failure_propagates_keeps_target_and_removes_tmp(self):
        self.target.write_text('{"antigo": true}', encoding='utf-8')
        with mock.patch.object(optimization_engine.os, 'replace',
                               side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError) as ctx:
                _atomic_json(self.target, {'novo': 1})
        self.assertEqual(str(ctx.exception), 'falha simulada')
        self.assertEqual(self.target.read_text(encoding='utf-8'), '{"antigo": true}')
        self.assertEqual(_leftover_tmps(self.folder), [])

    def test_each_write_uses_unique_tmp_in_target_folder(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src))
            return real_replace(src, dst)

        with mock.patch.object(optimization_engine.os, 'replace', side_effect=spy):
            _atomic_json(self.target, {'a': 1})
            _atomic_json(self.target, {'a': 2})
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0].name, seen[1].name)
        for temp in seen:
            self.assertNotEqual(temp.name, self.target.name + '.tmp')
            self.assertEqual(temp.parent.resolve(), self.folder.resolve())
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8')), {'a': 2})

    def test_foreign_stale_tmp_is_left_alone(self):
        stale = self.folder / (self.target.name + '.tmp')
        stale.write_text('sobra antiga', encoding='utf-8')
        _atomic_json(self.target, {'a': 1})
        with self.assertRaises(TypeError):
            _atomic_json(self.target, {'ruim': object()})
        self.assertTrue(stale.exists())
        self.assertEqual(stale.read_text(encoding='utf-8'), 'sobra antiga')
        self.assertEqual(_leftover_tmps(self.folder), [stale.name])


if __name__ == '__main__':
    unittest.main()
