"""Safe destination path checks for isolated backup writes.

Reject newly introduced junctions and symlinks in the destination ancestry.
This is not an atomic defense against privileged concurrent filesystem swaps.
"""
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
