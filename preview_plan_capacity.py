"""Read-only size bridge from an existing, explicitly reviewed backup Plan.

No filesystem walk, stat, open, copy or disk operation. This ONLY reuses the
already-computed size of selected files, and fails closed if the reviewed Plan
does not cover every chosen source drive. It cannot include other programs,
vaults, games or saves absent from the Plan. Never proof of backup feasibility.
"""
from __future__ import annotations

import ntpath

from backup_capacity_input import GIB

MAX_BYTES = 1 << 63
MAX_FILES = 5_000_000


def _drive_of_source(value):
    if not isinstance(value, str) or not value:
        return None
    drive, _ = ntpath.splitdrive(value.strip())
    if len(drive) != 2 or drive[1] != ':' or not drive[0].isalpha():
        return None
    letter = drive[0].upper()
    return letter if 'A' <= letter <= 'Z' else None


def _sources(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 32:
        raise ValueError('Selecione as unidades de origem antes de usar a prévia.')
    letters = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError('Letra de origem inválida.')
        normalized = value.strip().upper().rstrip(':')
        if len(normalized) != 1 or not 'A' <= normalized <= 'Z':
            raise ValueError('Letra de origem inválida.')
        if normalized in letters:
            raise ValueError('Unidade de origem repetida.')
        letters.add(normalized)
    return letters


def reviewed_preview_capacity(plan, source_letters):
    """Get a conservative GiB input from in-memory FileTask metadata only.

    Raises ValueError rather than quietly reusing partial, stale or divergent
    totals. Rounds UP to the UI's 0.001 GiB precision to avoid understating
    size. All errors are generic and never include private source paths.
    """
    required = _sources(source_letters)
    if plan is None:
        raise ValueError('Gere uma prévia de preservação antes desta comparação.')
    warnings = getattr(plan, 'warnings', None)
    selected = getattr(plan, 'selected', None)
    files = getattr(plan, 'files', None)
    total = getattr(plan, 'total', None)
    if (not isinstance(warnings, list) or warnings
            or not isinstance(selected, list) or not selected
            or not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
            or type(total) is not int or not 0 < total <= MAX_BYTES):
        raise ValueError('Prévia ausente, vazia, incompleta ou com alertas de leitura.')

    # Check not just included files but every explicit keep-selection root.
    selected_drives = {_drive_of_source(path) for path in selected}
    if None in selected_drives or selected_drives != required:
        raise ValueError('A prévia não cobre exatamente as origens selecionadas.')

    found = set()
    drives_with_files = set()
    sum_bytes = 0
    for item in files:
        source = getattr(item, 'source', None)
        count = getattr(item, 'size', None)
        drive = _drive_of_source(source)
        if (drive not in required or type(count) is not int
                or not 0 <= count <= MAX_BYTES or not isinstance(source, str)):
            raise ValueError('A prévia contém arquivos ou tamanhos inválidos.')
        name_key = source.casefold()
        if name_key in found:
            raise ValueError('A prévia contém arquivos duplicados.')
        found.add(name_key)
        drives_with_files.add(drive)
        sum_bytes += count
        if sum_bytes > MAX_BYTES:
            raise ValueError('Tamanho da prévia fora do limite.')
    if sum_bytes != total or drives_with_files != required:
        raise ValueError('A prévia não representa integralmente as origens selecionadas.')

    # UI accepts at most three decimals in GiB. Never round DOWN.
    milli_gib = (sum_bytes * 1000 + GIB - 1) // GIB
    whole, fraction = divmod(milli_gib, 1000)
    if whole > 99_999_999:
        raise ValueError('Tamanho acima do limite aceito pela interface.')
    return {
        'size_text': f'{whole},{fraction:03d}',
        'reported_files': len(files),
        'plan_total_bytes': sum_bytes,
        'source_count': len(required),
    }
