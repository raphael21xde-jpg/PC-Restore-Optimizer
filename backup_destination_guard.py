"""Safe destination path checks for isolated backup writes.

Reject newly introduced junctions and symlinks in the destination ancestry.
This is not an atomic defense against privileged concurrent filesystem swaps.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import stat
from backup_core import is_reparse


def validate_backup_destination_path(folder, destination):
    base = Path(folder)
    target = Path(destination)
    if not base.is_absolute() or not target.is_absolute():
        raise ValueError('Destino deve ser absoluto.')
    try:
        rel = target.relative_to(base)
    except ValueError as exc:
        raise ValueError('Destino fora da pasta autorizada.') from exc
    if not rel.parts or any(part in ('.', '..') for part in rel.parts):
        raise ValueError('Destino inválido.')
    # Check only the authorized ancestry and target, including ancestors of base.
    # Broken links must also be rejected; pathlib.exists() follows links.
    for path in (base, *base.parents, target, *target.parents):
        if is_reparse(path):
            raise ValueError('Link ou junção detectado no destino.')
    if os.path.lexists(target) and not target.is_file():
        raise ValueError('Destino ocupado por item incompatível.')
    return target


def destination_ancestry_identity(folder, destination):
    """Capture directory identities to detect ancestry swaps across a transfer.

    This is defense in depth, not an atomic guarantee against concurrent swaps.
    """
    target = validate_backup_destination_path(folder, destination)
    base = Path(folder)
    parts = [base]
    current = base
    for part in target.relative_to(base).parts[:-1]:
        current = current / part
        parts.append(current)
    identities = []
    for directory in parts:
        info = os.stat(directory, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or is_reparse(directory):
            raise ValueError('Ancestral do destino não é uma pasta segura.')
        identities.append((str(directory), info.st_dev, info.st_ino))
    return tuple(identities)


def require_unchanged_destination_ancestry(folder, destination, previous):
    current = destination_ancestry_identity(folder, destination)
    if current != previous:
        raise ValueError('Caminho do destino foi substituído durante a cópia.')


def _verified_temp_identity(temp_path, fd):
    """Ensure a newly created temporary file still names the opened handle."""
    by_handle = os.fstat(fd)
    by_name = os.lstat(temp_path)
    for item in (by_handle, by_name):
        if not stat.S_ISREG(item.st_mode) or not item.st_ino:
            raise OSError('Arquivo temporário não é regular ou não tem identidade verificável.')
        if stat.S_ISLNK(item.st_mode) or bool(
                getattr(item, 'st_file_attributes', 0) &
                getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise OSError('Arquivo temporário virou link/junção.')
    if ((by_handle.st_dev, by_handle.st_ino)
            != (by_name.st_dev, by_name.st_ino)):
        raise OSError('Arquivo temporário foi substituído durante a cópia.')


@contextmanager
def open_verified_backup_temp(folder, destination, temp_path, ancestry_before):
    """Create a private partial file, refusing destination swaps before and after IO.

    Best-effort identity checks cannot eliminate the final Windows pathname
    race; this helper is not authorization for production multi-disk writes.
    """
    temp_path = Path(temp_path)
    destination = Path(destination)
    if temp_path.parent != destination.parent or temp_path == destination:
        raise ValueError('Temporário não pertence à pasta do arquivo de destino.')
    if not temp_path.name.startswith(destination.name + '.partial-'):
        raise ValueError('Nome de arquivo temporário não autorizado.')
    require_unchanged_destination_ancestry(folder, destination, ancestry_before)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
             getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    fd = os.open(temp_path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            require_unchanged_destination_ancestry(folder, destination, ancestry_before)
            _verified_temp_identity(temp_path, stream.fileno())
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
            require_unchanged_destination_ancestry(folder, destination, ancestry_before)
            _verified_temp_identity(temp_path, stream.fileno())
    finally:
        if fd is not None:
            os.close(fd)


def safe_cleanup_backup_temp(folder, destination, temp_path, ancestry_before):
    """Avoid deleting a path when the authorized directory has been replaced."""
    try:
        require_unchanged_destination_ancestry(folder, destination, ancestry_before)
        info = os.lstat(temp_path)
        if (stat.S_ISREG(info.st_mode) and
                not stat.S_ISLNK(info.st_mode) and
                not bool(getattr(info, 'st_file_attributes', 0) &
                         getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))):
            Path(temp_path).unlink()
    except (OSError, ValueError):
        # Leaving a partial fixture is safer than deleting outside a swapped folder.
        return


def verify_committed_backup_file(folder, destination, ancestry_before,
                                 expected_size, expected_sha256, cancelled=None):
    """Bind a committed destination handle to its name, size and SHA-256.

    Fail closed before the manifest labels a copied file as verified. The
    parent directory identity is checked before and after the read, but
    pathname operations are not atomic on Windows.
    """
    from backup_source_guard import sha256_verified_backup_source

    require_unchanged_destination_ancestry(folder, destination, ancestry_before)
    info = os.lstat(destination)
    if (not stat.S_ISREG(info.st_mode) or not info.st_ino
            or is_reparse(destination) or info.st_size != expected_size):
        raise OSError('Arquivo de destino não é um arquivo comum íntegro.')
    checksum = sha256_verified_backup_source(
        destination, expected_size, info.st_mtime_ns, cancelled)
    require_unchanged_destination_ancestry(folder, destination, ancestry_before)
    if checksum != expected_sha256:
        raise OSError('SHA-256 do destino mudou após a gravação.')
    return checksum
