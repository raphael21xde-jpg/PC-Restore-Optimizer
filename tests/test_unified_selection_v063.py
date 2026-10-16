"""v0.6.3 guarantees: one choice, strictly separated volume evidence."""
import itertools
import unittest
from unified_selection import index_cards, card_detail, decision_label
from catalog_plan import selected_catalog_choices
from volume_paths import volume_of


def report(volumes=('C:', 'D:')):
    return dict(schema='pcro-discovery-v1', records=[
        dict(app_id='game42', app='Test Game', path=f'{d}/Games/Test Game', kind='Pasta da instalação',
             confidence='candidato', evidence='Teste', edition=None) for d in volumes],
        apps=[dict(id='game42', name='Test Game',category='Jogo')])


class UnifiedCards(unittest.TestCase):
    def test_combinations_do_not_merge_paths(self):
        letters=('C:', 'D:', 'F:', 'G:')
        for size in range(1,5):
            for combo in itertools.combinations(letters,size):
                with self.subTest(combo=combo):
                    cards=index_cards(report(combo),{}, {}, {})
                    self.assertEqual(set(cards),set(combo))
                    for drive in combo:
                        self.assertEqual(len(cards[drive]),1)
                        self.assertEqual({volume_of(p) for p in cards[drive][0]['record_paths']},{drive})

    def test_one_identity_one_decision_across_volumes(self):
        cards=index_cards(report(), {'deep:game42':{'kind':'game','name':'Test Game',
                           'paths':[], 'possible_paths':[]}},
                          {'deep:game42':'keep'}, {})
        self.assertEqual([cards[d][0]['choice'] for d in ('C:','D:')],['keep','keep'])
        self.assertEqual(cards['D:'][0]['related_scanned_paths'],['C:/Games/Test Game'])
        self.assertEqual(card_detail(cards['D:'][0],{})['backup_c'], [])
        self.assertEqual(card_detail(cards['D:'][0],{})['candidates'],
                         ['C:/Games/Test Game', 'D:/Games/Test Game'])

    def test_selected_d_game_known_c_save_requires_backup(self):
        items={'steam:42':dict(name='Test Game',kind='game',install_location='D:/SteamLibrary/Test',
                               paths=['C:/Users/A/AppData/Test/save','D:/SteamLibrary/Test/config'],
                               possible_paths=['F:/unknown'])}
        cards=index_cards(report(()),items,{'steam:42':'keep'}, {})
        self.assertEqual(set(cards), {'C:', 'D:', 'F:'})
        self.assertTrue(cards['D:'][0]['install_here'])
        d=card_detail(cards['D:'][0],items)
        self.assertEqual(d['backup_c'], ['C:/Users/A/AppData/Test/save'])
        self.assertNotIn('F:/unknown',d['confirmed'])
        self.assertIn('F:/unknown',d['candidates'] if d['drive']=='F:' else
                      card_detail(cards['F:'][0],items)['candidates'])

    def test_missing_install_is_not_assigned_to_c(self):
        cards=index_cards(report(()), {'app:unknown':{'kind':'app','name':'App X','paths':[]}},
                          {'app:unknown':'keep'}, {})
        self.assertEqual(cards,{})
        selections=selected_catalog_choices({'app:unknown':'keep'}, {'app:unknown':{'kind':'app','name':'App X'}})
        self.assertEqual(selections[0]['install_volume'],'SEM UNIDADE')

    def test_unknown_path_does_not_become_confirmed_save(self):
        cards=index_cards(report(('D:',)),{}, {'deep:game42':'keep'}, {})
        d=card_detail(cards['D:'][0],{})
        self.assertEqual(d['confirmed'],[])
        self.assertTrue(d['requires_review'])


if __name__=='__main__': unittest.main()
