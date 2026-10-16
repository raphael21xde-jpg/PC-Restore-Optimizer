"""Add known save evidence without breaking an explicitly chosen scan scope.

These records are candidate links for human inspection. Only the selected
Windows roots may be read. Merely finding a folder cannot certify recovery.
"""
from __future__ import annotations
from volume_paths import volume_of
from scan_scope import in_scope
from game_saves import same_game
import unicodedata


def scoped_user_roots(user_roots, selected_roots):
    return {name: [root for root in candidates if in_scope(root, selected_roots)]
            for name, candidates in user_roots.items()}


def incorporate_saves(report, candidates, catalog, selected_roots):
    """Add candidate save records only for previously scanned, selected paths.

    An exact unique title match may share a catalog identity, but files are
    still unconfirmed until the user examines them. Ambiguous matches get a
    separate ID to avoid accidental ownership.
    """
    result = dict(report)
    result['records'] = list(report.get('records', []))
    result['apps'] = list(report.get('apps', []))
    found = {(str(r.get('app_id')), str(r.get('path')).casefold()) for r in result['records']}
    for entry in candidates:
        path = str(entry.get('path') or '')
        name = str(entry.get('game') or '')
        if not path or not name or not in_scope(path, selected_roots):
            continue
        matching = [key for key, item in catalog.items() if item.get('kind')=='game' and
                    same_game(name, item.get('name', ''))]
        if len(matching) == 1:
            key = matching[0]
        else:
            safe = ''.join(char for char in unicodedata.normalize('NFKD', name.casefold())
                           if char.isalnum() and not unicodedata.combining(char))
            key = 'savelocal:' + safe
        token = (str(key), path.casefold())
        if token in found:
            continue
        found.add(token)
        result['records'].append(dict(app_id=key, app=name, path=path,
                            kind='Save/configuração local encontrada',
                            evidence=entry.get('source','Pasta local conhecida; rever dono'),
                            confidence='candidato' if entry.get('confidence')!='alta' else 'caminho identificado',
                            edition=None))
        if not any(a.get('id')==key for a in result['apps']):
            result['apps'].append(dict(id=key, name=name, category='Jogo / saves',
                                       source='Pesquisa de saves no volume selecionado'))
    return result
