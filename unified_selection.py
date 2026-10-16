"""Single, read-only presentation model for disk-scoped selection.

A game has ONE stable decision, even when its installation and saves reside on
separate volumes. Filesystem paths have independent, explicit decisions.
Candidates are never silently turned into confirmed saves. This module has no
filesystem operations, deletion, partitioning or formatting code.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import PureWindowsPath
from volume_paths import volume_of
from drive_catalog import groups_by_volume
from backup_core import effective_choice

CHOICES = ('keep', 'skip', 'pending')


def _uniq(values):
    return list(dict.fromkeys(str(v) for v in values if v))


def index_cards(report, catalog_items, catalog_choices, path_choices, approved_paths=None):
    """Return {drive: [cards]}; never assign unknown-location apps to C:.

    Every card is identified by an app catalog key, or a scoped report app ID.
    Cards with a shared ID on two volumes refer to the same decision; their
    files and scan evidence remain strictly specific to each volume.
    """
    approved_paths = approved_paths or {}
    report = report or {'records': [], 'apps': []}
    groups = groups_by_volume(report)
    registry_keys = {}
    for key, item in catalog_items.items():
        for identity in (key, item.get('registry_id')):
            if identity:
                registry_keys.setdefault(str(identity), str(key))
    indexed = defaultdict(dict)
    for drive, per_drive in groups.items():
        if drive == 'SEM UNIDADE':
            continue
        for group in per_drive:
            records = [report['records'][i] for i in group['records']]
            identities = [str(r.get('app_id')) for r in records if r.get('app_id')]
            identity = identities[0] if identities else group['name']
            catalog_key = next((registry_keys[t] for t in identities if t in registry_keys), None)
            key = catalog_key or 'deep:' + identity
            paths = _uniq(p['path'] for p in group['paths'] if volume_of(p['path']) == drive)
            if not paths:
                continue
            # Installation must be evidenced by a scanned installation record,
            # not inferred from a nearby save or a similarly named folder.
            evidence_installs = [r['path'] for r in records
                if volume_of(r.get('path')) == drive and
                ('instalação' in str(r.get('kind','')).casefold()) and
                r.get('confidence') in ('caminho identificado','estrutura identificada','alta')]
            reported_apps = [a for a in report.get('apps', [])
                             if str(a.get('id')) in identities]
            is_game = (group['category'] == 'Jogos' or
                any('jogo' in str(a.get('category','')).casefold() for a in reported_apps) or
                any('save' in str(r.get('kind','')).casefold() for r in records))
            token = (key, group['name'])
            card = indexed[drive].get(token)
            if not card:
                card = {
                    'key': key, 'name': group['name'], 'kind': group['category'],
                    'entity_kind': 'game' if is_game else 'app',
                    'drive': drive, 'record_paths': [], 'data_paths': [],
                    'possible_paths': [], 'install_location': evidence_installs[0] if evidence_installs else '',
                    'source': 'Varredura desta unidade', 'uncertain': bool(group['uncertain']),
                    'catalog_key': catalog_key, 'record_ids': [],
                }
                indexed[drive][token] = card
            card['record_paths'] = _uniq(card['record_paths'] + paths)
            if not card.get('install_location') and evidence_installs:
                card['install_location'] = evidence_installs[0]
            card['record_ids'] = sorted(set(card['record_ids'] + list(group['records'])))
    # Add trusted catalog identities and installed locations in the same tree.
    # Never treat unverified possible_paths as identified data.
    for key, item in catalog_items.items():
        install = str(item.get('install_location') or item.get('library') or '')
        install_drive = volume_of(install)
        confirmed = _uniq([*item.get('paths', []), *approved_paths.get(key, [])])
        possible = _uniq(item.get('possible_paths', []))
        actual_drives = {volume_of(p) for p in confirmed + possible}
        if install_drive != 'SEM UNIDADE':
            actual_drives.add(install_drive)
        for drive in sorted(actual_drives - {'SEM UNIDADE'}):
            paths_here = [p for p in confirmed if volume_of(p) == drive]
            possible_here = [p for p in possible if volume_of(p) == drive and p not in confirmed]
            matched = next((c for c in indexed[drive].values() if c['key'] == key), None)
            if matched is None:
                matched = {'key': str(key), 'name': item.get('name') or str(key),
                           'kind': 'Jogos' if item.get('kind') == 'game' else 'Aplicativos',
                           'entity_kind': item.get('kind', 'app'),
                           'drive': drive, 'record_paths': [], 'data_paths': [],
                           'possible_paths': [], 'install_location': install,
                           'source': item.get('source', 'Catálogo'), 'uncertain': False,
                           'catalog_key': str(key), 'record_ids': []}
                indexed[drive][(key, matched['name'])] = matched
            matched['data_paths'] = _uniq(matched['data_paths'] + paths_here)
            matched['possible_paths'] = _uniq(matched['possible_paths'] + possible_here)
            matched['install_location'] = install
            matched['catalog_key'] = str(key)
            matched['entity_kind'] = item.get('kind', 'app')
    # Connect the same game identity across inventories already available.
    # This is a CROSS-REFERENCE, not permission to inspect new volumes or a
    # claim that the referenced path is a verified save.
    related_by_key = defaultdict(list)
    for drive, entries in indexed.items():
        for card in entries.values():
            related_by_key[card['key']].extend(card['record_paths'])
    result = {}
    for drive, entries in indexed.items():
        cards = []
        for card in entries.values():
            key = card['key']
            catalog_choice = catalog_choices.get(key, 'pending')
            scanned_paths = card['record_paths']
            path_states = {effective_choice(p, path_choices) for p in scanned_paths}
            if catalog_choice != 'pending':
                card['choice'] = catalog_choice
            elif path_states == {'keep'}:
                card['choice'] = 'keep'
            elif path_states == {'skip'}:
                card['choice'] = 'skip'
            elif 'keep' in path_states or 'skip' in path_states:
                card['choice'] = 'mixed'
            else:
                card['choice'] = 'pending'
            # Show true associations only; unlocated entries are not presented as
            # installed on a guessed volume merely because they were selected.
            card['related_scanned_paths'] = _uniq(p for p in related_by_key[key] if volume_of(p) != drive)
            card['install_here'] = volume_of(card['install_location']) == drive
            card['needs_review'] = bool(card['possible_paths'] or card['uncertain'])
            cards.append(card)
        result[drive] = sorted(cards, key=lambda c: (c['kind'], c['name'].casefold(), c['key']))
    return dict(result)


def card_detail(card, catalog_items, approved_paths=None):
    """Describe the full game across drives without scanning them."""
    approved_paths = approved_paths or {}
    item = catalog_items.get(card['key'], {})
    confirmed = _uniq([*item.get('paths', []), *approved_paths.get(card['key'], [])])
    # Scanned candidates belong only to the currently viewed drive, never
    # imply other unexamined volumes were inspected.
    candidates = _uniq(card['possible_paths'] + card.get('related_scanned_paths', []) +
                       [p for p in card['record_paths'] if p not in confirmed])
    candidates = [p for p in candidates if p not in confirmed]
    other = [p for p in confirmed if volume_of(p) != card['drive']]
    return {
        'key': card['key'], 'name': card['name'], 'drive': card['drive'],
        'install': item.get('install_location') or card['install_location'] or '',
        'confirmed': confirmed, 'candidates': candidates,
        'other_volume_data': other,
        'backup_c': [p for p in confirmed if volume_of(p) == 'C:'],
        'requires_review': bool(candidates or not confirmed),
        'choice': card['choice'],
    }


def decision_label(decision):
    return {'keep':'Manter', 'skip':'Não preservar', 'pending':'Pendente', 'mixed':'Parcial'}.get(decision,'Pendente')
