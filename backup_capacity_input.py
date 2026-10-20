"""Parse operator-entered backup size for a read-only capacity estimate.

The size is explicitly manual: this module does not scan files, copy data,
measure network drives, guarantee free space, or authorize storage actions.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import re

GIB = 1024 ** 3
# Keep input bounded; Brazilian decimal commas and dot decimals are accepted.
_ESTIMATE = re.compile(r'(?:0|[1-9][0-9]{0,7})(?:[,.][0-9]{1,3})?\Z')


def parse_estimated_backup_gib(text):
    """Convert a manual positive GiB estimate to integer bytes, rounding up.

    Blank means the size was not supplied, NOT a zero-byte backup.
    Raises ValueError before any hardware query for malformed estimates.
    """
    if not isinstance(text, str):
        raise ValueError('Estimativa de backup inválida.')
    cleaned = text.strip()
    if cleaned == '':
        return None
    if len(cleaned) > 16 or not _ESTIMATE.fullmatch(cleaned):
        raise ValueError('Use um número positivo em GiB (ex.: 120 ou 1,5).')
    estimated = Decimal(cleaned.replace(',', '.'))
    if not estimated.is_finite() or estimated <= 0:
        raise ValueError('O tamanho planejado deve ser maior que zero.')
    return int((estimated * GIB).to_integral_value(rounding=ROUND_CEILING))
