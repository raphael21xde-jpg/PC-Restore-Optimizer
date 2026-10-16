"""Read-only, cancellable filesystem inventory with explicit evidence and coverage."""
from pathlib import Path
import os
import re
import stat
import time
from app_data import normalized_name
from windows_evidence import executable_metadata
from volume_paths import volume_of
from scan_scope import in_scope


def signature(name):
    name = re.sub(r'\s+(?:version\s*|versão\s*|v)?\d[\w. -]*$', '', str(name), flags=re.I)
    name = re.sub(r'\s*\((?:x64|x86|64-bit|32-bit)\)\s*$', '', name, flags=re.I)
    return normalized_name(name)


def regular(path, directory=False):
    try:
        s = Path(path).lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:return False
        return stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)
    except OSError:return False


def local_drives():
    if os.name != 'nt':return []
    import ctypes
    return [f'{chr(c)}:\\' for c in range(65,91) if ctypes.windll.kernel32.GetDriveTypeW(f'{chr(c)}:\\') in (2,3)]


def classic_data(root, names, allowed_roots=None):
    """Only documented classic structure; never inspect password/token values."""
    root=Path(root); found=[]
    for name,kind in [('Songs','Músicas e beatmaps'),('Skins','Skins'),('Replays','Replays'),('Data/r','Replays locais'),
                      ('osu!.db','Índice de beatmaps'),('collection.db','Coleções'),('scores.db','Pontuações locais')]:
        p=root/name
        if regular(p,True) or regular(p):found.append((p,kind))
    for name in names:
        if name.lower().startswith('osu!') and name.lower().endswith('.cfg'):
            cfg=root/name
            if not regular(cfg) or cfg.stat().st_size>2*1024**2:continue
            found.append((cfg,'Configuração (pode conter dados privados)'))
            try:
                for line in cfg.read_text(encoding='utf-8-sig',errors='replace').splitlines():
                    key,sep,value=line.partition('=')
                    if sep and key.strip()=='BeatmapDirectory':
                        p=Path(value.strip().strip('"'))
                        if not p.is_absolute():p=root/p
                        if (allowed_roots is None or in_scope(p, allowed_roots)) and regular(p,True):
                            found.append((p,'Músicas em caminho personalizado (BeatmapDirectory)'))
            except OSError:pass
    return found


def scan(apps, roots, *, excluded=(), cancel=None, progress=None):
    start=time.time(); records=[]; seen=set(); errors=[]; skipped=[]; unmatched=[]; dirs=0; files=0
    volume_stats={}
    def counters(path):
        drive=volume_of(path)
        return volume_stats.setdefault(drive, {'directories':0, 'files':0})
    entries=[dict(a) for a in apps]
    by_name={}
    by_root={}
    def key(path):return os.path.normcase(os.path.abspath(str(path)))
    exclusions=[key(p).rstrip(os.sep) for p in excluded if p]
    def excluded_path(p):
        k=key(p)
        return any(k==e or k.startswith(e+os.sep) for e in exclusions)
    def add(app,path,kind,evidence,confidence='candidato',edition=None):
        token=(app['id'],key(path),kind)
        if token in seen or not in_scope(path, roots) or excluded_path(path):return
        seen.add(token)
        records.append(dict(app_id=app['id'],app=app['name'],path=str(path),kind=kind,evidence=evidence,confidence=confidence,edition=edition))
    for a in entries:
        s=signature(a['name'])
        if len(s)>=4 or s=='osu':by_name.setdefault(s,[]).append(a)
        for field in ('install_location','shortcut_directory'):
            p=a.get(field)
            if p and in_scope(p, roots) and regular(p,True):by_root.setdefault(key(p),[]).append(a)
    # Identity-based anchors even when display names include localized/version suffixes.
    for a in entries:
        for path in (a.get('install_location'), a.get('shortcut_directory')):
            if path and in_scope(path, roots) and regular(path,True) and not excluded_path(path):
                add(a,Path(path),'Pasta da instalação','Registro/atalho aponta para esta pasta; revisar antes de copiar','caminho identificado')
        for field in ('display_icon','uninstall_command'):
            raw=str(a.get(field,'')).strip()
            match=re.match(r'^"([^"\r\n]+\.exe)"',raw,re.I) or re.match(r'^(.+?\.exe)(?:,[-0-9]+|\s.*)?$',raw,re.I)
            if match:
                executable=Path(os.path.expandvars(match.group(1)))
                if in_scope(executable, roots) and regular(executable) and not excluded_path(executable) and executable.parent.name.casefold() not in ('windows','system32','syswow64'):
                    add(a,executable.parent,'Pasta apontada pelo registro',field+' (comando NÃO executado)','caminho identificado')
        package=a.get('package_data')
        if package:
            for part in ('LocalState','RoamingState','Settings'):
                p=Path(package)/part
                if in_scope(p, roots) and regular(p,True):add(a,p,'Dados Microsoft Store','Identidade exata da família de pacote','caminho identificado')
    pending=[]
    for root in roots:
        p=Path(root)
        if regular(p,True):pending.append(p)
        else:errors.append({'path':str(p),'reason':'Raiz indisponível, protegida ou redirecionada'})
    visited=set(); last=0
    while pending:
        if cancel and cancel.is_set():break
        folder=pending.pop(); k=key(folder)
        if k in visited:continue
        visited.add(k)
        if excluded_path(folder):skipped.append({'path':str(folder),'reason':'Exclusão explícita (backups/aplicativo)'});continue
        if not regular(folder,True):skipped.append({'path':str(folder),'reason':'Link, junção ou diretório indisponível'});continue
        dirs+=1; counters(folder)['directories']+=1; names=[]; subdirs=[]
        try:
            with os.scandir(folder) as stream:
                for e in stream:
                    if cancel and cancel.is_set():break
                    try:
                        s=e.stat(follow_symlinks=False)
                        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
                            skipped.append({'path':e.path,'reason':'Link/junção não seguido'});continue
                        if stat.S_ISDIR(s.st_mode):subdirs.append(Path(e.path))
                        elif stat.S_ISREG(s.st_mode):names.append(e.name);files+=1;counters(folder)['files']+=1
                    except OSError as exc:errors.append({'path':e.path,'reason':str(exc)})
        except OSError as exc:
            errors.append({'path':str(folder),'reason':str(exc)});continue
        pending.extend(subdirs)
        children={p.name.casefold() for p in subdirs}; low={n.casefold() for n in names}
        for a in by_root.get(k,[]):add(a,folder,'Pasta da instalação','Caminho do registro/atalho; não garante todos os dados','caminho identificado')
        for a in by_name.get(signature(folder.name),[]):
            add(a,folder,'Pasta com nome correspondente','Nome completo normalizado; conteúdo e propriedade ainda não confirmados')
        for filename in names:
            if cancel and cancel.is_set():break
            if not filename.lower().endswith('.exe'):continue
            exe=folder/filename
            try:metadata=executable_metadata(exe)
            except (OSError, ValueError) as exc:
                errors.append({'path':str(exe),'reason':'VERSIONINFO: '+str(exc)});metadata={}
            product=metadata.get('ProductName','').strip()
            if product and not by_name.get(signature(product)):
                candidate={'id':'executable:'+key(exe),'name':product,'publisher':metadata.get('CompanyName',''),
                           'version':metadata.get('FileVersion',''),'source':'Produto declarado no executável (instalação não confirmada)',
                           'category':'Executável / possível aplicativo','install_location':str(folder)}
                entries.append(candidate)
                add(candidate,folder,'Possível instalação / portátil','VERSIONINFO: '+product+' | '+metadata.get('CompanyName','')+'; assinatura não verificada')
            elif not product and not by_name.get(signature(Path(filename).stem)):
                unmatched.append(str(exe))
            for a in by_name.get(signature(metadata.get('ProductName','')),[]):
                add(a,folder,'Executável com produto correspondente','VERSIONINFO: '+metadata.get('ProductName','')+' | '+metadata.get('CompanyName','')+' | '+metadata.get('FileVersion','')+'; recurso declarado, não assinatura validada','produto correspondente')
            for a in by_name.get(signature(Path(filename).stem),[]):
                add(a,folder,'Executável com nome correspondente',filename+'; correspondência de nome, revisar')
        classic='osu!.exe' in low and ('osu!.db' in low or ('songs' in children and any(n.startswith('osu!') and n.endswith('.cfg') for n in low)))
        lazer='client.realm' in low and 'files' in children
        if classic or lazer:
            edition='stable' if classic else 'lazer'
            owners=[a for a in entries if signature(a['name']) in ('osu','osulazer','osustable') and (('lazer' in a['name'].lower())==(edition=='lazer'))]
            if not owners:
                a={'id':'portable:osu:'+edition+':'+k,'name':'osu! clássico (stable)' if classic else 'osu! lazer','publisher':'ppy','install_location':str(folder),'edition':edition,'source':'Estrutura encontrada na varredura','category':'Jogo / dados locais'}
                entries.append(a);owners=[a]
            for a in owners:
                add(a,folder,'Instalação osu! '+edition,'Estrutura de arquivos compatível com '+edition,'estrutura identificada',edition)
                data=classic_data(folder,names,roots) if classic else [(folder/'files','Biblioteca lazer'),(folder/'client.realm','Banco lazer')]
                for path,kind in data:add(a,path,kind,'Estrutura osu! '+edition,'estrutura identificada',edition)
        now=time.monotonic()
        if progress and now-last>0.25:progress(dirs,files,str(folder));last=now
    cancelled=bool(cancel and cancel.is_set())
    return {'schema':'pcro-discovery-v1','roots':[str(r) for r in roots],'excluded':list(excluded),
            'status':'cancelada_parcial' if cancelled else ('concluida_com_lacunas' if errors or skipped else 'concluida'),
            'directories':dirs,'files':files,'volume_stats':volume_stats,'elapsed_seconds':round(time.time()-start,2),'records':records,
            'apps':entries,'errors':errors,'skipped':skipped,'unassociated_executables':unmatched,
            'notice':'Associações por nome são candidatos. Não prova cobertura universal, backup ou reinstalação equivalente.'}
