"""FIX-P3-06-09: ao salvar, as escolhas de duas janelas abertas são juntadas
(junção em 3 vias, dentro de uma trava), em vez de a última apagar a outra.
Só arquivos sintéticos em TemporaryDirectory; nenhuma ferramenta real."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import choices_store
from choices_store import merge_choices, save_merged

ROOT = Path(__file__).resolve().parent.parent


def _doc(**kw):
    doc = {'choices': {}, 'format_disks': [], 'destination': 'D:/Backups',
           'catalog_choices': {}, 'auto_save_paths': [], 'approved_catalog_paths': {},
           'personal_paths': [], 'browser_keep_paths': [], 'browser_vaults': {},
           'retained_discoveries': {}, 'cleanup_candidates': [], 'catalog_snapshots': {}}
    doc.update(kw)
    return doc


def _lock_path(path: Path) -> Path:
    return path.with_name('.' + path.name + '.lock')


class MergeTests(unittest.TestCase):
    def test_two_windows_different_keys_both_kept(self):
        base = _doc()
        window_a = _doc(choices={'c:/fotos': 'keep'})
        window_b = _doc(choices={'c:/musicas': 'skip'})
        disk_after_a, _ = merge_choices(base, window_a, base)
        merged, conflicts = merge_choices(base, window_b, disk_after_a)
        self.assertEqual(merged['choices'], {'c:/fotos': 'keep', 'c:/musicas': 'skip'})
        self.assertEqual(conflicts, [])

    def test_conflict_keep_vs_skip_keeps(self):
        base = _doc(choices={'c:/jogo': 'pending'}, catalog_choices={'steam:1': 'pending'})
        disk = _doc(choices={'c:/jogo': 'keep'}, catalog_choices={'steam:1': 'keep'})
        mine = _doc(choices={'c:/jogo': 'skip'}, catalog_choices={'steam:1': 'skip'})
        merged, conflicts = merge_choices(base, mine, disk)
        self.assertEqual(merged['choices']['c:/jogo'], 'keep')
        self.assertEqual(merged['catalog_choices']['steam:1'], 'keep')
        self.assertEqual(len(conflicts), 2)
        # e o contrário: esta janela marcou keep, a outra skip
        merged, _ = merge_choices(base, disk, mine)
        self.assertEqual(merged['catalog_choices']['steam:1'], 'keep')

    def test_conflict_skip_vs_pending_is_pending(self):
        base = _doc(catalog_choices={'steam:1': 'keep'})
        disk = _doc(catalog_choices={'steam:1': 'pending'})
        mine = _doc(catalog_choices={'steam:1': 'skip'})
        merged, conflicts = merge_choices(base, mine, disk)
        self.assertEqual(merged['catalog_choices']['steam:1'], 'pending')
        self.assertEqual(conflicts, [('catalog_choices', 'steam:1')])
        merged, _ = merge_choices(base, disk, mine)
        self.assertEqual(merged['catalog_choices']['steam:1'], 'pending')

    def test_removal_never_wins_over_value_in_conflict(self):
        base = _doc(choices={'c:/a': 'skip'}, browser_vaults={'p': 'v1'})
        disk = _doc(choices={'c:/a': 'keep'}, browser_vaults={'p': 'v2'})
        mine = _doc()
        merged, conflicts = merge_choices(base, mine, disk)
        self.assertEqual(merged['choices'], {'c:/a': 'keep'})
        self.assertEqual(merged['browser_vaults'], {'p': 'v2'})
        self.assertEqual(len(conflicts), 2)

    def test_plain_map_conflict_two_values_mine_wins(self):
        base = _doc(approved_catalog_paths={'k': ['a']})
        disk = _doc(approved_catalog_paths={'k': ['b']})
        mine = _doc(approved_catalog_paths={'k': ['c']})
        merged, _ = merge_choices(base, mine, disk)
        self.assertEqual(merged['approved_catalog_paths'], {'k': ['c']})

    def test_unchanged_key_follows_disk(self):
        base = _doc(choices={'c:/a': 'skip'})
        disk = _doc(choices={'c:/a': 'keep', 'c:/b': 'keep'})
        merged, conflicts = merge_choices(base, base, disk)
        self.assertEqual(merged['choices'], {'c:/a': 'keep', 'c:/b': 'keep'})
        self.assertEqual(conflicts, [])

    def test_list_addition_and_removal_from_two_windows(self):
        base = _doc(personal_paths=['c:/a', 'c:/b'])
        window_a = _doc(personal_paths=['c:/a', 'c:/b', 'c:/novo'])  # acrescentou
        window_b = _doc(personal_paths=['c:/a'])                    # tirou c:/b
        disk_after_a, _ = merge_choices(base, window_a, base)
        merged, _ = merge_choices(base, window_b, disk_after_a)
        self.assertEqual(merged['personal_paths'], ['c:/a', 'c:/novo'])

    def test_unknown_disk_key_preserved(self):
        disk = _doc(chave_futura={'x': 1})
        merged, _ = merge_choices(_doc(), _doc(choices={'c:/a': 'keep'}), disk)
        self.assertEqual(merged['chave_futura'], {'x': 1})

    def test_destination_only_changes_if_this_window_changed(self):
        base = _doc(destination='D:/A')
        disk = _doc(destination='E:/Outra')
        merged, _ = merge_choices(base, _doc(destination='D:/A'), disk)
        self.assertEqual(merged['destination'], 'E:/Outra')
        merged, _ = merge_choices(base, _doc(destination='F:/Minha'), disk)
        self.assertEqual(merged['destination'], 'F:/Minha')

    def test_format_disks_is_this_window_value(self):
        merged, _ = merge_choices(_doc(), _doc(format_disks=[]), _doc(format_disks=['C:']))
        self.assertEqual(merged['format_disks'], [])

    def test_inputs_not_mutated(self):
        base = _doc(choices={'c:/a': 'skip'})
        mine = _doc(choices={'c:/a': 'keep'})
        disk = _doc(choices={'c:/b': 'keep'})
        snapshot = json.dumps([base, mine, disk], sort_keys=True)
        merge_choices(base, mine, disk)
        self.assertEqual(json.dumps([base, mine, disk], sort_keys=True), snapshot)


class SaveMergedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.path = self.folder / 'preferencias.json'

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_missing_file_writes_everything(self):
        mine = _doc(choices={'c:/a': 'keep'})
        status, merged, conflicts = save_merged(self.path, mine, _doc(choices={'c:/a': 'keep'}))
        self.assertEqual(status, 'ok')
        self.assertEqual(self._read(), mine)
        self.assertFalse(_lock_path(self.path).exists())

    def test_two_windows_both_saved(self):
        base = _doc()
        self.assertEqual(save_merged(self.path, base, base)[0], 'ok')
        save_merged(self.path, _doc(choices={'c:/a': 'keep'}), base)
        save_merged(self.path, _doc(choices={'c:/b': 'skip'}), base)
        self.assertEqual(self._read()['choices'], {'c:/a': 'keep', 'c:/b': 'skip'})

    def test_broken_json_left_byte_for_byte(self):
        raw = b'{"choices": {"c:/a": "keep"'  # estragado
        self.path.write_bytes(raw)
        status, merged, _ = save_merged(self.path, _doc(choices={'c:/b': 'keep'}), _doc())
        self.assertEqual(status, 'ilegivel')
        self.assertIsNone(merged)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse(_lock_path(self.path).exists())

    def test_non_dict_left_intact(self):
        self.path.write_text('[1, 2]', encoding='utf-8')
        self.assertEqual(save_merged(self.path, _doc(), _doc())[0], 'ilegivel')
        self.assertEqual(self.path.read_text(encoding='utf-8'), '[1, 2]')

    def test_symlink_not_overwritten(self):
        target = self.folder / 'alvo.json'
        target.write_text('{}', encoding='utf-8')
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'sem links simbólicos: {exc}')
        self.assertEqual(save_merged(self.path, _doc(choices={'c:/a': 'keep'}), _doc())[0],
                         'ilegivel')
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(encoding='utf-8'), '{}')

    def test_recent_foreign_lock_busy_then_next_save_carries_diff(self):
        base = _doc()
        save_merged(self.path, base, base)
        before = self.path.read_bytes()
        lock = _lock_path(self.path)
        lock.write_text('outra janela', encoding='utf-8')
        first = _doc(choices={'c:/a': 'keep'})
        status, merged, _ = save_merged(self.path, first, base)
        self.assertEqual(status, 'ocupado')
        self.assertIsNone(merged)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(lock.read_text(encoding='utf-8'), 'outra janela')
        lock.unlink()  # a outra janela terminou
        # a base continua a mesma: a próxima gravação leva as duas mudanças
        second = _doc(choices={'c:/a': 'keep', 'c:/b': 'keep'})
        self.assertEqual(save_merged(self.path, second, base)[0], 'ok')
        self.assertEqual(self._read()['choices'], {'c:/a': 'keep', 'c:/b': 'keep'})

    def test_write_error_propagates_and_keeps_file(self):
        base = _doc()
        save_merged(self.path, base, base)
        before = self.path.read_bytes()
        with mock.patch.object(choices_store, 'atomic_write_text', side_effect=OSError('x')):
            with self.assertRaises(OSError):
                save_merged(self.path, _doc(choices={'c:/a': 'keep'}), base)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(_lock_path(self.path).exists())

    def test_two_threads_twenty_saves_each_no_loss(self):
        save_merged(self.path, _doc(), _doc())
        errors = []

        def window(prefix):
            base = _doc()
            mine = _doc()
            try:
                for index in range(20):
                    mine['choices'][f'c:/{prefix}/{index}'] = 'keep'
                    mine['personal_paths'].append(f'c:/{prefix}/{index}')
                    status, _, _ = save_merged(self.path, mine, base, lock_timeout=10)
                    if status != 'ok':
                        errors.append(status)
                        continue
                    base = json.loads(json.dumps(mine))
            except Exception as exc:  # pragma: no cover - falha do teste
                errors.append(exc)

        threads = [threading.Thread(target=window, args=(p,)) for p in ('a', 'b')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        data = self._read()
        self.assertEqual(len(data['choices']), 40)
        self.assertEqual(len(data['personal_paths']), 40)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [self.path.name])


class SaveChoicesSourceTests(unittest.TestCase):
    """Funciona sem Tk: app.py usa a junção e guarda a base desta janela."""

    def setUp(self):
        self.source = (ROOT / 'app.py').read_text(encoding='utf-8')

    def _body(self, name):
        start = self.source.index(f'def {name}(self')
        ends = [i for i in (self.source.find('\n    def ', start + 1),
                            self.source.find('\nif __name__', start + 1)) if i != -1]
        return self.source[start:min(ends)]

    def test_save_choices_uses_save_merged_and_keeps_own_doc_as_base(self):
        body = self._body('_save_choices')
        self.assertIn('choices_store.save_merged(self.local_state', body)
        self.assertIn('self._choices_base=mine', body)
        self.assertNotIn('atomic_write_text(self.local_state', body)

    def test_base_taken_after_rehydrate(self):
        init = self._body('__init__')
        self.assertLess(init.index('self._rehydrate_selected_catalog()'),
                        init.index('self._choices_base=self._choices_doc()'))

    def test_quit_question_text(self):
        self.assertIn('As últimas escolhas não foram salvas (outra janela está gravando). '
                      'Fechar mesmo assim?', self._body('_quit'))


class AppTkTests(unittest.TestCase):
    """Precisam do Tk (no Windows rodam; na nuvem sem Tk ficam como skip)."""

    def setUp(self):
        try:
            import app
        except ImportError as exc:  # nuvem Linux sem Tk
            self.skipTest(f'Tk indisponível: {exc}')
        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _fake(self, **extra):
        app = self.app
        fake = SimpleNamespace(
            local_state=self.folder / 'preferencias.json',
            choices={'C:/Jogos': 'keep'},
            format_vars={d: SimpleNamespace(get=lambda: False) for d in app.DISKS},
            dest=SimpleNamespace(get=lambda: 'D:'), catalog_choices={},
            auto_save_paths=set(), approved_catalog_paths={}, personal_paths=set(),
            browser_keep_paths=set(), browser_vaults={}, retained_discoveries={},
            cleanup_candidates=set(), catalog_items={})
        fake._choices_doc = lambda: app.App._choices_doc(fake)
        for key, value in extra.items():
            setattr(fake, key, value)
        return fake

    def test_save_choices_busy_returns_warning_and_keeps_base(self):
        fake = self._fake()
        base = fake._choices_doc()
        fake._choices_base = base
        _lock_path(fake.local_state).write_text('outra janela', encoding='utf-8')
        warning = self.app.App._save_choices(fake)
        self.assertIn('outra janela', warning)
        self.assertNotIn(str(self.folder), warning)
        self.assertIs(fake._choices_base, base)
        self.assertTrue(fake._choices_unsaved)

    def test_on_change_shows_warning_in_status_bar(self):
        messages = []
        fake = self._fake(plan=1, plan_stamp=1,
                          status=SimpleNamespace(set=messages.append),
                          _update_choices=lambda: None,
                          _refresh_home_metrics=lambda: None,
                          _save_choices=lambda: 'Aviso de teste')
        self.app.App._on_change(fake)
        self.assertIn('Aviso de teste', messages[-1])

    def test_quit_with_unsaved_choices_and_answer_no_keeps_window(self):
        destroyed = []
        fake = self._fake(deep_scan_running=False, busy=False,
                          optimizer_panel=SimpleNamespace(mon_running=False,
                                                          shutdown_capture=lambda: None),
                          _save_choices=lambda: 'ocupado',
                          _choices_unsaved=True,
                          destroy=lambda: destroyed.append(True))
        with mock.patch.object(self.app.messagebox, 'askyesno', return_value=False) as ask:
            self.app.App._quit(fake)
        self.assertEqual(destroyed, [])
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')


if __name__ == '__main__':
    unittest.main()
