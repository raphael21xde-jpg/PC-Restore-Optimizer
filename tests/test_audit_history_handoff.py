"""History -> existing preservation/EFI audit, without an implicit SHA-256 job."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App


class HistoryAuditHandoffTests(unittest.TestCase):
    def test_selected_manifest_passed_to_existing_readonly_audit(self):
        manifest = Path(r"G:\backup-test\manifest.json")
        fake = SimpleNamespace(selected_manifest=Mock(return_value=manifest))
        with patch('completeness_audit_ui_v068.show_completeness_audit') as open_audit:
            App.open_selected_backup_completeness_audit(fake)
        open_audit.assert_called_once_with(fake, {}, history_manifest=manifest)

    def test_no_manifest_does_not_open_audit(self):
        fake = SimpleNamespace(selected_manifest=Mock(return_value=None))
        with patch('completeness_audit_ui_v068.show_completeness_audit') as open_audit:
            with patch('app.messagebox.showinfo') as warning:
                App.open_selected_backup_completeness_audit(fake)
        open_audit.assert_not_called()
        warning.assert_called_once()


if __name__ == '__main__':
    unittest.main()
