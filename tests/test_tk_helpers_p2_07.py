"""P2-07: the shared Tk clean-up helper, checked with a fake root (no Tk needed)."""
import gc
import os
import sys
import threading
import unittest
import weakref
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tk_helpers  # noqa: E402


class FakeTk:
    """Mimics the parts of ``root.tk`` the helper uses."""
    def __init__(self, pending):
        self.pending = list(pending)
        self.calls = []

    def call(self, *args):
        self.calls.append(args)
        if args == ('after', 'info'):
            return tuple(self.pending)
        if args[:2] == ('after', 'cancel'):
            self.pending.remove(args[2])
            return ''
        raise AssertionError(args)

    @staticmethod
    def splitlist(value):
        return tuple(value)


class FakeRoot:
    def __init__(self, pending=('after#1', 'after#2', 'after#3')):
        self.tk = FakeTk(pending)
        self.events = []
        self.destroyed = False

    def after_cancel(self, after_id):
        self.events.append(('cancel', after_id))
        self.tk.call('after', 'cancel', after_id)

    def destroy(self):
        if self.destroyed:
            raise RuntimeError('application has been destroyed')
        self.events.append(('destroy',))
        self.destroyed = True


class TkHelpersTests(unittest.TestCase):
    def test_cancels_every_pending_after_before_destroy(self):
        root = FakeRoot()
        self.assertEqual(tk_helpers.close_tk_root(root), 3)
        self.assertEqual(root.tk.pending, [])
        cancels = [c for c in root.tk.calls if c[:2] == ('after', 'cancel')]
        self.assertEqual(cancels, [('after', 'cancel', 'after#1'), ('after', 'cancel', 'after#2'),
                                   ('after', 'cancel', 'after#3')])
        self.assertEqual(root.events, [('destroy',)])

    def test_never_uses_after_cancel_so_tk_commands_are_not_deleted(self):
        # after_cancel() also runs deletecommand, which may raise
        # (AttributeError/TclError) on a destroyed root or delete Tk's own commands.
        root = FakeRoot()
        root.after_cancel = mock.Mock(side_effect=AttributeError('no _tclCommands'))
        root.deletecommand = mock.Mock()
        self.assertEqual(tk_helpers.close_tk_root(root), 3)
        root.after_cancel.assert_not_called()
        root.deletecommand.assert_not_called()
        self.assertEqual(root.tk.pending, [])
        self.assertTrue(root.destroyed)

    def test_second_close_is_harmless(self):
        root = FakeRoot()
        tk_helpers.close_tk_root(root)
        self.assertEqual(tk_helpers.close_tk_root(root), 0)
        self.assertEqual(tk_helpers.close_tk_root(None), 0)

    def test_one_failing_cancel_does_not_stop_the_others(self):
        root = FakeRoot(('after#1', 'after#2'))
        real_call = root.tk.call

        def call(*args):
            if args == ('after', 'cancel', 'after#1'):
                raise AttributeError('broken')
            return real_call(*args)
        root.tk.call = call
        self.assertEqual(tk_helpers.cancel_pending_afters(root), 1)
        self.assertEqual(root.tk.pending, ['after#1'])

    def test_unreadable_after_list_still_destroys(self):
        root = FakeRoot()
        root.tk.call = mock.Mock(side_effect=RuntimeError('main thread is not in main loop'))
        self.assertEqual(tk_helpers.close_tk_root(root), 0)
        self.assertTrue(root.destroyed)

    def test_tracked_root_is_closed_released_and_collected_on_this_thread(self):
        root = FakeRoot()
        ref = weakref.ref(root)
        holder = unittest.TestCase()
        holder.root = root
        holder.other = 'kept'
        tk_helpers.track_tk_root(holder, root)
        del root
        collected = []
        real_collect = gc.collect

        def spy():
            collected.append(threading.current_thread())
            return real_collect()
        with mock.patch('tk_helpers.gc.collect', side_effect=spy):
            holder.doCleanups()
        self.assertEqual(collected, [threading.current_thread()])
        self.assertIsNone(holder.root)
        self.assertEqual(holder.other, 'kept')
        self.assertIsNone(ref(), 'the fake root must be freed by the clean-up')

    def test_waits_for_worker_started_during_the_test(self):
        holder = unittest.TestCase()
        tk_helpers.track_tk_root(holder, FakeRoot())
        release = threading.Event()
        finished = threading.Event()

        def worker():
            release.wait(5)
            finished.set()
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        threading.Timer(0.05, release.set).start()
        holder.doCleanups()
        self.assertTrue(finished.is_set())

    def test_stuck_worker_does_not_block_longer_than_budget(self):
        holder = unittest.TestCase()
        tk_helpers.track_tk_root(holder, FakeRoot(), join_seconds=0.05)
        stop = threading.Event()
        thread = threading.Thread(target=stop.wait, args=(5,), daemon=True)
        thread.start()
        self.addCleanup(stop.set)
        holder.doCleanups()
        self.assertTrue(thread.is_alive())

    def test_thread_that_cannot_be_joined_is_skipped(self):
        holder = unittest.TestCase()
        tk_helpers.track_tk_root(holder, FakeRoot())
        odd = mock.Mock(spec=threading.Thread)
        odd.join.side_effect = RuntimeError('cannot join a dummy thread')
        with mock.patch('tk_helpers.threading.enumerate',
                        return_value=[threading.current_thread(), odd]):
            holder.doCleanups()
        odd.join.assert_called_once()

    def test_tracking_does_not_need_tkinter(self):
        with mock.patch.object(tk_helpers, '_tk', None):
            holder = unittest.TestCase()
            root = FakeRoot()
            holder.root = root
            tk_helpers.track_tk_root(holder, root)
            holder.doCleanups()
            self.assertTrue(root.destroyed)
            self.assertIsNone(holder.root)


if __name__ == '__main__':
    unittest.main()
