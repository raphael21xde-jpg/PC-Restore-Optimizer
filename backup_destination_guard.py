"""Safe destination path checks for isolated backup writes.

Reject newly introduced junctions and symlinks in the destination ancestry.
This is not an atomic defense against privileged concurrent filesystem swaps.
"""
from pathlib import Path
import os
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
    for path in (base, *base.parents, target, *target.parents):
        if is_reparse(path):
            raise ValueError('Link ou junção detectado no destino.')
    if os.path.lexists(target) and not target.is_file():
        raise ValueError('Destino ocupado por item incompatível.')
    return target
