import tempfile
import unittest
from pathlib import Path
from backup_identity import make_descriptors, owners_for, inventory_text, title_for
from backup_core import build_plan, copy_backup
from backup_features import verified_entries, restore_selected, friendly_backup_name

class IdentityTests(unittest.TestCase):
    def test_unselected_program_is_not_in_title(self):
        c={'a':{'name':'Selected','kind':'app','paths':['C:/a']}, 'b':{'name':'Other','kind':'app','paths':['C:/b']}}
        r=make_descriptors(c,['C:/a'])
        self.assertIn('Selected',title_for(r)); self.assertNotIn('Other',title_for(r))
    def test_save_and_config_differ(self):
        c={'g':{'name':'Game','kind':'game','paths':['C:/save','C:/config'],'path_kinds':{'C:/save':'save','C:/config':'config'}}}
        r=make_descriptors(c,['C:/save','C:/config'])
        self.assertEqual(owners_for('C:/save/x',r)[0]['category'],'Save do jogo')
        self.assertEqual(owners_for('C:/config/x',r)[0]['category'],'Configurações do jogo')
    def test_boundary_and_shared_owner(self):
        r=[{'name':n,'category':'Dados do jogo','root':'C:/game'} for n in ('A','B')]
        self.assertEqual(len(owners_for('C:/game/save',r)),2)
        self.assertEqual(owners_for('C:/game2/save',r)[0]['category'],'Arquivo sem associação')
    def test_specific_owner_beats_personal_parent(self):
        c={'a':{'name':'App','kind':'app','paths':['C:/Docs/App']}}
        r=make_descriptors(c,['C:/Docs'])
        self.assertEqual(owners_for('C:/Docs/App/x',r)[0]['name'],'App')
        self.assertEqual(owners_for('C:/Docs/other',r)[0]['name'],'Docs')
    def test_legacy_is_readable_without_invented_owner(self):
        d={'files':[{'source':'C:/file','relative':'files/a','bytes':1}]}
        self.assertIn('associação não registrada',inventory_text(d))
        self.assertEqual(friendly_backup_name('/backup/manifest.json',d),'backup')
    def test_real_backup_identity_survives_restore(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); src=root/'MyGame'; src.mkdir(); (src/'save.dat').write_text('progress')
            cat={'g':{'name':'Meu Jogo','kind':'game','paths':[str(src)],'path_kinds':{str(src):'save'}}}
            r=make_descriptors(cat,[str(src)])
            folder,m=copy_backup(build_plan({str(src):'keep'},[str(root)]),root/'backup',item_descriptors=r)
            self.assertEqual(m['status'],'concluido')
            self.assertIn('Meu-Jogo',folder.name)
            self.assertEqual(m['files'][0]['owners'][0]['name'],'Meu Jogo')
            self.assertIn('Save do jogo: Meu Jogo',(folder/'CONTEUDO-DO-BACKUP.txt').read_text())
            entries=verified_entries(folder/'manifest.json')
            _,count=restore_selected(folder/'manifest.json',list(entries),root)
            self.assertEqual(count,1)
