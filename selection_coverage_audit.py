"""Privacy-safe, in-memory audit of selection coverage before using plan size.

This does not scan files or inspect browsers, saves or installations.
It distinguishes file tasks represented in an existing Plan from choices that
still require a separate backup/recovery strategy. No copy authorization.
"""
from __future__ import annotations

import ntpath

MAX_SELECTED = 1_000_000
MAX_CATALOG = 100_000
MAX_BROWSER = 100_000
REASONS = frozenset({
    'file_choices_outside_preview',
    'auto_saves_outside_preview',
    'catalog_recovery_not_verified',
    'catalog_paths_need_review',
    'browser_vaults_not_verified',
    'selection_state_unavailable',
})


def _normal_path(value):
    if not isinstance(value, str) or not ntpath.isabs(value):
        return None
    drive, _ = ntpath.splitdrive(value)
    if len(drive) != 2 or drive[1] != ':' or not drive[0].isascii() or not drive[0].isalpha():
        return None
    return ntpath.normcase(ntpath.normpath(value))


def _bounded_collection(value, limit):
    try:
        return len(value) <= limit
    except (TypeError, ValueError):
        return False


def audit_selection_coverage(plan, *, choices=None, catalog_choices=None,
                             catalog_items=None, browser_keep_paths=None,
                             auto_save_paths=None):
    """Identify selected material absent/unverified in the existing file Plan.

    Counts and fixed reason codes only: NEVER return selected file names,
    application IDs, browser paths, serials, vault paths, or raw exceptions.
    A positive result only permits *consideration* of the Plan's file-task
    estimate; it is not proof of full recovery or of a safe destination.
    """
    choices = {} if choices is None else choices
    catalog_choices = {} if catalog_choices is None else catalog_choices
    catalog_items = {} if catalog_items is None else catalog_items
    browser_keep_paths = () if browser_keep_paths is None else browser_keep_paths
    auto_save_paths = () if auto_save_paths is None else auto_save_paths
    valid = (isinstance(choices, dict) and _bounded_collection(choices, MAX_SELECTED)
             and isinstance(catalog_choices, dict) and _bounded_collection(catalog_choices, MAX_CATALOG)
             and isinstance(catalog_items, dict) and _bounded_collection(catalog_items, MAX_CATALOG)
             and isinstance(browser_keep_paths, (list, tuple, set, frozenset))
             and _bounded_collection(browser_keep_paths, MAX_BROWSER)
             and isinstance(auto_save_paths, (list, tuple, set, frozenset))
             and _bounded_collection(auto_save_paths, MAX_SELECTED))
    if not valid:
        return {
            'status': 'requires_review',
            'can_use_file_preview_estimate': False,
            'file_choices_outside_preview': None,
            'auto_saves_outside_preview': None,
            'catalog_selected': None,
            'catalog_pending_paths': None,
            'browser_profiles_selected': None,
            'reasons': ['selection_state_unavailable'],
        }

    selected = getattr(plan, 'selected', None)
    selected_paths = set()
    if isinstance(selected, list) and len(selected) <= MAX_SELECTED:
        for value in selected:
            normalized = _normal_path(value)
            if normalized is not None:
                selected_paths.add(normalized)
    elif plan is not None:
        # Incomplete/malformed Plan cannot establish selection coverage.
        return {
            'status': 'requires_review',
            'can_use_file_preview_estimate': False,
            'file_choices_outside_preview': None,
            'auto_saves_outside_preview': None,
            'catalog_selected': None,
            'catalog_pending_paths': None,
            'browser_profiles_selected': None,
            'reasons': ['selection_state_unavailable'],
        }

    auto = {_normal_path(p) for p in auto_save_paths}
    selected_keep = [(_normal_path(path), state) for path, state in choices.items()
                     if state == 'keep']
    outside = [path for path, _ in selected_keep
               if path is None or path not in selected_paths]
    auto_outside = sum(path in auto for path in outside if path is not None)

    catalog = [key for key, state in catalog_choices.items() if state == 'keep']
    pending = 0
    for key in catalog:
        record = catalog_items.get(key)
        if not isinstance(record, dict):
            pending += 1
            continue
        paths = record.get('possible_paths')
        if not isinstance(paths, (list, tuple)):
            pending += 1
        else:
            pending += len(paths) if len(paths) <= MAX_SELECTED else 1

    browsers = len(browser_keep_paths)
    codes = []
    if outside:
        codes.append('file_choices_outside_preview')
    if auto_outside:
        codes.append('auto_saves_outside_preview')
    if catalog:
        codes.append('catalog_recovery_not_verified')
    if pending:
        codes.append('catalog_paths_need_review')
    if browsers:
        codes.append('browser_vaults_not_verified')

    return {
        'status': 'requires_review' if codes else 'no_unresolved_extra_choices',
        'can_use_file_preview_estimate': not codes,
        'file_choices_outside_preview': len(outside),
        'auto_saves_outside_preview': auto_outside,
        'catalog_selected': len(catalog),
        'catalog_pending_paths': pending,
        'browser_profiles_selected': browsers,
        'reasons': codes,
    }


REASON_TEXT = {
    'file_choices_outside_preview': 'Há arquivos ou pastas marcados para preservar fora da prévia atual.',
    'auto_saves_outside_preview': 'Alguns saves escolhidos não estão representados na prévia de arquivos.',
    'catalog_recovery_not_verified': 'Jogos/aplicativos escolhidos exigem verificar dados, dependências e reinstalação separadamente.',
    'catalog_paths_need_review': 'Há caminhos de jogos/aplicativos pendentes de conferência.',
    'browser_vaults_not_verified': 'Perfis de navegador selecionados dependem de cofre/restauração independente; não somar tamanho sem auditoria.',
    'selection_state_unavailable': 'Não foi possível conferir todas as escolhas do aplicativo.',
}
