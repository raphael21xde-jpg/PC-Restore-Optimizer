import unittest
from scoped_saves import scoped_user_roots, incorporate_saves
from volume_paths import volume_of

class StrictSaveScope(unittest.TestCase):
    def test_user_roots_never_enumerate_unselected_disks(self):
        roots={'documents':['C:/Users/U/Documents','D:/Docs'],
               'appdata':['C:/Users/U/AppData/Roaming','F:/OldApps']}
        self.assertEqual(scoped_user_roots(roots,['C:/']),{
            'documents':['C:/Users/U/Documents'],
            'appdata':['C:/Users/U/AppData/Roaming']})
        self.assertEqual(scoped_user_roots(roots,['D:/']),{
            'documents':['D:/Docs'], 'appdata':[]})

    def test_save_only_added_to_selected_volume(self):
        base={'records':[],'apps':[]}
        data=[{'path':'C:/Users/U/Saved Games/Test Game','game':'Test Game',
               'source':'known','confidence':'alta'},
              {'path':'F:/Saves/Test Game','game':'Test Game','confidence':'alta'}]
        catalog={'steam:42':{'kind':'game','name':'Test Game','install_location':'D:/Games/Test'}}
        found=incorporate_saves(base,data,catalog,['C:/'])
        self.assertEqual([r['path'] for r in found['records']],['C:/Users/U/Saved Games/Test Game'])
        self.assertEqual(found['records'][0]['app_id'],'steam:42')
        self.assertEqual(base['records'],[])

    def test_ambiguous_name_does_not_take_wrong_owner(self):
        candidates=[{'path':'C:/Save/Game','game':'Game'}]
        catalog={'a':{'kind':'game','name':'Game'}, 'b':{'kind':'game','name':'Game'}}
        found=incorporate_saves({'records':[],'apps':[]},candidates,catalog,['C:/'])
        self.assertTrue(found['records'][0]['app_id'].startswith('savelocal:'))

if __name__=='__main__':unittest.main()
