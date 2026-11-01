"""Gravação atômica de texto (FIX-P3-06-07) e trava de arquivo (FIX-P3-06-08).

Módulo pequeno e sem dependências do app, para poder ser usado por qualquer
módulo sem criar importação circular.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from contextlib import contextmanager
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


@contextmanager
def exclusive_lock(path, timeout: float = 5.0, stale_after: float = 120.0):
    """Trava simples entre janelas/processos para gravar `path` (FIX-P3-06-08).

    Cria `.<nome>.lock` na mesma pasta com O_CREAT|O_EXCL (só um consegue) e
    tenta de novo a cada 50 ms até `timeout`; depois levanta TimeoutError. Uma
    trava cujo mtime é mais velho que `stale_after` segundos é sobra de uma
    janela que fechou no meio: é apagada e a criação é tentada de novo, sempre
    com O_EXCL. Trava recente de outro nunca é apagada. No fim (inclusive em
    erro) fecha e apaga só a própria trava, conferida por um código único
    gravado dentro dela.
    """
    path = Path(path)
    lock = path.with_name('.' + path.name + '.lock')
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - os.stat(lock).st_mtime
            except FileNotFoundError:
                continue  # a outra janela acabou de soltar: tenta já
            if age > stale_after:
                try:
                    os.unlink(lock)
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f'trava ocupada: {lock.name}')
            time.sleep(0.05)
    try:
        try:
            os.write(fd, token.encode('ascii'))
        finally:
            os.close(fd)
        yield lock
    finally:
        try:
            if lock.read_text(encoding='ascii', errors='replace') == token:
                os.unlink(lock)
        except FileNotFoundError:
            pass
