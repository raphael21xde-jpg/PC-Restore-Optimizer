"""Windows volume inventory (read-only).

Use Windows volume GUIDs as identifiers; drive letters are *mount points*, not
persistent identities. This module NEVER selects targets for formatting,
deletion, installation, or backup. A snapshot is not backup verification.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ntpath
import os
import re
import uuid

MAX_VOLUMES = 4096
MAX_PATH_CHARS = 65536
ERROR_NO_MORE_FILES = 18
ERROR_MORE_DATA = 234
ERROR_INSUFFICIENT_BUFFER = 122
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

DRIVE_TYPES = {0: 'unknown', 1: 'not_ready', 2: 'removable',
               3: 'fixed', 4: 'network', 5: 'optical', 6: 'ramdisk'}
ELIGIBLE_TYPES = {'fixed', 'removable'}
GUID_PATTERN = re.compile(r'^\\\\\?\\Volume\{([0-9a-fA-F-]{36})\}\\$')
ROOT_PATTERN = re.compile(r'^[A-Za-z]:\\$')


def normalize_volume_id(value):
    """Canonical uppercase GUID, never accept arbitrary device or file paths."""
    match = GUID_PATTERN.fullmatch(str(value))
    if not match:
        raise ValueError('Identificador de volume inválido')
    return '\\\\?\\Volume{' + str(uuid.UUID(match.group(1))).upper() + '}\\'


def normalize_mount_point(value):
    """Allow local drive roots or absolute local folder mount points only."""
    raw = str(value)
    if '\x00' in raw or not raw.endswith(('\\', '/')):
        raise ValueError('Montagem inválida')
    raw = raw.replace('/', '\\')
    if not re.match(r'^[A-Za-z]:\\', raw):
        raise ValueError('Montagem não local')
    parts = raw[3:].split('\\')
    if any(p in ('.', '..') for p in parts):
        raise ValueError('Montagem com caminho relativo')
    canonical = ntpath.normpath(raw) + '\\'
    if ROOT_PATTERN.fullmatch(raw[:3]):
        canonical = ntpath.normpath(raw).rstrip('\\') + '\\'
    return canonical[0].upper() + canonical[1:]


def summarize_volumes(raw_volumes, errors=()):
    """Pure, testable policy: snapshot status never implies all files scanned."""
    issues = [str(e)[:250] for e in errors]
    found = {}
    for entry in raw_volumes:
        try:
            volume_id = normalize_volume_id(entry['volume_id'])
            mounts = sorted(set(normalize_mount_point(p) for p in entry.get('mount_points', ())), key=str.casefold)
            dtype = DRIVE_TYPES.get(entry.get('drive_type'), 'unknown')
        except (KeyError, TypeError, ValueError) as exc:
            issues.append('Volume ignorado: ' + str(exc))
            continue
        if volume_id in found:
            issues.append('Identificador duplicado: ' + volume_id)
            continue
        scannable = tuple(p for p in mounts if dtype in ELIGIBLE_TYPES)
        found[volume_id] = {
            'volume_id': volume_id,
            'mount_points': mounts,
            'drive_type': dtype,
            'scan_roots': list(scannable),
            'has_letter': any(ROOT_PATTERN.fullmatch(p) for p in mounts),
            'needs_manual_review': not scannable,
        }
    if not found:
        issues.append('Nenhum volume Windows foi identificado.')
    return {'schema': 'pcro-volume-inventory-v1',
            'status': 'ok' if not issues else 'partial',
            'volumes': sorted(found.values(), key=lambda x: x['volume_id']),
            'issues': issues,
            'notice': ('Metadados de montagem somente. Identificar um volume não comprova '
                       'a leitura de seus arquivos nem a segurança para backup ou formatação.')}


def letter_scan_roots(snapshot):
    """Compatibility with the current per-letter UI; never include network drives."""
    roots = {p for v in snapshot.get('volumes', ())
             for p in v.get('scan_roots', ()) if ROOT_PATTERN.fullmatch(p)}
    return sorted(roots, key=str.casefold)


class WindowsVolumeSource:
    """Thin Win32 read-only adapter. Enumeration works without administrator rights."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Inventário de volumes só está disponível no Windows')
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.FindFirstVolumeW.argtypes = [ctypes.POINTER(ctypes.c_wchar), wintypes.DWORD]
        k.FindFirstVolumeW.restype = wintypes.HANDLE
        k.FindNextVolumeW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar), wintypes.DWORD]
        k.FindNextVolumeW.restype = wintypes.BOOL
        k.FindVolumeClose.argtypes = [wintypes.HANDLE]
        k.FindVolumeClose.restype = wintypes.BOOL
        k.GetVolumePathNamesForVolumeNameW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_wchar),
                                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k.GetVolumePathNamesForVolumeNameW.restype = wintypes.BOOL
        k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        k.GetDriveTypeW.restype = wintypes.UINT
        self.kernel = k

    def volume_ids(self):
        ids = []
        buffer = ctypes.create_unicode_buffer(64)
        handle = self.kernel.FindFirstVolumeW(buffer, len(buffer))
        if handle == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            for _ in range(MAX_VOLUMES):
                ids.append(buffer.value)
                if not self.kernel.FindNextVolumeW(handle, buffer, len(buffer)):
                    error = ctypes.get_last_error()
                    if error != ERROR_NO_MORE_FILES:
                        raise ctypes.WinError(error)
                    return ids
            raise OSError('Limite de volumes atingido; inventário incompleto')
        finally:
            self.kernel.FindVolumeClose(handle)

    def mount_points(self, volume_id):
        size = 256
        while size <= MAX_PATH_CHARS:
            buffer = ctypes.create_unicode_buffer(size)
            required = wintypes.DWORD()
            if self.kernel.GetVolumePathNamesForVolumeNameW(volume_id, buffer, size, ctypes.byref(required)):
                return [path for path in buffer[:size].split('\x00') if path]
            error = ctypes.get_last_error()
            if error not in (ERROR_MORE_DATA, ERROR_INSUFFICIENT_BUFFER):
                raise ctypes.WinError(error)
            size = max(size * 2, int(required.value), size + 1)
        raise OSError('Muitos pontos de montagem; inventário incompleto')

    def drive_type(self, path):
        return int(self.kernel.GetDriveTypeW(path))


def collect_volume_inventory(source=None):
    """Return partial data and errors without inventing unobserved volumes."""
    if source is None and os.name != 'nt':
        return {'schema': 'pcro-volume-inventory-v1', 'status': 'unsupported',
                'volumes': [], 'issues': ['Inventário de volumes somente para Windows'],
                'notice': 'Nenhum disco foi consultado.'}
    try:
        source = source if source is not None else WindowsVolumeSource()
        ids = source.volume_ids()
    except (OSError, ValueError) as exc:
        return summarize_volumes([], [str(exc)])
    rows, errors = [], []
    for volume_id in ids:
        try:
            clean_id = normalize_volume_id(volume_id)
            mounts = source.mount_points(clean_id)
            dtype = source.drive_type(mounts[0] if mounts else clean_id)
            rows.append({'volume_id': clean_id, 'mount_points': mounts, 'drive_type': dtype})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append('Falha ao consultar ' + str(volume_id)[:80] + ': ' + str(exc)[:180])
    return summarize_volumes(rows, errors)
