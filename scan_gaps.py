"""Audit read-only scan gaps by volume, including snapshots from previous scans."""
from __future__ import annotations
from collections import Counter
from volume_paths import volume_of


def _entries(report, key, drive=None):
    for row in report.get(key, []) or []:
        if isinstance(row, dict):
            path = row.get('path', '')
            reason = row.get('reason') or row.get('error') or row.get('kind') or row.get('source') or 'Sem detalhe'
        else:
            path, reason = str(row), 'Sem detalhe'
        if drive is None or volume_of(path) == drive:
            yield {'kind': key, 'path': str(path), 'reason': str(reason), 'drive': volume_of(path)}


def report_by_drive(report, saved_by_drive=None):
    """Return all examined units with exact error/skipped paths and status.

    Entries without volume are kept in a separate bucket rather than hidden.
    """
    report = report or {}
    saved_by_drive = saved_by_drive or {}
    drives = sorted(set(report.get('scanned_drives', [])) | set(saved_by_drive) |
                    set(report.get('volume_stats', {})))
    output = {}
    for drive in drives:
        scoped = saved_by_drive.get(drive) or report
        errors = list(_entries(scoped, 'errors', drive))
        skipped = list(_entries(scoped, 'skipped', drive))
        output[drive] = {
            'drive': drive,
            'errors': errors, 'skipped': skipped,
            'errors_count': len(errors), 'skipped_count': len(skipped),
            'last_scanned_utc': scoped.get('last_scanned_utc') or
                                report.get('scan_dates_by_drive', {}).get(drive, ''),
            'status': scoped.get('status', report.get('status', 'não examinado')),
            'files_scanned': scoped.get('volume_stats', {}).get(drive, {}).get('files', 0),
            'is_partial': scoped.get('status') == 'cancelada_parcial',
        }
    # Preserve global/metadata errors in a separate category. Never count
    # them as disk failures if no physical volume can be associated.
    unassigned = [entry for kind in ('errors', 'skipped')
                  for entry in _entries(report, kind)
                  if entry['drive'] not in output]
    if unassigned:
        output['OUTROS'] = {
            'drive': 'OUTROS', 'errors': [e for e in unassigned if e['kind']=='errors'],
            'skipped': [e for e in unassigned if e['kind']=='skipped'],
            'errors_count': sum(e['kind']=='errors' for e in unassigned),
            'skipped_count': sum(e['kind']=='skipped' for e in unassigned),
            'last_scanned_utc': '', 'status': 'origem não atribuída',
            'files_scanned': 0, 'is_partial': False,
        }
    return output
