"""Logical groups only. No files are moved, compressed or deleted."""
from collections import defaultdict
from pathlib import PureWindowsPath
from deep_discovery import signature
from backup_identity import canonical, inside


def family(name):
    s=signature(name)
    if s.startswith('operagx'):return 'opera-gx'
    if s.startswith('opera') and 'gx' not in s:return 'opera'
    if s.startswith('osu') and s not in ('osumedia',):return 'osu'
    return s


def group_records(report):
    records=report.get('records',[])
    metadata={a['id']:a for a in report.get('apps',[]) if a.get('id')}
    editions=[(r['path'],r['edition']) for r in records if r.get('edition') and family(r.get('app',''))=='osu']
    known_publishers=defaultdict(set)
    for r in records:
        p=signature(metadata.get(r['app_id'],{}).get('publisher',''))
        if p:known_publishers[family(r['app'])].add(p)
    groups={}
    for index,r in enumerate(records):
        f=family(r['app']); a=metadata.get(r['app_id'],{})
        edition=r.get('edition') or a.get('edition') or ''
        if f=='osu':
            matches=[(p,e) for p,e in editions if inside(r['path'],p)]
            if matches:edition=max(matches,key=lambda x:len(canonical(x[0])))[1]
            if not edition and 'lazer' in r['app'].casefold():edition='lazer'
            edition=edition or 'unknown'
        publisher=signature(a.get('publisher',''))
        if not publisher:
            publishers=known_publishers[f]
            publisher=next(iter(publishers)) if len(publishers)==1 else ('unconfirmed:'+r['app_id'] if len(publishers)>1 else '')
        # Explicit browser/OSU families are disambiguated by edition; others by publisher.
        group_key=(f,edition,'' if f in ('osu','opera','opera-gx') else publisher)
        title={'opera-gx':'Opera GX','opera':'Opera','osu':{'stable':'osu! clássico (stable)','lazer':'osu! lazer','unknown':'osu! — edição a conferir'}.get(edition,'osu!')}.get(f,r['app'])
        g=groups.setdefault(group_key,{'key':group_key,'name':title,'family':f,'edition':edition,'records':[], 'paths':{},'uncertain':False})
        g['records'].append(index)
        pathkey=canonical(r['path'])
        row=g['paths'].setdefault(pathkey,{'path':r['path'],'indices':[],'kinds':set(),'evidence':set()})
        row['indices'].append(index);row['kinds'].add(r['kind']);row['evidence'].add(r['evidence'])
        if r.get('confidence')=='candidato':g['uncertain']=True
    output=[]
    for g in groups.values():
        rows=list(g['paths'].values())
        # Paths remain individually available; parent display combines duplicate findings.
        for row in rows:
            row['kinds']=sorted(row['kinds']);row['evidence']=sorted(row['evidence'])
        g['paths']=sorted(rows,key=lambda x:canonical(x['path']))
        output.append(g)
    return sorted(output,key=lambda g:g['name'].casefold())


def record_indices(node_ids, node_map):
    return sorted({i for n in node_ids for i in node_map.get(n,[])})


def selected_records(report, indices):
    """Carry the disambiguated edition into backup choices, not just display labels."""
    identities={}
    for g in group_records(report):
        if g['family']=='osu':
            for i in g['records']:identities[i]=(g['name'],g['edition'])
    output=[]
    for i in sorted(set(indices)):
        row=dict(report['records'][i])
        if i in identities:
            name,edition=identities[i]
            row['app']=name
            if edition!='unknown':
                row['edition']=edition
                row['app_id']=row['app_id']+':edition:'+edition
        output.append(row)
    return output


def other_osu_editions_under_selection(report, selected):
    exclusions=set()
    for r in selected:
        if family(r['app'])!='osu' or r.get('edition') not in ('stable','lazer'):continue
        for group in group_records(report):
            if group['family']!='osu' or group['edition'] not in ('stable','lazer') or group['edition']==r['edition']:continue
            for path in group['paths']:
                if canonical(path['path'])!=canonical(r['path']) and inside(path['path'],r['path']):exclusions.add(path['path'])
    return sorted(exclusions)
