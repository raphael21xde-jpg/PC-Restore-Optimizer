"""P2-07 slice 2: the audit window owns its Tk timers (WindowTimers).

Two layers:
- source checks with ``ast`` (no tkinter needed, run on Linux);
- a Tk check (skipped without tkinter/display) that opens the window with
  the disk reader and the report builder mocked, arms ``warn_slow``, closes
  the window and proves no timer of the window is left or fires later.
Only synthetic data inside ``TemporaryDirectory``; real disks are never read.
"""
import ast
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / 'completeness_audit_ui_v068.py'


def _calls(tree, owner, attr):
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr and isinstance(node.func.value, ast.Name)
                and node.func.value.id == owner):
            found.append(node)
    return found


class AuditTimersSourceTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding='utf-8')
        self.tree = ast.parse(self.text)

    def test_no_window_after_left(self):
        self.assertNotIn('window.after(', self.text)
        self.assertEqual(_calls(self.tree, 'window', 'after'), [])

    def test_imports_window_timers(self):
        imports = [n for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)
                   and n.module == 'ui_timers']
        self.assertTrue(any(a.name == 'WindowTimers' for n in imports for a in n.names))

    def test_timers_created_from_window_before_first_use(self):
        assigns = [n for n in ast.walk(self.tree) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'timers' for t in n.targets)]
        self.assertEqual(len(assigns), 1)
        value = assigns[0].value
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(getattr(value.func, 'id', None), 'WindowTimers')
        self.assertEqual([getattr(a, 'id', None) for a in value.args], ['window'])
        uses = _calls(self.tree, 'timers', 'after')
        self.assertTrue(uses)
        self.assertLess(assigns[0].lineno, min(c.lineno for c in uses))

    def test_exactly_five_timers_for_poll_and_warn_slow(self):
        uses = _calls(self.tree, 'timers', 'after')
        self.assertEqual(len(uses), 5)
        names = [c.args[1].id for c in uses]
        self.assertEqual(names.count('poll'), 4)
        self.assertEqual(names.count('warn_slow'), 1)


def _tk_available():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:  # noqa: BLE001 - no tkinter or no display
        return False


class AuditTimersTkTests(unittest.TestCase):
    def setUp(self):
        if not _tk_available():
            self.skipTest('tkinter/display indisponível')
        from app import App
        from tk_helpers import close_tk_root, track_tk_root
        import completeness_audit_ui_v068 as audit
        self.audit = audit
        self.close_tk_root = close_tk_root
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App()
        track_tk_root(self, self.app)
        self.app.withdraw()
        self.app.local_state = Path(self.tmp.name) / 'prefs.json'

    def _report(self, folder):
        return {
            'counts': {'locations_reviewed': 1, 'locations_needing_review': 1,
                       'selected_c_paths': 0, 'c_scan_errors': 0, 'c_scan_skipped': 0},
            'scan_c': {'status': 'SEM INVENTÁRIO', 'errors': [], 'skipped': []},
            'candidate_locations': [{'name': 'Sintética', 'path': str(folder),
                                     'category': 'PESSOAL', 'status': 'REVISAR',
                                     'detail': 'teste'}],
            'disk_evidence': {'available': False, 'data': {}},
            'boot': {'status': 'MAPEAMENTO INCOMPLETO', 'note': 'teste'},
            'recovery_map': [], 'manual_tasks': [], 'selected_c_paths': []}

    def descend(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descend(child)

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.02)

    def test_closing_window_cancels_poll_and_warn_slow(self):
        folder = Path(self.tmp.name) / 'pasta'
        folder.mkdir()
        created = []
        fired_after_close = []
        closed = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        real_timers = self.audit.WindowTimers

        class SpyTimers(real_timers):
            def __init__(self, owner):
                super().__init__(owner)
                self.tokens = []
                created.append(self)

            def after(self, delay_ms, callback, *args):
                def wrapped(*a):
                    if closed.is_set():
                        fired_after_close.append(callback.__name__)
                    return callback(*a)
                wrapped.__name__ = callback.__name__
                token = super().after(delay_ms, wrapped, *args)
                if token is not None:
                    self.tokens.append((token, callback.__name__))
                return token

        def slow_inspect(root, offset=0):
            release.wait(5)
            return {'rows': [], 'has_more': False, 'next_offset': 0}

        with mock.patch.object(self.audit, 'collect_disk_evidence_068',
                               return_value={'available': False, 'data': {}}), \
             mock.patch.object(self.audit, 'build_completeness_report',
                               return_value=self._report(folder)), \
             mock.patch.object(self.audit, 'inspect_children_once', side_effect=slow_inspect), \
             mock.patch.object(self.audit, 'WindowTimers', SpyTimers):
            window = self.audit.show_completeness_audit(self.app, {})
            self.pump(0.6)
            widgets = list(self.descend(window))
            tree = next(t for t in widgets if t.winfo_class() == 'Treeview'
                        and 'loc-0' in t.get_children())
            tree.selection_set('loc-0')
            button = next(b for b in widgets if b.winfo_class() == 'TButton'
                          and 'Examinar selecionado' in b.cget('text'))
            button.invoke()
            self.pump(0.2)
            self.assertEqual(len(created), 1)
            timers = created[0]
            names = {name for _, name in timers.tokens}
            self.assertIn('poll', names)
            self.assertIn('warn_slow', names)
            self.assertTrue(timers.pending)
            tokens = {token for token, _ in timers.tokens}

            window.destroy()
            closed.set()
            self.assertTrue(timers.closed)
            self.assertEqual(timers.pending, set())
            pending = set(self.app.tk.splitlist(self.app.tk.call('after', 'info')))
            self.assertEqual(pending & tokens, set())
            release.set()
            self.pump(0.4)
        self.assertEqual(fired_after_close, [])


if __name__ == '__main__':
    unittest.main()
