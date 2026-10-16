import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from deep_discovery import scan, signature
from app_recovery import require_equivalent_edition
from recovery_kit import create_plan, load_plan

class DeepDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.apps=[{'id':'a','name':'My Program 2.3','publisher':'Vendor','install_location':''}]
    def run_scan(self,apps=None,**kw):return scan(self.apps if apps is None else apps,[self.root],**kw)
    def test_nested_folder_beyond_old_depth(self):
        p=self.root/'a'/'b'/'c'/'My Program';p.mkdir(parents=True);(p/'prefs.ini').write_text('x')
        r=self.run_scan();self.assertTrue(any(x['path']==str(p) and x['app_id']=='a' for x in r['records']))
    def test_publisher_alone_does_not_match(self):
        p=self.root/'Vendor';p.mkdir();(p/'unknown').touch()
        self.assertEqual(self.run_scan()['records'],[])
    def test_registry_anchor_does_not_need_name_match(self):
        p=self.root/'random';p.mkdir();self.apps[0]['install_location']=str(p)
        self.assertTrue(any(x['confidence']=='caminho identificado' for x in self.run_scan()['records']))
    def test_symlink_is_reported_not_followed(self):
        outside=self.root/'other';outside.mkdir();(self.root/'link').symlink_to(outside,target_is_directory=True)
        r=self.run_scan();self.assertTrue(any(x['path'].endswith('link') for x in r['skipped']))
    def test_excluded_backups_not_treated_as_installation(self):
        p=self.root/'backups'/'My Program';p.mkdir(parents=True)
        r=self.run_scan(excluded=[str(self.root/'backups')]);self.assertFalse(r['records']);self.assertTrue(r['skipped'])
    def test_cancel_is_partial(self):
        stop=threading.Event();stop.set();r=self.run_scan(cancel=stop)
        self.assertEqual(r['status'],'cancelada_parcial')
    def test_denied_folder_is_reported(self):
        with patch('deep_discovery.os.scandir',side_effect=PermissionError('denied')):
            r=self.run_scan()
        self.assertEqual(r['status'],'concluida_com_lacunas');self.assertIn('denied',r['errors'][0]['reason'])
    def test_classic_library_and_external_songs(self):
        p=self.root/'DifferentName';p.mkdir();(p/'osu!.exe').touch();(p/'osu!.db').touch()
        for name in ('Songs','Skins','Replays'):(p/name).mkdir()
        custom=self.root/'my-music';custom.mkdir()
        (p/'osu!.user.cfg').write_text('Password = DO_NOT_REPORT\nBeatmapDirectory = '+str(custom))
        r=self.run_scan(apps=[{'id':'osu','name':'osu!'}]);rows=r['records']
        self.assertTrue(any(x['path']==str(custom) for x in rows))
        self.assertTrue(any(x['kind']=='Músicas e beatmaps' for x in rows))
        self.assertNotIn('DO_NOT_REPORT',json.dumps(r));self.assertTrue(any(x['edition']=='stable' for x in rows))
    def test_lazer_not_assigned_to_classic(self):
        p=self.root/'LazerData';p.mkdir();(p/'client.realm').touch();(p/'files').mkdir()
        r=self.run_scan(apps=[{'id':'osu','name':'osu!'}])
        self.assertFalse(any(x['app_id']=='osu' and x['edition']=='lazer' for x in r['records']))
    def test_classic_blocked_from_lazer_package(self):
        for i in ({'name':'osu!'}, {'name':'osu!','edition':'stable'}):
            with self.assertRaises(ValueError):require_equivalent_edition(i,'ppy.osu')
        require_equivalent_edition({'name':'osu!(lazer)','edition':'lazer'},'ppy.osu')
    def test_edition_survives_recovery_plan(self):
        p=self.root/'plan.json'
        create_plan(p,{'osu':{'kind':'app','name':'osu!','edition':'stable','paths':[]}}, {'osu':'keep'},[],str(self.root))
        self.assertEqual(load_plan(p)['items'][0]['edition'],'stable')
    def test_product_metadata_produces_candidate_without_running_file(self):
        p=self.root/'client.exe';p.write_bytes(b'not executable')
        with patch('deep_discovery.executable_metadata',return_value={'ProductName':'Portable Editor','CompanyName':'Studio'}):
            r=self.run_scan()
        self.assertTrue(any(x['app']=='Portable Editor' and x['confidence']=='candidato' for x in r['records']))
    def test_unknown_executable_is_not_claimed_detected(self):
        (self.root/'unknown.exe').touch();r=self.run_scan()
        self.assertIn(str(self.root/'unknown.exe'),r['unassociated_executables'])
    def test_common_runtime_uninstaller_does_not_associate_system32(self):
        p=self.root/'System32';p.mkdir();(p/'msiexec.exe').touch()
        self.apps[0]['uninstall_command']='"'+str(p/'msiexec.exe')+'" /x identifier'
        self.assertFalse(any(x['kind']=='Pasta apontada pelo registro' for x in self.run_scan()['records']))
