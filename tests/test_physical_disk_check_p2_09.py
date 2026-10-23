"""P2-09 slice 2a: pure physical-disk independence judge.

Only hand-made dictionaries; no command, disk or file is touched.
"""
import copy
import json
import re
import unittest
from pathlib import Path

import physical_disk_check as pdc

ROOT = Path(__file__).resolve().parents[1]


def volume(letter, disks, *, extent='observed_logical_only',
           cross='logical_match', status=None, partition=None):
    item = {
        'letter': letter,
        'logical_disk_numbers': list(disks),
        'extent_status': extent,
        'partition_crosscheck': cross,
        'partition_logical_disk_numbers': list(
            disks if partition is None else partition),
    }
    if status is not None:
        item['status'] = status
    return item


def report(sources, targets, boot=(0,)):
    return {
        'source_volumes': sources,
        'destinations': targets,
        'boot_related_logical_disks': list(boot),
    }


def disk(number, bus):
    row = {'Number': number, 'FriendlyName': 'Modelo X',
           'SerialNumber': 'ABC123'}
    if bus is not None:
        row['BusType'] = bus
    return row


GOOD_DISKS = [disk(0, 'NVMe'), disk(1, 'SATA'), disk(2, 'USB')]


def good_report():
    return report([volume('C:', [0])],
                  [volume('E:', [1], status='requires_review')])


class IndependentTests(unittest.TestCase):
    def test_nvme_source_sata_target_is_independent(self):
        result = pdc.judge_physical_disks(good_report(), GOOD_DISKS)
        self.assertEqual(result['veredito'], 'independentes')
        self.assertEqual(result['destinos'], [
            {'unidade': 'E:', 'veredito': 'independentes',
             'motivo': result['destinos'][0]['motivo']}])
        self.assertTrue(result['motivos'])

    def test_other_accepted_buses(self):
        # SCSI/SAS stay accepted (spec); virtual disks of Hyper-V/VMware may
        # show up as SCSI/SAS: limitation to review in slice 2b.
        for bus in ('ATA', 'SAS', 'SCSI', 'USB', ' sata '):
            data = good_report()
            disks = [disk(0, 'NVMe'), disk(1, bus)]
            with self.subTest(bus=bus):
                self.assertEqual(
                    pdc.judge_physical_disks(data, disks)['veredito'],
                    'independentes')

    def test_does_not_modify_input(self):
        data = good_report()
        disks = copy.deepcopy(GOOD_DISKS)
        before = (copy.deepcopy(data), copy.deepcopy(disks))
        pdc.judge_physical_disks(data, disks)
        self.assertEqual((data, disks), before)


class SameDiskTests(unittest.TestCase):
    def test_target_on_source_disk(self):
        data = report([volume('D:', [1])],
                      [volume('E:', [1], status='blocked')], boot=[0])
        result = pdc.judge_physical_disks(data, GOOD_DISKS)
        self.assertEqual(result['veredito'], 'mesmo_disco')
        self.assertEqual(result['destinos'][0]['veredito'], 'mesmo_disco')

    def test_same_disk_seen_only_by_partitions(self):
        data = report([volume('D:', [2], partition=[1])],
                      [volume('E:', [1])], boot=[0])
        self.assertEqual(pdc.judge_physical_disks(data, GOOD_DISKS)['veredito'],
                         'mesmo_disco')

    def test_target_letter_equal_to_source(self):
        data = report([volume('C:', [0])], [volume('C:', [0])], boot=[])
        self.assertEqual(pdc.judge_physical_disks(data, GOOD_DISKS)['veredito'],
                         'mesmo_disco')


class DoubtTests(unittest.TestCase):
    def assertDoubt(self, data, disks=GOOD_DISKS):
        result = pdc.judge_physical_disks(data, disks)
        self.assertEqual(result['veredito'], 'duvida')
        self.assertTrue(result['motivos'])
        return result

    def test_extent_status_not_observed(self):
        for status in ('virtual_spaces', 'multi_disk', 'disk_not_listed',
                       'incomplete', 'qualquer'):
            with self.subTest(target=status):
                data = good_report()
                data['destinations'][0]['extent_status'] = status
                self.assertDoubt(data)
            with self.subTest(source=status):
                data = good_report()
                data['source_volumes'][0]['extent_status'] = status
                self.assertDoubt(data)

    def test_more_than_one_disk_number(self):
        data = report([volume('C:', [0])], [volume('E:', [1, 2])])
        self.assertDoubt(data)

    def test_crosscheck_not_matching(self):
        for cross in ('limited_match', 'conflict', 'inconclusive', 'unavailable',
                      'extent_only', 'partition_only'):
            with self.subTest(target=cross):
                data = good_report()
                data['destinations'][0]['partition_crosscheck'] = cross
                self.assertDoubt(data)
            with self.subTest(source=cross):
                data = good_report()
                data['source_volumes'][0]['partition_crosscheck'] = cross
                self.assertDoubt(data)

    def test_blocked_target(self):
        data = good_report()
        data['destinations'][0]['status'] = 'blocked'
        self.assertDoubt(data)

    def test_missing_or_unknown_target_status(self):
        data = good_report()
        del data['destinations'][0]['status']
        self.assertDoubt(data)
        for status in ('xyz', '', None, 'REQUIRES_REVIEW', 1):
            with self.subTest(status=status):
                data = good_report()
                data['destinations'][0]['status'] = status
                self.assertDoubt(data)

    def test_empty_boot_list_is_doubt(self):
        data = report([volume('D:', [1])],
                      [volume('C:', [0], status='requires_review')], boot=[])
        result = self.assertDoubt(data)
        self.assertEqual(result['destinos'][0]['veredito'], 'duvida')
        text = pdc.format_verdict_pt(result)
        self.assertNotIn('\\', text)

    def test_target_on_boot_disk_that_is_not_source(self):
        data = report([volume('D:', [2])], [volume('E:', [0])], boot=[0])
        result = self.assertDoubt(data)
        self.assertEqual(result['destinos'][0]['veredito'], 'duvida')

    def test_unaccepted_bus_types(self):
        for bus in ('RAID', 'iSCSI', 'File Backed Virtual', 'Virtual',
                    'Spaces', 'Storage Spaces', '', None, 17, 'Unknown'):
            with self.subTest(target=bus):
                self.assertDoubt(good_report(), [disk(0, 'NVMe'), disk(1, bus)])
            with self.subTest(source=bus):
                self.assertDoubt(good_report(), [disk(0, bus), disk(1, 'SATA')])

    def test_disk_missing_or_duplicated_in_get_disk(self):
        self.assertDoubt(good_report(), [disk(0, 'NVMe')])
        self.assertDoubt(good_report(),
                         [disk(0, 'NVMe'), disk(1, 'SATA'), disk(1, 'SATA')])

    def test_no_sources_or_no_targets(self):
        self.assertDoubt(report([], [volume('E:', [1])]))
        self.assertDoubt(report([volume('C:', [0])], []))

    def test_missing_boot_list_is_doubt(self):
        data = good_report()
        del data['boot_related_logical_disks']
        self.assertDoubt(data)


class WorstVerdictTests(unittest.TestCase):
    def test_one_good_one_doubtful(self):
        data = report([volume('C:', [0])],
                      [volume('E:', [1], status='requires_review'),
                       volume('F:', [2], cross='conflict',
                              status='requires_review')])
        result = pdc.judge_physical_disks(data, GOOD_DISKS)
        self.assertEqual(result['veredito'], 'duvida')
        self.assertEqual([x['veredito'] for x in result['destinos']],
                         ['independentes', 'duvida'])
        self.assertEqual(len(result['motivos']), 1)

    def test_same_disk_beats_doubt(self):
        data = report([volume('C:', [0]), volume('D:', [2])],
                      [volume('E:', [1], cross='conflict'), volume('F:', [2])])
        result = pdc.judge_physical_disks(data, GOOD_DISKS)
        self.assertEqual(result['veredito'], 'mesmo_disco')
        self.assertEqual([x['veredito'] for x in result['destinos']],
                         ['duvida', 'mesmo_disco'])

    def test_severity_order_is_documented(self):
        self.assertLess(pdc.SEVERITY['independentes'], pdc.SEVERITY['duvida'])
        self.assertLess(pdc.SEVERITY['duvida'], pdc.SEVERITY['mesmo_disco'])


class MalformedTests(unittest.TestCase):
    def test_malformed_inputs_never_raise(self):
        base = good_report()
        cases = [
            (None, GOOD_DISKS), (base, None), ([], GOOD_DISKS),
            ('texto', GOOD_DISKS), (base, 'texto'), ({}, GOOD_DISKS),
            (report(None, [volume('E:', [1])]), GOOD_DISKS),
            (report([volume('C:', [0])], None), GOOD_DISKS),
            (report([volume('C:', [0])], [None]), GOOD_DISKS),
            (report([volume('C:', [0])], ['E:']), GOOD_DISKS),
            (report([None], [volume('E:', [1])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [-1])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [True])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [1.0])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', ['1'])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [1, 1])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [70000])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [1])], boot=[True]),
             GOOD_DISKS),
            (report([volume('C:', [0])], [volume('E:', [1])], boot=[-1]),
             GOOD_DISKS),
            (report([volume('C:', [0])], [volume(5, [1])]), GOOD_DISKS),
            (report([volume('C:', [0])], [volume('EE:', [1])]), GOOD_DISKS),
            (good_report(), [None, 'x', 3]),
            (good_report(), [{'Number': True, 'BusType': 'SATA'},
                             disk(0, 'NVMe')]),
        ]
        for key in ('letter', 'logical_disk_numbers', 'extent_status',
                    'partition_crosscheck'):
            data = good_report()
            del data['destinations'][0][key]
            cases.append((data, GOOD_DISKS))
            data = good_report()
            data['destinations'][0][key] = None
            cases.append((data, GOOD_DISKS))
            data = good_report()
            del data['source_volumes'][0][key]
            cases.append((data, GOOD_DISKS))
        for index, (data, disks) in enumerate(cases):
            with self.subTest(case=index):
                result = pdc.judge_physical_disks(data, disks)
                self.assertEqual(result['veredito'], 'duvida')
                self.assertIsInstance(result['motivos'], list)
                self.assertTrue(result['motivos'])
                self.assertIsInstance(result['destinos'], list)
                self.assertIsInstance(pdc.format_verdict_pt(result), str)

    def test_format_handles_garbage(self):
        for value in (None, {}, [], 'x', {'veredito': 'sim'},
                      {'veredito': 'independentes', 'destinos': 'x',
                       'motivos': None}):
            with self.subTest(value=value):
                text = pdc.format_verdict_pt(value)
                self.assertIsInstance(text, str)
                self.assertTrue(text)


class PrivacyAndTextTests(unittest.TestCase):
    def test_output_has_no_identifiers_or_paths(self):
        results = [
            pdc.judge_physical_disks(good_report(), GOOD_DISKS),
            pdc.judge_physical_disks(
                report([volume('D:', [1])], [volume('E:', [1])]), GOOD_DISKS),
            pdc.judge_physical_disks(
                report([volume('D:', [2])], [volume('E:', [0])]), GOOD_DISKS),
            pdc.judge_physical_disks(None, None),
        ]
        for result in results:
            dumped = json.dumps(result, ensure_ascii=False)
            text = pdc.format_verdict_pt(result)
            for blob in (dumped, text):
                self.assertNotIn('\\', blob)
                for word in ('Serial', 'FriendlyName', 'Modelo X', 'ABC123',
                             'BusType'):
                    self.assertNotIn(word, blob)
            self.assertEqual(set(result), {'veredito', 'motivos', 'destinos'})
            for item in result['destinos']:
                self.assertEqual(set(item), {'unidade', 'veredito', 'motivo'})

    def test_texts_in_plain_portuguese(self):
        text = pdc.format_verdict_pt(
            pdc.judge_physical_disks(good_report(), GOOD_DISKS))
        self.assertIn('Discos separados', text)
        self.assertIn('E:', text)
        doubt = pdc.format_verdict_pt(pdc.judge_physical_disks(None, None))
        self.assertIn('Não deu para confirmar', doubt)
        for internal in ('extent', 'crosscheck', 'observed_logical_only',
                         'duvida', 'mesmo_disco'):
            self.assertNotIn(internal, text)
            self.assertNotIn(internal, doubt)


class SourceCodeTests(unittest.TestCase):
    def test_module_has_no_locks_commands_or_deletions(self):
        source = (ROOT / 'physical_disk_check.py').read_text(encoding='utf-8')
        locks = [
            'copy' + '_authorized',
            'physical_independence' + '_verified',
            'ready_for' + '_format',
            'installation' + '_authorized',
            'deletions' + '_authorized',
        ]
        for name in locks:
            self.assertNotIn(name, source)
        for forbidden in ('subprocess', 'os.remove', 'shutil.rmtree',
                          'unlink', 'rmdir', 'os.system', 'powershell',
                          'PowerShell', 'tkinter', 'open('):
            self.assertNotIn(forbidden, source)

    def test_not_imported_by_app_ui_or_executor(self):
        files = [ROOT / 'app.py', ROOT / 'multi_source_executor.py']
        files += sorted(ROOT.glob('*_ui.py'))
        pattern = re.compile(r'\bphysical_disk_check\b')
        for path in files:
            with self.subTest(file=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertIsNone(pattern.search(text))


if __name__ == '__main__':
    unittest.main()
