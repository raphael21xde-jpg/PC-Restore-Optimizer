"""Keep the user's game/app decisions visible even when no save is found.

Selecting a program is an INTENT, not proof its executables or save files are
protected. Never automatically turn a possible-path guess into a verified save.
"""
from __future__ import annotations
from volume_paths import volume_of


def selected_catalog_choices(catalog_choices, catalog_items, approved_paths=None):
    approved_paths = approved_paths or {}
    result = []
    for key, choice in sorted(catalog_choices.items(), key=lambda entry: str(entry[0]).casefold()):
        if choice != 'keep':
            continue
        item = catalog_items.get(key, {})
        confirmed = list(dict.fromkeys([p for p in item.get('paths', []) if p] +
                                        [p for p in approved_paths.get(key, []) if p]))
        possible = [p for p in item.get('possible_paths', []) if p and p not in confirmed]
        install_path = item.get('install_location') or item.get('library') or ''
        install_drive = volume_of(install_path)
        known_volumes = sorted({volume_of(path) for path in confirmed if volume_of(path) != 'SEM UNIDADE'})
        # Do not present the save's disk as a confirmed installation location.
        observed = sorted({v for v in item.get('observed_volumes', [])
                           if v != 'SEM UNIDADE'} | set(known_volumes))
        display_drive = (install_drive if install_drive != 'SEM UNIDADE' else
                         ', '.join(observed) if observed else 'SEM UNIDADE')
        result.append({
            'id': key,
            'kind': item.get('kind', 'unknown'),
            'name': item.get('name') or str(key),
            'choice': 'keep',
            'install_location': install_path,
            'install_volume': install_drive,
            'display_volume': display_drive,
            'installation_confirmed': install_drive != 'SEM UNIDADE',
            'known_paths': confirmed,
            'possible_paths': possible,
            'known_data_volumes': known_volumes,
            'has_confirmed_data': bool(confirmed),
            'backup_required_for_c': [p for p in confirmed if volume_of(p) == 'C:'],
            'status': ('INVENTÁRIO SALVO — REVALIDAR LOCAIS' if item.get('stale_snapshot') else
                       'INSTALAÇÃO NÃO CONFIRMADA — REVISAR UNIDADE' if install_drive == 'SEM UNIDADE' else
                       'DADOS IDENTIFICADOS — TESTAR RECUPERAÇÃO' if confirmed else
                       'DADOS NÃO CONFIRMADOS — REVISÃO NECESSÁRIA'),
        })
    return result
