"""P2-09 slice 2b: bridge between a NEW disk inventory and the physical judge.

``verify_physical_independence`` asks the given collector for one fresh
inventory, runs the read-only safety inspection
(``drive_safety_report.inspect_fresh_drive_safety``) and the pure judge
(``physical_disk_check.judge_physical_disks``) on that same snapshot, and
returns the verdict with a plain-Portuguese text.

This module has no Tk, runs no command of its own and writes nothing. The
collector is required (no default), so every caller decides explicitly
where the inventory comes from; tests pass a fake one. The answer is
``physical_independence_verified = False`` unless the judge says
'independentes' for exactly the drive letters that were asked for, on an
inventory collected right now. Any error or doubt gives False. It never
touches the other safety locks and never authorizes copying, formatting or
installing anything.
"""
from __future__ import annotations

import copy
import re

from drive_safety_report import inspect_fresh_drive_safety
from physical_disk_check import (DOUBT, INDEPENDENT, MSG_READ_ONLY,
                                 format_verdict_pt, judge_physical_disks)

# Re-exported so the executor can leave this line out of its own report.
READ_ONLY_NOTE = MSG_READ_ONLY

MSG_ERROR = ('Não foi possível conferir os discos agora. Por segurança, '
             'nada foi considerado separado.')
MSG_LETTERS = ('As unidades conferidas não são exatamente as unidades '
               'pedidas. Por segurança, nada foi considerado separado.')

FALLBACK_TEXT = ('Não deu para confirmar que os discos são separados.\n'
                 'Por segurança, escolha um destino em outro disco ou '
                 'confira os discos antes de copiar.')

_LETTER = re.compile(r'[A-Za-z]:?\Z')
MAX_LETTERS = 32


def _letters(values):
    """Normalize to ['X:', ...]; None when malformed or repeated."""
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_LETTERS:
        return None
    result = []
    for item in values:
        if not isinstance(item, str) or not _LETTER.fullmatch(item.strip()):
            return None
        letter = item.strip()[0].upper() + ':'
        if letter in result:
            return None
        result.append(letter)
    return result


def _refused(reason):
    """Generic 'not verified' answer: no path, serial number or model."""
    try:
        texto = format_verdict_pt(
            {'veredito': DOUBT, 'motivos': [reason], 'destinos': []})
    except Exception:  # noqa: BLE001 - the refusal itself must never fail
        texto = FALLBACK_TEXT
    return {
        'physical_independence_verified': False,
        'veredito': DOUBT,
        'destinos': [],
        'texto': texto,
    }


def _reported_letters(rows):
    if not isinstance(rows, list):
        return None
    letters = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        letters.append(row.get('letter', row.get('unidade')))
    return letters


def verify_physical_independence(source_letters, target_letters, *, collector):
    """Check, on a new inventory, that every target is on another disk.

    Returns ``{'physical_independence_verified', 'veredito', 'destinos',
    'texto'}``. Calls ``collector`` exactly once. Never raises.
    """
    try:
        sources = _letters(source_letters)
        targets = _letters(target_letters)
        if sources is None or targets is None:
            return _refused(MSG_LETTERS)
        snapshot = copy.deepcopy(collector())
        report = inspect_fresh_drive_safety(
            sources, targets, collector=lambda: snapshot)
        verdict = judge_physical_disks(report, snapshot['disks'])
        destinos = verdict.get('destinos')
        letters_match = (
            _reported_letters(report.get('source_volumes')) == sources and
            _reported_letters(report.get('destinations')) == targets and
            _reported_letters(destinos) == targets)
        # The only place where the answer can become positive.
        verified = (verdict.get('veredito') == INDEPENDENT and
                    report.get('inventory_status') == 'fresh_collected' and
                    letters_match)
        if not letters_match:
            return _refused(MSG_LETTERS)
        return {
            'physical_independence_verified': verified,
            'veredito': verdict['veredito'],
            'destinos': [dict(item) for item in destinos],
            'texto': format_verdict_pt(verdict),
        }
    except Exception:  # noqa: BLE001 - any failure means "not verified"
        return _refused(MSG_ERROR)
