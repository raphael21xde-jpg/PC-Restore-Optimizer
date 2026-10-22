"""Exercise timer ownership against a real Tcl/Tk event loop."""
import tkinter as tk
import unittest

from ui_timers import WindowTimers
from tk_helpers import track_tk_root


class WindowTimerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        track_tk_root(self, self.root)
        self.errors = []
        self.root.tk.createcommand('bgerror', self.errors.append)

    def test_destroy_cancels_only_owned_callbacks(self):
        window = tk.Toplevel(self.root)
        timers = WindowTimers(window)
        calls = []
        token = timers.after(0, calls.append, 'closed')
        other = self.root.after(0, calls.append, 'other')
        window.destroy()
        pending = self.root.tk.call('after', 'info')
        self.assertNotIn(token, pending)
        self.assertIn(other, pending)
        self.root.update()
        self.assertEqual(calls, ['other'])
        self.assertEqual(self.errors, [])
        self.assertIsNone(timers.after(0, calls.append, 'late'))

    def test_destroy_child_keeps_owner_timer_and_poll_rearms(self):
        window = tk.Toplevel(self.root)
        child = tk.Label(window)
        timers = WindowTimers(window)
        calls = []

        def poll():
            calls.append('tick')
            if len(calls) == 1:
                timers.after(0, poll)

        timers.after(0, poll)
        child.destroy()
        self.root.update()
        self.assertEqual(calls, ['tick', 'tick'])
        self.assertEqual(timers.pending, set())
        self.assertEqual(self.errors, [])

    def test_destroy_parent_cancels_descendant_timers(self):
        parent = tk.Toplevel(self.root)
        child = tk.Toplevel(parent)
        timers = WindowTimers(child)
        token = timers.after(0, self.fail, 'Callback outlived parent')
        parent.destroy()
        self.assertNotIn(token, self.root.tk.call('after', 'info'))
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_close_is_idempotent_and_does_not_close_widget(self):
        timers = WindowTimers(self.root)
        token = timers.after(0, self.fail, 'Cancelled callback executed')
        timers.close()
        timers.close()
        self.assertTrue(self.root.winfo_exists())
        self.assertNotIn(token, self.root.tk.call('after', 'info'))
        self.root.update()
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
