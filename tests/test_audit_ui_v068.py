"""Headless-safe Tk integration checks when executed under Xvfb."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from app import App
from completeness_audit_ui_v068 import show_completeness_audit


class AuditUI068Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=App()
        self.app.withdraw()
        self.app.local_state=Path(self.tmp.name)/'prefs.json'

    def tearDown(self):
        for child in self.app.winfo_children():
            if child.winfo_class()=='Toplevel': child.destroy()
        self.app.destroy()
        self.tmp.cleanup()

    def descend(self,widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descend(child)

    def test_new_dialog_has_review_import_proof_and_never_formats(self):
        report={
          'counts':{'locations_reviewed':1,'locations_needing_review':1,'selected_c_paths':0,
                    'c_scan_errors':0,'c_scan_skipped':0},
          'scan_c':{'status':'SEM INVENTÁRIO','errors':[],'skipped':[]},
          'candidate_locations':[{'name':'Documentos','path':r'C:\Users\demo\Documents',
                                  'category':'PESSOAL','status':'REVISAR — NÃO SELECIONADO',
                                  'detail':'Não auditado'}],
          'disk_evidence':{'available':True,'data':{'disks':[], 'physical_disks':[{'index':1,'model':'Kingston'}],
               'legacy_volumes':[{'letter':'F:', 'filesystem':'NTFS', 'system_volume':False}],
               'efi_partitions':[],'errors':[],'warnings':[]}},
          'boot':{'status':'MAPEAMENTO INCOMPLETO','note':'A EFI pode existir sem mapeamento.'},
          'recovery_map':[],'manual_tasks':['Revisar local'], 'selected_c_paths':[]}
        with mock.patch('completeness_audit_ui_v068.build_completeness_report',return_value=report), \
             mock.patch('completeness_audit_ui_v068.collect_disk_evidence_068',return_value={'available':False,'data':{}}):
            w=show_completeness_audit(self.app, {})
            self.app.after(600,self.app.quit)
            self.app.mainloop()
            widgets=list(self.descend(w))
            buttons=[x.cget('text') for x in widgets if x.winfo_class()=='TButton']
            self.assertTrue(any('Examinar selecionado' in x for x in buttons))
            self.assertTrue(any('Importar inventário' in x for x in buttons))
            self.assertTrue(any('manifest.json' in x for x in buttons))
            self.assertTrue(any('Não preservar' in x for x in buttons))
            tabs=[x for x in widgets if x.winfo_class()=='TNotebook']
            self.assertEqual(len(tabs),1)
            self.assertEqual(len(tabs[0].tabs()),6)
            trees=[x for x in widgets if x.winfo_class()=='Treeview']
            self.assertEqual(len(trees),5)
            self.assertTrue(any('Kingston' in str(t.item(iid)['text']) for t in trees
                                for iid in t.get_children()))
            w.destroy()

if __name__=='__main__': unittest.main()
