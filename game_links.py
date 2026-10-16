"""Non-destructive catalog relationships; never equate an association to backup.

Explicit approvals are shown even when game discovery classified a game as
an application. Unreviewed candidate paths never become confirmed links.
"""
from __future__ import annotations
from volume_paths import volume_of


def _unique_paths(values):
    found = set()
    for path in values:
        if not isinstance(path, str) or not path.strip():
            continue
        token = path.replace('/', '\\').casefold().rstrip('\\')
        if token not in found:
            found.add(token)
            yield path


def infer_links(catalog_items, game_saves, approved_paths=None, selected_keys=None):
    """Show selected games' identified data and *any* manually approved item.

    `approved_paths` means that the user approved the association, **not**
    that the contents were checked by PCRO or safely copied. Game vs app
    misclassification never hides a user's explicit review.
    """
    approved_paths = approved_paths or {}
    game_saves = game_saves or {}
    permitted = set(selected_keys) if selected_keys is not None else None
    links = []
    for key, item in sorted(catalog_items.items(), key=lambda x: str(x[1].get('name', '')).casefold()):
        if permitted is not None and key not in permitted:
            continue
        is_game = item.get('kind') == 'game'
        manual = list(_unique_paths(approved_paths.get(key, [])))
        if not is_game and not manual:
            continue
        install = item.get('install_location') or item.get('library') or ''
        install_volume = volume_of(install)
        observed = [v for v in item.get('observed_volumes', []) if v != 'SEM UNIDADE']
        known = list(_unique_paths([*(game_saves.get(key, []) if is_game else []), *manual]))
        approved_tokens = {p.replace('/', '\\').casefold().rstrip('\\') for p in manual}
        for path in known:
            data_volume = volume_of(path)
            if data_volume == 'SEM UNIDADE':
                continue
            user_approved = path.replace('/', '\\').casefold().rstrip('\\') in approved_tokens
            if install_volume != 'SEM UNIDADE':
                relation = 'ENTRE UNIDADES' if data_volume != install_volume else 'MESMA UNIDADE'
            elif observed and data_volume not in observed:
                relation = 'POSSÍVEL VÍNCULO ENTRE UNIDADES'
            else:
                relation = 'INSTALAÇÃO NÃO CONFIRMADA'
            links.append({
                'game': item.get('name', key), 'game_id': key,
                'entity_kind': 'game' if is_game else 'app',
                'game_locations': [install] if install else list(item.get('paths', [])) or list(observed),
                'install_volume': install_volume if install_volume != 'SEM UNIDADE' else
                                  ', '.join(observed) if observed else 'A confirmar',
                'data_path': path, 'volume': data_volume, 'relation': relation,
                'confidence': 'CONFIRMADO PELO USUÁRIO' if user_approved else 'REVISAR',
                'evidence': ('Associação conferida pelo usuário; conteúdo e backup NÃO verificados'
                             if user_approved else 'Dados identificados; conferir se é save/configuração'),
                'backup_verified': False,
                'needs_backup_if_c_formatted': data_volume == 'C:',
                'classification_pending': not is_game,
            })
    return links
