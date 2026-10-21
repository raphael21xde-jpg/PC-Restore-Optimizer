"""P2-05: launchers e bibliotecas de jogos em outros discos (somente leitura).

As "unidades" são pastas A e B dentro de TemporaryDirectory e sempre passam por
roots=. Os testes nunca varrem discos reais: local_drives é simulado.
"""
import gc
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game_launchers as gl

ROOT = Path(__file__).resolve().parents[1]


def _manifest(name):
    return ('"AppState"\n{\n\t"appid"\t\t"1"\n\t"name"\t\t"%s"\n'
            '\t"installdir"\t\t"x"\n}\n' % name)


def _touch(path, text='x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _snapshot(root):
    out = []
    for folder, dirs, files in os.walk(root):
        for name in sorted(dirs) + sorted(files):
            p = Path(folder) / name
            st = os.lstat(p)
            out.append((str(p), st.st_size if not p.is_dir() else 0, st.st_mtime_ns))
    return sorted(out)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.a = self.base / 'A'
        self.b = self.base / 'B'
        self.a.mkdir()
        self.b.mkdir()

    def build_all(self):
        steam = self.a / 'SteamLibrary' / 'steamapps'
        _touch(steam / 'libraryfolders.vdf', '"libraryfolders" {}')
        _touch(steam / 'appmanifest_10.acf', _manifest('Counter-Strike'))
        _touch(steam / 'appmanifest_20.acf', _manifest('Terraria'))
        (steam / 'common' / 'Terraria').mkdir(parents=True)
        (self.b / 'Epic Games' / 'Fortnite' / '.egstore').mkdir(parents=True)
        (self.b / 'Epic Games' / 'RocketLeague' / '.egstore').mkdir(parents=True)
        (self.b / 'EA Games' / 'FIFA' / '__Installer').mkdir(parents=True)
        _touch(self.a / 'Jogos' / 'Ubisoft' / 'AC' / 'uplay_install.state')
        (self.b / 'Ubisoft' / 'Ubisoft Game Launcher' / 'games' / 'Rainbow Six').mkdir(parents=True)
        (self.a / 'Riot Games' / 'VALORANT').mkdir(parents=True)
        (self.a / 'Riot Games' / 'Riot Client').mkdir(parents=True)
        (self.b / 'Rockstar Games' / 'GTAV').mkdir(parents=True)
        (self.b / 'Rockstar Games' / 'Launcher').mkdir(parents=True)
        (self.b / 'Rockstar Games' / 'Social Club').mkdir(parents=True)

    def libs(self, result, launcher):
        return [lib for lib in result['libraries'] if lib['launcher'] == launcher]


class DetectionTests(Base):
    def test_each_launcher_found_on_different_drives(self):
        self.build_all()
        result = gl.detect_launchers([self.a, self.b])
        self.assertFalse(result['truncated'])
        steam = self.libs(result, gl.STEAM)
        self.assertEqual(len(steam), 1)
        self.assertEqual(steam[0]['path'], str(self.a / 'SteamLibrary'))
        self.assertEqual(steam[0]['root'], str(self.a))
        self.assertEqual(steam[0]['games'], ['Counter-Strike', 'Terraria'])
        self.assertEqual(steam[0]['confidence'], gl.HIGH)
        epic = self.libs(result, gl.EPIC)
        self.assertEqual([lib['path'] for lib in epic], [str(self.b / 'Epic Games')])
        self.assertEqual(epic[0]['games'], ['Fortnite', 'RocketLeague'])
        self.assertEqual(epic[0]['root'], str(self.b))
        ea = self.libs(result, gl.EA)
        self.assertEqual(ea[0]['path'], str(self.b / 'EA Games'))
        self.assertEqual(ea[0]['games'], ['FIFA'])
        ubi = sorted(self.libs(result, gl.UBISOFT), key=lambda lib: lib['path'])
        self.assertEqual([lib['path'] for lib in ubi],
                         sorted([str(self.a / 'Jogos' / 'Ubisoft'),
                                 str(self.b / 'Ubisoft' / 'Ubisoft Game Launcher' / 'games')]))
        self.assertTrue(all(lib['confidence'] == gl.HIGH for lib in ubi))
        riot = self.libs(result, gl.RIOT)
        self.assertEqual(riot[0]['games'], ['VALORANT'])
        self.assertEqual(riot[0]['confidence'], gl.PROBABLE)
        rock = self.libs(result, gl.ROCKSTAR)
        self.assertEqual(rock[0]['games'], ['GTAV'])
        self.assertEqual(rock[0]['confidence'], gl.PROBABLE)

    def test_symlink_or_junction_to_steam_folder_is_not_followed(self):
        target = self.base / 'fora' / 'SteamLibrary' / 'steamapps'
        _touch(target / 'libraryfolders.vdf')
        try:
            os.symlink(self.base / 'fora', self.a / 'atalho', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('não foi possível criar link simbólico neste sistema')
        result = gl.detect_launchers([self.a])
        self.assertEqual(result['libraries'], [])

    def test_depth_six_is_not_found(self):
        deep = self.a / '1' / '2' / '3' / '4' / '5' / '6' / 'steamapps'
        _touch(deep / 'libraryfolders.vdf')
        self.assertEqual(gl.detect_launchers([self.a])['libraries'], [])

    def test_max_dirs_truncates_with_warning(self):
        for i in range(20):
            (self.a / f'pasta{i}' / 'sub').mkdir(parents=True)
        result = gl.detect_launchers([self.a], max_dirs=5)
        self.assertTrue(result['truncated'])
        self.assertTrue(result['warnings'])

    def test_windows_and_users_are_skipped(self):
        _touch(self.a / 'Windows' / 'steamapps' / 'libraryfolders.vdf')
        (self.a / 'Users' / 'Epic Games' / 'Jogo' / '.egstore').mkdir(parents=True)
        (self.a / '$Recycle.Bin' / 'Riot Games' / 'VALORANT').mkdir(parents=True)
        self.assertEqual(gl.detect_launchers([self.a])['libraries'], [])

    def test_big_appmanifest_is_ignored(self):
        steam = self.a / 'SteamLibrary' / 'steamapps'
        _touch(steam / 'appmanifest_1.acf', _manifest('Pequeno'))
        _touch(steam / 'appmanifest_2.acf', _manifest('Grande') + ' ' * (64 * 1024))
        lib = gl.detect_launchers([self.a])['libraries'][0]
        self.assertEqual(lib['games'], ['Pequeno'])

    def test_max_manifests_limits_reading(self):
        steam = self.a / 'SteamLibrary' / 'steamapps'
        for i in range(5):
            _touch(steam / f'appmanifest_{i}.acf', _manifest(f'Jogo {i}'))
        lib = gl.detect_launchers([self.a], max_manifests=2)['libraries'][0]
        self.assertEqual(len(lib['games']), 2)

    def test_tree_is_unchanged(self):
        self.build_all()
        before = _snapshot(self.base)
        gl.detect_launchers([self.a, self.b])
        self.assertEqual(_snapshot(self.base), before)

    def test_missing_root_gives_empty_result(self):
        result = gl.detect_launchers([self.base / 'nao-existe'])
        self.assertEqual(result['libraries'], [])


class RootsTests(Base):
    def test_none_outside_windows_is_empty(self):
        with mock.patch.object(gl, '_on_windows', return_value=False), \
                mock.patch('deep_discovery.local_drives', side_effect=AssertionError('não')):
            result = gl.detect_launchers(None)
        self.assertEqual(result, {'libraries': [], 'truncated': False, 'warnings': []})

    def test_given_roots_do_not_call_local_drives(self):
        with mock.patch('deep_discovery.local_drives',
                        side_effect=AssertionError('não deve varrer discos reais')) as fake:
            gl.detect_launchers([self.a])
        fake.assert_not_called()

    def test_none_on_windows_uses_local_drives(self):
        _touch(self.a / 'steamapps' / 'libraryfolders.vdf')
        with mock.patch.object(gl, '_on_windows', return_value=True), \
                mock.patch('deep_discovery.local_drives', return_value=[str(self.a)]) as fake:
            result = gl.detect_launchers(None)
        fake.assert_called_once()
        self.assertEqual(len(result['libraries']), 1)


class GuideTests(unittest.TestCase):
    def test_guides(self):
        self.assertIn('Adicionar unidade', gl.guide_for(gl.STEAM, r'D:\SteamLibrary'))
        self.assertIn(r'D:\SteamLibrary', gl.guide_for(gl.STEAM, r'D:\SteamLibrary'))
        self.assertIn('.egstore', gl.guide_for(gl.EPIC, r'D:\Epic Games'))
        for launcher in (gl.EA, gl.UBISOFT, gl.RIOT, gl.ROCKSTAR):
            self.assertIn('Localizar jogo', gl.guide_for(launcher, r'D:\Jogos'))

    def test_guides_never_say_delete_or_rename(self):
        for launcher in gl.LAUNCHERS:
            text = gl.guide_for(launcher, r'D:\X').lower()
            for word in ('apague', 'apagar', 'renomeie', 'renomear', 'exclua', 'excluir',
                         'desinstal', 'formate'):
                self.assertNotIn(word, text, launcher)

    def test_module_never_runs_anything(self):
        src = (ROOT / 'game_launchers.py').read_text(encoding='utf-8')
        ui = (ROOT / 'launcher_guide_ui.py').read_text(encoding='utf-8')
        for text in (src, ui):
            for word in ('subprocess', 'os.startfile', 'os.system', 'os.remove', 'shutil'):
                self.assertNotIn(word, text)

    def test_restore_ui_has_button(self):
        ui = (ROOT / 'restore_ui.py').read_text(encoding='utf-8')
        self.assertTrue('show_launchers(dlg)' in ui, 'restore_ui sem show_launchers')
        self.assertTrue("'Launchers de jogos'" in ui, 'restore_ui sem o botão')


try:
    import tkinter as tk
    from tkinter import ttk
    from launcher_guide_ui import show_launchers
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = show_launchers = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(gc.collect)

    def widgets(self, cls, widget):
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.widgets(cls, child)

    def wait(self, dlg):
        until = time.monotonic() + 5
        while dlg.launcher_state['busy'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(dlg.launcher_state['busy'])

    def test_window_lists_rows_and_shows_guide(self):
        fake = {'libraries': [
            {'launcher': gl.STEAM, 'path': r'D:\SteamLibrary', 'root': 'D:\\',
             'games': ['A', 'B'], 'confidence': gl.HIGH},
            {'launcher': gl.EPIC, 'path': r'E:\Epic Games', 'root': 'E:\\',
             'games': ['C'], 'confidence': gl.HIGH},
            {'launcher': gl.RIOT, 'path': r'E:\Riot Games', 'root': 'E:\\',
             'games': ['V'], 'confidence': gl.PROBABLE}],
            'truncated': True, 'warnings': ['limite']}
        calls = []

        def scanner(roots):
            calls.append(roots)
            return fake
        dlg = show_launchers(self.root, roots=['X'], scanner=scanner)
        self.wait(dlg)
        self.assertEqual(calls, [['X']])
        tree = next(self.widgets(ttk.Treeview, dlg))
        rows = tree.get_children('')
        self.assertEqual(len(rows), 3)
        tree.selection_set(rows[0])
        self.root.update()
        text = next(self.widgets(tk.Text, dlg))
        self.assertIn('Adicionar unidade', text.get('1.0', 'end'))
        self.assertEqual(str(text.cget('state')), 'disabled')
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        for name in ('Pesquisar de novo', 'Copiar caminho', 'Fechar'):
            self.assertIn(name, buttons)
        buttons['Copiar caminho'].invoke()
        self.assertEqual(self.root.clipboard_get(), r'D:\SteamLibrary')
        self.assertIn('limite', dlg.launcher_warning.get())
        buttons['Pesquisar de novo'].invoke()
        self.wait(dlg)
        self.assertEqual(len(calls), 2)
        dlg.destroy()


if __name__ == '__main__':
    unittest.main()
