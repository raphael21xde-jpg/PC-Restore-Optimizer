import unittest
from discovery_groups import group_records, record_indices, selected_records


def row(app,id,path,edition=None):
    return dict(app=app,app_id=id,path=path,edition=edition,kind='Dados',evidence='Teste',confidence='candidato')

class GroupTests(unittest.TestCase):
    def test_thirty_paths_one_item(self):
        r={'records':[row('osu!','osu',f'C:/osu/Songs/{n}','stable') for n in range(30)]}
        g=group_records(r);self.assertEqual(len(g),1);self.assertEqual(len(g[0]['paths']),30)
    def test_stable_lazer_separate_even_shared_display_name(self):
        r={'records':[row('osu!','a','C:/osu','stable'),row('osu!','a','C:/lazer','lazer')]}
        self.assertEqual({g['name'] for g in group_records(r)},{'osu! clássico (stable)','osu! lazer'})
    def test_edition_follows_parent_path(self):
        r={'records':[row('osu!','a','C:/osu','stable'),row('osu!','other','C:/osu/Songs')]}
        self.assertEqual(len(group_records(r)),1)
    def test_unknown_edition_is_not_guessed(self):
        g=group_records({'records':[row('osu!','a','C:/random')]})
        self.assertEqual(g[0]['edition'],'unknown')
    def test_opera_gx_and_regular_are_different(self):
        r={'records':[row('Opera GX Stable','a','C:/gx'),row('Opera GX','b','C:/gxprofile'),row('Opera Stable','c','C:/opera')]}
        g=group_records(r);self.assertEqual(len(g),2)
        self.assertEqual(len(next(x for x in g if x['name']=='Opera GX')['paths']),2)
    def test_duplicate_paths_one_visible_entry_all_evidence_retained(self):
        r={'records':[row('Editor','a','C:/App'),row('Editor','b','c:/app')]}
        g=group_records(r);self.assertEqual(len(g[0]['paths']),1);self.assertEqual(g[0]['paths'][0]['indices'],[0,1])
    def test_distinct_known_publishers_not_merged(self):
        r={'apps':[{'id':'a','publisher':'One'},{'id':'b','publisher':'Two'}], 'records':[row('Editor','a','C:/a'),row('Editor','b','C:/b')]}
        self.assertEqual(len(group_records(r)),2)
    def test_group_selection_deduplicates_child_selection(self):
        self.assertEqual(record_indices(['g','p'],{'g':[0,1,2],'p':[1]}),[0,1,2])
    def test_selected_editions_have_distinct_persistent_identity(self):
        r={'records':[row('osu!','a','C:/stable','stable'),row('osu!','a','C:/lazer','lazer')]}
        a,b=selected_records(r,[0,1]);self.assertNotEqual(a['app_id'],b['app_id'])
        self.assertEqual(a['edition'],'stable');self.assertEqual(b['edition'],'lazer')
    def test_input_report_is_not_changed(self):
        import copy
        r={'records':[row('osu!','a','C:/stable','stable')]};before=copy.deepcopy(r)
        group_records(r);selected_records(r,[0]);self.assertEqual(r,before)

    def test_nested_lazer_is_excluded_when_preserving_classic(self):
        from discovery_groups import other_osu_editions_under_selection
        r={'records':[row('osu!','a','C:/osu','stable'),row('osu!','b','C:/osu/lazer','lazer')]}
        selected=selected_records(r,[0])
        self.assertEqual(other_osu_editions_under_selection(r,selected),['C:/osu/lazer'])
