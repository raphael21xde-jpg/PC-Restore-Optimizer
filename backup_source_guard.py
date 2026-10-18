"""Defense-in-depth for opening backup sources using handle identity checks.

The caller must have already authorized the selection in its backup plan.
Metadata/path checks detect ordinary replacements but cannot make a Windows
filesystem pathname immune to all concurrent privileged namespace changes.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import stat

REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _is_reparse_info(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & REPARSE_FLAG)


def _identity(info):
    return (info.st_dev, info.st_ino)


def _source_ancestry(path):
    """Reject a link/junction on the complete path and record directory IDs."""
    entries = []
    for directory in reversed(path.parents):
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or _is_reparse_info(info):
            raise OSError('Origem contém pasta substituída por link/junção.')
        if not info.st_ino:
            raise OSError('Identidade da pasta de origem indisponível.')
        entries.append((str(directory), *_identity(info)))
    return tuple(entries)


def _verify_open_handle(path, handle, baseline, expected_size, expected_mtime_ns):
    opened = os.fstat(handle)
    current = os.lstat(path)
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
            or _is_reparse_info(current)):
        raise OSError('Origem não é arquivo comum ou virou link/junção.')
    if not opened.st_ino or not current.st_ino:
        raise OSError('Identidade do arquivo de origem indisponível.')
    if (_identity(opened) != _identity(baseline)
            or _identity(current) != _identity(baseline)):
        raise OSError('Arquivo de origem foi substituído durante a transferência.')
    if (opened.st_size != expected_size or current.st_size != expected_size
            or opened.st_mtime_ns != expected_mtime_ns
            or current.st_mtime_ns != expected_mtime_ns):
        raise OSError('Arquivo de origem mudou desde a prévia.')


@contextmanager
def open_verified_backup_source(source, expected_size, expected_mtime_ns):
    """Open a regular source without following a final symlink (where supported).

    Bind the opened handle to the pre-open file identity, then verify again
    when leaving the stream. On Windows, O_NOFOLLOW is not available, so
    the independent fstat/lstat identity comparison is mandatory.
    """
    path = Path(source).absolute()
    parents_before = _source_ancestry(path)
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or _is_reparse_info(before):
        raise OSError('Fonte não é arquivo regular ou contém link/junção.')
    if not before.st_ino:
        raise OSError('Identidade da origem indisponível.')
    if before.st_size != expected_size or before.st_mtime_ns != expected_mtime_ns:
        raise OSError('Arquivo de origem mudou desde a prévia.')

    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            _verify_open_handle(path, stream.fileno(), before,
                                expected_size, expected_mtime_ns)
            if _source_ancestry(path) != parents_before:
                raise OSError('Pasta de origem mudou durante a abertura.')
            yield stream
            _verify_open_handle(path, stream.fileno(), before,
                                expected_size, expected_mtime_ns)
            if _source_ancestry(path) != parents_before:
                raise OSError('Pasta de origem mudou durante a cópia.')
    finally:
        if fd is not None:
            os.close(fd)


def sha256_verified_backup_source(source, expected_size, expected_mtime_ns,
                                  cancelled=None, chunk_size=2 * 1024 * 1024):
    digest = hashlib.sha256()
    with open_verified_backup_source(source, expected_size, expected_mtime_ns) as stream:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError('Verificação de origem interrompida')
            data = stream.read(chunk_size)
            if not data:
                return digest.hexdigest()
            digest.update(data)
