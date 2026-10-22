"""FIX-20261022: os caminhos das bibliotecas mantêm a grafia original.

No Windows, os.path.normcase deixa tudo em minúsculas. A normalização agora só
serve para comparar (gl._case_key); o que aparece para o usuário é a grafia
original. Aqui o Windows é simulado trocando _case_key por uma versão que
deixa tudo em minúsculas. As "unidades" são pastas A e B em TemporaryDirectory.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game_launchers as gl


def _lower_key(path):
    return os.path.abspath(str(path)).lower()


def _touch(path, text='x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class OriginalSpellingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.a = self.base / 'A'
        self.b = self.base / 'B'
        self.a.mkdir()
        self.b.mkdir()
        patcher = mock.patch.object(gl, '_case_key', _lower_key)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_path_and_root_keep_original_spelling(self):
        _touch(self.a / 'SteamLibrary' / 'steamapps' / 'libraryfolders.vdf')
        (self.b / 'Epic Games' / 'Fortnite' / '.egstore').mkdir(parents=True)
        libs = gl.detect_launchers([self.a, self.b])['libraries']
        self.assertEqual([(lib['path'], lib['root']) for lib in libs],
                         [(str(self.a / 'SteamLibrary'), str(self.a)),
                          (str(self.b / 'Epic Games'), str(self.b))])

    def test_same_root_with_two_spellings_is_searched_once(self):
        _touch(self.a / 'SteamLibrary' / 'steamapps' / 'libraryfolders.vdf')
        other = str(self.a).lower() if str(self.a) != str(self.a).lower() else str(self.a).upper()
        calls = []
        real_walk = gl._walk_dirs

        def counting_walk(root, **kwargs):
            calls.append(root)
            return real_walk(root, **kwargs)
        with mock.patch.object(gl, '_walk_dirs', counting_walk):
            libs = gl.detect_launchers([self.a, other])['libraries']
        self.assertEqual(calls, [str(self.a)])
        self.assertEqual([lib['path'] for lib in libs], [str(self.a / 'SteamLibrary')])

    def test_on_system_drive_ignores_spelling(self):
        _touch(self.a / 'SteamLibrary' / 'steamapps' / 'libraryfolders.vdf')
        _touch(self.b / 'SteamLibrary' / 'steamapps' / 'libraryfolders.vdf')
        with mock.patch.object(gl, '_drive_key', lambda p: str(p).lower().rstrip('\\/')):
            libs = gl.detect_launchers([self.a, self.b],
                                       system_drive=str(self.a).upper())['libraries']
        by_root = {lib['root']: lib['on_system_drive'] for lib in libs}
        self.assertEqual(by_root, {str(self.a): True, str(self.b): False})

    def test_limit_warning_shows_original_spelling(self):
        for i in range(60):
            (self.a / f'Pasta{i:02d}').mkdir()
        result = gl.detect_launchers([self.a], max_dirs=50)
        self.assertTrue(result['truncated'])
        self.assertTrue(any(str(self.a) in w for w in result['warnings']), result['warnings'])


if __name__ == '__main__':
    unittest.main()
