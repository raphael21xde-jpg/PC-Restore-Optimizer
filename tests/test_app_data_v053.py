"""Verificações simuladas, jamais acessam arquivos de usuário nem alteram discos."""
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_data import find_app_data, associate_app_data, matching_app_folder
from game_saves import find_game_saves, associate_saves
from backup_core import build_plan


class AppDataV053Tests(unittest.TestCase):
    def create(self, path, content=b'contents'):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)

    def roots(self, home):
        return dict(appdata=[home/'Roaming'],localappdata=[home/'Local'],
                    locallow=[home/'LocalLow'],programdata=[home/'ProgramData'],documents=[home/'Documents'])

    def test_wallpaper_engine_personal_config_and_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            steam=home/'F'/'SteamLibrary'
            (steam/'steamapps').mkdir(parents=True)
            config=steam/'steamapps/common/wallpaper_engine/config.json'
            project=steam/'steamapps/common/wallpaper_engine/projects/myprojects/PersonalWall/project.json'
            self.create(config,b'{"quality":1}')
            self.create(project)
            game={'game':'Wallpaper Engine','launcher':'Steam','appid':'431960','library':str(steam)}
            records=find_game_saves([game],roots=self.roots(home),steam_roots=[])
            trusted,possible=associate_saves(game,records)
            self.assertIn(str(config),trusted)
            self.assertIn(str(project.parent.parent),trusted)
            self.assertNotIn(str(steam/'steamapps/workshop/content/431960'),trusted)
            self.assertFalse(possible)
            plan=build_plan({str(config):'keep',str(project.parent.parent):'keep'},[str(home)])
            self.assertEqual(plan.count,2)

    def test_wallpaper_engine_cloud_copy_is_only_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);steam=home/'Steam';steam.mkdir()
            target=steam/'userdata/777/431960/remote/config.json'
            self.create(target)
            game={'game':'Wallpaper Engine','launcher':'Steam','appid':'431960','library':str(steam)}
            records=find_game_saves([game],roots=self.roots(home),steam_roots=[steam])
            _,possible=associate_saves(game,records)
            self.assertIn(str(target.parent),possible)

    def test_logitech_g_hub_hints_possible_not_automatic(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);file=home/'Local/LGHUB/settings.db'
            self.create(file)
            app={'name':'Logitech G HUB','publisher':'Logitech','id':'reg:lghub'}
            found=find_app_data([app],roots=self.roots(home))
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['confidence'],'possivel')
            self.assertEqual(associate_app_data(app,found),[str(file.parent)])
            self.assertEqual(associate_app_data({'name':'Logitech Something','id':'other'},found),[])

    def test_personal_app_folder_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'Roaming/Sample Utility'
            self.create(folder/'config.json')
            a={'name':'Sample Utility','id':'sample'}
            found=find_app_data([a],roots=self.roots(home))
            self.assertIn(str(folder),associate_app_data(a,found))
            self.assertFalse(matching_app_folder('Sample Utility','Sample Utility Other'))

    def test_unrelated_and_sensitive_folders_are_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            self.create(home/'Roaming/Discord/Cookies')
            self.create(home/'Local/Packages/a/settings.db')
            a={'name':'Discord','id':'discord'}
            self.assertFalse(associate_app_data(a,find_app_data([a],roots=self.roots(home))))

    def test_uwp_config_folder_candidate_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            folder=home/'Local/Packages/NGenuity_aabbcc/LocalState'
            self.create(folder/'profiles.cfg')
            app={'name':'HyperX NGENUITY','id':'x'}
            records=find_app_data([app],roots=self.roots(home))
            self.assertIn(str(folder), associate_app_data(app,records))
            self.assertTrue(all(r['confidence']=='possivel' for r in records))

    def test_no_diskwide_scan_for_missing_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            self.create(home/'Roaming/OtherThing/test.ini')
            out=find_app_data([{'name':'Not Installed Utility','id':'1'}],roots=self.roots(home))
            self.assertEqual(out,[])

if __name__=='__main__': unittest.main()
