"""Testes de integração v0.5.2 apenas com pastas e arquivos fictícios."""
from pathlib import Path
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_saves import find_game_saves, associate_saves, same_game, progress_is_online
from backup_core import build_plan

class GameSaveV052Tests(unittest.TestCase):
    def make_roots(self, home):
        return dict(documents=[home/'Documents'], userprofile=[home],
                    appdata=[home/'Roaming'], localappdata=[home/'Local'],
                    locallow=[home/'LocalLow'])

    def create(self,path,content=b'data'):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)

    def test_rdr2_profile(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);target=home/'Documents/Rockstar Games/Red Dead Redemption 2/Profiles/AB123/SRDR30000'
            self.create(target)
            game=dict(game='Red Dead Redemption 2',appid='1174180',launcher='Steam')
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[])
            trusted,possible=associate_saves(game,found)
            self.assertIn(str(target.parent.parent),trusted)

    def test_ragnarok_accented_path(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);target=home/'Saved Games/God of War Ragnarök/123456789/save.dat'
            self.create(target)
            game=dict(game='God of War Ragnarok',appid='2322010',launcher='Steam')
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[])
            trusted,_=associate_saves(game,found)
            self.assertIn(str(target.parent.parent),trusted)

    def test_stray_and_repo_known_saves(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)
            stray=home/'Local/Hk_project/Saved/SaveGames/123/Slots/Slot_1/Data.sav'
            repo=home/'LocalLow/semiwork/Repo/saves/run.es3'
            self.create(stray);self.create(repo)
            games=[dict(game='Stray',appid='1332010',launcher='Steam'),
                   dict(game='R.E.P.O.',appid='3241660',launcher='Steam')]
            found=find_game_saves(games,roots=self.make_roots(home),steam_roots=[])
            for game in games:
                trusted,_=associate_saves(game,found)
                self.assertTrue(trusted,game['game'])

    def test_cs2_userdata_configuration_not_save(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t); steam=home/'Steam'
            config=steam/'userdata/1234/730/local/cfg/cs2_user_convars_0_slot0.vcfg'
            self.create(config)
            game=dict(game='Counter-Strike 2',appid='730',launcher='Steam',library=str(steam))
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[steam])
            trusted,_=associate_saves(game,found)
            self.assertIn(str(config.parent),trusted)
            item=next(i for i in found if i['path']==str(config.parent))
            self.assertEqual(item['data_kind'],'config')

    def test_custom_mrs_cfg_is_detected_and_backuppable(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);steam=home/'F'/'SteamLibrary';(steam/'steamapps').mkdir(parents=True)
            cfg=steam/'steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/MRS.cfg'
            self.create(cfg,b'bind w +forward')
            game=dict(game='Counter-Strike 2',appid='730',launcher='Steam',library=str(steam))
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[])
            trusted,_=associate_saves(game,found)
            self.assertIn(str(cfg),trusted)
            plan=build_plan({str(cfg):'keep'},[str(home)])
            self.assertEqual(plan.count,1)
            self.assertEqual(plan.files[0].source,str(cfg))

    def test_other_game_default_cfg_not_auto_added(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);steam=home/'Library';(steam/'steamapps').mkdir(parents=True)
            cfg=steam/'steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/default.cfg'
            self.create(cfg)
            game=dict(game='Counter-Strike 2',appid='730',launcher='Steam',library=str(steam))
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[])
            trusted,_=associate_saves(game,found)
            self.assertNotIn(str(cfg),trusted)

    def test_fortnite_local_settings_not_saves(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);file=home/'Local/FortniteGame/Saved/Config/WindowsClient/GameUserSettings.ini'
            self.create(file)
            game=dict(game='Fortnite',appid='epicfortnite',launcher='Epic')
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[])
            trusted,_=associate_saves(game,found)
            self.assertIn(str(file.parent),trusted)
            item=next(i for i in found if i['path']==str(file.parent))
            self.assertEqual(item['data_kind'],'config')
            self.assertTrue(progress_is_online('Fortnite'))
            self.assertFalse(progress_is_online('Stray'))

    def test_a_plague_tale_steam_remote_known(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);steam=home/'Steam'
            path=steam/'userdata/123/1182900/remote/SAVE_01'
            self.create(path)
            game=dict(game='A Plague Tale: Requiem',appid='1182900',launcher='Steam')
            found=find_game_saves([game],roots=self.make_roots(home),steam_roots=[steam])
            trusted,_=associate_saves(game,found)
            self.assertIn(str(path.parent),trusted)

if __name__=='__main__': unittest.main()
