"""Detecção simulada; somente leitura, nenhum acesso a jogos reais."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_saves import find_game_saves, associate_saves, same_game

class GameSaveDetectionTests(unittest.TestCase):
    def test_witcher_remastered_is_the_same_game(self):
        self.assertTrue(same_game('The Witcher 3','The Witcher 3: Wild Hunt Remastered'))
        self.assertFalse(same_game('The Witcher 3','The Witcher 2: Assassins of Kings'))

    def test_witcher_save_in_documents_is_associated(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            docs=home/'Documents'
            path=docs/'The Witcher 3'/'gamesaves'
            path.mkdir(parents=True)
            (path/'ManualSave.sav').write_bytes(b'fake-save')
            roots={'documents':[docs], 'appdata':[], 'localappdata':[], 'userprofile':[home], 'locallow':[]}
            game={'game':'The Witcher 3: Wild Hunt Remastered','appid':'292030','launcher':'Steam'}
            candidates=find_game_saves([game], roots=roots, steam_roots=[])
            trusted,possible=associate_saves(game,candidates)
            self.assertEqual(trusted,[str(path)])
            self.assertEqual(possible,[])

    def test_unknown_game_folder_is_unverified_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            docs=home/'Documents'
            save=docs/'Fictional Adventure'/'Saves'
            save.mkdir(parents=True)
            (save/'slot.dat').write_bytes(b'test')
            roots={'documents':[docs],'appdata':[], 'localappdata':[], 'userprofile':[home], 'locallow':[]}
            game={'game':'Fictional Adventure Remastered','appid':'99999','launcher':'Steam'}
            candidates=find_game_saves([game], roots=roots, steam_roots=[])
            trusted,possible=associate_saves(game,candidates)
            self.assertEqual(trusted,[])
            self.assertIn(str(save.parent),possible)

    def test_does_not_wrongly_associate_unrelated_game(self):
        candidate={'game':'Elden Ring','path':'C:/x','confidence':'alta'}
        game={'game':'Dark Souls III Remastered','appid':'374320','launcher':'Steam'}
        self.assertEqual(associate_saves(game,[candidate]),([],[]))

    def test_userdata_is_not_trusted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Steam'
            path=root/'userdata'/'12345'/'292030'/'remote'
            path.mkdir(parents=True)
            (path/'file.dat').write_bytes(b'data')
            roots={'documents':[], 'appdata':[], 'localappdata':[], 'userprofile':[], 'locallow':[]}
            game={'game':'The Witcher 3: Wild Hunt Remastered','appid':'292030','launcher':'Steam'}
            data=find_game_saves([game],roots=roots,steam_roots=[root])
            trusted,possible=associate_saves(game,data)
            self.assertEqual(trusted,[])
            self.assertEqual(possible,[str(path)])

if __name__=='__main__':unittest.main()
