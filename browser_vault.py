"""Cofre opt-in para dados de navegadores, sem ler segredos ou controlar contas.

Descoberta: caminhos/metadados. Cópia: apenas arquivos selecionados de perfil + CSV
exportado explicitamente pelo usuário; pacote AES-256-GCM autenticado. Restauração
NUNCA altera perfis reais, sempre para uma pasta nova e isolada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import uuid

MAGIC = b'PCRO-BROWSER-1\0'
HEADER_SIZE = len(MAGIC) + 16 + 12
TAG_SIZE = 16
BUFFER = 1024 * 1024
MAX_ENTRY = 30 * 1024**3
MAX_MANUAL_CSV = 128 * 1024**2

# Explicit links opened by the USER in their own browser, not programmatic logins.
BROWSERS = {
    'Opera GX': {'relative': ('APPDATA', 'Opera Software/Opera GX Stable'), 'type': 'chromium', 'process': 'opera.exe',
                 'sync': 'opera://settings/syncSetup', 'help': 'https://help.opera.com/en/latest/features/'},
    'Opera': {'relative': ('APPDATA', 'Opera Software/Opera Stable'), 'type': 'chromium', 'process': 'opera.exe',
              'sync': 'opera://settings/syncSetup', 'help': 'https://help.opera.com/en/latest/features/'},
    'Google Chrome': {'relative': ('LOCALAPPDATA', 'Google/Chrome/User Data'), 'type': 'chromium-multi', 'process': 'chrome.exe',
                      'sync': 'chrome://settings/syncSetup', 'help': 'https://support.google.com/chrome/answer/13068232'},
    'Microsoft Edge': {'relative': ('LOCALAPPDATA', 'Microsoft/Edge/User Data'), 'type': 'chromium-multi', 'process': 'msedge.exe',
                       'sync': 'edge://settings/profiles/sync', 'help': 'https://support.microsoft.com/pt-br/edge/sign-in-to-sync-microsoft-edge-across-devices'},
    'Brave': {'relative': ('LOCALAPPDATA', 'BraveSoftware/Brave-Browser/User Data'), 'type': 'chromium-multi', 'process': 'brave.exe',
              'sync': 'brave://settings/braveSync/setup', 'help': 'https://support.brave.com/hc/pt/articles/360021218111-Como-configuro-a-Sincroniza%C3%A7%C3%A3o'},
    'Vivaldi': {'relative': ('LOCALAPPDATA', 'Vivaldi/User Data'), 'type': 'chromium-multi', 'process': 'vivaldi.exe',
                'sync': 'vivaldi://settings/sync/', 'help': 'https://help.vivaldi.com/pt-br/desktop-pt-br/ferramentas/sync/'},
    'Chromium': {'relative': ('LOCALAPPDATA', 'Chromium/User Data'), 'type': 'chromium-multi', 'process': 'chrome.exe',
                 'sync': '', 'help': 'https://www.chromium.org/user-experience/'},
    'Mozilla Firefox': {'relative': ('APPDATA', 'Mozilla/Firefox/Profiles'), 'type': 'firefox', 'process': 'firefox.exe',
                        'sync': 'about:preferences#sync', 'help': 'https://support.mozilla.org/pt-BR/kb/sincronizacao'},
}

# Never copy credential/password stores, cookies or device-bound cryptographic keys automatically.
CHROMIUM_FILES = (
    'Bookmarks', 'Bookmarks.bak', 'BookmarksExtras', 'History', 'Visited Links',
    'Preferences', 'Secure Preferences', 'Favicons', 'Shortcuts', 'Top Sites',
)
CHROMIUM_FOLDERS = ('Sessions', 'Extensions', 'Extension State', 'Local Extension Settings',
                    'Extension Rules', 'Local Extension Settings')
CHROMIUM_EXTENDED = ('Local Storage', 'IndexedDB', 'Session Storage')
FIREFOX_FILES = ('places.sqlite', 'favicons.sqlite', 'prefs.js', 'user.js', 'search.json.mozlz4',
                 'sessionstore.jsonlz4', 'containers.json', 'handlers.json', 'extensions.json',
                 'permissions.sqlite', 'formhistory.sqlite')
FIREFOX_FOLDERS = ('bookmarkbackups', 'sessionstore-backups', 'extensions')
FIREFOX_EXTENDED = ('storage',)
FORBIDDEN_PARTS = {x.casefold() for x in (
    'Login Data', 'Login Data For Account', 'Cookies', 'Network', 'Local State', 'Sync Data',
    'Web Data', 'logins.json', 'key4.db', 'key3.db', 'cookies.sqlite', 'cert9.db',
    'signedInUser.json', 'accounts', 'logins-backup.json',
)}

@dataclass(frozen=True)
class BrowserProfile:
    browser: str
    label: str
    path: Path

    @property
    def kind(self):
        return 'firefox' if self.browser == 'Mozilla Firefox' else 'chromium'


def _special(path: Path) -> bool:
    try:
        st = path.lstat()
        return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True


def _allowed_path(profile: Path, path: Path) -> bool:
    # resolve strict and reject junctions at ANY level inside a profile.
    try:
        path.relative_to(profile)
        cursor = path
        while cursor != profile:
            if _special(cursor):
                return False
            cursor = cursor.parent
        return not _special(profile)
    except ValueError:
        return False


def discover_profiles(environ=None):
    env = environ if environ is not None else os.environ
    results = []
    for browser, settings in BROWSERS.items():
        envkey, suffix = settings['relative']
        base = env.get(envkey)
        if not base:
            continue
        root = Path(base) / suffix
        if not root.is_dir() or _special(root):
            continue
        typ = settings['type']
        if typ == 'chromium-multi':
            candidates = [root / 'Default']
            try:
                candidates.extend(sorted((p for p in root.iterdir() if re.fullmatch(r'Profile \d+', p.name)),key=lambda p:p.name))
            except OSError:
                pass
        elif typ == 'firefox':
            try:
                candidates = sorted((p for p in root.iterdir() if p.is_dir()),key=lambda p:p.name)
            except OSError:
                candidates = []
        else:
            candidates = [root]
            try:
                candidates.extend(sorted((p for p in root.iterdir() if p.is_dir() and
                    (p.name == 'Default' or re.fullmatch(r'Profile \d+', p.name))),key=lambda p:p.name))
            except OSError:
                pass
        marker = ('places.sqlite', 'prefs.js', 'bookmarkbackups') if typ == 'firefox' else ('Preferences', 'Bookmarks', 'History', 'Sessions')
        for cand in candidates:
            if cand.is_dir() and not _special(cand) and any((cand / file).exists() for file in marker):
                results.append(BrowserProfile(browser, cand.name, cand))
    return results


def profile_files(profile: BrowserProfile, extended=False):
    root = profile.path
    if not root.is_dir() or _special(root):
        raise ValueError('O perfil selecionado não está acessível ou usa um link/junção.')
    names = (FIREFOX_FILES + FIREFOX_FOLDERS + (FIREFOX_EXTENDED if extended else ())) if profile.kind == 'firefox' else (
        CHROMIUM_FILES + CHROMIUM_FOLDERS + (CHROMIUM_EXTENDED if extended else ()))
    found, seen = [], set()
    for item in names:
        p = root / item
        if not p.exists() or _special(p) or not _allowed_path(root, p):
            continue
        if p.is_file():
            if p.name.casefold() not in FORBIDDEN_PARTS and p not in seen:
                found.append(p); seen.add(p)
        elif p.is_dir():
            for folder, dirs, files in os.walk(p, followlinks=False):
                base = Path(folder)
                dirs[:] = [d for d in dirs if d.casefold() not in FORBIDDEN_PARTS and
                           _allowed_path(root, base/d)]
                for f in files:
                    candidate = base / f
                    if (f.casefold() not in FORBIDDEN_PARTS and candidate.is_file() and
                            _allowed_path(root, candidate) and candidate not in seen):
                        found.append(candidate);seen.add(candidate)
    return sorted(found,key=lambda p: str(p).lower())


def browser_is_running(browser):
    if os.name != 'nt':
        return False
    proc = BROWSERS.get(browser, {}).get('process')
    if not proc:
        return False
    try:
        completed = subprocess.run(['tasklist','/FI',f'IMAGENAME eq {proc}','/FO','CSV','/NH'],
                                    capture_output=True,text=True,timeout=8,check=False)
        return ('"' + proc.lower() + '"') in completed.stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _cipher():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError('Instale a dependência criptográfica com INSTALAR-CRIPTOGRAFIA.bat') from exc
    return Cipher, algorithms, modes


def _derive(phrase, salt):
    if not isinstance(phrase, str) or len(phrase) < 12:
        raise ValueError('A frase-senha precisa de no mínimo 12 caracteres.')
    return hashlib.scrypt(phrase.encode('utf-8'),salt=salt,n=2**14,r=8,p=1,dklen=32)


class _EncryptWriter:
    def __init__(self, output, encryptor):
        self.output=output;self.encryptor=encryptor;self.count=0
    def write(self, data):
        if data:
            self.output.write(self.encryptor.update(data));self.count += len(data)
        return len(data)
    def tell(self):return self.count
    def flush(self):self.output.flush()


class _DecryptReader:
    def __init__(self, stream, decryptor, length):
        self.stream=stream;self.dec=decryptor;self.remaining=length
    def read(self, amount=-1):
        if not self.remaining:return b''
        if amount is None or amount < 0:amount=BUFFER
        block=self.stream.read(min(amount,self.remaining))
        if not block:raise ValueError('Pacote criptografado truncado.')
        self.remaining-=len(block)
        return self.dec.update(block)


def _inspect_tar(tar, on_item=None):
    seen=set(); items=[]; total=0
    for member in tar:
        name=member.name
        rel=PurePosixPath(name)
        if not member.isfile() or member.issym() or member.islnk() or (not name or '\\' in name or ':' in name or
            name.startswith('/') or any(x in ('', '.', '..') for x in name.split('/')) or
            rel.parts[0] not in ('profile', 'manual-export', 'metadata') or
            len(rel.parts) < 2 or member.size > MAX_ENTRY or name in seen):
            raise ValueError('Pacote contém uma entrada inválida ou insegura.')
        seen.add(name);total+=member.size
        if total > 60 * 1024**3:raise ValueError('Pacote excede o limite de segurança.')
        payload = tar.extractfile(member)
        if payload is None:raise ValueError('Arquivo interno ilegível.')
        if on_item:on_item(name, member.size, payload)
        else:
            while payload.read(BUFFER):pass
        items.append(name)
    return items


def _decrypt_package(package, phrase, callback=None):
    Cipher, algorithms, modes = _cipher()
    package=Path(package)
    size=package.stat().st_size
    if size <= HEADER_SIZE + TAG_SIZE:raise ValueError('Pacote inválido ou vazio.')
    with package.open('rb') as inp:
        head=inp.read(HEADER_SIZE)
        if head[:len(MAGIC)] != MAGIC:raise ValueError('O arquivo não é um cofre PC Restore compatível.')
        salt=head[len(MAGIC):len(MAGIC)+16]
        nonce=head[-12:]
        inp.seek(-TAG_SIZE,os.SEEK_END);tag=inp.read(TAG_SIZE)
        inp.seek(HEADER_SIZE)
        decryptor=Cipher(algorithms.AES(_derive(phrase,salt)),modes.GCM(nonce,tag)).decryptor()
        reader=_DecryptReader(inp,decryptor,size-HEADER_SIZE-TAG_SIZE)
        with tarfile.open(fileobj=reader, mode='r|') as tar:
            entries=_inspect_tar(tar,callback)
        while reader.read(BUFFER):pass
        decryptor.finalize()  # authentication must succeed before reporting verified
        return entries


def create_vault(profile: BrowserProfile, destination, phrase, *, extended=False, csv_path=None, bookmarks_html=None):
    Cipher, algorithms, modes = _cipher()
    root=profile.path
    files=profile_files(profile,extended)
    if not files and not csv_path:raise ValueError('Nenhum dado local foi encontrado neste perfil.')
    csv=None
    if csv_path:
        csv=Path(csv_path)
        if csv.suffix.casefold()!='.csv' or not csv.is_file() or _special(csv):
            raise ValueError('Selecione um CSV real exportado MANUALMENTE pelo navegador.')
        if csv.stat().st_size > MAX_MANUAL_CSV:
            raise ValueError('O CSV excede 128 MiB. Confira sua origem antes de selecionar.')
    bookmarks=None
    if bookmarks_html:
        bookmarks=Path(bookmarks_html)
        if bookmarks.suffix.casefold() not in ('.html','.htm') or not bookmarks.is_file() or _special(bookmarks):
            raise ValueError('Selecione um HTML real exportado MANUALMENTE do navegador.')
        if bookmarks.stat().st_size > MAX_MANUAL_CSV:
            raise ValueError('O HTML excede o limite de 128 MiB.')
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    if destination == root.resolve() or root.resolve() in destination.parents:
        raise ValueError('O destino não pode ficar dentro do perfil de navegação.')
    if csv and (destination==csv.resolve().parent or csv.resolve() in destination.parents):
        raise ValueError('O destino não pode ficar dentro da pasta de origem do CSV.')
    source_bytes=sum(p.stat().st_size for p in files)+(csv.stat().st_size if csv else 0)+(bookmarks.stat().st_size if bookmarks else 0)
    if shutil.disk_usage(destination).free < source_bytes + 128*1024**2:
        raise OSError('Espaço livre insuficiente para criar o cofre.')
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    crypt=Cipher(algorithms.AES(_derive(phrase,salt)),modes.GCM(nonce)).encryptor()
    filename=re.sub('[^a-zA-Z0-9-]','-',profile.browser).strip('-')
    label=re.sub('[^a-zA-Z0-9-]', '-', profile.label)[:35]
    contents='Perfil' + ('-Senhas-CSV' if csv else '') + ('-Favoritos-HTML' if bookmarks else '')
    target=destination/f'Backup-Navegador-{filename}-{label}-{contents}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.pcbrowser'
    partial=target.with_suffix('.pcbrowser.partial')
    info={'schema':'pc-restore-browser-v1','browser':profile.browser,'profile':profile.label,
          'created':datetime.now().isoformat(),'profile_items':len(files),'manual_csv':bool(csv),'manual_bookmarks':bool(bookmarks),
          'note':'Restauração de referência; não copia credenciais, cookies ou chaves vinculadas ao dispositivo.'}
    try:
        with partial.open('xb') as out:
            out.write(MAGIC+salt+nonce)
            writer=_EncryptWriter(out,crypt)
            with tarfile.open(fileobj=writer,mode='w|',format=tarfile.PAX_FORMAT) as tar:
                data=json.dumps(info,ensure_ascii=False).encode('utf-8')
                import io
                header=tarfile.TarInfo('metadata/info.json');header.size=len(data);header.mode=0o600
                tar.addfile(header,io.BytesIO(data))
                for src in files:
                    if not _allowed_path(root,src):raise ValueError('Fonte passou a apontar para um link/junção.')
                    before=src.stat()
                    if before.st_size > MAX_ENTRY:raise ValueError('Arquivo muito grande para o cofre.')
                    tar.add(src,arcname='profile/'+src.relative_to(root).as_posix(),recursive=False)
                    after=src.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                        raise OSError('Um arquivo mudou durante a cópia. Feche o navegador e tente novamente.')
                if bookmarks:
                    before=bookmarks.stat()
                    tar.add(bookmarks,arcname='manual-export/favoritos.html',recursive=False)
                    after=bookmarks.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                        raise OSError('O arquivo de favoritos mudou durante a cópia.')
                if csv:
                    before=csv.stat()
                    tar.add(csv,arcname='manual-export/senhas-exportadas.csv',recursive=False)
                    after=csv.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                        raise OSError('O arquivo CSV mudou durante a cópia.')
            writer.write(crypt.finalize());out.write(crypt.tag);out.flush();os.fsync(out.fileno())
        verify_vault(partial,phrase)
        partial.replace(target)
        return target,len(files),source_bytes,bool(csv),bool(bookmarks)
    finally:
        if partial.exists():partial.unlink()


def verify_vault(package, phrase):
    return _decrypt_package(package,phrase)


def restore_to_staging(package, destination, phrase):
    # Authenticate the ENTIRE archive before creating ANY restored files.
    items=verify_vault(package,phrase)
    destination=Path(destination).resolve(strict=True)
    if not destination.is_dir() or _special(destination):raise ValueError('Selecione uma pasta normal e existente.')
    restored=destination/('CONFERIR-NAVEGADOR-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    restored.mkdir(mode=0o700)
    try:
        def save(name, size, reader):
            rel=PurePosixPath(name)
            out=restored.joinpath(*rel.parts)
            if not out.resolve().is_relative_to(restored.resolve()):raise ValueError('Caminho perigoso.')
            out.parent.mkdir(parents=True,exist_ok=True)
            with out.open('xb') as target:
                os.chmod(out,0o600)
                remaining=size
                while remaining:
                    data=reader.read(min(BUFFER,remaining))
                    if not data:raise ValueError('Arquivo interno incompleto.')
                    target.write(data);remaining-=len(data)
        restored_items=_decrypt_package(package,phrase,save)
        if restored_items != items:raise ValueError('Conteúdo mudou durante a restauração.')
        return restored
    except Exception:
        shutil.rmtree(restored,ignore_errors=True)
        raise
