"""Processos filhos do app, nos dois modos (pelo Python e no .exe do PyInstaller).

Sem tkinter: o processo filho não cria janela. No .exe, `sys.executable` é o
próprio programa, então o filho é o .exe com um argumento reservado. Esse
argumento é atendido no TOPO de `app.py`, antes de qualquer outro import
(tkinter, os módulos do app e a lista de unidades), para o filho não gastar o
tempo limite nem criar janela. Não mover esse atendimento de volta para o fim
de `app.py` (FIX-P4-03-01, fatia 2).
"""
from __future__ import annotations

import sys
from pathlib import Path

EXTENTS_FLAG = '--pcro-volume-extents'
# Texto quando o filho falha sem mensagem (FIX-P4-03-01, fatia 2): nunca "seguro".
EMPTY_CHILD_ERROR = ('Não foi possível consultar em que disco está cada volume; '
                     'trate como não confirmado.')


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
