"""#41-43 integration safeguards: real engines only on synthetic data."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from autotestes_41_43 import (
    scan_metadata_extended,
    run_inventory_permissions_autotest,
    run_cross_volume_links_autotest,
    run_restore_write_recovery_autotest,
)


class TestBateria41a43(unittest.TestCase):
    def check_safety(self, report, number):
        self.assertEqual(report["status"], "aprovado")
        self.assertEqual(report["schema"], f"pcro-autoteste-bateria-v{number}")
        for field in ("ready_for_format", "installation_authorized",
                      "real_user_backups_accessed", "physical_independence_verified"):
            self.assertFalse(report[field])

    def test_41_classifies_permission_denied_without_failing_whole_volume(self):
        with tempfile.TemporaryDirectory(prefix="PCRO-TESTE41-") as tmp:
            root = Path(tmp) / "volume"
            root.mkdir()
            blocked = root / "bloqueada"
            blocked.mkdir()
            (root / "SteamApps").mkdir()
            (root / "SteamApps" / "demo.dat").write_bytes(b"sample")
            original = os.scandir

            def denied(path):
                if Path(path) == blocked:
                    raise PermissionError(13, "acesso negado")
                return original(path)

            with patch("autotestes_41_43.os.scandir", side_effect=denied):
                report = run_inventory_permissions_autotest(roots=[root])
            self.check_safety(report, 41)
            self.assertEqual(report["permission_denied_count"], 1)
            self.assertEqual(report["candidate_folders"], 1)
            self.assertEqual(report["content_files_opened"], 0)
            self.assertFalse(report["writes_performed"])
            self.assertTrue(report["partial_coverage"])

    def test_41_limits_depth_and_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "subfolder").mkdir()
            (root / "subfolder" / "nested").mkdir()
            for idx in range(10):
                (root / f"file-{idx}").write_bytes(b"fake")
            limited = scan_metadata_extended([root], max_entries=2, max_depth=0)
            self.assertEqual(limited[0]["entries_examined"], 2)
            self.assertTrue(limited[0]["entry_limit_reached"])
            expanded = scan_metadata_extended([root], max_entries=20, max_depth=0)
            self.assertGreaterEqual(expanded[0]["depth_limited_folders"], 1)

    def test_41_stops_when_cancelled(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            run_inventory_permissions_autotest(roots=["not-inspected"], cancelled=event)
        with self.assertRaises(ValueError):
            scan_metadata_extended([], max_depth=13)

    def test_42_cross_volume_user_approval_is_not_verified_backup(self):
        with patch("builtins.open", side_effect=AssertionError("do not access files")):
            report = run_cross_volume_links_autotest()
        self.check_safety(report, 42)
        self.assertEqual(report["synthetic_links"], 3)
        self.assertEqual(report["user_approved_associations"], 2)
        self.assertEqual(report["unreviewed_links"], 1)
        self.assertEqual(report["verified_backups"], 0)
        self.assertEqual(report["c_volume_data_requires_preservation"], 2)

    def test_43_failure_is_rejected_then_resume_verified(self):
        report = run_restore_write_recovery_autotest()
        self.check_safety(report, 43)
        for field in ("injected_write_error_caught",
                      "partial_journal_rejected_as_complete",
                      "abandoned_transfer_fragments_cleaned",
                      "restore_sha256_verified", "source_files_preserved",
                      "temporary_data_cleaned"):
            self.assertTrue(report[field], field)
        self.assertEqual(report["resume_count"], 1)

    def test_43_cancel_before_work(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            run_restore_write_recovery_autotest(cancelled=event)


if __name__ == "__main__":
    unittest.main()
