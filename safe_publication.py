"""Exclusive publication of completed copies; never replace a new arrival.

Interrupted-job replacements retain the previous file as a uniquely named
recovery copy. Verification describes the file at the time it was checked,
not a guarantee against later writes by other processes.
"""
import os
from pathlib import Path
import stat
import uuid


def file_version(path):
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & 0x400):
        raise OSError('Destino não é um arquivo regular seguro.')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def move_exclusive(source, destination):
    if os.name == 'nt':
        # Windows rename fails atomically if the destination already exists.
        os.rename(source, destination)
    else:
        # link is an atomic create-if-absent on the same filesystem.
        # Fail closed on filesystems without hard-link support.
        os.link(source, destination, follow_symlinks=False)
        os.unlink(source)


def publish_copy(temporary, destination, previous=None):
    destination = Path(destination)
    if previous is not None:
        if file_version(destination) != previous:
            raise OSError('Destino mudou durante a cópia; arquivo concorrente preservado.')
        retained = destination.with_name(destination.name + '.retained-' + uuid.uuid4().hex)
        move_exclusive(destination, retained)
        if file_version(retained) != previous:
            try:
                move_exclusive(retained, destination)
            except OSError:
                pass  # Never overwrite a new arrival; retained copy stays intact.
            raise OSError(f'Destino mudou durante a publicação; cópia preservada: {retained}')
        try:
            move_exclusive(temporary, destination)
        except OSError:
            try:
                move_exclusive(retained, destination)
            except OSError:
                pass
            raise
    else:
        move_exclusive(temporary, destination)


def verify_published(path, expected_size, expected_hash, hash_file, cancelled=None):
    before = file_version(path)
    if (before is None or before[2] != expected_size or
            hash_file(path, cancelled).lower() != expected_hash.lower() or
            file_version(path) != before):
        raise OSError('Destino alterado; conferência SHA-256 final não aprovada.')
