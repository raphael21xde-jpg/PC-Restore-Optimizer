"""P2-03: caminhos longos (LongPathsEnabled).

Tudo sintético: o registro é sempre simulado (leitor falso ou um ``winreg``
falso colocado em ``sys.modules``); nada lê nem grava o registro real. As
pastas ficam dentro de TemporaryDirectory.
"""
import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import long_paths
import restore_place_flow as flow
from backup_features import new_restore_folder
from restore_place import plan_placement

TODAY = datetime.date(2026, 10, 21)


def raises(error):
    def reader():
        raise error
    return reader


class ReadRegistryTests(unittest.TestCase):
    def test_fake_reader_values(self):
        cases = [(lambda: 1, True), (lambda: 0, False),
                 (raises(FileNotFoundError()), False),
                 (raises(PermissionError()), None),
                 (lambda: '1', None)]
        for reader, expected in cases:
            with self.subTest(expected=expected):
                self.assertIs(long_paths.read_long_paths_enabled(reader), expected)

    def test_bool_is_wrong_type(self):
        self.assertIsNone(long_paths.read_long_paths_enabled(lambda: True))

    def fake_winreg(self, value=1, kind=4, missing=False):
        fake = types.SimpleNamespace(HKEY_LOCAL_MACHINE='HKLM', KEY_READ=0x20019,
                                     KEY_WRITE=0x20006, REG_DWORD=4, REG_SZ=1)
        opened = []

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def open_key(root, path, reserved, access):
            opened.append((root, path, reserved, access))
            return Key()

        def query(key, name):
            if missing:
                raise FileNotFoundError(name)
            return value, kind

        fake.OpenKey = mock.Mock(side_effect=open_key)
        fake.QueryValueEx = mock.Mock(side_effect=query)
        for name in ('SetValueEx', 'SetValue', 'CreateKey', 'CreateKeyEx',
                     'DeleteValue', 'DeleteKey'):
            setattr(fake, name, mock.Mock(side_effect=AssertionError(name)))
        return fake, opened

    def assert_never_wrote(self, fake):
        for name in ('SetValueEx', 'SetValue', 'CreateKey', 'CreateKeyEx',
                     'DeleteValue', 'DeleteKey'):
            getattr(fake, name).assert_not_called()

    def test_windows_reader_only_reads(self):
        for kwargs, expected in [({'value': 1}, True), ({'value': 0}, False),
                                 ({'missing': True}, False),
                                 ({'value': '1', 'kind': 1}, None)]:
            with self.subTest(**kwargs):
                fake, opened = self.fake_winreg(**kwargs)
                with mock.patch.dict(sys.modules, {'winreg': fake}), \
                        mock.patch.object(long_paths.sys, 'platform', 'win32'):
                    self.assertIs(long_paths.read_long_paths_enabled(), expected)
                self.assertEqual(opened, [('HKLM', r'SYSTEM\CurrentControlSet\Control\FileSystem',
                                           0, fake.KEY_READ)])
                fake.QueryValueEx.assert_called_once()
                self.assertEqual(fake.QueryValueEx.call_args.args[1], 'LongPathsEnabled')
                self.assert_never_wrote(fake)

    def test_permission_error_on_open_is_none(self):
        fake, _ = self.fake_winreg()
        fake.OpenKey = mock.Mock(side_effect=PermissionError('negado'))
        with mock.patch.dict(sys.modules, {'winreg': fake}), \
                mock.patch.object(long_paths.sys, 'platform', 'win32'):
            self.assertIsNone(long_paths.read_long_paths_enabled())
        self.assert_never_wrote(fake)

    def test_outside_windows_is_none(self):
        with mock.patch.object(long_paths.sys, 'platform', 'linux'):
            self.assertIsNone(long_paths.read_long_paths_enabled())


class CountAndLengthTests(unittest.TestCase):
    def test_count_limit(self):
        self.assertEqual(long_paths.LIMIT, 259)
        paths = ['a' * 259, 'b' * 260, Path('c' * 300), 'curto']
        self.assertEqual(long_paths.count_long(paths), 2)
        self.assertEqual(long_paths.count_long([]), 0)

    def test_staging_length_matches_real_new_folder(self):
        with tempfile.TemporaryDirectory(prefix='pcro-p2-03-') as temp:
            relative = 'Jogos/osu!/Songs/musica.osz'
            real = new_restore_folder(temp)
            self.assertEqual(len(real.name), 30)
            self.assertEqual(long_paths.staging_target_length(temp, relative),
                             len(str(Path(temp).resolve() / real.name / relative)))


class WarningTextTests(unittest.TestCase):
    def test_no_long_path_no_text(self):
        for enabled in (True, False, None):
            self.assertEqual(long_paths.warning_text(0, enabled), '')

    def test_warning_when_off_or_unknown(self):
        for enabled in (False, None):
            text = long_paths.warning_text(3, enabled)
            self.assertIn('3 arquivo(s)', text)
            self.assertIn(long_paths.ENABLE_COMMAND, text)
            self.assertIn('administrador', text)
            self.assertIn('reinicie', text)
        self.assertIn('desligados', long_paths.warning_text(1, False))
        self.assertIn('não conseguiu', long_paths.warning_text(1, None))

    def test_only_count_when_on(self):
        text = long_paths.warning_text(2, True)
        self.assertIn('2 arquivo(s)', text)
        self.assertNotIn(long_paths.ENABLE_COMMAND, text)

    def test_command_text(self):
        self.assertEqual(long_paths.ENABLE_COMMAND,
                         'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem" '
                         '/v LongPathsEnabled /t REG_DWORD /d 1 /f')


class PlacementPreviewTests(unittest.TestCase):
    """Prévia da colocação com manifesto sintético e target_map temporário."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-p2-03-flow-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.backup = self.root / 'backup'
        self.staging = self.root / 'restauracoes' / 'TESTE-RESTAURACAO-v05-abcd1234'
        self.original = self.root / 'original'
        self.mapped = self.root / 'novo-lugar'
        for folder in (self.backup, self.staging, self.original, self.mapped):
            folder.mkdir(parents=True)
        self.entries = []

    def add(self, relative, data=b'dados'):
        for base in (self.backup, self.staging):
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.entries.append({'source': str(self.original / relative), 'relative': relative,
                             'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                             'verified': True})

    def plan(self):
        manifest = self.backup / 'manifest.json'
        manifest.write_text(json.dumps({'schema': 'pc-restore-backup-v0.4',
                                        'files': self.entries}), encoding='utf-8')
        return plan_placement(manifest, self.staging, today=TODAY, environ={},
                              target_map={str(self.original): str(self.mapped)})

    def long_relative(self):
        prefix = len(str(self.mapped)) + 1
        depth = (long_paths.LIMIT - prefix) // 51 + 2
        return '/'.join(['p' * 50] * depth) + '/arquivo.txt'

    def test_preview_counts_long_target(self):
        self.add('curto.txt')
        self.add(self.long_relative())
        plan = self.plan()
        self.assertEqual(long_paths.count_long(i.target for i in plan.items), 1)
        off = flow.preview_summary(plan, long_paths_enabled=False)
        self.assertIn('1 arquivo(s) vão ficar com o caminho mais longo que 259', off)
        self.assertIn(long_paths.ENABLE_COMMAND, off)
        self.assertIn(long_paths.ENABLE_COMMAND, flow.preview_summary(plan))
        on = flow.preview_summary(plan, long_paths_enabled=True)
        self.assertIn('1 arquivo(s) vão ficar', on)
        self.assertNotIn(long_paths.ENABLE_COMMAND, on)
        confirm = flow.confirmation_text(plan, False, long_paths_enabled=None)
        self.assertIn(long_paths.ENABLE_COMMAND, confirm)
        self.assertTrue(confirm.endswith('Deseja colocar os arquivos no lugar original agora?'))

    def test_preview_unchanged_without_long_target(self):
        self.add('curto.txt')
        plan = self.plan()
        base = flow.preview_summary(plan)
        self.assertEqual(base, 'Prévia: 1 arquivo(s) conferido(s) nesta pasta.\n'
                               '1 arquivo(s) novo(s): ainda não existem no lugar original '
                               'e serão colocados.')
        for enabled in (True, False, None):
            self.assertEqual(flow.preview_summary(plan, long_paths_enabled=enabled), base)
            self.assertNotIn('caracteres', flow.confirmation_text(plan, False, enabled))


if __name__ == '__main__':
    unittest.main()
