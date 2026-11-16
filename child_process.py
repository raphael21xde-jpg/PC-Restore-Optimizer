"""Processos filhos do app, nos dois modos (pelo Python e no .exe do PyInstaller).

Sem tkinter: o processo filho não cria janela. No .exe, `sys.executable` é o
próprio programa, então o filho é o .exe com um argumento reservado, que o
`__main__` de `app.py` atende antes de criar qualquer janela.
"""
from __future__ import annotations

import sys
from pathlib import Path

EXTENTS_FLAG = '--pcro-volume-extents'


def extents_command(*, frozen: bool | None = None, executable: str | None = None,
                    source_file: str | None = None) -> list[str]:
    """Comando da consulta somente leitura de extensões de volume (`volume_extents`)."""
    is_frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else bool(frozen)
    exe = sys.executable if executable is None else executable
    if is_frozen:
        return [exe, EXTENTS_FLAG]
    helper = Path(source_file or __file__).resolve().with_name('volume_extents.py')
    return [exe, str(helper)]


def dispatch_child(argv) -> int | None:
    """Atende só o argumento exato `--pcro-volume-extents`; qualquer outro devolve None."""
    if list(argv) != [EXTENTS_FLAG]:
        return None
    try:
        import volume_extents
        return volume_extents.run_child(sys.stdin, sys.stdout)
    except Exception as exc:  # nunca deixar o .exe sem console abrir janela de erro
        # Só o tipo do erro: sem mensagem, para não vazar caminhos nem dados.
        if sys.stderr is not None:
            try:
                sys.stderr.write('Erro no processo filho: ' + type(exc).__name__)
            except Exception:
                pass
        return 1
