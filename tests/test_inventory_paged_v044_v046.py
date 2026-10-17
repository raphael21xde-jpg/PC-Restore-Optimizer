"""Tests for the real paginated read-only engine and synthetic #44-46."""
import os
from pathlib import Path
import tempfile
import threading
import unittest

from inventory_paged import PagedMetadataScanner
from autotestes_44_46 import (
    run_paged_inventory_autotest,
    run_pause_resume_inventory_autotest,
    run_gaps_inventory_autotest,
)


class TestPaginacao(unittest.TestCase):
    def safety(self, report, number):
        self.assertEqual(report["schema"], f"pcro-autoteste-bateria-v{number}")
        self.assertEqual(report["status"], "aprovado")
        for key in ("ready_for_format", "installation_authorized",
                    "real_user_backups_accessed", "physical_independence_verified"):
            self.assertFalse(report[key])
        self.assertTrue(report["temporary_data_cleaned"])

    def test_44_more_than_one_page_and_no_duplicates(self):
        report = run_paged_inventory_autotest()
        self.safety(report, 44)
        self.assertTrue(report["no_global_entry_cutoff"])
        self.assertTrue(report["no_duplicates"])
        self.assertEqual(report["entries_examined"], 126)
        self.assertGreater(report["pages_used"], 3)

    def test_45_pause_resume_keeps_same_iterator(self):
        report = run_pause_resume_inventory_autotest()
        self.safety(report, 45)
        self.assertTrue(report["pause_was_safe"])
        self.assertTrue(report["resume_without_duplicates"])

    def test_46_access_denied_never_means_verified(self):
        report = run_gaps_inventory_autotest()
        self.safety(report, 46)
        self.assertTrue(report["injected_permission_error_recorded"])
        self.assertTrue(report["incomplete_inventory_never_certified"])

    def test_page_parameter_rejection_and_closed_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            s = PagedMetadataScanner([directory])
            for page_size in (0, 10001, True, "20"):
                with self.subTest(size=page_size), self.assertRaises(ValueError):
                    s.step(page_size=page_size)
            s.close()
            with self.assertRaises(ValueError):
                s.step()

    def test_multiple_roots_counts_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            one, two = Path(directory) / "one", Path(directory) / "two"
            one.mkdir()
            two.mkdir()
            (one / "one.txt").write_bytes(b"1")
            (two / "a.txt").write_bytes(b"a")
            (two / "b.txt").write_bytes(b"b")
            s = PagedMetadataScanner([one, two])
            try:
                report = None
                for _ in range(20):
                    report = s.step(page_size=1)
                    if report["finished_current_session"]:
                        break
                self.assertTrue(report["finished_current_session"])
                self.assertEqual(report["entries_examined"], 3)
                self.assertEqual([v["files"] for v in report["volumes"]], [1, 2])
                self.assertTrue(report["partial_coverage"])
            finally:
                s.close()

    def test_cancellation_before_start_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_bytes(b"safe")
            cancel = threading.Event()
            cancel.set()
            s = PagedMetadataScanner([directory])
            try:
                with self.assertRaises(InterruptedError):
                    s.step(cancelled=cancel)
                self.assertEqual(s.snapshot()["entries_examined"], 0)
                cancel.clear()
                self.assertEqual(s.step(cancelled=cancel)["entries_examined"], 1)
            finally:
                s.close()
            self.assertEqual((root / "keep.txt").read_bytes(), b"safe")


if __name__ == "__main__":
    unittest.main()
