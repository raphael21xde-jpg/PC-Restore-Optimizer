"""Regressions found in the real restore of 20/10/2026 (synthetic files only).

1. The backup plan stored every path in lower case (os.path.normcase), so a
   restore recreated "nova pasta" instead of "Nova pasta".
2. The restore folder came from tempfile.mkdtemp(mode 0o700). On Windows with
   Python 3.13 that is a protected owner-only ACL; run elevated, the normal
   user could not open any restored file.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import backup_core
import backup_features


class CasePreservationTests(unittest.TestCase):
    def test_plan_keeps_original_case_even_with_windows_normcase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Origem'
            pasta = root / 'Nova Pasta' / 'Sub Pasta'
            pasta.mkdir(parents=True)
            (pasta / 'LeiaMe.TXT').write_bytes(b'x')
            (root / 'Nova Pasta' / 'Ignorar.bin').write_bytes(b'y')
            choices = {str(root): 'keep', str(root / 'Nova Pasta' / 'Ignorar.bin'): 'skip'}
            # Simulate Windows: comparisons are case-insensitive (lower case).
            with mock.patch.object(backup_core.os.path, 'normcase', side_effect=str.lower):
                plan = backup_core.build_plan(choices, [tmp])
            self.assertEqual([Path(t.source).name for t in plan.files], ['LeiaMe.TXT'])
            task = plan.files[0]
            self.assertIn('Nova Pasta', task.source)
            self.assertIn('Sub Pasta', task.source)
            self.assertTrue(task.destination.endswith(
                str(Path('Origem', 'Nova Pasta', 'Sub Pasta', 'LeiaMe.TXT'))))

    def test_skip_still_matches_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Origem'
            root.mkdir()
            (root / 'Guardar.txt').write_bytes(b'a')
            (root / 'Pular.txt').write_bytes(b'b')
            choices = {str(root): 'keep', str(root / 'PULAR.TXT'): 'skip'}
            with mock.patch.object(backup_core.os.path, 'normcase', side_effect=str.lower):
                plan = backup_core.build_plan(choices, [tmp])
            self.assertEqual([Path(t.source).name for t in plan.files], ['Guardar.txt'])

    def test_destination_relative_keeps_case(self):
        rel = backup_core.destination_relative(os.path.join(os.sep, 'X', 'Meus Jogos', 'Save.DAT'))
        self.assertIn('Meus Jogos', rel)
        self.assertTrue(rel.endswith('Save.DAT'))


class RestoreFolderPermissionTests(unittest.TestCase):
    def test_restore_folder_is_not_created_owner_only(self):
        calls = []
        real_mkdir = os.mkdir

        def spy(path, *args, **kwargs):
            calls.append((path, args, kwargs))
            return real_mkdir(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(backup_features.os, 'mkdir', side_effect=spy), \
                mock.patch('tempfile.mkdtemp', side_effect=AssertionError('mkdtemp proibido')):
            folder = backup_features.new_restore_folder(tmp)
            self.assertTrue(folder.is_dir())
            self.assertTrue(folder.name.startswith('TESTE-RESTAURACAO-v05-'))
        self.assertEqual(len(calls), 1)
        _, args, kwargs = calls[0]
        self.assertNotIn(0o700, args)
        self.assertNotIn('mode', kwargs)

    def test_name_collision_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / 'TESTE-RESTAURACAO-v05-aaaaaaaa'
            first.mkdir()
            ids = iter([mock.Mock(hex='aaaaaaaa' + '0' * 24), mock.Mock(hex='bbbbbbbb' + '0' * 24)])
            with mock.patch.object(backup_features.uuid, 'uuid4', side_effect=lambda: next(ids)):
                folder = backup_features.new_restore_folder(tmp)
            self.assertEqual(folder.name, 'TESTE-RESTAURACAO-v05-bbbbbbbb')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ['TESTE-RESTAURACAO-v05-aaaaaaaa', 'TESTE-RESTAURACAO-v05-bbbbbbbb'])


if __name__ == '__main__':
    unittest.main()
