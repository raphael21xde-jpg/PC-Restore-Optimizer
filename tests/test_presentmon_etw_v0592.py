import unittest
from optimization_ui import build_presentmon_args, presentmon_capture_explanation


class EtwCaptureIsolationTests(unittest.TestCase):
    def test_unique_session_used_and_other_sessions_not_modified(self):
        cmd = build_presentmon_args('PresentMon-2.6.0-x64.exe', 'cs2.exe', 'out.csv', 90, 'PCRO_abcdef123456')
        self.assertEqual(cmd[cmd.index('--session_name') + 1], 'PCRO_abcdef123456')
        self.assertEqual(cmd[cmd.index('--process_name') + 1], 'cs2.exe')
        self.assertEqual(cmd[cmd.index('--timed') + 1], '90')
        self.assertNotIn('--stop_existing_session', cmd)
        self.assertNotIn('--restart_as_admin', cmd)

    def test_session_name_validated(self):
        for name in ('PresentMon', 'bad name', 'PCRO_x', 'PCRO_ABCDEF123456'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_presentmon_args('pm.exe', 'cs2.exe', 'out.csv', 90, name)

    def test_exit_code_six_has_actionable_message_without_console(self):
        msg = presentmon_capture_explanation(6, '')
        self.assertIn('Código 6', msg)
        self.assertIn('ETW', msg)
        self.assertIn('permissão', msg)
        self.assertNotIn('Consulte a mensagem original abaixo', msg)

if __name__ == '__main__':
    unittest.main()
