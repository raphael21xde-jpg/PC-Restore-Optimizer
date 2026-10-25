"""FIX-P2-09-06: short reasons of the copy screen come from typed refusals.

Only fake disk inventories and synthetic files inside TemporaryDirectory.
No real disk, command, PowerShell, WMI or registry is used, and no tkinter.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_disks_p2_09 import CountingCollector, fake_inventory  # noqa: E402
from test_real_copy_flow_p2_09 import ORIGINAL_VALIDATE, Base  # noqa: E402

import backup_core  # noqa: E402
import copy_refusal as cr  # noqa: E402
import multi_source_executor as executor  # noqa: E402
import multi_source_recheck  # noqa: E402
import real_copy_flow as rcf  # noqa: E402
import selective_recovery  # noqa: E402

NOTHING = 'Nada foi gravado'

# Every message that was converted, with the short reason it already had
# through the text search. The typed path must give the very same reason.
CONVERTED = [
    (cr.KIND_CONFIRM, executor.REFUSED_CONFIRM, executor.REFUSED_CONFIRM),
    (cr.KIND_DISKS, executor.REFUSED_DISKS + '\nTexto do juiz.',
     executor.REFUSED_DISKS),
    (cr.KIND_UNIDADE, 'Destino precisa ser uma pasta existente.', rcf.MSG_UNIDADE),
    (cr.KIND_UNIDADE, 'Selecione uma pasta de destino existente e acessível.',
     rcf.MSG_UNIDADE),
    (cr.KIND_UNIDADE, 'Escolha uma pasta existente em unidade diferente de C:. '
     'Este fluxo preserva somente origens selecionadas no C:.', rcf.MSG_UNIDADE),
    (cr.KIND_RAIZ, executor.ROOT_REFUSED, rcf.MSG_RAIZ),
    (cr.KIND_LINK, 'Link/junção proibido no caminho: X', rcf.MSG_LINK),
    (cr.KIND_SOBREPOR, 'O destino não pode se sobrepor à origem.', rcf.MSG_SOBREPOR),
    (cr.KIND_SOBREPOR, 'A pasta de destino não pode se sobrepor à origem/backup.',
     rcf.MSG_SOBREPOR),
    (cr.KIND_MUDOU, 'Quantidade de destinos mudou após a revalidação.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Destino divergente após a revalidação.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Diagnóstico de discos alterado; refaça a prévia.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Fonte desapareceu ou tornou-se inacessível.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Fonte modificada depois do planejamento.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Unidades de origem mudaram desde a prévia.', rcf.MSG_MUDOU),
    (cr.KIND_MUDOU, 'Destino ou unidade mudou desde a prévia.', rcf.MSG_MUDOU),
]


class TypedRefusalTests(unittest.TestCase):
    def test_refusal_is_a_value_error_with_the_same_text(self):
        error = cr.CopyRefusal(cr.KIND_RAIZ, executor.ROOT_REFUSED)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(str(error), executor.ROOT_REFUSED)
        self.assertEqual(error.kind, cr.KIND_RAIZ)
        # FIX-P2-09-08 added KIND_ADMIN (a new refusal, not a converted text).
        self.assertEqual(set(cr.KINDS) - {cr.KIND_ADMIN},
                         {kind for kind, _, _ in CONVERTED})

    def test_each_kind_gives_the_same_short_reason_as_before(self):
        for kind, message, reason in CONVERTED:
            with self.subTest(message=message[:40]):
                self.assertEqual(rcf._reason(cr.CopyRefusal(kind, message)), reason)
                # Same answer the old text search gives for this message.
                self.assertEqual(rcf._reason(ValueError(message)), reason)

    def test_kind_wins_over_the_text(self):
        # The text alone would say "changed"; the kind decides.
        error = cr.CopyRefusal(cr.KIND_RAIZ, 'algo mudou')
        self.assertEqual(rcf._reason(error), rcf.MSG_RAIZ)

    def test_plain_value_error_still_uses_the_text_search(self):
        cases = {
            'Link/junção proibido no caminho: Z': rcf.MSG_LINK,
            'Fonte modificada depois do planejamento.': rcf.MSG_MUDOU,
            'O destino não pode se sobrepor à origem.': rcf.MSG_SOBREPOR,
            'Erro qualquer': rcf.MSG_PREVIA,
        }
        for message, reason in cases.items():
            with self.subTest(message=message):
                self.assertEqual(rcf._reason(ValueError(message)), reason)

    def test_unknown_kind_falls_back_without_error(self):
        for kind in ('desconhecido', None, 3, ['x']):
            with self.subTest(kind=kind):
                self.assertEqual(rcf._reason(cr.CopyRefusal(kind, 'Erro qualquer')),
                                 rcf.MSG_PREVIA)
                self.assertEqual(
                    rcf._reason(cr.CopyRefusal(kind, 'Fonte modificada.')),
                    rcf.MSG_MUDOU)
        # A non-ValueError with a "kind" attribute is still unexpected.
        error = RuntimeError('x')
        error.kind = cr.KIND_RAIZ
        self.assertEqual(rcf._reason(error), rcf.MSG_INESPERADO)


class ExecutorRaisesTypedTests(Base):
    def refusal(self, *, preview=None, wrap=True, collector=None):
        validate = (ORIGINAL_VALIDATE if not wrap else
                    lambda destination, **kw: ORIGINAL_VALIDATE(
                        destination, **dict(kw, test_root=str(self.root))))
        with patch.object(executor, 'validate_target', validate), \
                self.assertRaises(cr.CopyRefusal) as caught:
            executor.preview_real_execution(
                self.plan, preview or self.preview(), **self.kwargs(collector))
        return caught.exception

    def test_preview_refusals_carry_the_right_kind(self):
        root = self.preview()
        root['destinations'][0]['path'] = self.root.anchor
        inside = self.folders['source_A'] / 'dentro'
        inside.mkdir()
        overlap = self.preview()
        overlap['destinations'][0]['path'] = str(inside)
        a_file = self.root / 'arquivo.txt'
        a_file.write_bytes(b'x')
        not_folder = self.preview()
        not_folder['destinations'][0]['path'] = str(a_file)
        cases = [
            ('raiz', dict(preview=root), cr.KIND_RAIZ),
            ('sobrepor', dict(preview=overlap), cr.KIND_SOBREPOR),
            ('não é pasta', dict(preview=not_folder), cr.KIND_UNIDADE),
        ]
        for label, extra, kind in cases:
            with self.subTest(label):
                self.assertEqual(self.refusal(**extra).kind, kind)
        # Without the wrapper the target counts as C: (or not Windows).
        with patch.object(selective_recovery, 'volume_of', return_value='C:'):
            self.assertEqual(self.refusal(wrap=False).kind, cr.KIND_UNIDADE)
        self.assertNothingWritten()

    def test_link_in_the_path_is_typed(self):
        link = self.root / 'atalho'
        try:
            link.symlink_to(self.folders['target_T'], target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('links simbólicos indisponíveis aqui')
        preview = self.preview()
        preview['destinations'][0]['path'] = str(link / 'sub')
        (self.folders['target_T'] / 'sub').mkdir()
        error = self.refusal(preview=preview)
        self.assertEqual(error.kind, cr.KIND_LINK)
        self.assertEqual(rcf._reason(error), rcf.MSG_LINK)

    def test_changed_source_is_typed(self):
        preview = self.preview()
        self.first.write_bytes(b'mudou' * 999)
        self.state = self.source_state()
        error = self.refusal(preview=preview)
        self.assertEqual(error.kind, cr.KIND_MUDOU)
        self.assertEqual(rcf._reason(error), rcf.MSG_MUDOU)

    def test_recheck_raises_typed_changes(self):
        preview = self.preview()
        preview['source_volumes'] = ['Q:']
        with self.assertRaises(cr.CopyRefusal) as caught:
            multi_source_recheck.recheck_multi_source_preview(
                self.plan, preview, volume_lookup=self.volume, usage=self.usage)
        self.assertEqual(caught.exception.kind, cr.KIND_MUDOU)

    def test_copy_refusals_disks_and_confirmation_are_typed(self):
        self.allow_temp_target()
        same = fake_inventory({'C': 0, 'A': 1, 'B': 1, 'T': 1, 'U': 3})
        with self.assertRaises(cr.CopyRefusal) as caught:
            executor.run_real_copy(self.plan, self.preview(),
                                   **self.kwargs(CountingCollector(same)),
                                   authorization=None)
        self.assertEqual(caught.exception.kind, cr.KIND_DISKS)
        with self.assertRaises(cr.CopyRefusal) as caught:
            executor.run_real_copy(self.plan, self.preview(), **self.kwargs(),
                                   authorization=None)
        self.assertEqual(caught.exception.kind, cr.KIND_CONFIRM)
        self.assertEqual(str(caught.exception), executor.REFUSED_CONFIRM)
        self.assertNothingWritten()


class NothingWrittenPromiseTests(Base):
    """Review note of PR #108: "Nada foi gravado" only when it is true."""

    def test_refusals_before_the_executor_keep_the_promise(self):
        root = self.preview()
        root['destinations'][0]['path'] = self.root.anchor
        changed = self.preview()
        self.first.write_bytes(b'mudou' * 999)
        self.state = self.source_state()
        for label, preview in (('raiz', root), ('mudou', changed)):
            with self.subTest(label):
                flow = self.flow(preview=preview)
                flow.request_disk_check()
                self.assertEqual(flow.confirm_disk_check(True), rcf.RECUSADO)
                self.assertIs(flow.executor_called, False)
                self.assertIn(NOTHING, flow.message)
                self.assertClean(flow.message)
        # Copy without a confirmation: refused before the executor.
        flow = self.flow(preview=root)
        self.assertEqual(flow.run(), rcf.RECUSADO)
        self.assertIs(flow.executor_called, False)
        self.assertEqual(flow.message, executor.REFUSED_CONFIRM)
        self.assertIn(NOTHING, flow.message)
        self.assertNothingWritten()

    def confirmed_flow(self):
        self.allow_temp_target()
        flow = self.flow()
        flow.request_disk_check()
        self.assertEqual(flow.confirm_disk_check(True), rcf.PREVIA)
        self.assertEqual(flow.confirm_copy(True), rcf.CONFIRMADO)
        return flow

    def test_no_promise_after_something_was_written(self):
        original = backup_core.copy_backup
        errors = [FileNotFoundError('x'), NotADirectoryError('x'),
                  ValueError('Fonte modificada.'),
                  cr.CopyRefusal(cr.KIND_MUDOU, 'Fonte modificada.'),
                  cr.CopyRefusal(cr.KIND_CONFIRM, executor.REFUSED_CONFIRM),
                  RuntimeError('x'), KeyError('x')]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                calls = []

                def fake_copy(plan, target, *args, _error=error, **kwargs):
                    # First destination really copied; the second one writes
                    # a file and then fails.
                    calls.append(target)
                    if len(calls) == 1:
                        return original(plan, target, *args, **kwargs)
                    (Path(target) / 'parcial.bin').write_bytes(b'x')
                    raise _error

                flow = self.confirmed_flow()
                with patch.object(backup_core, 'copy_backup', fake_copy):
                    state = flow.run()
                self.assertIs(flow.executor_called, True)
                self.assertIn(state, (rcf.INCOMPLETO, rcf.RECUSADO))
                self.assertNotIn(NOTHING, flow.message or '')
                self.assertNotIn(NOTHING, rcf.cancel_text(flow))
                for name in ('target_T', 'target_U'):
                    for item in list(self.folders[name].iterdir()):
                        _remove(item)

    def test_recheck_failing_after_first_copy_makes_no_promise(self):
        flow = self.confirmed_flow()
        original = multi_source_recheck.recheck_multi_source_preview
        calls = []

        def fake_recheck(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise cr.CopyRefusal(cr.KIND_MUDOU, 'Fonte modificada.')
            return original(*args, **kwargs)

        with patch.object(executor, 'recheck_multi_source_preview', fake_recheck):
            self.assertEqual(flow.run(), rcf.INCOMPLETO)
        self.assertNotIn(NOTHING, flow.message)
        self.assertEqual(flow.result['copies_verified'], 1)


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            _remove(child)
        path.rmdir()
    else:
        path.unlink()


if __name__ == '__main__':
    unittest.main()
