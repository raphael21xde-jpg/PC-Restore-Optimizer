"""P2-04 (fatia 2): instalar os programas marcados e conferir um por um.

O winget é SEMPRE simulado: subprocess.run e subprocess.Popen são trocados por
funções que falham se forem chamadas, e o teste de administrador recebe uma
função falsa. Só pastas sintéticas em TemporaryDirectory.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import winget_install as wi
import winget_programs as wp

ROOT = Path(__file__).resolve().parents[1]


def _forbidden(*args, **kwargs):
    raise AssertionError('o winget real (subprocess) nunca deve ser chamado nos testes')


def _not_admin():
    return False


def _admin():
    return True


def _export_doc(winget_ids=(), msstore_ids=()):
    sources = [{'Packages': [{'PackageIdentifier': i, 'Version': '1.0'} for i in winget_ids],
                'SourceDetails': {'Name': 'winget'}}]
    if msstore_ids:
        sources.append({'Packages': [{'PackageIdentifier': i} for i in msstore_ids],
                        'SourceDetails': {'Name': 'msstore'}})
    return {'Sources': sources}


def _packages(winget_ids=('Git.Git', 'Valve.Steam', 'Mozilla.Firefox', 'ppy.osu'),
              msstore_ids=('9NBLGGH4NNS1',)):
    return wp.parse_export(_export_doc(winget_ids, msstore_ids))


def _snapshot(folder):
    out = {}
    for path in sorted(Path(folder).rglob('*')):
        out[str(path.relative_to(folder))] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'dir')
    return out


class FakeWinget:
    """Simula `winget list` e `winget import`. Guarda cada chamada."""

    def __init__(self, before=(), installs=(), import_output='', import_code=0,
                 import_raises=None, list_raises=None):
        self.installed = {i.casefold() for i in before}
        self.installs = set(installs)
        self.import_output, self.import_code = import_output, import_code
        self.import_raises, self.list_raises = import_raises, list_raises
        self.calls, self.imported_docs = [], []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[1] == 'list':
            if self.list_raises is not None:
                raise self.list_raises
            pid = cmd[cmd.index('--id') + 1]
            if pid.casefold() in self.installed:
                return 0, f'Nome  ID  Versão\n------\nPrograma  {pid}  1.0'
            return 1, 'No installed package found matching input criteria.'
        if cmd[1] == 'import':
            doc = json.loads(Path(cmd[cmd.index('--import-file') + 1]).read_text(encoding='utf-8'))
            self.imported_docs.append(doc)
            if self.import_raises is not None:
                raise self.import_raises
            for pid in self.installs:
                self.installed.add(pid.casefold())
            return self.import_code, self.import_output
        raise AssertionError(f'comando inesperado: {cmd}')

    def lists(self):
        return [c for c in self.calls if c[1] == 'list']

    def imports(self):
        return [c for c in self.calls if c[1] == 'import']


class Base(unittest.TestCase):
    def setUp(self):
        for target in ('subprocess.run', 'subprocess.Popen'):
            p = mock.patch(target, side_effect=_forbidden)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(wi, '_platform_is_windows', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'estado'
        self.backup = Path(self.temp.name) / 'Backup-teste'
        (self.backup / 'programas-winget').mkdir(parents=True)
        (self.backup / 'manifest.json').write_bytes(b'{"status": "concluido"}')
        (self.backup / 'programas-winget' / 'winget-export.json').write_bytes(b'{}')

    def run_install(self, fake, selected, packages=None, probe=_not_admin, **kwargs):
        return wi.run_install(_packages() if packages is None else packages, selected,
                              runner=fake, state_dir=self.state, elevated_probe=probe,
                              executable='winget', **kwargs)

    def run_dirs(self):
        return [p for p in self.state.iterdir() if p.is_dir()] if self.state.exists() else []


class DocumentTests(unittest.TestCase):
    def test_document_has_fixed_source_no_versions_only_selected(self):
        doc = wi.build_import_document(_packages(), ['Git.Git', 'Mozilla.Firefox'])
        self.assertEqual(len(doc['Sources']), 1)
        source = doc['Sources'][0]
        self.assertEqual(source['SourceDetails'], wi.WINGET_SOURCE)
        self.assertEqual(source['SourceDetails']['Name'], 'winget')
        # ordem da lista (por categoria), não a ordem em que foram marcados
        self.assertEqual(source['Packages'], [{'PackageIdentifier': 'Mozilla.Firefox'},
                                              {'PackageIdentifier': 'Git.Git'}])
        for package in source['Packages']:
            self.assertEqual(set(package), {'PackageIdentifier'})  # sem versão fixa
        self.assertNotIn('"Version"', json.dumps(doc))

    def test_store_osu_invalid_and_unknown_ids_are_left_out(self):
        packages = _packages()
        packages.append({'id': '--evil', 'version': '', 'source': 'winget', 'category': 'Outros',
                         'selectable': True, 'note': ''})
        packages.append({'id': 'Outra.Fonte', 'version': '', 'source': 'empresa',
                         'category': 'Outros', 'selectable': True, 'note': ''})
        doc = wi.build_import_document(packages, ['Git.Git', '9NBLGGH4NNS1', 'ppy.osu', '--evil',
                                                  'Outra.Fonte', 'Nao.Esta.Na.Lista', 'git.git'])
        self.assertEqual(doc['Sources'][0]['Packages'], [{'PackageIdentifier': 'Git.Git'}])

    def test_osu_is_refused_even_if_marked_selectable(self):
        packages = [{'id': 'ppy.osu', 'version': '', 'source': 'winget', 'category': 'Outros',
                     'selectable': True, 'note': ''}]
        with self.assertRaises(ValueError):
            wi.build_import_document(packages, ['ppy.osu'])

    def test_empty_selection_raises(self):
        with self.assertRaises(ValueError):
            wi.build_import_document(_packages(), [])
        with self.assertRaises(ValueError):
            wi.build_import_document(_packages(), ['9NBLGGH4NNS1'])


class CommandTests(Base):
    def test_import_command_is_exact(self):
        cmd = wi.import_command('X:/importar.json', 'winget')
        self.assertEqual(cmd, ['winget', 'import', '--import-file', 'X:/importar.json',
                               '--ignore-unavailable', '--no-upgrade', '--disable-interactivity'])
        self.assertFalse(any(part.startswith('--accept-') for part in cmd))
        self.assertNotIn('runas', ' '.join(cmd).casefold())

    def test_list_command_uses_exact_id(self):
        fake = FakeWinget()
        wi.check_installed('Git.Git', fake, 'winget')
        cmd = fake.calls[0]
        self.assertEqual(cmd[:5], ['winget', 'list', '--id', 'Git.Git', '--exact'])

    def test_default_runner_list_no_shell_devnull(self):
        run = mock.Mock(return_value=mock.Mock(returncode=0, stdout='ok', stderr=''))
        with mock.patch('subprocess.run', run):
            code, output = wi._default_runner(['winget', 'list', '--id', 'Git.Git', '--exact'])
        self.assertEqual(code, 0)
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs['shell'], False)
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
        self.assertIn('timeout', kwargs)

    def test_default_runner_import_waits_without_killing(self):
        import_file = Path(self.temp.name) / 'importar.json'
        import_file.write_text('{}', encoding='utf-8')
        proc = mock.Mock()
        proc.wait.side_effect = subprocess.TimeoutExpired(['winget'], wi.IMPORT_TIMEOUT_SEC)
        popen = mock.Mock(return_value=proc)
        with mock.patch('subprocess.Popen', popen):
            code, _ = wi._default_runner(wi.import_command(str(import_file), 'winget'))
        self.assertIsNone(code)  # tempo esgotado
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs['shell'], False)
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(proc.wait.call_args.kwargs['timeout'], 2 * 60 * 60)
        proc.kill.assert_not_called()
        proc.terminate.assert_not_called()

    def test_source_has_no_shell_runas_or_accept(self):
        source = (ROOT / 'winget_install.py').read_text(encoding='utf-8')
        for forbidden in ('shell=True', 'runas', '--accept-', 'unlink', 'rmtree', 'rmdir',
                          '.kill(', '.terminate(', 'ShellExecute'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class RefusalTests(Base):
    def test_admin_refuses_without_calling_runner(self):
        fake = FakeWinget()
        result = self.run_install(fake, ['Git.Git'], probe=_admin)
        self.assertEqual(result['status'], 'recusado')
        self.assertIn('administrador', result['message'])
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.run_dirs(), [])

    def test_outside_windows_refuses(self):
        fake = FakeWinget()
        with mock.patch.object(wi, '_platform_is_windows', return_value=False):
            result = self.run_install(fake, ['Git.Git'])
        self.assertEqual(result['status'], 'indisponivel')
        self.assertIn('Windows', result['message'])
        self.assertEqual(fake.calls, [])

    def test_without_winget_refuses(self):
        fake = FakeWinget()
        with mock.patch.object(wi, '_find_winget', return_value=None):
            result = wi.run_install(_packages(), ['Git.Git'], runner=fake, state_dir=self.state,
                                    elevated_probe=_not_admin)
        self.assertEqual(result['status'], 'indisponivel')
        self.assertIn('winget não foi encontrado', result['message'])
        self.assertEqual(fake.calls, [])

    def test_empty_selection_refuses_in_portuguese(self):
        fake = FakeWinget()
        result = self.run_install(fake, [])
        self.assertEqual(result['status'], 'recusado')
        self.assertIn('Nenhum programa', result['message'])
        self.assertEqual(fake.calls, [])


class InstallFlowTests(Base):
    def test_installs_only_missing_and_verifies_each(self):
        fake = FakeWinget(before=['Git.Git'], installs=['Valve.Steam'],
                          import_output='Found Steam [Valve.Steam]\nSuccessfully installed\n'
                                        'Found Firefox [Mozilla.Firefox]\nInstaller hash does not match.')
        before = _snapshot(self.backup)
        result = self.run_install(fake, ['Git.Git', 'Valve.Steam', 'Mozilla.Firefox'])
        self.assertEqual(result['status'], 'concluido', result)
        by_id = {r['id']: r for r in result['results']}
        self.assertEqual(by_id['Git.Git']['status'], 'já instalado')
        self.assertEqual(by_id['Valve.Steam']['status'], 'instalado')
        self.assertEqual(by_id['Mozilla.Firefox']['status'], 'não instalado')
        self.assertIn('site oficial', by_id['Mozilla.Firefox']['explanation'])
        # o já instalado sai do arquivo de importação
        self.assertEqual(len(fake.imports()), 1)
        packages = fake.imported_docs[0]['Sources'][0]['Packages']
        self.assertEqual(packages, [{'PackageIdentifier': 'Valve.Steam'},
                                    {'PackageIdentifier': 'Mozilla.Firefox'}])
        # conferência: um list por pacote antes, e um por pacote que foi para o import depois
        listed = [c[c.index('--id') + 1] for c in fake.lists()]
        self.assertEqual(listed, ['Valve.Steam', 'Mozilla.Firefox', 'Git.Git',
                                  'Valve.Steam', 'Mozilla.Firefox'])
        # o import vem depois da primeira conferência e antes da segunda
        kinds = [c[1] for c in fake.calls]
        self.assertEqual(kinds, ['list'] * 3 + ['import'] + ['list'] * 2)
        self.assertEqual(_snapshot(self.backup), before)

    def test_all_already_installed_skips_import(self):
        fake = FakeWinget(before=['Git.Git', 'Valve.Steam'])
        result = self.run_install(fake, ['Git.Git', 'Valve.Steam'])
        self.assertEqual(result['status'], 'concluido')
        self.assertEqual(fake.imports(), [])
        self.assertEqual({r['status'] for r in result['results']}, {'já instalado'})
        self.assertIn('já instalado', (Path(result['report_dir']) / 'relatorio.txt')
                      .read_text(encoding='utf-8'))

    def test_import_file_written_in_new_state_folder(self):
        fake = FakeWinget(installs=['Git.Git'])
        result = self.run_install(fake, ['Git.Git'])
        run_dir = Path(result['report_dir'])
        self.assertEqual(run_dir.parent, self.state)
        self.assertRegex(run_dir.name, r'^\d{8}-\d{6}')
        self.assertTrue((run_dir / 'importar.json').is_file())
        import_path = fake.imports()[0][3]
        self.assertEqual(Path(import_path).parent, run_dir)
        self.assertNotIn(str(self.backup), import_path)

    def test_prepare_run_never_reuses_folder(self):
        doc = wi.build_import_document(_packages(), ['Git.Git'])
        first, _ = wi.prepare_run(self.state, doc)
        (first / 'marca.txt').write_text('não mexer', encoding='utf-8')
        with mock.patch.object(wi, '_timestamp', return_value=first.name):
            second, _ = wi.prepare_run(self.state, doc)
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'marca.txt').read_text(encoding='utf-8'), 'não mexer')

    def test_timeout_still_verifies(self):
        fake = FakeWinget(installs=['Git.Git'], import_code=None)
        result = self.run_install(fake, ['Git.Git', 'Valve.Steam'])
        self.assertEqual(result['status'], 'concluido')
        self.assertTrue(result['timed_out'])
        self.assertIn('tempo', result['message'])
        self.assertEqual(len(fake.lists()), 4)
        by_id = {r['id']: r['status'] for r in result['results']}
        self.assertEqual(by_id, {'Git.Git': 'instalado', 'Valve.Steam': 'não instalado'})

    def test_runner_timeout_exception_still_verifies(self):
        fake = FakeWinget(import_raises=subprocess.TimeoutExpired(['winget'], 10))
        result = self.run_install(fake, ['Git.Git'])
        self.assertTrue(result['timed_out'])
        self.assertEqual(len(fake.lists()), 2)

    def test_runner_oserror_is_portuguese_and_never_raises(self):
        fake = FakeWinget(import_raises=OSError('boom'))
        result = self.run_install(fake, ['Git.Git'])
        self.assertEqual(result['status'], 'falhou')
        self.assertIn('Não foi possível', result['message'])
        self.assertNotIn('boom', result['message'])
        self.assertEqual(result['results'][0]['status'], 'não instalado')

    def test_list_failure_is_portuguese(self):
        fake = FakeWinget(list_raises=OSError('x'))
        result = self.run_install(fake, ['Git.Git'])
        self.assertIn(result['status'], ('concluido', 'falhou'))
        self.assertEqual(result['results'][0]['status'], 'não instalado')

    def test_state_folder_oserror_is_portuguese(self):
        fake = FakeWinget()
        with mock.patch.object(wi.os, 'mkdir', side_effect=PermissionError('negado')):
            result = self.run_install(fake, ['Git.Git'])
        self.assertEqual(result['status'], 'falhou')
        self.assertIn('Não foi possível', result['message'])
        self.assertEqual(fake.imports(), [])

    def test_unexpected_error_never_raises(self):
        def broken(cmd):
            raise RuntimeError('interno')
        result = self.run_install(broken, ['Git.Git'])
        self.assertIn(result['status'], ('concluido', 'falhou'))
        self.assertNotIn('interno', result['message'])


class ReportTests(Base):
    def test_report_one_line_per_package_without_user_paths(self):
        fake = FakeWinget(before=['Git.Git'], installs=['Valve.Steam'],
                          import_output='[Mozilla.Firefox] No package found matching input criteria.')
        state_before = self.state / 'antigo.txt'
        self.state.mkdir(parents=True)
        state_before.write_text('mantido', encoding='utf-8')
        result = self.run_install(fake, ['Git.Git', 'Valve.Steam', 'Mozilla.Firefox'])
        run_dir = Path(result['report_dir'])
        text = (run_dir / 'relatorio.txt').read_text(encoding='utf-8')
        data = json.loads((run_dir / 'relatorio.json').read_text(encoding='utf-8'))
        for pid in ('Git.Git', 'Valve.Steam', 'Mozilla.Firefox'):
            self.assertEqual(sum(1 for line in text.splitlines() if pid in line), 1, pid)
        self.assertEqual([p['id'] for p in data['pacotes']],
                         ['Valve.Steam', 'Mozilla.Firefox', 'Git.Git'])
        self.assertEqual({tuple(sorted(p)) for p in data['pacotes']},
                         {('explicacao', 'id', 'status')})
        for content in (text, json.dumps(data, ensure_ascii=False)):
            self.assertNotIn(str(Path.home()), content)
            self.assertNotIn(self.temp.name, content)
            self.assertNotIn(os.environ.get('USERNAME') or os.environ.get('USER') or '§', content)
        self.assertEqual(state_before.read_text(encoding='utf-8'), 'mantido')
        self.assertTrue((run_dir / 'importar.json').is_file())
        self.assertFalse([p for p in run_dir.iterdir() if '.tmp' in p.name])


class ExplainTests(unittest.TestCase):
    CASES = {
        'hash': ('Installer hash does not match; this cannot be overridden when running as admin',
                 'O hash do instalador não corresponde'),
        'encontrado': ('No package found matching input criteria.', 'Nenhum pacote encontrado'),
        'administrador': ('Access is denied. 0x80070005', 'Acesso negado: execute como administrador'),
        'já instalado': ('Found an existing package already installed.', 'O pacote já está instalado'),
    }

    def test_known_failures_in_english_and_portuguese(self):
        for expected, outputs in self.CASES.items():
            for output in outputs:
                with self.subTest(output=output):
                    text = wi.explain_failure('Git.Git', f'Found Git [Git.Git]\n{output}')
                    self.assertIn(expected, text.casefold())

    def test_specific_texts(self):
        self.assertIn('site oficial', wi.explain_failure('A.B', '[A.B] hash mismatch'))
        self.assertIn('não encontrado', wi.explain_failure('A.B', '[A.B] 0x8a150014'))
        admin = wi.explain_failure('A.B', '[A.B] requires administrator')
        self.assertIn('instale sozinho pelo site oficial', admin)
        self.assertIn('aceite o aviso do Windows', admin)

    def test_unknown_failure(self):
        text = wi.explain_failure('Git.Git', '[Git.Git] something odd happened')
        self.assertIn('Não deu para confirmar', text)
        self.assertIn('site oficial', text)
        self.assertEqual(wi.explain_failure('Git.Git', ''), text)

    def test_only_looks_between_this_id_and_next_selected(self):
        output = ('Found Git [Git.Git]\nInstalling...\n'
                  'Found Steam [Valve.Steam]\nInstaller hash does not match.')
        ids = ['Git.Git', 'Valve.Steam']
        self.assertIn('Não deu para confirmar', wi.explain_failure('Git.Git', output, ids))
        self.assertIn('hash', wi.explain_failure('Valve.Steam', output, ids))
        # ID que é prefixo de outro não pega o trecho do outro
        self.assertIn('Não deu para confirmar',
                      wi.explain_failure('Git.Git', '[Git.GitLFS] hash mismatch', ['Git.Git']))


class InstalledCheckTests(unittest.TestCase):
    def test_installed_requires_code_zero_and_id(self):
        self.assertTrue(wi.check_installed('Git.Git', lambda c: (0, 'Git  Git.Git  2.0'), 'winget'))
        self.assertFalse(wi.check_installed('Git.Git', lambda c: (1, 'Git  Git.Git  2.0'), 'winget'))
        self.assertFalse(wi.check_installed('Git.Git', lambda c: (0, 'nada aqui'), 'winget'))
        self.assertFalse(wi.check_installed('Git.Git', lambda c: (0, 'Git.GitLFS'), 'winget'))

    def test_invalid_id_and_errors_are_not_installed(self):
        self.assertFalse(wi.check_installed('--x', lambda c: (0, '--x'), 'winget'))

        def boom(cmd):
            raise OSError('x')
        self.assertFalse(wi.check_installed('Git.Git', boom, 'winget'))


class ProgramsListFixesTests(unittest.TestCase):
    """Ressalvas da PR #69 no winget_programs.py."""

    def setUp(self):
        for target in ('subprocess.run', 'subprocess.Popen'):
            p = mock.patch(target, side_effect=_forbidden)
            p.start()
            self.addCleanup(p.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'Backup-teste'
        self.folder.mkdir()
        (self.folder / 'manifest.json').write_bytes(b'{"status": "concluido"}')

    def save(self, ids, **kwargs):
        def runner(cmd):
            Path(cmd[cmd.index('--output') + 1]).write_text(json.dumps(_export_doc(ids)),
                                                            encoding='utf-8')
            return 0, ''
        return wp.save_export(self.folder, runner=runner, executable='winget', **kwargs)

    def test_load_permission_error_is_portuguese(self):
        self.save(['Git.Git'])
        with mock.patch('builtins.open', side_effect=PermissionError('negado')):
            with self.assertRaises(ValueError) as ctx:
                wp.load_export(self.folder)
        self.assertIn('Não foi possível ler a lista', str(ctx.exception))
        self.assertIn('não foram tocados', str(ctx.exception))

    def test_short_peripheral_terms_only_as_whole_segment(self):
        self.assertEqual(wp.categorize('Foo.Swarmify'), 'Outros')
        self.assertEqual(wp.categorize('X.Sonar'), 'Periféricos')
        self.assertEqual(wp.categorize('Foo.Razerish'), 'Outros')
        self.assertEqual(wp.categorize('Vendor.Razer-Cortex'), 'Periféricos')
        self.assertEqual(wp.categorize('SomeVendor.Corsair.iCUE5'), 'Periféricos')

    def test_missing_text_explains_old_backups(self):
        self.assertIn('anteriores a esta versão', wp.MISSING_TEXT)
        self.assertIn('site oficial', wp.MISSING_TEXT)

    def test_save_again_uses_new_numbered_folder(self):
        self.assertEqual(self.save(['Git.Git'])['status'], 'salvo')
        first = _snapshot(self.folder / 'programas-winget')
        result = self.save(['Git.Git', 'Valve.Steam'], new_folder=True)
        self.assertEqual(result['status'], 'salvo', result)
        self.assertTrue((self.folder / 'programas-winget-2' / 'winget-export.json').is_file())
        self.assertEqual(_snapshot(self.folder / 'programas-winget'), first)
        self.assertEqual([p['id'] for p in wp.load_export(self.folder)], ['Valve.Steam', 'Git.Git'])
        self.assertEqual(self.save(['Git.Git'], new_folder=True)['status'], 'salvo')
        self.assertTrue((self.folder / 'programas-winget-3').is_dir())

    def test_without_new_folder_still_refuses(self):
        self.save(['Git.Git'])
        result = self.save(['Valve.Steam'])
        self.assertEqual(result['status'], 'recusado')
        self.assertFalse((self.folder / 'programas-winget-2').exists())

    def test_load_picks_highest_valid_folder(self):
        self.save(['Git.Git'])
        self.save(['Valve.Steam'], new_folder=True)
        broken = self.folder / 'programas-winget-3'
        broken.mkdir()
        (broken / 'winget-export.json.parcial').write_bytes(b'{')
        self.assertEqual([p['id'] for p in wp.load_export(self.folder)], ['Valve.Steam'])
        (self.folder / 'programas-winget-2' / 'winget-export.json').write_bytes(b'{"Sources": []}')
        self.assertEqual([p['id'] for p in wp.load_export(self.folder)], ['Git.Git'])
        self.assertTrue(broken.is_dir())


class SourceWiringTests(unittest.TestCase):
    def test_only_winget_install_runs_import(self):
        for name in ('winget_programs.py', 'winget_programs_ui.py', 'app.py', 'restore_ui.py'):
            source = (ROOT / name).read_text(encoding='utf-8')
            with self.subTest(module=name):
                self.assertNotIn("'import', '--import-file'", source)
        ui = (ROOT / 'winget_programs_ui.py').read_text(encoding='utf-8')
        self.assertIn('run_install(', ui)
        self.assertIn('confirm_install(', ui)
        self.assertIn('As marcações valem só enquanto esta janela estiver aberta', ui)


try:
    import tkinter as tk
    from tkinter import ttk
    import winget_programs_ui as wui
except ImportError:  # Python sem Tk (ex.: servidor Linux): os testes de tela pulam.
    tk = ttk = wui = None

NO_DISPLAY = tk is None or (sys.platform != 'win32' and not os.environ.get('DISPLAY'))


@unittest.skipIf(NO_DISPLAY, 'Sem Tk ou sem tela gráfica')
class ConfirmWindowTests(Base):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def widgets(self, cls, widget):
        if isinstance(widget, cls):
            yield widget
        for child in widget.winfo_children():
            yield from self.widgets(cls, child)

    def test_confirmation_starts_disabled_and_cancel_is_default(self):
        win, state = wui.build_confirm(self.root, ['Git.Git', 'Valve.Steam'])
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, win)}
        install = buttons['Instalar 2 programa(s)']
        self.assertTrue(install.instate(['disabled']))
        self.assertEqual(str(buttons['Cancelar'].cget('default')), 'active')
        check = next(self.widgets(ttk.Checkbutton, win))
        self.assertIn('Entendi que estes programas serão baixados e instalados neste PC',
                      check.cget('text'))
        check.invoke()
        self.assertFalse(install.instate(['disabled']))
        buttons['Cancelar'].invoke()
        self.assertFalse(state['ok'])

    def test_cancel_never_calls_runner(self):
        fake = FakeWinget()
        save_folder = self.backup
        (save_folder / 'programas-winget' / 'winget-export.json').write_text(
            json.dumps(_export_doc(['Git.Git'])), encoding='utf-8')
        raw = (save_folder / 'programas-winget' / 'winget-export.json').read_bytes()
        (save_folder / 'programas-winget' / 'info.json').write_text(
            json.dumps({'sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
        dlg = wui.show_programs(self.root, save_folder, runner=fake, state_dir=self.state,
                                elevated_probe=_not_admin, confirm=lambda parent, ids: False)
        import time
        until = time.monotonic() + 5
        while not dlg.program_state['loaded'] and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        install = buttons['Instalar marcados…']
        self.assertTrue(install.instate(['disabled']))
        buttons['Marcar tudo'].invoke()
        self.assertFalse(install.instate(['disabled']))
        install.invoke()
        self.root.update()
        self.assertEqual(fake.calls, [])
        dlg.destroy()

    def _write_list(self, ids):
        sub = self.backup / 'programas-winget'
        (sub / 'winget-export.json').write_text(json.dumps(_export_doc(ids)), encoding='utf-8')
        raw = (sub / 'winget-export.json').read_bytes()
        (sub / 'info.json').write_text(json.dumps({'sha256': hashlib.sha256(raw).hexdigest()}),
                                       encoding='utf-8')

    def _pump(self, condition, seconds=5):
        import time
        until = time.monotonic() + seconds
        while not condition() and time.monotonic() < until:
            self.root.update()
            time.sleep(0.02)
        return condition()

    def test_install_locks_window_and_shows_results(self):
        import threading
        self._write_list(['Git.Git', 'Valve.Steam'])
        release = threading.Event()
        fake = FakeWinget(installs=['Git.Git'])

        def slow(cmd):
            if cmd[1] == 'import':
                release.wait(5)
            return fake(cmd)

        dlg = wui.show_programs(self.root, self.backup, runner=slow, state_dir=self.state,
                                elevated_probe=_not_admin, confirm=lambda parent, ids: True)
        self.assertTrue(self._pump(lambda: dlg.program_state['loaded']))
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        buttons['Marcar tudo'].invoke()
        with mock.patch.object(wui, 'run_install', wraps=wi.run_install) as spy, \
             mock.patch.object(wi, '_platform_is_windows', return_value=True), \
             mock.patch.object(wi, '_find_winget', return_value='winget'), \
             mock.patch.object(wui.messagebox, 'showinfo') as info:
            buttons['Instalar marcados…'].invoke()
            self.assertTrue(dlg.program_state['busy'])
            for text in ('Marcar tudo', 'Instalar marcados…', 'Fechar'):
                self.assertTrue(buttons[text].instate(['disabled']), text)
            handler = dlg.protocol('WM_DELETE_WINDOW')  # tratador próprio da janela
            self.assertTrue(handler)
            dlg.tk.call(handler)
            self.assertTrue(dlg.winfo_exists())
            self.assertIn('aguarde', info.call_args.args[1].casefold())
            release.set()
            self.assertTrue(self._pump(lambda: dlg.program_state['result'] is not None))
            self.assertEqual(spy.call_args.args[1], ['Valve.Steam', 'Git.Git'])
        result = dlg.program_state['result']
        self.assertEqual({r['id']: r['status'] for r in result['results']},
                         {'Git.Git': 'instalado', 'Valve.Steam': 'não instalado'})
        self.assertFalse(dlg.program_state['busy'])
        self.assertFalse(buttons['Fechar'].instate(['disabled']))
        dlg.destroy()

    def test_admin_keeps_install_disabled(self):
        self._write_list(['Git.Git'])
        fake = FakeWinget()
        dlg = wui.show_programs(self.root, self.backup, runner=fake, state_dir=self.state,
                                elevated_probe=_admin, confirm=lambda parent, ids: True)
        self.assertTrue(self._pump(lambda: dlg.program_state['loaded']))
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        buttons['Marcar tudo'].invoke()
        self.assertTrue(buttons['Instalar marcados…'].instate(['disabled']))
        buttons['Instalar marcados…'].invoke()
        self.assertEqual(fake.calls, [])
        dlg.destroy()

    def test_save_now_appears_when_missing_and_asks_first(self):
        (self.backup / 'programas-winget' / 'winget-export.json').write_bytes(b'{}')
        asked = []
        dlg = wui.show_programs(self.root, self.backup, runner=FakeWinget(), state_dir=self.state,
                                elevated_probe=_not_admin,
                                ask_save=lambda: asked.append(True) or False)
        self.assertTrue(self._pump(lambda: dlg.program_state['error'] is not None))
        buttons = {b.cget('text'): b for b in self.widgets(ttk.Button, dlg)}
        self.assertEqual(buttons['Salvar lista agora'].winfo_manager(), 'pack')
        before = _snapshot(self.backup)
        buttons['Salvar lista agora'].invoke()
        self.assertEqual(asked, [True])
        self.assertEqual(_snapshot(self.backup), before)
        self.assertIn('ANTES de formatar', wui.SAVE_NOW_QUESTION)
        dlg.destroy()


if __name__ == '__main__':
    unittest.main()
