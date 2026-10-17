"""Reproduces stuck preview after first asynchronous audit response (v0.6.8 regression)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import App
from completeness_audit_ui_v068 import show_completeness_audit


class AuditUIHotfix0681Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App()
        self.app.withdraw()
        self.app.local_state = Path(self.tmp.name) / 'preferences.json'

    def tearDown(self):
        for child in self.app.winfo_children():
            if child.winfo_class() == 'Toplevel':
                child.destroy()
        self.app.destroy()
        self.tmp.cleanup()

    @staticmethod
    def descendants(widget):
        for c in widget.winfo_children():
            yield c
            yield from AuditUIHotfix0681Tests.descendants(c)

    def test_second_async_result_updates_preview_table(self):
        report = {
            'counts': {'locations_reviewed': 1, 'locations_needing_review': 1,
                       'selected_c_paths': 0, 'c_scan_errors': 0, 'c_scan_skipped': 0},
            'scan_c': {'status': 'SEM INVENTÁRIO', 'errors': [], 'skipped': []},
            'candidate_locations': [
                {'name': 'Test dir', 'path': r'C:\Users\demo\Docs', 'category': 'PESSOAL',
                 'status': 'REVISAR', 'detail': 'Revisar'}],
            'disk_evidence': {'available': False, 'data': {}},
            'boot': {'status': 'REVISAR', 'note': 'Não testado'},
            'recovery_map': [], 'manual_tasks': ['Revisar'], 'selected_c_paths': [],
        }
        preview = {'rows': [{'name': 'arquivo-teste.txt', 'path': r'C:\Users\demo\Docs\arquivo-teste.txt',
                             'type': 'ARQUIVO', 'bytes': 8}], 'has_more': False, 'next_offset': None}
        with mock.patch('completeness_audit_ui_v068.build_completeness_report', return_value=report), \
             mock.patch('completeness_audit_ui_v068.collect_disk_evidence_068', return_value={'available': False, 'data': {}}), \
             mock.patch('completeness_audit_ui_v068.inspect_children_once', return_value=preview):
            w = show_completeness_audit(self.app, {})
            widgets = list(self.descendants(w))
            trees = [x for x in widgets if x.winfo_class() == 'Treeview']
            buttons = [x for x in widgets if x.winfo_class() == 'TButton']
            inspector = next(x for x in buttons if 'Examinar selecionado' in x.cget('text'))
            def wait_for_preview():
                if any('arquivo-teste.txt' in str(t.item(iid)['text']) for t in trees
                       for iid in t.get_children()):
                    self.app.quit()
                else:
                    self.app.after(40, wait_for_preview)
            def click_after_first_audit():
                loc = next((t for t in trees if t.exists('loc-0')), None)
                if loc is None:
                    self.app.after(40, click_after_first_audit)
                    return
                loc.selection_set('loc-0')
                inspector.invoke()
                self.app.after(40, wait_for_preview)
            self.app.after(40, click_after_first_audit)
            self.app.after(10000, self.app.quit)
            self.app.mainloop()
            self.assertTrue(any('arquivo-teste.txt' in str(t.item(iid)['text']) for t in trees
                                for iid in t.get_children()),
                            'Preview must be rendered after the audit, not remain at consulting')
            w.destroy()

if __name__ == '__main__':
    unittest.main()

