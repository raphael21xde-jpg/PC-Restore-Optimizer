"""Open the recovery center with disposable synthetic data (Windows/Tk).

Usage from the repository root:
    py -3 scripts/demo_multi_source_recovery_center.py

The program writes only inside a TemporaryDirectory, never touches user's
real games/backups, never formats disks, and removes this demo data on exit.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import tempfile
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backup_core
from multi_source_fixture_runner import run_multi_source_fixture_backups
from multi_source_plan import prepare_multi_source_preview
from multi_source_recovery_center_ui import show_fixture_recovery_center
from multi_source_targets import preview_multi_source_targets
from transfer_engine import choose_strategy


def create_demo(root):
    """Build two fake sources and two copies, never using real drive letters."""
    root = Path(root).resolve(strict=True)
    source_a = root / 'origem_exemplo_A'
    source_b = root / 'origem_exemplo_B'
    backup_a = root / 'copia_exemplo_T'
    backup_b = root / 'copia_exemplo_U'
    restore = root / 'recuperacoes_exemplo'
    for folder in (source_a, source_b, backup_a, backup_b, restore):
        folder.mkdir()
    example = [source_a / 'documento-exemplo.txt',
               source_b / 'save-jogo-ficticio.sav']
    example[0].write_bytes(b'Documento de teste PCRO - sem dados pessoais')
    example[1].write_bytes(b'Save ficticio do jogo - nao e save real')
    plan = prepare_multi_source_preview(
        [str(x) for x in example], [str(source_a), str(source_b)])
    mapping = [(source_a, 'A:'), (source_b, 'B:'),
               (backup_a, 'T:'), (backup_b, 'U:')]

    def volume(value):
        path = Path(value)
        for folder, drive in mapping:
            if path == folder or folder in path.parents:
                return drive
        return 'SEM UNIDADE'

    def usage(_value):
        return SimpleNamespace(free=100 * 1024**3)

    preview = preview_multi_source_targets(
        plan, [str(backup_a), str(backup_b)],
        usage=usage, volume_lookup=volume)
    # Only these two tiny synthetic files are copied. Hardware strategy
    # detection is suppressed; all copies stay inside the sandbox.
    with patch.object(
        backup_core, 'choose_strategy',
        lambda src, dst, inventory=None:
            choose_strategy(src, dst, inventory={}),
    ):
        copies = run_multi_source_fixture_backups(
            plan, preview, test_root=str(root),
            usage=usage, volume_lookup=volume)
    if copies['status'] != 'all_local_copies_verified':
        raise RuntimeError('Não foi possível preparar as cópias fictícias.')
    return plan, copies, restore


def main():
    with tempfile.TemporaryDirectory(prefix='pcro-centro-demo-') as name:
        sandbox = Path(name).resolve()
        plan, copies, restore = create_demo(sandbox)
        root = tk.Tk()
        root.withdraw()
        try:
            dialog = show_fixture_recovery_center(
                root, plan, copies,
                test_root=str(sandbox), restore_parent=str(restore))
            root.wait_window(dialog)
        finally:
            root.destroy()
        print('Demo encerrada. Arquivos temporários de teste removidos.')


if __name__ == '__main__':
    main()
