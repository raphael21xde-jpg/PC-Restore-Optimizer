"""P2-04 (fatia 1): lista de programas do backup (winget export).

O winget é SEMPRE simulado: subprocess.run e subprocess.Popen são trocados por
funções que falham se forem chamadas. Só pastas sintéticas em TemporaryDirectory.
"""
import gc
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import winget_programs as wp
from tk_helpers import track_tk_root

ROOT = Path(__file__).resolve().parents[1]


def _forbidden(*args, **kwargs):
    raise AssertionError('o winget real (subprocess) nunca deve ser chamado nos testes')


def _export_doc(winget_ids=(), msstore_ids=()):
    sources = [{'Packages': [{'PackageIdentifier': i, 'Version': '1.0'} for i in winget_ids],
                'SourceDetails': {'Name': 'winget', 'Identifier': 'Microsoft.Winget.Source_x',
                                  'Argument': 'https://cdn.winget.microsoft.com/cache',
                                  'Type': 'Microsoft.PreIndexed.Package'}}]
    if msstore_ids:
        sources.append({'Packages': [{'PackageIdentifier': i} for i in msstore_ids],
                        'SourceDetails': {'Name': 'msstore', 'Identifier': 'StoreEdgeFD',
                                          'Argument': 'https://storeedgefd.dsx.mp.microsoft.com/v9.0',
                                          'Type': 'Microsoft.Rest'}})
    return {'$schema': 'https://aka.ms/winget-packages.schema.2.0.json',
            'CreationDate': '2026-10-21T10:00:00', 'Sources': sources,
            'WinGetVersion': '1.9.0'}


class FakeRunner:
    def __init__(self, payload=None, code=0, output='', raises=None):
        self.payload, self.code, self.output, self.raises = payload, code, output, raises
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.raises is not None:
            raise self.raises
        if self.payload is not None:
            target = Path(cmd[cmd.index('--output') + 1])
            data = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode('utf-8')
            target.write_bytes(data)
        return self.code, self.output


class Base(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch('subprocess.run', side_effect=_forbidden),
                   mock.patch('subprocess.Popen', side_effect=_forbidden)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'Backup-teste'
        self.folder.mkdir()
        self.manifest = self.folder / 'manifest.json'
        self.manifest.write_bytes(b'{"status": "concluido", "files": {}, "errors": []}')
        (self.folder / 'arquivo.txt').write_bytes(b'dados sinteticos')

    def save(self, payload=None, **kwargs):
        runner = kwargs.pop('runner', None) or FakeRunner(payload)
        return wp.save_export(self.folder, runner=runner, executable='winget'), runner


class CommandTests(Base):
    def test_export_command_is_exact_and_read_only(self):
        cmd = wp.export_command('X:/saida.json', 'winget')
        self.assertEqual(cmd, ['winget', 'export', '--output', 'X:/saida.json', '--source', 'winget',
                               '--include-versions', '--disable-interactivity'])
        for word in ('install', 'import', 'uninstall', 'upgrade'):
            self.assertNotIn(word, cmd)
        self.assertFalse(any(part.startswith('--accept-') for part in cmd))

    def test_default_runner_uses_no_shell_devnull_and_timeout(self):
        fake = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        with mock.patch('subprocess.run', fake):
            wp._default_runner(['winget', 'export'])
        kwargs = fake.call_args.kwargs
        self.assertIs(kwargs['shell'], False)
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['timeout'], 180)


class SaveTests(Base):
    def test_save_creates_subfolder_file_and_info_without_touching_backup(self):
        before_manifest = self.manifest.read_bytes()
        before_file = (self.folder / 'arquivo.txt').read_bytes()
        result, runner = self.save(_export_doc(['Git.Git', 'Valve.Steam']))
        self.assertEqual(result['status'], 'salvo', result)
        self.assertEqual(result['count'], 2)
        sub = self.folder / 'programas-winget'
        raw = (sub / 'winget-export.json').read_bytes()
        self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
        info = json.loads((sub / 'info.json').read_text(encoding='utf-8'))
        self.assertEqual(info['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(info['quantidade'], 2)
        self.assertIn('data', info)
        self.assertFalse((sub / 'winget-export.json.parcial').exists())
        self.assertEqual(self.manifest.read_bytes(), before_manifest)
        self.assertEqual((self.folder / 'arquivo.txt').read_bytes(), before_file)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ['arquivo.txt', 'manifest.json', 'programas-winget'])
        self.assertEqual(runner.calls[0][1], 'export')
        self.assertTrue(runner.calls[0][3].endswith('winget-export.json.parcial'))
        self.assertNotIn(str(Path.home()), result['message'])


class RefusalTests(Base):
    def test_refuses_when_subfolder_is_link(self):
        target = Path(self.temp.name) / 'outro-lugar'
        target.mkdir()
        try:
            os.symlink(target, self.folder / 'programas-winget', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('não foi possível criar link simbólico neste sistema')
        result, runner = self.save(_export_doc(['Git.Git']))
        self.assertEqual(result['status'], 'recusado')
        self.assertIn('link', result['message'])
        self.assertEqual(runner.calls, [])
        self.assertEqual(list(target.iterdir()), [])

    def test_refuses_existing_export_without_overwriting(self):
        sub = self.folder / 'programas-winget'
        sub.mkdir()
        (sub / 'winget-export.json').write_bytes(b'original')
        result, runner = self.save(_export_doc(['Git.Git']))
        self.assertEqual(result['status'], 'recusado')
        self.assertIn('não será substituída', result['message'])
        self.assertEqual((sub / 'winget-export.json').read_bytes(), b'original')
        self.assertEqual(runner.calls, [])

    def test_refuses_folder_without_manifest(self):
        self.manifest.unlink()
        result, runner = self.save(_export_doc(['Git.Git']))
        self.assertEqual(result['status'], 'recusado')
        self.assertIn('manifest.json', result['message'])
        self.assertFalse((self.folder / 'programas-winget').exists())
        self.assertEqual(runner.calls, [])


class FailureTests(Base):
    def assert_failed_cleanly(self, result):
        self.assertEqual(result['status'], 'falhou', result)
        self.assertIsNone(result['sha256'])
        sub = self.folder / 'programas-winget'
        self.assertFalse((sub / 'info.json').exists())
        self.assertFalse((sub / 'winget-export.json').exists())
        self.assertTrue(self.manifest.exists())

    def test_nonzero_exit(self):
        result, _ = self.save(runner=FakeRunner(_export_doc(['Git.Git']), code=1))
        self.assert_failed_cleanly(result)
        # o .parcial fica onde está (nada é apagado), apenas ignorado
        self.assertTrue((self.folder / 'programas-winget' / 'winget-export.json.parcial').exists())

    def test_timeout(self):
        result, _ = self.save(runner=FakeRunner(raises=subprocess.TimeoutExpired(['winget'], 180)))
        self.assert_failed_cleanly(result)
        self.assertIn('demorou', result['message'])

    def test_invalid_json(self):
        result, _ = self.save(runner=FakeRunner(b'{isto nao e json'))
        self.assert_failed_cleanly(result)

    def test_source_agreement_is_explained(self):
        result, _ = self.save(runner=FakeRunner(code=-1978335141,
                              output='The source requires the current machine agreements to be accepted.'))
        self.assert_failed_cleanly(result)
        self.assertIn('Abra o winget uma vez', result['message'])


class AvailabilityTests(Base):
    def test_outside_windows(self):
        with mock.patch.object(wp, '_platform_is_windows', return_value=False):
            result = wp.save_export(self.folder, runner=FakeRunner(_export_doc(['Git.Git'])))
        self.assertEqual(result['status'], 'indisponivel')
        self.assertIn('só pode ser salva no Windows', result['message'])
        self.assertFalse((self.folder / 'programas-winget').exists())

    def test_without_winget(self):
        with mock.patch.object(wp, '_platform_is_windows', return_value=True), \
             mock.patch.object(wp, '_find_winget', return_value=None):
            result = wp.save_export(self.folder, runner=FakeRunner(_export_doc(['Git.Git'])))
        self.assertEqual(result['status'], 'indisponivel')
        self.assertIn('winget não foi encontrado', result['message'])
        self.assertFalse((self.folder / 'programas-winget').exists())


class ParseTests(unittest.TestCase):
    def test_parse_mixed_sources_duplicates_invalid_and_osu(self):
        doc = _export_doc(['Git.Git', 'git.git', '--x', 'a;b', 'ppy.osu', 'Valve.Steam', 'semponto'],
                          ['9NBLGGH4NNS1', '9NBLGGH4NNS1'])
        packages = wp.parse_export(doc)
        ids = [p['id'] for p in packages]
        self.assertEqual(sorted(ids, key=str.casefold), ['9NBLGGH4NNS1', 'Git.Git', 'ppy.osu', 'Valve.Steam'])
        by_id = {p['id']: p for p in packages}
        self.assertFalse(by_id['9NBLGGH4NNS1']['selectable'])
        self.assertIn('Microsoft Store', by_id['9NBLGGH4NNS1']['note'])
        self.assertEqual(by_id['9NBLGGH4NNS1']['source'], 'msstore')
        self.assertFalse(by_id['ppy.osu']['selectable'])
        self.assertIn('osu!lazer', by_id['ppy.osu']['note'])
        self.assertTrue(by_id['Git.Git']['selectable'])
        self.assertEqual(by_id['Git.Git']['version'], '1.0')
        for p in packages:
            self.assertEqual(set(p), {'id', 'version', 'source', 'category', 'selectable', 'note'})

    def test_parse_rejects_bad_structure_and_too_many(self):
        with self.assertRaises(ValueError):
            wp.parse_export([])
        with self.assertRaises(ValueError):
            wp.parse_export(_export_doc([f'Pub.App{i}' for i in range(5001)]))

    def test_default_selection_is_empty(self):
        packages = wp.parse_export(_export_doc(['Git.Git', 'Valve.Steam']))
        self.assertEqual(wp.default_selection(packages), set())


class CategorizeTests(unittest.TestCase):
    def test_all_categories(self):
        cases = {
            'Runtimes': ('Microsoft.VCRedist.2015+.x64', 'Microsoft.DotNet.DesktopRuntime.8'),
            'Launchers': ('Valve.Steam', 'EpicGames.EpicGamesLauncher'),
            'Periféricos': ('Logitech.GHUB', 'Razer.Synapse3'),
            'Dia a dia': ('Google.Chrome', 'Discord.Discord'),
            'Dev': ('Git.Git', 'Microsoft.VisualStudioCode'),
            'Outros': ('Fabricante.ProgramaDesconhecido', 'Xyz.Abc'),
        }
        self.assertEqual(tuple(cases), wp.CATEGORIES)
        for category, ids in cases.items():
            for pid in ids:
                with self.subTest(pid=pid):
                    self.assertEqual(wp.categorize(pid), category)
                    self.assertEqual(wp.categorize(pid.upper()), category)

    def test_peripheral_terms_from_catalog(self):
        self.assertEqual(wp.categorize('Elgato.StreamDeck'), 'Periféricos')
        self.assertEqual(wp.categorize('SomeVendor.Corsair.iCUE5'), 'Periféricos')
        self.assertEqual(wp.categorize('SonarSource.SonarLint'), 'Dev')

    def test_group_by_category_keeps_order(self):
        groups = wp.group_by_category(wp.parse_export(_export_doc(['Git.Git', 'Valve.Steam'])))
        self.assertEqual(tuple(groups), wp.CATEGORIES)
        self.assertEqual([p['id'] for p in groups['Dev']], ['Git.Git'])


class LoadTests(Base):
    def test_load_round_trip(self):
        self.save(_export_doc(['Git.Git', 'Valve.Steam'], ['9NBLGGH4NNS1']))
        packages = wp.load_export(self.folder)
        self.assertEqual(len(packages), 3)

    def test_tampered_list_is_refused(self):
        self.save(_export_doc(['Git.Git']))
        path = self.folder / 'programas-winget' / 'winget-export.json'
        path.write_bytes(json.dumps(_export_doc(['Mal.Intencionado'])).encode('utf-8'))
        with self.assertRaises(ValueError) as ctx:
            wp.load_export(self.folder)
        self.assertIn('lista de programas foi alterada', str(ctx.exception))

    def test_missing_list(self):
        with self.assertRaises(ValueError) as ctx:
            wp.load_export(self.folder)
        self.assertIn('Este backup não tem a lista', str(ctx.exception))

    def test_too_big_list(self):
        sub = self.folder / 'programas-winget'
        sub.mkdir()
        (sub / 'winget-export.json').write_bytes(b' ' * (wp.MAX_BYTES + 1))
        (sub / 'info.json').write_text('{"sha256": "x"}', encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            wp.load_export(self.folder)
        self.assertIn('grande demais', str(ctx.exception))


class AfterBackupTests(Base):
    def test_does_not_run_for_partial_backup(self):
        ask = mock.Mock(return_value=True)
        runner = FakeRunner(_export_doc(['Git.Git']))
        self.assertIsNone(wp.export_after_backup(self.folder, {'status': 'parcial'}, ask, runner, 'winget'))
        ask.assert_not_called()
        self.assertEqual(runner.calls, [])

    def test_does_not_run_when_user_says_no(self):
        runner = FakeRunner(_export_doc(['Git.Git']))
        self.assertIsNone(wp.export_after_backup(self.folder, {'status': 'concluido'},
                                                 lambda: False, runner, 'winget'))
        self.assertEqual(runner.calls, [])
        self.assertFalse((self.folder / 'programas-winget').exists())

    def test_runs_when_concluded_and_yes(self):
        runner = FakeRunner(_export_doc(['Git.Git']))
        result = wp.export_after_backup(self.folder, {'status': 'concluido'}, lambda: True, runner, 'winget')
        self.assertEqual(result['status'], 'salvo')


class SourceWiringTests(unittest.TestCase):
    def test_app_offers_export_only_after_concluded_backup(self):
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        done = app.split('def _backup_done', 1)[1].split('def _build_browsers', 1)[0]
        self.assertIn('_offer_program_list(folder, manifest)', done)
        offer = done.split('def _offer_program_list', 1)[1]
        self.assertIn('askyesno', offer)
        self.assertIn('export_after_backup', offer)
        self.assertIn('Job(', offer)

    def test_restore_screen_has_programs_button(self):
        ui = (ROOT / 'restore_ui.py').read_text(encoding='utf-8')
        self.assertIn("text='Programas do backup'", ui)
        self.assertIn('show_programs(dlg, Path(manifest).parent)', ui)

    def test_modules_never_install_or_delete(self):
        # Fatia 2: a instalação existe, mas só no winget_install.py (testado em
        # test_winget_install_p2_04). Estes dois módulos continuam sem montar
        # comando de instalação: a tela só chama winget_install.run_install.
        for name in ('winget_programs.py', 'winget_programs_ui.py'):
            source = (ROOT / name).read_text(encoding='utf-8')
            for forbidden in ("'install'", "'import'", '--accept-', 'unlink', 'rmtree', 'rmdir',
                              'shell=True', 'Popen'):
                with self.subTest(module=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, source)
        ui = (ROOT / 'winget_programs_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('subprocess', ui)


try:
    import tkinter as tk
    from tkinter import ttk
    from winget_programs_ui import show_programs
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = show_programs = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ProgramsWindowTests(Base):
    def setUp(self):
        super().setUp()
        self.save(_export_doc(['Git.Git', 'Python.Python.3.13', 'Valve.Steam', 'ppy.osu'], ['9NBLGGH4NNS1']))
        self.root = tk.Tk()
        self.root.withdraw()
        track_tk_root(self, self.root)

    def widgets(self, cls, widget):
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.widgets(cls, child)

    def test_window_lists_categories_and_marks_category(self):
        dlg = show_programs(self.root, self.folder)
        until = time.monotonic() + 5
        while not dlg.program_state['loaded'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(dlg.program_state['loaded'], dlg.program_state['error'])
        tree = next(self.widgets(ttk.Treeview, dlg))
        roots = tree.get_children('')
        self.assertEqual(len(roots), 6)
        self.assertEqual(dlg.program_state['selected'], set())
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        for text in ('Marcar categoria', 'Marcar tudo', 'Desmarcar tudo'):
            self.assertIn(text, buttons)
        # fatia 2: o botão de instalar existe, mas começa desligado (nada marcado)
        self.assertTrue(buttons['Instalar marcados…'].instate(['disabled']))
        dev = roots[wp.CATEGORIES.index('Dev')]
        tree.focus(dev)
        buttons['Marcar categoria'].invoke()
        chosen = {dlg.program_state['packages'][i]['id'] for i in dlg.program_state['selected']}
        self.assertEqual(chosen, {'Git.Git', 'Python.Python.3.13'})
        buttons['Marcar tudo'].invoke()
        chosen = {dlg.program_state['packages'][i]['id'] for i in dlg.program_state['selected']}
        self.assertNotIn('ppy.osu', chosen)
        self.assertNotIn('9NBLGGH4NNS1', chosen)
        buttons['Desmarcar tudo'].invoke()
        self.assertEqual(dlg.program_state['selected'], set())
        dlg.destroy()


if __name__ == '__main__':
    unittest.main()
