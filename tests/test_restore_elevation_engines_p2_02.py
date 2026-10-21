"""P2-02 fatia 2: the administrator lock lives inside the restore engines.

Elevation is always simulated with an injected probe; the real Windows API is
never asked. Every file is synthetic and lives in a TemporaryDirectory.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup_core
import browser_vault
import elevation_guard
import restore_elevation
from backup_features import restore_selected, verified_entries
from multi_source_plan import prepare_multi_source_preview

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'passphrase-for-test-2026-long'
NOT_TRUE = (1, 'yes', 'True', None, False, 0)


def elevated():
    return True


def not_elevated():
    return False


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-p2-02-eng-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()


class SelectedRestoreEngineTests(Temp):
    def setUp(self):
        super().setUp()
        source_folder = self.root / 'source'
        source_folder.mkdir()
        self.source = source_folder / 'osu!.db'
        self.payload = b'synthetic-osu-database-p2-02-engine'
        self.source.write_bytes(self.payload)
        backups = self.root / 'backups'
        backups.mkdir()
        self.restores = self.root / 'restores'
        self.restores.mkdir()
        plan = prepare_multi_source_preview([str(self.source)], [str(source_folder)])
        folder, result = backup_core.copy_backup(plan, backups, strategy_inventory={})
        self.assertEqual(result['status'], 'concluido')
        self.manifest = folder / 'manifest.json'
        self.keys = list(verified_entries(self.manifest))

    def test_refuses_when_elevated_and_destination_stays_empty(self):
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused) as caught:
            restore_selected(self.manifest, self.keys, self.restores,
                             strategy_inventory={}, elevation_probe=elevated)
        self.assertEqual(str(caught.exception), elevation_guard.REFUSAL_MESSAGE)
        self.assertEqual(list(self.restores.iterdir()), [])

    def test_refusal_comes_before_cancellation_check(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            restore_selected(self.manifest, self.keys, self.restores, cancelled=cancelled,
                             strategy_inventory={}, elevation_probe=elevated)
        self.assertEqual(list(self.restores.iterdir()), [])

    def test_refuses_resume_without_touching_interrupted_folder(self):
        interrupted = self.restores / 'TESTE-RESTAURACAO-sintetico'
        interrupted.mkdir()
        marker = interrupted / 'ESTADO-RESTAURACAO.json'
        marker.write_text('{"status": "interrompida"}', encoding='utf-8')
        before = marker.read_bytes()
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            restore_selected(self.manifest, self.keys, self.restores, resume_from=interrupted,
                             strategy_inventory={}, elevation_probe=elevated)
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.restores.iterdir()), [interrupted.name])
        self.assertEqual([p.name for p in interrupted.iterdir()], ['ESTADO-RESTAURACAO.json'])

    def test_probe_is_asked_before_manifest_is_resolved(self):
        order = []

        def probe():
            order.append('probe')
            return True

        missing = self.root / 'nao-existe' / 'manifest.json'
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            restore_selected(missing, self.keys, self.restores, elevation_probe=probe)
        self.assertEqual(order, ['probe'])

    def test_only_literal_true_releases(self):
        for value in NOT_TRUE:
            with self.subTest(allow_elevated=value):
                with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
                    restore_selected(self.manifest, self.keys, self.restores,
                                     strategy_inventory={}, allow_elevated=value,
                                     elevation_probe=elevated)
        self.assertEqual(list(self.restores.iterdir()), [])
        folder, count = restore_selected(self.manifest, self.keys, self.restores,
                                         strategy_inventory={}, allow_elevated=True,
                                         elevation_probe=elevated)
        self.assertEqual(count, len(self.keys))
        self.assertEqual(next(folder.rglob('osu!.db')).read_bytes(), self.payload)

    def test_not_elevated_restores_normally(self):
        folder, count = restore_selected(self.manifest, self.keys, self.restores,
                                         strategy_inventory={}, elevation_probe=not_elevated)
        self.assertEqual(count, len(self.keys))
        self.assertEqual(next(folder.rglob('osu!.db')).read_bytes(), self.payload)


class GuardedForwardingTests(Temp):
    def test_guarded_forwards_allow_and_probe_to_engine(self):
        calls = []

        def fake(*args, **kwargs):
            calls.append((args, kwargs))
            return 'folder', 1

        with patch('restore_elevation.restore_selected', side_effect=fake):
            restore_elevation.guarded_restore_selected(
                'm.json', ['k'], 'dest', allow_elevated=True, elevation_probe=elevated,
                progress=print)
            restore_elevation.guarded_restore_selected(
                'm.json', ['k'], 'dest', elevation_probe=not_elevated)
        self.assertEqual(calls[0][1], {'allow_elevated': True, 'elevation_probe': elevated,
                                       'progress': print})
        self.assertEqual(calls[1][1], {'allow_elevated': False,
                                       'elevation_probe': not_elevated})

    def test_guarded_still_refuses_before_engine(self):
        with patch('restore_elevation.restore_selected') as engine:
            with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
                restore_elevation.guarded_restore_selected(
                    'm.json', ['k'], 'dest', elevation_probe=elevated)
        engine.assert_not_called()


class RestoreTestEngineTests(Temp):
    def setUp(self):
        super().setUp()
        backup = self.root / 'backup'
        (backup / 'dados').mkdir(parents=True)
        payload = b'synthetic-small-file'
        (backup / 'dados' / 'a.txt').write_bytes(payload)
        self.manifest = backup / 'manifest.json'
        self.manifest.write_text(json.dumps({
            'schema': 'pc-restore-backup-v0.4',
            'files': [{'relative': 'dados/a.txt', 'verified': True, 'bytes': len(payload),
                       'sha256': hashlib.sha256(payload).hexdigest()}],
        }), encoding='utf-8')
        self.destination = self.root / 'destino'
        self.destination.mkdir()

    def created(self):
        return [p.name for p in self.destination.iterdir() if p.name.startswith('teste-restauracao-')]

    def test_refuses_when_elevated_without_creating_folder(self):
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            backup_core.restore_test(self.manifest, self.destination, elevation_probe=elevated)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_probe_is_asked_before_manifest_is_read(self):
        order = []

        def probe():
            order.append('probe')
            return True

        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            backup_core.restore_test(self.root / 'nao-existe.json', self.destination,
                                     elevation_probe=probe)
        self.assertEqual(order, ['probe'])

    def test_only_literal_true_releases(self):
        for value in NOT_TRUE:
            with self.subTest(allow_elevated=value):
                with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
                    backup_core.restore_test(self.manifest, self.destination,
                                             allow_elevated=value, elevation_probe=elevated)
        self.assertEqual(self.created(), [])
        restored = backup_core.restore_test(self.manifest, self.destination,
                                            allow_elevated=True, elevation_probe=elevated)
        self.assertEqual(restored.read_bytes(), b'synthetic-small-file')
        self.assertEqual(len(self.created()), 1)

    def test_not_elevated_works(self):
        restored = backup_core.restore_test(self.manifest, self.destination,
                                            elevation_probe=not_elevated)
        self.assertEqual(restored.read_bytes(), b'synthetic-small-file')


class BrowserStagingEngineTests(Temp):
    def setUp(self):
        super().setUp()
        profile = self.root / 'browser-profile'
        profile.mkdir()
        (profile / 'Bookmarks').write_text('favorites-sinteticos', encoding='utf-8')
        (profile / 'Preferences').write_text('{"prefs":1}', encoding='utf-8')
        self.package, *_ = browser_vault.create_vault(
            browser_vault.BrowserProfile('Google Chrome', 'Default', profile),
            self.root / 'backup', PASSWORD)
        self.destination = self.root / 'destino'
        self.destination.mkdir()

    def staged(self):
        return [p for p in self.destination.iterdir() if p.name.startswith('CONFERIR-NAVEGADOR-')]

    def test_refuses_when_elevated_without_creating_folder(self):
        with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
            browser_vault.restore_to_staging(self.package, self.destination, PASSWORD,
                                             elevation_probe=elevated)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_probe_is_asked_before_verify_vault(self):
        order = []

        def probe():
            order.append('probe')
            return True

        def fake_verify(*args, **kwargs):
            order.append('verify_vault')
            raise AssertionError('verify_vault should not run when elevated')

        with patch.object(browser_vault, 'verify_vault', side_effect=fake_verify) as verify:
            with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
                browser_vault.restore_to_staging(self.package, self.destination, PASSWORD,
                                                 elevation_probe=probe)
        verify.assert_not_called()
        self.assertEqual(order, ['probe'])
        self.assertEqual(self.staged(), [])

    def test_only_literal_true_releases(self):
        for value in NOT_TRUE:
            with self.subTest(allow_elevated=value):
                with self.assertRaises(elevation_guard.ElevatedRestoreRefused):
                    browser_vault.restore_to_staging(self.package, self.destination, PASSWORD,
                                                     allow_elevated=value,
                                                     elevation_probe=elevated)
        self.assertEqual(self.staged(), [])
        output = browser_vault.restore_to_staging(self.package, self.destination, PASSWORD,
                                                  allow_elevated=True, elevation_probe=elevated)
        self.assertEqual((output / 'profile' / 'Bookmarks').read_text(encoding='utf-8'),
                         'favorites-sinteticos')

    def test_not_elevated_works(self):
        output = browser_vault.restore_to_staging(self.package, self.destination, PASSWORD,
                                                  elevation_probe=not_elevated)
        self.assertTrue(output.name.startswith('CONFERIR-NAVEGADOR-'))


class ModuleShapeTests(unittest.TestCase):
    ORDERS = (
        ('elevation_guard', 'restore_elevation', 'backup_features', 'backup_core', 'browser_vault'),
        ('restore_elevation', 'elevation_guard'),
        ('backup_features', 'restore_elevation'),
        ('backup_core', 'backup_features', 'restore_elevation'),
        ('browser_vault', 'restore_elevation', 'backup_core'),
        ('restore_place_flow', 'selective_recovery'),
        ('selective_recovery', 'restore_place_flow', 'elevation_guard'),
    )

    def test_imports_in_any_order_without_circular_import(self):
        for order in self.ORDERS:
            with self.subTest(order=order):
                code = 'import sys; sys.path.insert(0, %r)\n' % str(ROOT)
                code += ''.join(f'import {name}\n' for name in order)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                        text=True, cwd=str(ROOT), env=env, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_guard_module_imports_nothing_from_project(self):
        source = (ROOT / 'elevation_guard.py').read_text(encoding='utf-8')
        local = {p.stem for p in ROOT.glob('*.py')}
        for line in source.splitlines():
            words = line.split()
            if len(words) >= 2 and words[0] in ('import', 'from'):
                self.assertNotIn(words[1].split('.')[0], local, line)

    def test_reexported_names_are_the_same_objects(self):
        for name in ('ElevatedRestoreRefused', 'REFUSAL_MESSAGE', 'ELEVATION_WARNING',
                     'is_process_elevated', 'require_not_elevated'):
            with self.subTest(name=name):
                self.assertIs(getattr(restore_elevation, name), getattr(elevation_guard, name))
        import restore_place_flow
        import selective_recovery
        self.assertIs(restore_place_flow.require_not_elevated, elevation_guard.require_not_elevated)
        self.assertIs(selective_recovery.require_not_elevated, elevation_guard.require_not_elevated)

    def test_refusal_is_still_a_permission_error(self):
        self.assertTrue(issubclass(elevation_guard.ElevatedRestoreRefused, PermissionError))


if __name__ == '__main__':
    unittest.main()
