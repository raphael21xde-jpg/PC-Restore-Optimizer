"""Restoration group indexing is read-only; restore_selected remains the authority."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from restore_groups import build_restore_index, sorted_children, PAGE_SIZE
from backup_features import verified_entries, restore_selected
from backup_core import build_plan, copy_backup
from backup_identity import make_descriptors


class GroupedRestoreTests(unittest.TestCase):
    def entry(self, key, source, owners=None, size=10):
        return key, {'source': source, 'relative': key, 'owners': owners or [], 'bytes': size}

    def test_osu_edition_is_not_mixed(self):
        classic = self.entry('C/Games/osu!/Songs/hello.osu', r'C:\Games\osu!\Songs\hello.osu')
        lazer = self.entry('C/Users/user/AppData/Roaming/ppy.osu/maps/world.osu',
                           r'C:\Users\user\AppData\Roaming\ppy.osu\maps\world.osu')
        index = build_restore_index(dict((classic, lazer)))
        self.assertEqual(index.root.count, 2)
        self.assertEqual({n.name for n in sorted_children(index.root)},
                         {'Jogo: osu! clássico', 'Jogo: osu! lazer'})
        self.assertEqual(index.search_counts('songs')[0], 1)
        self.assertEqual(index.search_counts('osu')[0], 2)
        self.assertEqual(index.search_counts('hello.osu')[0], 1)
        self.assertEqual(len(index.files), 2)

    def test_explicit_owners_and_categories_and_unrecognized(self):
        owner = [{'name':'A Plague Tale: Requiem', 'category':'Save do jogo', 'root':r'C:\Saved Games\Requiem'}]
        data = dict([
            self.entry('C/saves/save1.dat',r'C:\Saved Games\Requiem\save1.dat',owner),
            self.entry('C/random/file.bin',r'C:\Unrecognized\file.bin')])
        index = build_restore_index(data)
        names = {n.name for n in index.root.children.values()}
        self.assertIn('Jogo: A Plague Tale: Requiem', names)
        self.assertIn('Arquivos sem associação confirmada', names)
        game = next(n for n in index.root.children.values() if n.name.startswith('Jogo:'))
        self.assertIn('Saves e progresso', [x.name for x in game.children.values()])
        self.assertEqual(index.search_counts('requiem').get(0), 1)
        self.assertEqual(index.search_counts('missing').get(0), None)

    def test_generic_selected_song_folder_uses_source_proof(self):
        owners = [{'name':'Songs','category':'Arquivo ou pasta selecionada','root':r'D:\osu!\Songs'}]
        key, value = self.entry('D/osu!/Songs/abc.osz',r'D:\osu!\Songs\abc.osz',owners)
        index = build_restore_index({key: value})
        self.assertEqual(next(iter(index.root.children.values())).name, 'Jogo: osu! clássico')

    def test_selected_generic_folder_preserves_its_name(self):
        owner = [{'name':'GameAssets','category':'Arquivo ou pasta selecionada','root':r'E:\Assets\GameAssets'}]
        key, value = self.entry('E/Assets/GameAssets/x.bin',r'E:\Assets\GameAssets\x.bin',owner)
        index = build_restore_index({key: value})
        self.assertTrue(next(iter(index.root.children.values())).name.startswith('Pasta selecionada: GameAssets — E:'))

    def test_shared_owners_are_not_restored_twice(self):
        owners = [
            {'name':'Game A','category':'Save do jogo','root':r'C:\Shared'},
            {'name':'Game B','category':'Save do jogo','root':r'C:\Shared'}]
        key, value = self.entry('C/Shared/a.dat',r'C:\Shared\a.dat',owners)
        index = build_restore_index({key:value})
        self.assertEqual(index.root.count,1)
        self.assertEqual(index.root.keys,[key])
        self.assertIn('Game A + Game B',next(iter(index.root.children.values())).name)

    def test_large_manifest_is_indexed_without_pagination_of_files_at_root(self):
        total=22611
        entries={}
        for i in range(total):
            entries[f'C/osu!/Songs/pack{i//150}/file{i}.osu']={
                'source':rf'C:\Games\osu!\Songs\pack{i//150}\file{i}.osu',
                'bytes':128,
                'owners':[]}
        index=build_restore_index(entries)
        self.assertEqual(index.root.count,total)
        self.assertEqual(len(sorted_children(index.root)),1)
        first=next(iter(index.root.children.values()))
        self.assertEqual(first.count,total)
        self.assertEqual(len(sorted_children(first)),1)  # category, not 22k files
        self.assertLessEqual(PAGE_SIZE,200)
        selected=set(first.keys)
        self.assertEqual(len(selected),total)
        # Selection continues to contain all keys while the filter changes.
        self.assertEqual(index.search_counts('file42.osu').get(0),1)
        self.assertEqual(len(selected),total)
        self.assertEqual(sum(index.bytes_by_key[k] for k in selected),total*128)

    def test_grouped_selection_restores_only_requested_verified_file(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            source=base/'mygame';source.mkdir()
            (source/'save1.dat').write_bytes(b'one')
            (source/'save2.dat').write_bytes(b'two')
            owners=make_descriptors({'a':{'name':'My Game','kind':'game','paths':[str(source)],
                                             'path_kinds':{str(source):'save'}}},[str(source)])
            backup,_=copy_backup(build_plan({str(source):'keep'},[str(base)]),base/'archive',item_descriptors=owners)
            entries=verified_entries(backup/'manifest.json')
            index=build_restore_index(entries)
            chosen=[key for key in index.files if key.endswith('save2.dat')]
            self.assertEqual(len(chosen),1)
            out,count=restore_selected(backup/'manifest.json',chosen,base)
            self.assertEqual(count,1)
            self.assertEqual((out/chosen[0]).read_bytes(),b'two')
            self.assertFalse((out/next(key for key in entries if key not in chosen)).exists())
            self.assertEqual((source/'save1.dat').read_bytes(),b'one')

if __name__ == '__main__':
    unittest.main()
