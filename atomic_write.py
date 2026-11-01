"""Gravação atômica de texto (FIX-P3-06-07).

Módulo pequeno e sem dependências do app, para poder ser usado por qualquer
módulo sem criar importação circular.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path, text: str, encoding: str = 'utf-8') -> None:
    """Grava `text` em `path` sem deixar o arquivo pela metade.

    Usa um temporário de nome único na mesma pasta do destino (o os.replace
    fica no mesmo volume), com fsync antes de trocar. Se qualquer passo falhar,
    apaga só o temporário desta chamada e relança o erro original; nunca mexe
    em `.tmp` de outras gravações.
    """
    path = Path(path)
    stream = tempfile.NamedTemporaryFile('w', encoding=encoding, dir=path.parent,
                                         prefix='.' + path.name + '.', suffix='.tmp',
                                         delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
