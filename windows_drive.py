"""P2-11: qual é a unidade (letra) do Windows, conferida em duas variáveis.

Usa só variáveis de ambiente: a unidade de %SystemRoot% (ou %windir%) tem de
ser a mesma de %SystemDrive%. Se faltar alguma ou se elas discordarem, devolve
None com um aviso, para a tela não marcar nada como "fora do disco do Windows"
sem ter certeza.

Sem imports do projeto e sem tocar no disco: só lê o dicionário de ambiente.
"""
from __future__ import annotations

import ntpath
import os
import re

WARNING = ('Não deu para confirmar qual é o disco do Windows. Confira você mesmo em qual '
           'disco cada pasta está.')
_LETTER = re.compile(r'^[A-Za-z]:$')


def _get(environ, name):
    """Busca sem diferenciar maiúsculas (no Windows o ambiente é assim)."""
    value = environ.get(name)
    if value:
        return value
    wanted = name.casefold()
    for key, value in environ.items():
        if str(key).casefold() == wanted and value:
            return value
    return None


def _letter(text):
    if not text:
        return None
    drive = ntpath.splitdrive(str(text).strip())[0]
    if not _LETTER.match(drive):
        return None
    return drive.upper()


def windows_drive(environ=None):
    """(letra, aviso). Ex.: ('C:', '') ou (None, WARNING)."""
    environ = os.environ if environ is None else environ
    root = _letter(_get(environ, 'SystemRoot') or _get(environ, 'windir'))
    drive = _letter(_get(environ, 'SystemDrive'))
    if root is None or drive is None or root != drive:
        return None, WARNING
    return root, ''
