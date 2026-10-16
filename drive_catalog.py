"""Per-volume discovery presentation and bounded, read-only directory browsing.

This module does NOT claim that files are protected from disk erasure.  Selections
are planning metadata; backup/format workflows must perform separate preflight.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import islice
import ntpath
from volume_paths import volume_of, drive_root
import os
from pathlib import Path
import re
import stat

from discovery_groups import group_records

REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
CATEGORIES = ('Jogos', 'Navegadores', 'Aplicativos', 'Dados e saves', 'Outros identificados')


def category_for(group, report):
    records = report.get('records', [])
    apps = {a.get('id'): a for a in report.get('apps', [])}
    kinds = ' '.join(str(records[i].get('kind', '')) for i in group['records'] if i < len(records)).casefold()
    appcats = ' '.join(str(apps.get(records[i].get('app_id'), {}).get('category', ''))
                       for i in group['records'] if i < len(records)).casefold()
    name = group['name'].casefold()
    if group['family'] in ('opera', 'opera-gx') or any(x in name for x in ('chrome', 'firefox', 'edge', 'brave', 'vivaldi', 'navegador')):
        return 'Navegadores'
    if ('jogo' in appcats or 'game' in appcats or 'jogo' in kinds or
        group['family'] == 'osu' or any(x in name for x in ('steam', 'epic games', 'gog galaxy'))):
        return 'Jogos'
    if any(x in kinds for x in ('save', 'beatmap', 'configuraç', 'perfil', 'músicas')):
        return 'Dados e saves'
    if any(x in kinds for x in ('instalação', 'executável', 'aplicativo', 'microsoft store')):
        return 'Aplicativos'
    return 'Outros identificados'


def groups_by_volume(report):
    """Split logical app groups by physical *volume letter* while preserving indices.

    A program spanning C:/D: appears on both tabs. Selecting the D: group
    never silently selects its C: records.
    """
    result = defaultdict(list)
    for g in group_records(report):
        paths = defaultdict(list)
        for p in g['paths']:
            paths[volume_of(p['path'])].append(p)
        for drive, included in paths.items():
            indices = sorted({i for p in included for i in p['indices']})
            partial = dict(g, paths=included, records=indices, drive=drive)
            partial['category'] = category_for(partial, report)
            result[drive].append(partial)
    return {drive: sorted(groups, key=lambda g: (CATEGORIES.index(g['category']), g['name'].casefold()))
            for drive, groups in result.items()}


def coverage(report, drive):
    stats = report.get('volume_stats', {}).get(drive, {})
    errors = sum(volume_of(e.get('path')) == drive for e in report.get('errors', []))
    skipped = sum(volume_of(e.get('path')) == drive for e in report.get('skipped', []))
    return {
        'directories': stats.get('directories', 0),
        'files': stats.get('files', 0),
        'errors': errors,
        'skipped': skipped,
        'complete': report.get('status') not in ('cancelada_parcial', None),
    }


def list_folder_page(path, *, offset=0, limit=120):
    """Expose at most `limit` entries to the GUI, without a 200k-item tree.

    Scanning page N does re-enumerate previous entries. Contents must be
    refreshed after filesystem changes. Symlinks and junctions are identified
    but never traversed by the GUI tree.
    """
    if offset < 0 or limit < 1 or limit > 300:
        raise ValueError('Página inválida')
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & REPARSE:
        raise ValueError('Diretório indisponível, link ou junção')
    entries = []
    with os.scandir(path) as stream:
        # Don't materialize the whole directory in memory.
        for item in islice(stream, offset, offset + limit + 1):
            try:
                st = item.stat(follow_symlinks=False)
                special = stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & REPARSE)
                entries.append(dict(name=item.name, path=item.path,
                                    is_dir=stat.S_ISDIR(st.st_mode), special=special,
                                    size=st.st_size if stat.S_ISREG(st.st_mode) else None))
            except OSError as exc:
                entries.append(dict(name=item.name, path=item.path, is_dir=False,
                                    special=True, size=None, error=str(exc)))
    has_more = len(entries) > limit
    return {'entries': entries[:limit], 'next_offset': offset + limit if has_more else None,
            'path': str(path), 'offset': offset}


def safe_to_mark(path):
    """Block dangerous broad system paths; this does not validate backup safety."""
    raw = str(path)
    drive = volume_of(raw)
    if drive == 'SEM UNIDADE':
        # Only used on real Windows paths from the selection GUI.
        return False
    if not ntpath.isabs(raw.replace('/', '\\')):
        return False
    canonical = ntpath.normcase(ntpath.normpath(raw.replace('/', '\\')))
    root = ntpath.normcase(drive_root(drive)).rstrip('\\')
    if canonical.rstrip('\\') == root:
        return False
    relative = canonical[len(root):].strip('\\')
    top = relative.split('\\')[0]
    # Root Windows/system containers are not appropriate one-click selections.
    system_roots = {'windows', 'program files', 'program files (x86)', 'users',
                    'programdata', 'recovery', 'system volume information',
                    '$recycle.bin', 'boot', 'efi', '$windows.~bt'}
    if relative in system_roots:
        return False
    if top == 'windows' or top in ('system volume information', '$recycle.bin', 'recovery', 'efi', 'boot', '$windows.~bt'):
        return False
    return True
