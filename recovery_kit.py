"""Plano pós-Windows: inventário e escolhas, sem executáveis ou segredos.
Não instala aplicativos e não modifica originais.
"""
from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime
from backup_core import atomic_json

SCHEMA='pcro-recovery-plan-v0.5'

def create_plan(path, catalog_items, catalog_choices, save_selections, backup_base, disk_alerts=None, *, browsers=(), browser_vaults=None):
    selected=[]
    for key,choice in catalog_choices.items():
        if choice not in ('keep','skip'):
            continue
        item=catalog_items.get(key)
        if not item:
            continue
        selected.append(dict(id=key,decision=choice,kind=item.get('kind'),
                             name=item.get('name'),origin=item.get('source'),edition=item.get('edition'),publisher=item.get('publisher'),version=item.get('version'),install_location=item.get('install_location'),
                             save_paths=item.get('paths',[]) if item.get('kind')=='game' else [],
                             data_paths=item.get('paths',[]) if item.get('kind')=='app' else [],
                             possible_paths=item.get('possible_paths',[])))
    plan={'schema':SCHEMA,'created':datetime.now().isoformat(),
          'notice':'Metadados e decisões, NÃO é um backup nem reinstalador.',
          'items':selected,'save_selections':list(save_selections),
          'backup_base_hint':str(backup_base),
          'disk_alerts':list(disk_alerts or []),
          'browser_profiles_to_preserve':list(browsers),
          'browser_vault_hints':{k:str(v) for k,v in (browser_vaults or {}).items() if k in browsers}}
    atomic_json(path,plan)
    return len(selected)


def load_plan(path):
    p=Path(path)
    if p.stat().st_size>8*1024*1024:
        raise ValueError('Plano grande demais ou inválido.')
    doc=json.loads(p.read_text(encoding='utf-8'))
    if doc.get('schema')!=SCHEMA or not isinstance(doc.get('items'),list) or len(doc['items'])>50000:
        raise ValueError('Este arquivo não é um plano v0.5 válido.')
    return doc


def summarize_plan(doc):
    keep=[i for i in doc['items'] if i.get('decision')=='keep']
    games=[i for i in keep if i.get('kind')=='game']
    apps=[i for i in keep if i.get('kind')=='app']
    lines=[f'Plano de {doc.get("created", "data desconhecida")}',
           f'Jogos escolhidos: {len(games)}; aplicativos escolhidos: {len(apps)}.', '',
           'A lista NÃO contém instaladores, licenças ou executáveis e NÃO restaura aplicativos automaticamente.',
           'Reinstale programas por fontes oficiais e depois restaure configurações/saves verificados.',
           'Saves que não foram localizados NÃO estão garantidos.', '', 'JOGOS A REINSTALAR:']
    lines.extend('  - '+i.get('name','?')+' | saves: '+ ('; '.join(i.get('save_paths') or []) or 'NÃO LOCALIZADOS') for i in games)
    lines.append('');lines.append('APLICATIVOS A REINSTALAR:')
    lines.extend('  - '+i.get('name','?')+' | dados selecionados: '+('; '.join(i.get('data_paths') or []) or 'NÃO LOCALIZADOS') for i in apps)
    lines.extend(['','PERFIS DE NAVEGADOR A PROTEGER (cofres separados):'])
    lines.extend('  - '+p for p in doc.get('browser_profiles_to_preserve',[]))
    lines.extend(['','ALERTAS DE DISCO (válidos apenas no PC de origem):'])
    lines.extend('  ! '+a for a in doc.get('disk_alerts',[])[:30])
    return '\n'.join(lines)
