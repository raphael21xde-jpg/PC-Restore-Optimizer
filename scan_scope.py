"""Canonical, conservative root matching for selective filesystem discovery.

Root filtering applies to both traversed directories and *metadata anchors*;
no cross-drive discovery is permitted merely because the registry names an app.
"""
from __future__ import annotations
import ntpath
import os


def normalized(path):
    raw = str(path).replace('/', '\\')
    drive, _ = ntpath.splitdrive(raw)
    if drive and len(drive) == 2 and drive[1] == ':':
        return ntpath.normcase(ntpath.normpath(raw))
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def in_scope(path, roots):
    """Only an absolute path under one of the explicitly chosen roots qualifies."""
    if not path:
        return False
    value = normalized(path)
    raw = str(path)
    drive = ntpath.splitdrive(raw.replace('/', '\\'))[0]
    if drive and (len(drive) != 2 or not ntpath.isabs(raw.replace('/', '\\'))):
        return False
    for root in roots:
        base = normalized(root)
        if value == base or value.startswith(base.rstrip('\\/') + ('\\' if len(ntpath.splitdrive(base)[0]) == 2 else os.sep)):
            return True
    return False


def filter_report(report, roots):
    """Defense in depth: remove any stale/out-of-scope rows before rendering."""
    result = dict(report)
    for key in ('records', 'errors', 'skipped'):
        result[key] = [entry for entry in report.get(key, []) if in_scope(entry.get('path'), roots)]
    result['unassociated_executables'] = [p for p in report.get('unassociated_executables', []) if in_scope(p, roots)]
    result['volume_stats'] = {drive: counts for drive, counts in report.get('volume_stats', {}).items()
                              if any(in_scope(drive + '\\', [r]) for r in roots)}
    result['roots'] = list(map(str, roots))
    result['scan_scope_only'] = True
    return result
