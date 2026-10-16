"""Consistent, non-destructive selection totals and save links for the UI."""
from __future__ import annotations
from collections import Counter
from preservation_plan import classify_choices
from catalog_plan import selected_catalog_choices
from game_links import infer_links
from volume_paths import volume_of


def _dedupe_paths(paths):
    unique = {}
    for path in paths:
        if isinstance(path, str) and path.strip():
            unique.setdefault(path.replace('/', '\\').rstrip('\\').casefold(), path)
    return sorted(unique.values(), key=str.casefold)


def build_audit(choices, catalog_choices, catalog_items, approved_paths=None,
                game_saves=None, *, scanned_roots=(), removal_candidates=()):
    """A plan with explicitly separated entity/path counters and verified-copy *needs*.

    Never labels any file as backed up. Approved = linked, not copied.
    """
    approved_paths = approved_paths or {}
    game_saves = game_saves or {}
    plan = classify_choices(choices, scanned_roots=scanned_roots,
                            removal_candidates=removal_candidates)
    selected = selected_catalog_choices(catalog_choices, catalog_items, approved_paths)
    links = infer_links(catalog_items, game_saves, approved_paths,
                        selected_keys={s['id'] for s in selected})
    # A manually confirmed game save counts once, even if it also exists in
    # the user's explicit file choices and the catalog's detected paths.
    need_backup = _dedupe_paths([*plan['requires_verified_backup'],
                                 *(p for item in selected for p in item['backup_required_for_c'])])
    plan['requires_verified_backup'] = need_backup
    plan['catalog_selections'] = selected
    plan['game_save_candidates'] = links
    plan['catalog_unverified'] = [s['id'] for s in selected if not s['has_confirmed_data']]
    entity_counts = Counter()
    for item in selected:
        # The app stores one decision for a game/app, even if its data crosses drives.
        entity_counts[item['display_volume']] += 1
    path_counts = Counter(e['drive'] for e in plan['entries'] if e['choice'] == 'keep')
    plan['selection_metrics'] = {
        'selected_games_apps': len(selected),
        'explicit_keep_paths': sum(path_counts.values()),
        'backup_required_paths_c': len(need_backup),
        'removal_candidates': len(plan['removal_candidates']),
        'games_apps_by_display_volume': dict(entity_counts),
        'paths_keep_by_volume': dict(path_counts),
        'confirmed_user_links': sum(x['confidence'] == 'CONFIRMADO PELO USUÁRIO' for x in links),
        'possible_links_to_review': sum(x['confidence'] != 'CONFIRMADO PELO USUÁRIO' for x in links),
    }
    plan['note'] = ('As decisões de jogos e aplicativos são contadas separadamente das '
                    'decisões de arquivos/pastas. Uma mesma pasta pode pertencer a um jogo '
                    'selecionado; não somar essas categorias. Nenhuma cópia foi comprovada.')
    return plan
