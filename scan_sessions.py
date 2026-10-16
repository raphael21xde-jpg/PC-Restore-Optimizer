"""Read-only, per-volume scan snapshots and lossless session merge.

Scanning one set of drives replaces *only* their snapshots. Neither a scan nor
its cache modifies the decisions made in the preservation planner.
"""
from __future__ import annotations
from datetime import datetime, timezone
from scan_scope import filter_report
from volume_paths import volume_of, drive_root


def split_by_drive(report, drives=None):
    if not report or report.get('schema') != 'pcro-discovery-v1':
        return {}
    observed = {volume_of(r) for r in report.get('roots', [])}
    selected = drives if drives is not None else observed
    output = {}
    for drive in selected:
        if drive == 'SEM UNIDADE':
            continue
        scoped = filter_report(report, [drive_root(drive)])
        scoped['apps'] = [app for app in report.get('apps', [])
                          if app.get('id') in {r.get('app_id') for r in scoped['records']}]
        stats = scoped.get('volume_stats', {}).get(drive, {})
        scoped['directories'] = int(stats.get('directories', 0))
        scoped['files'] = int(stats.get('files', 0))
        scoped['roots'] = [r for r in report.get('roots', []) if volume_of(r) == drive]
        if not scoped['roots']:
            scoped['roots'] = [drive_root(drive)]
        scoped['last_scanned_utc'] = datetime.now(timezone.utc).isoformat()
        output[drive] = scoped
    return output


def merge_cache(cache, *, latest=()):
    """Render all scanned disks; leave their past selections untouched."""
    ordered = sorted(cache)
    reports = [cache[d] for d in ordered]
    combined = {'schema': 'pcro-discovery-v1', 'roots': [], 'excluded': [],
                'records': [], 'apps': [], 'errors': [], 'skipped': [],
                'unassociated_executables': [], 'volume_stats': {},
                'directories': 0, 'files': 0, 'elapsed_seconds': 0,
                'scanned_drives': ordered, 'latest_scanned_drives': list(latest),
                'scan_dates_by_drive': {}, 'scan_scope_only': True,
                'notice': 'Inventários por disco. Uma unidade em cache não foi reexaminada nesta sessão.'}
    seen_records = set()
    seen_apps = set()
    seen_unmatched = set()
    partial = False
    for drive, report in zip(ordered, reports):
        combined['roots'].extend(report.get('roots', [drive_root(drive)]))
        combined['excluded'].extend(report.get('excluded', []))
        combined['volume_stats'][drive] = report.get('volume_stats', {}).get(drive, {'directories': 0, 'files': 0})
        combined['directories'] += int(report.get('directories', 0))
        combined['files'] += int(report.get('files', 0))
        combined['elapsed_seconds'] += float(report.get('elapsed_seconds', 0))
        combined['errors'].extend(report.get('errors', []))
        combined['skipped'].extend(report.get('skipped', []))
        combined['scan_dates_by_drive'][drive] = report.get('last_scanned_utc', '')
        partial = partial or report.get('status') == 'cancelada_parcial'
        for record in report.get('records', []):
            token = (record.get('app_id'), str(record.get('path', '')).casefold(), record.get('kind'))
            if token not in seen_records:
                seen_records.add(token)
                combined['records'].append(record)
        for app in report.get('apps', []):
            app_id = app.get('id')
            if app_id not in seen_apps:
                seen_apps.add(app_id)
                combined['apps'].append(app)
        for path in report.get('unassociated_executables', []):
            if path not in seen_unmatched:
                seen_unmatched.add(path)
                combined['unassociated_executables'].append(path)
    combined['status'] = ('cancelada_parcial' if partial else
                          'concluida_com_lacunas' if combined['errors'] or combined['skipped'] else 'concluida')
    return combined


def cache_from_saved(report):
    """Load historical merged snapshots or the single-scope v0.6.1 report."""
    cache = split_by_drive(report, report.get('scanned_drives') or None)
    for drive, snapshot in cache.items():
        date = report.get('scan_dates_by_drive', {}).get(drive)
        if date:
            snapshot['last_scanned_utc'] = date
    return cache
