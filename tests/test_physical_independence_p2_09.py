"""P2-09 slice 2b: physical-independence lock wired to the judge and executor.

Only fake collectors and synthetic files inside TemporaryDirectory. No real
disk, command, PowerShell or WMI query is used.
"""
import ast
import copy
import hashlib
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import (FAKE_MODEL, FAKE_SERIAL, CountingCollector,  # noqa: E402
                              fake_inventory)

import backup_core  # noqa: E402
import multi_source_executor as executor  # noqa: E402
import physical_independence as pi  # noqa: E402
from multi_source_plan import prepare_multi_source_preview  # noqa: E402
from multi_source_targets import preview_multi_source_targets  # noqa: E402
from transfer_engine import choose_strategy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'physical_independence' + '_verified'
SOURCES = ['A:', 'B:']
TARGETS = ['T:', 'U:']


def verify(collector, sources=SOURCES, targets=TARGETS):
    return pi.verify_physical_independence(sources, targets, collector=collector)


def assert_private(test, result):
    # Raw text of every string in the result (json.dumps would escape \n).
    blob = '\n'.join([result['texto'], result['veredito']] +
                     [str(v) for item in result['destinos'] for v in item.values()])
    for secret in (FAKE_SERIAL, FAKE_MODEL, 'Volume{', '\\', 'SerialNumber',
                   'FriendlyName', 'Virtual', 'VMware', '/tmp', 'Users'):
        test.assertNotIn(secret, blob)
        test.assertNotIn(secret, result['texto'])


class VerifyTests(unittest.TestCase):
    def assertRefused(self, result):
        self.assertIs(result[LOCK], False)
        self.assertNotEqual(result['veredito'], 'independentes')
        self.assertIn('Por segurança', result['texto'])
        self.assertEqual(set(result), {LOCK, 'veredito', 'destinos', 'texto'})
        assert_private(self, result)
        return result

    def test_separate_nvme_and_sata_is_true(self):
        collector = CountingCollector()
        result = verify(collector)
        self.assertIs(result[LOCK], True)
        self.assertEqual(result['veredito'], 'independentes')
        self.assertEqual([x['unidade'] for x in result['destinos']], TARGETS)
        self.assertIn('Discos separados', result['texto'])
        self.assertEqual(collector.calls, 1)
        assert_private(self, result)

    def test_lowercase_and_no_colon_letters_are_accepted(self):
        self.assertIs(verify(CountingCollector(), ['a', 'b:'], ['t', 'U'])[LOCK],
                      True)

    def test_same_disk_is_false(self):
        layout = {'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3}
        result = self.assertRefused(verify(CountingCollector(fake_inventory(layout))))
        self.assertEqual(result['veredito'], 'mesmo_disco')

    def test_boot_disk_target_is_false(self):
        layout = {'C': 0, 'A': 1, 'B': 1, 'T': 0, 'U': 3}
        self.assertRefused(verify(CountingCollector(fake_inventory(layout))))

    def test_raid_spaces_scsi_sas_are_false(self):
        for bus in ('RAID', 'Spaces', 'Storage Spaces', 'SCSI', 'SAS', 'iSCSI'):
            with self.subTest(bus=bus):
                inv = fake_inventory(bus={0: 'NVMe', 1: 'NVMe', 2: bus, 3: 'SATA'})
                self.assertRefused(verify(CountingCollector(inv)))

    def test_storage_spaces_extent_is_false(self):
        inv = fake_inventory()
        inv['extent_mapping']['volumes'][3]['status'] = 'virtual_spaces'
        self.assertRefused(verify(CountingCollector(inv)))

    def test_virtual_names_on_nvme_are_false(self):
        for name in ('Virtual Disk', 'VMware Virtual NVMe Disk', 'VBOX HARDDISK',
                     'QEMU HARDDISK', 'Msft Virtual Disk'):
            with self.subTest(name=name):
                inv = fake_inventory(bus={0: 'NVMe', 1: 'NVMe', 2: 'NVMe', 3: 'NVMe'},
                                     names={2: name})
                self.assertRefused(verify(CountingCollector(inv)))

    def test_collector_problems_are_false_without_exception(self):
        no_disks = fake_inventory()
        del no_disks['disks']
        cases = [
            CountingCollector(error=OSError('falha')),
            CountingCollector(error=RuntimeError('falha')),
            CountingCollector(error=KeyError('x')),
            CountingCollector(error=Exception('C:\\Users\\fulano\\segredo')),
            CountingCollector(None),
            CountingCollector(no_disks),
            CountingCollector({}),
            CountingCollector('texto'),
            CountingCollector(dict(fake_inventory(), disks='x')),
        ]
        for collector in cases:
            with self.subTest(case=repr(collector.inventories[0])[:40]):
                result = self.assertRefused(verify(collector))
                self.assertNotIn('fulano', result['texto'])
                self.assertEqual(collector.calls, 1)

    def test_bad_or_repeated_letters_are_false(self):
        cases = [
            (['A:', 'A:'], TARGETS), (SOURCES, ['T:', 't']), (None, TARGETS),
            (SOURCES, None), ('A:', TARGETS), ([], TARGETS), (SOURCES, []),
            (['AA:'], TARGETS), ([1], TARGETS), (SOURCES, ['C:\\pasta']),
        ]
        for sources, targets in cases:
            with self.subTest(sources=sources, targets=targets):
                self.assertRefused(verify(CountingCollector(), sources, targets))

    def test_target_equal_to_source_letter_is_false(self):
        self.assertRefused(verify(CountingCollector(), ['A:'], ['A:']))

    def test_letters_not_matching_report_are_false(self):
        real = pi.inspect_fresh_drive_safety

        def other_letters(*args, **kwargs):
            report = real(*args, **kwargs)
            report['source_volumes'][1]['letter'] = 'Z:'
            return report

        with patch.object(pi, 'inspect_fresh_drive_safety', other_letters):
            self.assertRefused(verify(CountingCollector()))

        def repeated_target(*args, **kwargs):
            report = real(*args, **kwargs)
            report['destinations'][1]['letter'] = 'T:'
            return report

        with patch.object(pi, 'inspect_fresh_drive_safety', repeated_target):
            self.assertRefused(verify(CountingCollector()))

    def test_judge_independent_but_inventory_not_fresh_is_false(self):
        real = pi.inspect_fresh_drive_safety

        def stale(*args, **kwargs):
            report = real(*args, **kwargs)
            report['inventory_status'] = 'cached'
            return report

        with patch.object(pi, 'inspect_fresh_drive_safety', stale):
            result = verify(CountingCollector())
        self.assertIs(result[LOCK], False)

    def test_inspection_or_judge_error_is_false(self):
        def boom(*args, **kwargs):
            raise RuntimeError('C:\\Users\\fulano')

        for name in ('inspect_fresh_drive_safety', 'judge_physical_disks',
                     'format_verdict_pt'):
            with self.subTest(name=name), patch.object(pi, name, boom):
                result = pi.verify_physical_independence(
                    SOURCES, TARGETS, collector=CountingCollector())
                self.assertIs(result[LOCK], False)
                self.assertNotIn('fulano', json.dumps(result))
                self.assertIn('Por segurança', result['texto'])

    def test_judge_gets_deep_copy_of_one_snapshot(self):
        original = fake_inventory()
        seen = []
        real = pi.inspect_fresh_drive_safety

        def spy(sources, targets, *, collector):
            first, second = collector(), collector()
            seen.append((first, second))
            return real(sources, targets, collector=lambda: first)

        with patch.object(pi, 'inspect_fresh_drive_safety', spy):
            result = pi.verify_physical_independence(
                SOURCES, TARGETS, collector=lambda: original)
        self.assertIs(result[LOCK], True)
        first, second = seen[0]
        self.assertIs(first, second)
        self.assertIsNot(first, original)
        self.assertEqual(first, original)

    def test_repeated_target_letter_says_same_drive(self):
        for targets in (['T:', 'T:'], ['T:', 't'], ['u', 'T:', 'U:']):
            with self.subTest(targets=targets):
                collector = CountingCollector()
                result = self.assertRefused(verify(collector, SOURCES, targets))
                self.assertIn('mesma unidade', result['texto'])
                letter = targets[-1].strip()[0].upper() + ':'
                self.assertIn(f'({letter})', result['texto'])
                self.assertEqual(collector.calls, 0)

    def test_not_fresh_with_independent_verdict_never_says_separate(self):
        real = pi.inspect_fresh_drive_safety

        def stale(*args, **kwargs):
            report = real(*args, **kwargs)
            report['inventory_status'] = 'cached'
            return report

        with patch.object(pi, 'inspect_fresh_drive_safety', stale):
            result = self.assertRefused(verify(CountingCollector()))
        self.assertEqual(result['veredito'], 'duvida')
        self.assertEqual(result['destinos'], [])
        self.assertIn(pi.MSG_NOT_FRESH, result['texto'])
        for text in ('Discos separados', 'disco separado', 'liberado',
                     'pode copiar'):
            self.assertNotIn(text, result['texto'])

    def test_inventory_status_none_is_refused_as_not_fresh(self):
        def not_fresh_value(*args, **kwargs):
            report = real(*args, **kwargs)
            report['inventory_status'] = None
            return report

        real = pi.inspect_fresh_drive_safety
        with patch.object(pi, 'inspect_fresh_drive_safety', not_fresh_value):
            result = self.assertRefused(verify(CountingCollector()))
        self.assertIn(pi.MSG_NOT_FRESH, result['texto'])
        self.assertNotIn('Discos separados', result['texto'])
        self.assertNotIn('disco separado', result['texto'])

    def test_missing_or_bad_collector_is_refused_without_exception(self):
        for collector in (None, 'x', 3):
            with self.subTest(collector=collector):
                result = pi.verify_physical_independence(
                    SOURCES, TARGETS, collector=collector)
                self.assertIs(result[LOCK], False)
                self.assertEqual(result['veredito'], 'duvida')
                self.assertIn(pi.MSG_NO_COLLECTOR, result['texto'])
                self.assertIn('a cópia foi recusada', result['texto'])
                self.assertNotIn('Discos separados', result['texto'])

    def test_numeric_bus_type_stays_doubt(self):
        # Pending for slice 3: numeric BusType codes are not mapped yet.
        for bus in (17, 11, '11', '17', True, 0, None, ''):
            with self.subTest(bus=bus):
                inv = fake_inventory(bus={0: 'NVMe', 1: 'NVMe', 2: bus, 3: 'SATA'})
                result = self.assertRefused(verify(CountingCollector(inv)))
                self.assertEqual(result['veredito'], 'duvida')

    def test_no_server_disk_wording_in_code(self):
        for name in ('physical_disk_check.py', 'physical_independence.py',
                     'multi_source_executor.py'):
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                self.assertNotIn('disco de servidor', text)
        self.assertIn('(por exemplo RAID, disco virtual ou tipo desconhecido)',
                      pi.format_verdict_pt.__globals__['MSG_BUS'])

    def test_collector_is_called_exactly_once(self):
        for inv in (fake_inventory(), None,
                    fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})):
            collector = CountingCollector(inv)
            verify(collector)
            self.assertEqual(collector.calls, 1)


class CodeShapeTests(unittest.TestCase):
    def test_collectors_are_required_keyword_only(self):
        param = inspect.signature(pi.verify_physical_independence).parameters['collector']
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)
        for func in (executor.preview_execution, executor.run_protected_copy):
            with self.subTest(func=func.__name__):
                param = inspect.signature(func).parameters['disk_collector']
                self.assertIs(param.default, inspect.Parameter.empty)
                self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_true_only_from_one_expression_tied_to_the_verdict(self):
        source = (ROOT / 'physical_independence.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        constants_true = [node for node in ast.walk(tree)
                          if isinstance(node, ast.Constant) and node.value is True]
        self.assertEqual(constants_true, [])
        values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == LOCK:
                        values.append(value)
        self.assertEqual(len(values), 2)
        names = [v for v in values if isinstance(v, ast.Name)]
        falses = [v for v in values
                  if isinstance(v, ast.Constant) and v.value is False]
        self.assertEqual((len(names), len(falses)), (1, 1))
        assigns = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == names[0].id
                           for t in node.targets)]
        self.assertEqual(len(assigns), 1)
        expr = assigns[0].value
        self.assertIsInstance(expr, ast.BoolOp)
        self.assertIsInstance(expr.op, ast.And)
        text = ast.get_source_segment(source, expr)
        self.assertIn("'veredito'", text)
        self.assertIn('INDEPENDENT', text)
        self.assertIn("'fresh_collected'", text)
        self.assertIn('letters_match', text)

    def test_executor_never_writes_the_lock(self):
        source = (ROOT / 'multi_source_executor.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    self.assertFalse(isinstance(key, ast.Constant)
                                     and key.value == LOCK)
            if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
                self.assertNotEqual(getattr(node.slice, 'value', None), LOCK)
            if isinstance(node, ast.keyword):
                self.assertNotEqual(node.arg, LOCK)
        for lock in ('copy_authorized', 'deletions_authorized',
                     'ready_for_format', 'installation_authorized'):
            self.assertNotIn(lock, source)

    def test_bridge_has_no_commands_tk_or_writes(self):
        source = (ROOT / 'physical_independence.py').read_text(encoding='utf-8')
        for word in ('subprocess', 'tkinter', 'powershell', 'PowerShell',
                     'open(', 'unlink', 'rmtree', 'os.system', 'disk_inventory',
                     'copy_authorized', 'deletions_authorized',
                     'ready_for_format', 'installation_authorized'):
            self.assertNotIn(word, source)

    def test_app_and_screens_do_not_import_bridge_or_executor(self):
        pattern = re.compile(
            r'\b(physical_independence|multi_source_executor)\b(?!_verified)')
        files = [ROOT / 'app.py', *sorted(ROOT.glob('*_ui.py'))]
        self.assertGreater(len(files), 1)
        for path in files:
            with self.subTest(file=path.name):
                self.assertIsNone(pattern.search(path.read_text(encoding='utf-8')))


class ExecutorGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pcro-lock-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.sandbox = self.root / 'sandbox'
        self.folders = {}
        for name in ('source_A', 'source_B', 'target_T', 'target_U'):
            folder = self.sandbox / name
            folder.mkdir(parents=True)
            self.folders[name] = folder
        self.first = self.folders['source_A'] / 'documento.txt'
        self.second = self.folders['source_B'] / 'jogo.sav'
        self.first.write_bytes(b'doc' * 100)
        self.second.write_bytes(b'save' * 100)
        self.plan = prepare_multi_source_preview(
            [str(self.first), str(self.second)],
            [str(self.folders['source_A']), str(self.folders['source_B'])])
        self.state = self.source_state()
        for target, value in (
                ('choose_strategy',
                 lambda src, dst, inventory=None: choose_strategy(src, dst, inventory={})),
                ('free_space', lambda folder: 100 * 1024 ** 3)):
            patcher = patch.object(backup_core, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def volume(self, raw):
        path = Path(raw)
        for name, drive in (('source_A', 'A:'), ('source_B', 'B:'),
                            ('target_T', 'T:'), ('target_U', 'U:')):
            folder = self.folders[name]
            if path == folder or folder in path.parents:
                return drive
        return 'S:'

    @staticmethod
    def usage(_):
        return SimpleNamespace(free=100 * 1024 ** 3)

    def preview(self):
        return preview_multi_source_targets(
            self.plan, [str(self.folders['target_T']), str(self.folders['target_U'])],
            usage=self.usage, volume_lookup=self.volume)

    def kwargs(self, collector):
        return dict(test_root=str(self.sandbox), volume_lookup=self.volume,
                    usage=self.usage, disk_collector=collector)

    def source_state(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in (self.first, self.second)}

    def tree(self, name):
        return sorted(p.name for p in self.folders[name].rglob('*'))

    def test_not_independent_refuses_before_first_byte(self):
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        scsi = fake_inventory(bus={0: 'NVMe', 1: 'NVMe', 2: 'SCSI', 3: 'SATA'})
        virtual = fake_inventory(names={3: 'VMware Virtual NVMe Disk'})
        for label, collector in (('mesmo disco', CountingCollector(same)),
                                 ('scsi', CountingCollector(scsi)),
                                 ('virtual', CountingCollector(virtual)),
                                 ('erro', CountingCollector(error=OSError('x')))):
            with self.subTest(label), patch.object(
                    backup_core, 'copy_backup',
                    side_effect=AssertionError('não podia copiar')) as copier:
                with self.assertRaisesRegex(ValueError, 'Cópia recusada') as caught:
                    executor.run_protected_copy(
                        self.plan, self.preview(), **self.kwargs(collector))
                copier.assert_not_called()
                self.assertEqual(collector.calls, 1)
                self.assertIn('Por segurança', str(caught.exception))
                self.assertNotIn(str(self.root), str(caught.exception))
                self.assertEqual(self.tree('target_T'), [])
                self.assertEqual(self.tree('target_U'), [])
        self.assertEqual(self.source_state(), self.state)

    def test_verdict_changes_after_first_destination(self):
        good = fake_inventory()
        moved = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 2, 'U': 1})
        collector = CountingCollector(good, moved)
        result = executor.run_protected_copy(
            self.plan, self.preview(), **self.kwargs(collector))
        self.assertEqual(collector.calls, 2)
        first, second = result['destinations']
        self.assertEqual(first['status'], 'verificado')
        self.assertEqual(second['status'], 'nao_iniciado')
        self.assertEqual(second['problem'], executor.PROBLEMS['discos'])
        self.assertEqual(result['reason'], executor.PROBLEMS['discos'])
        self.assertEqual(result['status'], 'parcial')
        self.assertEqual(self.tree('target_U'), [])
        self.assertEqual(result['physical_check']['veredito'], 'mesmo_disco')
        text = executor.format_report_pt(result)
        self.assertIn('mesmo disco', text)
        self.assertNotIn('Isto não prova', text)
        self.assertNotIn(pi.READ_ONLY_NOTE, text)
        self.assertNotIn(str(self.root), text)
        self.assertEqual(self.source_state(), self.state)

    def test_collector_called_once_per_destination(self):
        collector = CountingCollector()
        result = executor.run_protected_copy(
            self.plan, self.preview(), **self.kwargs(collector))
        self.assertEqual(result['status'], 'verificado')
        self.assertEqual(collector.calls, 2)
        text = executor.format_report_pt(result)
        self.assertIn('Discos separados', text)
        for secret in (FAKE_SERIAL, FAKE_MODEL, str(self.root)):
            self.assertNotIn(secret, text)

    def test_preview_shows_verdict_and_writes_nothing(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        for inv, verdict in (
                (fake_inventory(), 'independentes'),
                (fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3}), 'mesmo_disco'),
                (None, 'duvida')):
            with self.subTest(verdict=verdict):
                collector = CountingCollector(inv)
                info = executor.preview_execution(
                    self.plan, self.preview(), **self.kwargs(collector))
                self.assertEqual(collector.calls, 1)
                self.assertEqual(info['physical_check']['veredito'], verdict)
                self.assertTrue(info['physical_check']['texto'])
                self.assertNotIn(LOCK, info)
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*')), before)

    def test_ready_made_answer_from_outside_is_not_accepted(self):
        with self.assertRaises(TypeError):
            executor.run_protected_copy(
                self.plan, self.preview(), test_root=str(self.sandbox),
                volume_lookup=self.volume, usage=self.usage)
        with self.assertRaises(TypeError):
            executor.run_protected_copy(
                self.plan, self.preview(), **self.kwargs(CountingCollector()),
                physical_independence_verified=True)
        self.assertEqual(self.tree('target_T'), [])

    def test_two_targets_on_same_drive_refuse_with_reason(self):
        folder_a = self.folders['target_T'] / 'a'
        folder_b = self.folders['target_T'] / 'b'
        folder_a.mkdir()
        folder_b.mkdir()
        preview = preview_multi_source_targets(
            self.plan, [str(folder_a), str(folder_b)],
            usage=self.usage, volume_lookup=self.volume)
        collector = CountingCollector()
        with patch.object(backup_core, 'copy_backup',
                          side_effect=AssertionError('não podia copiar')) as copier:
            with self.assertRaisesRegex(ValueError, 'Cópia recusada') as caught:
                executor.run_protected_copy(
                    self.plan, preview, **self.kwargs(collector))
        copier.assert_not_called()
        self.assertIn('mesma unidade', str(caught.exception))
        self.assertNotIn('Discos separados', str(caught.exception))
        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertEqual(self.tree('target_T'), ['a', 'b'])
        self.assertEqual(sorted(p.name for p in folder_a.rglob('*')), [])
        self.assertEqual(sorted(p.name for p in folder_b.rglob('*')), [])
        self.assertEqual(self.source_state(), self.state)

    def test_missing_disk_collector_refuses_without_crash(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        info = executor.preview_execution(
            self.plan, self.preview(), **self.kwargs(None))
        self.assertEqual(info['physical_check']['veredito'], 'duvida')
        self.assertIn(pi.MSG_NO_COLLECTOR, info['physical_check']['texto'])
        with patch.object(backup_core, 'copy_backup',
                          side_effect=AssertionError('não podia copiar')) as copier:
            with self.assertRaisesRegex(ValueError, 'Cópia recusada') as caught:
                executor.run_protected_copy(
                    self.plan, self.preview(), **self.kwargs(None))
        copier.assert_not_called()
        self.assertIn(pi.MSG_NO_COLLECTOR, str(caught.exception))
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*')), before)

    def test_report_without_check_says_it_was_not_done(self):
        text = executor.format_report_pt({'status': 'verificado', 'destinations': []})
        self.assertIn(executor.NO_DISK_CHECK, text)


if __name__ == '__main__':
    unittest.main()
