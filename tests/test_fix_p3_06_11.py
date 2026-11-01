"""FIX-P3-06-11: avisos neutros e pergunta ao fechar (ressalvas da PR #169).

- O status 'ilegivel' junta causas diferentes (JSON estragado, link simbólico,
  erro de leitura de um arquivo bom preso por antivírus ou OneDrive). Por isso
  o aviso é neutro ("não pôde ser lido agora") e a orientação vale para todas
  as causas (regra R-37).
- A pergunta ao fechar diz claramente que as últimas escolhas se perdem.
- `_choices_last_warning` nasce como None no `__init__`; sem aviso guardado, a
  pergunta usa o texto de reserva.

Funciona sem Tk: `_save_choices` e `_quit` são lidos de app.py (ast) e rodam
com um objeto falso e um `messagebox` falso. Só arquivos sintéticos em
TemporaryDirectory; nenhuma ferramenta real.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import choices_store
from choices_store import save_merged

ROOT = Path(__file__).resolve().parent.parent

BUSY = 'Escolhas não salvas agora: outra janela está gravando. Serão salvas na próxima mudança.'
QUIT_TAIL = '\n\nSe fechar agora, essas últimas escolhas não serão salvas. Fechar mesmo assim?'
FALLBACK = 'As últimas escolhas não foram salvas.'


def unreadable(name):
    return (f'O arquivo {name} não pôde ser lido agora (pode estar danificado ou em uso) '
            'e não foi alterado. As escolhas desta janela não estão sendo salvas. Feche o '
            'app e abra de novo mais tarde; se o aviso continuar, peça ajuda ou renomeie '
            'esse arquivo para o app criar um novo.')


def _doc(**kw):
    doc = {'choices': {}, 'format_disks': [], 'destination': 'D:/Backups',
           'catalog_choices': {}, 'auto_save_paths': [], 'approved_catalog_paths': {},
           'personal_paths': [], 'browser_keep_paths': [], 'browser_vaults': {},
           'retained_discoveries': {}, 'cleanup_candidates': [], 'catalog_snapshots': {}}
    doc.update(kw)
    return doc


def _app_source():
    return (ROOT / 'app.py').read_text(encoding='utf-8')


def _app_class():
    tree = ast.parse(_app_source())
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == 'App')


def _app_methods(fake_messagebox):
    """Compila `_save_choices` e `_quit` de app.py sem importar o app (sem Tk)."""
    wanted = [node for node in _app_class().body
              if isinstance(node, ast.FunctionDef) and node.name in ('_save_choices', '_quit')]
    module = ast.Module(body=wanted, type_ignores=[])
    namespace = {'choices_store': choices_store, 'messagebox': fake_messagebox, 'json': json}
    exec(compile(module, str(ROOT / 'app.py'), 'exec'), namespace)
    return namespace['_save_choices'], namespace['_quit']


class NeutralUnreadableWarningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.path = self.folder / 'preferencias.json'
        self.save_choices, _ = _app_methods(SimpleNamespace())

    def tearDown(self):
        self._tmp.cleanup()

    def _fake(self, mine, base):
        return SimpleNamespace(local_state=self.path, _choices_base=base,
                               _choices_doc=lambda: json.loads(json.dumps(mine)))

    def _assert_neutral(self, warning, fake):
        self.assertEqual(warning, unreadable('preferencias.json'))
        self.assertNotIn('está danificado', warning)
        self.assertNotIn(str(self.folder), warning)
        self.assertTrue(fake._choices_unsaved)
        self.assertEqual(fake._choices_last_warning, warning)

    def test_broken_json_gets_neutral_warning(self):
        raw = b'{"choices": {"c:/a": "keep"'
        self.path.write_bytes(raw)
        fake = self._fake(_doc(choices={'c:/b': 'keep'}), _doc())
        self._assert_neutral(self.save_choices(fake), fake)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_symlink_gets_neutral_warning_and_is_not_overwritten(self):
        target = self.folder / 'alvo.json'
        target.write_text('{}', encoding='utf-8')
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'sem links simbólicos: {exc}')
        fake = self._fake(_doc(choices={'c:/a': 'keep'}), _doc())
        self._assert_neutral(self.save_choices(fake), fake)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(encoding='utf-8'), '{}')
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ['alvo.json', 'preferencias.json'])

    def _read_error(self, exc):
        good = json.dumps(_doc(choices={'c:/a': 'keep'})).encode('utf-8')
        self.path.write_bytes(good)
        real_read_text = Path.read_text
        target = self.path

        def fake_read_text(path_self, *args, **kwargs):
            if Path(path_self) == target:
                raise exc
            return real_read_text(path_self, *args, **kwargs)

        fake = self._fake(_doc(choices={'c:/b': 'skip'}), _doc())
        with mock.patch.object(Path, 'read_text', fake_read_text):
            self.assertEqual(save_merged(self.path, _doc(), _doc())[0], 'ilegivel')
            warning = self.save_choices(fake)
        self._assert_neutral(warning, fake)
        # o arquivo bom (só preso) fica intacto, sem temporário nem trava
        self.assertEqual(self.path.read_bytes(), good)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['preferencias.json'])

    def test_permission_error_gets_neutral_warning_and_file_untouched(self):
        self._read_error(PermissionError('preso pelo antivírus'))

    def test_os_error_gets_neutral_warning_and_file_untouched(self):
        self._read_error(OSError('nuvem ainda baixando'))


class QuitQuestionTests(unittest.TestCase):
    def _fake(self, save_result, unsaved, last_warning=None):
        destroyed = []
        fake = SimpleNamespace(
            deep_scan_running=False, busy=False,
            optimizer_panel=SimpleNamespace(mon_running=False, shutdown_capture=lambda: None),
            _choices_unsaved=unsaved, _choices_last_warning=last_warning,
            destroy=lambda: destroyed.append(True))
        fake._save_choices = lambda: save_result
        return fake, destroyed

    def _run(self, fake, answer):
        box = SimpleNamespace(askyesno=mock.Mock(return_value=answer),
                              showwarning=mock.Mock(), showerror=mock.Mock())
        _, quit_ = _app_methods(box)
        quit_(fake)
        return box.askyesno

    def test_question_says_last_choices_will_be_lost(self):
        fake, destroyed = self._fake(BUSY, True, BUSY)
        ask = self._run(fake, False)
        self.assertEqual(ask.call_args.args[1], BUSY + QUIT_TAIL)
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')
        self.assertEqual(destroyed, [])

    def test_unreadable_question_uses_neutral_text(self):
        text = unreadable('preferencias.json')
        fake, destroyed = self._fake(text, True, text)
        ask = self._run(fake, True)
        self.assertEqual(ask.call_args.args[1], text + QUIT_TAIL)
        self.assertEqual(destroyed, [True])

    def test_fallback_text_when_no_warning_kept(self):
        fake, destroyed = self._fake(None, True, None)
        ask = self._run(fake, False)
        self.assertEqual(ask.call_args.args[1], FALLBACK + QUIT_TAIL)
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')
        self.assertEqual(destroyed, [])


class InitTests(unittest.TestCase):
    def test_last_warning_starts_as_none_in_init(self):
        init = next(node for node in _app_class().body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
        found = [node for node in ast.walk(init)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Attribute)
                 and node.targets[0].attr == '_choices_last_warning'
                 and isinstance(node.targets[0].value, ast.Name)
                 and node.targets[0].value.id == 'self']
        self.assertEqual(len(found), 1)
        self.assertIsInstance(found[0].value, ast.Constant)
        self.assertIsNone(found[0].value.value)


if __name__ == '__main__':
    unittest.main()
