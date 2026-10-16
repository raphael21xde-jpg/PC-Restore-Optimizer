"""Import only non-destructive selection metadata from an earlier PCRO folder.

Do not import formatting flags, selected backup destinations or any disk action.
No filesystem operations on the selected paths occur during the import.
"""
from __future__ import annotations
from backup_core import norm

VALID_CHOICES = {'keep', 'skip'}
VALID_CATALOG = {'keep', 'skip', 'pending'}


def merge_preferences(app, document):
    if not isinstance(document, dict):
        raise ValueError('Arquivo de preferências inválido')
    selections = document.get('choices', {})
    catalog = document.get('catalog_choices', {})
    if not isinstance(selections, dict) or not isinstance(catalog, dict):
        raise ValueError('Formato de escolhas incompatível')
    safe_choices = {norm(k): v for k, v in selections.items()
                    if isinstance(k, str) and len(k) < 4096 and v in VALID_CHOICES}
    safe_catalog = {k: v for k, v in catalog.items()
                    if isinstance(k, str) and len(k) < 1024 and v in VALID_CATALOG}
    app.choices.update(safe_choices)
    app.catalog_choices.update(safe_catalog)
    for attr, key in [('auto_save_paths','auto_save_paths'), ('personal_paths','personal_paths'),
                      ('browser_keep_paths','browser_keep_paths'), ('cleanup_candidates','cleanup_candidates')]:
        values = document.get(key, [])
        if isinstance(values, list):
            getattr(app, attr).update(norm(p) for p in values if isinstance(p,str) and len(p)<4096)
    approved = document.get('approved_catalog_paths', {})
    if isinstance(approved, dict):
        for key, paths in approved.items():
            if isinstance(key,str) and isinstance(paths,list):
                old = app.approved_catalog_paths.setdefault(key, [])
                old.extend(p for p in paths if isinstance(p,str) and len(p)<4096 and p not in old)
    snapshots = document.get('catalog_snapshots', {})
    if isinstance(snapshots, dict) and hasattr(app, 'catalog_snapshots'):
        for key, item in snapshots.items():
            if key in safe_catalog and isinstance(item, dict):
                app.catalog_snapshots[key] = {
                    field: item[field] for field in
                    ('kind', 'name', 'category', 'install_location', 'paths',
                     'possible_paths', 'registry_id', 'edition', 'observed_volumes')
                    if field in item and isinstance(item[field], (str, list))}
    discoveries = document.get('retained_discoveries', {})
    if isinstance(discoveries, dict):
        app.retained_discoveries.update({k:v for k,v in discoveries.items()
                                         if isinstance(k,str) and isinstance(v,dict)})
    return len(safe_choices), sum(v == 'keep' for v in safe_catalog.values())
