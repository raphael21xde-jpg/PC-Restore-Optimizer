import unittest
from drive_catalog import coverage


class HonestCoverageTests(unittest.TestCase):
    def report(self, status='concluida', errors=(), skipped=(), stats=None):
        return dict(
            status=status,
            volume_stats=stats if stats is not None else {'C:': {'directories': 5, 'files': 8}},
            errors=[{'path': path} for path in errors],
            skipped=[{'path': path} for path in skipped],
        )

    def test_finished_scan_with_no_gaps_is_complete(self):
        self.assertTrue(coverage(self.report(), 'C:')['complete'])

    def test_finished_scan_with_gaps_is_not_complete(self):
        r = self.report('concluida_com_lacunas', errors=('C:/inaccessible',))
        self.assertFalse(coverage(r, 'C:')['complete'])

    def test_cancelled_scan_is_not_complete(self):
        self.assertFalse(coverage(self.report('cancelada_parcial'), 'C:')['complete'])

    def test_unknown_or_unscanned_drive_is_not_complete(self):
        self.assertFalse(coverage(self.report(), 'Z:')['complete'])

    def test_explicitly_skipped_directory_is_not_complete(self):
        self.assertFalse(coverage(self.report('concluida_com_lacunas', skipped=('C:/backup',)), 'C:')['complete'])


if __name__ == '__main__':
    unittest.main()
