"""P2-09 fatia 3a: user authorization for the protected copy (pure logic).

The copy lock (``copy_authorized``) is True only when the person confirmed
(``user_confirmed is True``) a preview of the protected copy whose disk
check said the destinations are on separate physical disks. The answer is
tied to that exact preview by a SHA-256 fingerprint, lasts 5 minutes on a
monotonic clock and carries a one-time token. The executor consumes it right
before the first byte; a changed preview, an old answer or a reused token
means no copy.

This module only computes and compares values in memory: no window, no
external command, no disk query and no file is read or written. It does not
authorize formatting or installing anything.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time

PREVIEW_SCHEMA = 'pcro-multi-source-executor-preview-v1'
VALID_SECONDS = 5 * 60
NOT_AUTHORIZED = ('Cópia não autorizada: falta a sua confirmação, ou a prévia '
                  'não permite copiar. Nada foi gravado. Faça a prévia e '
                  'confirme de novo.')

# Tokens issued and not yet used: token -> (fingerprint, issued_at). Entries
# older than VALID_SECONDS are dropped whenever a new token is issued.
_ISSUED = {}
_LOCK = threading.Lock()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _canonical(preview):
    """Fields that define the preview. free_bytes and texto stay out."""
    if not isinstance(preview, dict):
        raise ValueError('Prévia inválida.')
    sources = preview['sources']
    if (not isinstance(sources, list)
            or not all(isinstance(item, str) for item in sources)):
        raise ValueError('Prévia inválida.')
    destinations = []
    for row in preview['destinations']:
        if not isinstance(row, dict):
            raise ValueError('Prévia inválida.')
        path, volume, resume = row['path'], row['volume'], row['resume']
        if (not isinstance(path, str) or not isinstance(resume, bool)
                or not (volume is None or isinstance(volume, str))):
            raise ValueError('Prévia inválida.')
        destinations.append({'path': path, 'volume': volume, 'resume': resume})
    check = preview['physical_check']
    numbers = [preview['files_per_copy'], preview['bytes_per_copy'],
               preview['copies']]
    if (not isinstance(check, dict) or not isinstance(check['veredito'], str)
            or not isinstance(preview['schema'], str)
            or not all(_is_int(value) for value in numbers)):
        raise ValueError('Prévia inválida.')
    return {
        'schema': preview['schema'],
        'sources': sources,
        'destinations': destinations,
        'files_per_copy': preview['files_per_copy'],
        'bytes_per_copy': preview['bytes_per_copy'],
        'copies': preview['copies'],
        'veredito': check['veredito'],
    }


def preview_fingerprint(preview):
    """SHA-256 of the preview in canonical JSON (ValueError if malformed)."""
    try:
        data = _canonical(preview)
    except (KeyError, TypeError) as error:
        raise ValueError('Prévia inválida.') from error
    text = json.dumps(data, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _refused():
    return {'copy_authorized': False, 'fingerprint': None, 'token': None,
            'emitida_em': None, 'motivo': NOT_AUTHORIZED}


def authorize_copy(preview, *, user_confirmed, clock=time.monotonic):
    """Turn the person's confirmation of this preview into an authorization.

    Any problem gives copy_authorized False, a generic reason and no path.
    """
    try:
        fingerprint = preview_fingerprint(preview)
        copies = preview['copies']
        veredito = preview['physical_check']['veredito']
        schema = preview['schema']
        copy_authorized = (user_confirmed is True
                           and schema == PREVIEW_SCHEMA
                           and _is_int(copies) and copies >= 1
                           and copies == len(preview['destinations'])
                           and veredito == 'independentes')
        if copy_authorized is not True:
            return _refused()
        issued_at = clock()
        if not isinstance(issued_at, (int, float)) or isinstance(issued_at, bool):
            return _refused()
        token = secrets.token_hex(32)
        with _LOCK:
            for old in [key for key, (_, when) in _ISSUED.items()
                        if not 0 <= issued_at - when <= VALID_SECONDS]:
                del _ISSUED[old]
            _ISSUED[token] = (fingerprint, issued_at)
    except Exception:  # noqa: BLE001 - any error means "not authorized"
        return _refused()
    return {'copy_authorized': copy_authorized, 'fingerprint': fingerprint,
            'token': token, 'emitida_em': issued_at, 'motivo': None}


def discard_authorization(auth):
    """Use up the token without copying (the executor refused earlier)."""
    try:
        token = auth.get('token') if isinstance(auth, dict) else None
        if isinstance(token, str):
            with _LOCK:
                _ISSUED.pop(token, None)
    except Exception:  # noqa: BLE001 - nothing to use up
        pass


def consume_authorization(auth, preview_atual, *, clock):
    """True only once, for a valid, unexpired authorization of this preview.

    A registered token is used up on every call that receives it, accepted
    or refused (lock not True, other preview, expired, forged fingerprint or
    time): after a refusal the person makes a new preview and confirms
    again. A missing or unregistered token has nothing to use up.
    """
    try:
        if not isinstance(auth, dict):
            return False
        token = auth.get('token')
        if not isinstance(token, str):
            return False
        with _LOCK:
            stored = _ISSUED.pop(token, None)
        if stored is None or auth.get('copy_authorized') is not True:
            return False
        fingerprint, issued_at = stored
        if auth.get('fingerprint') != fingerprint or auth.get('emitida_em') != issued_at:
            return False
        if preview_fingerprint(preview_atual) != fingerprint:
            return False
        now = clock()
        if not isinstance(now, (int, float)) or isinstance(now, bool):
            return False
        return 0 <= now - issued_at <= VALID_SECONDS
    except Exception:  # noqa: BLE001 - any error means "not authorized"
        return False
