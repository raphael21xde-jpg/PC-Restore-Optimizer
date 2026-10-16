"""Real Tk smoke/integration checks for v0.6.7 read-only audit."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import App, APP_VERSION
from completeness_audit_ui_v067 import show_completeness_audit


class CompletenessUI067Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App()
        self.app.withdraw()
        self.app.local_state = Path(self.temp.name)/'prefs.json'

    def tearDown(self):
        for popup in self.app.winfo_children():
            if popup.winfo_class() == 'Toplevel':
                popup.destroy()
        self.app.destroy()
        self.temp.cleanup()

    def _children(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self._children(child)

    def test_button_present_in_preservation_and_installation(self):
        self.assertIn(APP_VERSION, ('0.6.7', '0.6.8', '0.6.8.1', '0.6.9'))
        p = [c.cget('text') for c in self._children(self.app.preservation) if c.winfo_class() == 'TButton']
        i = [c.cget('text') for c in self._children(self.app.installation) if c.winfo_class() == 'TButton']
        self.assertTrue(any('Auditar dados do C:' in x for x in p), p)
        self.assertTrue(any('Auditoria C: / EFI' in x for x in i), i)

    def test_dialog_builds_report_asynchronously_without_authorizing_format(self):
        with mock.patch('completeness_audit_ui_v067.build_completeness_report') as build:
            build.return_value = {
                'counts': {'locations_reviewed':1, 'locations_needing_review':1,
                           'c_scan_errors':1, 'c_scan_skipped':0},
                'recovery_map':[],
                'candidate_locations':[{'name':'Documentos','path':r'C:\Users\test\Documents',
                                        'category':'PESSOAL','status':'REVISAR — NÃO SELECIONADO',
                                        'detail':'Conteúdo não auditado'}],
                'scan_c':{'errors':[{'path':r'C:\Users\test\bad', 'reason':'Negado'}], 'skipped':[]},
                'boot':{'status':'DEPENDÊNCIA POSSÍVEL','note':'EFI no outro disco'},
                'disk_evidence':{'available':True, 'data':{'disks':[], 'efi_partitions':[], 'errors':[]}},
                'manual_tasks':['Revisar dados pessoais'],
                'ready_for_format':False
            }
            dialog = show_completeness_audit(self.app, {'requires_verified_backup':[]})
            self.app.after(450, self.app.quit)
            self.app.mainloop()
            treeviews = [c for c in self._children(dialog) if c.winfo_class() == 'Treeview']
            self.assertEqual(len(treeviews),4)
            self.assertEqual(len(treeviews[0].get_children()),1)
            self.assertIn('Documentos', treeviews[0].item(treeviews[0].get_children()[0])['text'])
            self.assertTrue(build.called)
            dialog.destroy()


if __name__ == '__main__':
    unittest.main()
