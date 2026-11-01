"""FIX-P3-06-10: avisos das escolhas entre duas janelas (ressalvas da PR #167).

- O aviso de conflito conta só as decisões do usuário (Manter / Não preservar)
  e diz onde ficou cada uma: no arquivo, a opção mais segura; nesta janela, a
  escolha dela.
- O aviso de arquivo danificado é claro e o app nunca conserta, apaga ou
  renomeia esse arquivo sozinho.
- Ao fechar com escolhas pendentes, a pergunta repete o último aviso.

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
from choices_store import decision_conflicts, save_merged

ROOT = Path(__file__).resolve().parent.parent

CONFLICT_ONE = ('Escolhas salvas junto com as de outra janela. Em 1 item(ns) as janelas '
                'discordavam: o arquivo guardou a opção mais segura, mas esta janela '
                'continua com as suas escolhas. Feche e abra o app para ver tudo junto.')
BUSY = 'Escolhas não salvas agora: outra janela está gravando. Serão salvas na próxima mudança.'


def _unreadable(name):
    return (f'O arquivo {name} está danificado e não foi alterado. As escolhas desta janela '
            'não estão sendo salvas. Feche o app e peça ajuda, ou renomeie esse arquivo '
            'para o app criar um novo.')


def _doc(**kw):
    doc = {'choices': {}, 'format_disks': [], 'destination': 'D:/Backups',
           'catalog_choices': {}, 'auto_save_paths': [], 'approved_catalog_paths': {},
           'personal_paths': [], 'browser_keep_paths': [], 'browser_vaults': {},
           'retained_discoveries': {}, 'cleanup_candidates': [], 'catalog_snapshots': {}}
    doc.update(kw)
    return doc


def _app_methods(fake_messagebox):
    """Compila `_save_choices` e `_quit` de app.py sem importar o app (sem Tk)."""
    source = (ROOT / 'app.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    app_class = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == 'App')
    wanted = [node for node in app_class.body
              if isinstance(node, ast.FunctionDef) and node.name in ('_save_choices', '_quit')]
    module = ast.Module(body=wanted, type_ignores=[])
    namespace = {'choices_store': choices_store, 'messagebox': fake_messagebox, 'json': json}
    exec(compile(module, str(ROOT / 'app.py'), 'exec'), namespace)
    return namespace['_save_choices'], namespace['_quit']


class DecisionConflictsTests(unittest.TestCase):
    def test_only_non_decision_conflicts_count_zero(self):
        conflicts = [('catalog_snapshots', 'steam:1'), ('browser_vaults', 'c:/perfil')]
        self.assertEqual(decision_conflicts(conflicts), [])
        self.assertEqual(len(decision_conflicts(conflicts)), 0)

    def test_choices_and_catalog_choices_count_two(self):
        conflicts = [('choices', 'c:/jogo'), ('catalog_snapshots', 'steam:1'),
                     ('catalog_choices', 'steam:1'), ('approved_catalog_paths', 'k')]
        self.assertEqual(decision_conflicts(conflicts),
                         [('choices', 'c:/jogo'), ('catalog_choices', 'steam:1')])
        self.assertEqual(len(decision_conflicts(conflicts)), 2)

    def test_empty_and_odd_entries(self):
        self.assertEqual(decision_conflicts([]), [])
        self.assertEqual(decision_conflicts(None), [])
        self.assertEqual(decision_conflicts(['choices', ('choices',)]), [])


class SaveChoicesWarningTests(unittest.TestCase):
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

    def test_conflict_keep_vs_skip_warning_text(self):
        base = _doc(choices={'c:/jogo': 'pending'})
        save_merged(self.path, _doc(choices={'c:/jogo': 'keep'}), base)  # outra janela
        fake = self._fake(_doc(choices={'c:/jogo': 'skip'}), base)
        warning = self.save_choices(fake)
        self.assertEqual(warning, CONFLICT_ONE)
        self.assertNotIn('ficou a opção mais segura', warning)
        self.assertFalse(fake._choices_unsaved)
        self.assertIsNone(fake._choices_last_warning)
        # no arquivo ficou a opção mais segura; a janela continua com a dela
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data['choices']['c:/jogo'], 'keep')

    def test_conflict_only_in_catalog_snapshots_returns_none(self):
        base = _doc(catalog_snapshots={'steam:1': {'name': 'A'}})
        save_merged(self.path, _doc(catalog_snapshots={'steam:1': {'name': 'B'}}), base)
        fake = self._fake(_doc(catalog_snapshots={'steam:1': {'name': 'C'}}), base)
        self.assertIsNone(self.save_choices(fake))
        self.assertFalse(fake._choices_unsaved)

    def test_unreadable_file_warning_and_file_untouched(self):
        raw = b'{"choices": {"c:/a": "keep"'
        self.path.write_bytes(raw)
        fake = self._fake(_doc(choices={'c:/b': 'keep'}), _doc())
        warning = self.save_choices(fake)
        self.assertEqual(warning, _unreadable('preferencias.json'))
        self.assertNotIn(str(self.folder), warning)
        self.assertTrue(fake._choices_unsaved)
        self.assertEqual(fake._choices_last_warning, warning)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['preferencias.json'])

    def test_replace_failure_warning_and_old_file_kept(self):
        base = _doc()
        save_merged(self.path, base, base)
        before = self.path.read_bytes()
        fake = self._fake(_doc(choices={'c:/a': 'keep'}), base)
        with mock.patch('os.replace', side_effect=OSError('travado')):
            warning = self.save_choices(fake)
        self.assertEqual(warning, 'Não foi possível salvar as escolhas em preferencias.json '
                                  'agora. Elas serão salvas na próxima mudança.')
        self.assertTrue(fake._choices_unsaved)
        self.assertEqual(fake._choices_last_warning, warning)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['preferencias.json'])

    def test_busy_warning_then_success_clears_last_warning(self):
        base = _doc()
        save_merged(self.path, base, base)
        lock = self.folder / '.preferencias.json.lock'
        lock.write_text('outra janela', encoding='utf-8')
        fake = self._fake(_doc(choices={'c:/a': 'keep'}), base)
        warning = self.save_choices(fake)
        self.assertEqual(warning, BUSY)
        self.assertTrue(fake._choices_unsaved)
        self.assertEqual(fake._choices_last_warning, BUSY)
        self.assertIs(fake._choices_base, base)
        lock.unlink()
        self.assertIsNone(self.save_choices(fake))
        self.assertFalse(fake._choices_unsaved)
        self.assertIsNone(fake._choices_last_warning)


class QuitTests(unittest.TestCase):
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

    def test_pending_and_yes_destroys(self):
        fake, destroyed = self._fake(BUSY, True, BUSY)
        ask = self._run(fake, True)
        self.assertEqual(destroyed, [True])
        self.assertEqual(ask.call_args.args[1], f'{BUSY}\n\nFechar mesmo assim?')
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')

    def test_pending_and_no_keeps_window(self):
        fake, destroyed = self._fake(BUSY, True, BUSY)
        ask = self._run(fake, False)
        self.assertEqual(destroyed, [])
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')

    def test_pending_unreadable_question_shows_its_text(self):
        text = _unreadable('preferencias.json')
        fake, destroyed = self._fake(text, True, text)
        ask = self._run(fake, False)
        self.assertEqual(ask.call_args.args[1], f'{text}\n\nFechar mesmo assim?')
        self.assertEqual(destroyed, [])

    def test_no_pending_closes_without_asking(self):
        fake, destroyed = self._fake(None, False)
        ask = self._run(fake, True)
        ask.assert_not_called()
        self.assertEqual(destroyed, [True])


if __name__ == '__main__':
    unittest.main()
