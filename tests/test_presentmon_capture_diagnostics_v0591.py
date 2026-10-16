import unittest
from optimization_ui import looks_like_presentmon_installer, presentmon_capture_explanation

class PresentMonCaptureDiagnosticsTests(unittest.TestCase):
    def test_reject_known_installer_names(self):
        for filename in ('PresentMon-2.6.0.exe','PresentMon 2.6.0.exe','IntelPresentMon-Setup.exe','PresentMon-Installer.exe'):
            with self.subTest(filename=filename):
                self.assertTrue(looks_like_presentmon_installer(filename))

    def test_accept_real_console_version_and_renamed_cli(self):
        for filename in ('PresentMon-2.6.0-x64.exe','PresentMon-2.5.1-x64.exe','PresentMon.exe','C:/Tools/PresentMon-2.6.0-x64.exe'):
            with self.subTest(filename=filename):
                self.assertFalse(looks_like_presentmon_installer(filename))

    def test_access_denied_uses_real_log(self):
        explanation=presentmon_capture_explanation(5,'Failed to start trace session (access denied)')
        self.assertIn('permissão',explanation)
        self.assertIn('access denied',explanation)

    def test_bad_args_and_empty_log_are_not_identical(self):
        self.assertIn('argumentos',presentmon_capture_explanation(2,'Unknown option: --timed'))
        self.assertIn('CSV',presentmon_capture_explanation(0,'',False))
        self.assertIn('código 3',presentmon_capture_explanation(3,'Something failed'))

    def test_bounded_error_excerpt(self):
        output=presentmon_capture_explanation(3,'oops'*900)
        self.assertLess(len(output),900)

if __name__=='__main__':unittest.main()
