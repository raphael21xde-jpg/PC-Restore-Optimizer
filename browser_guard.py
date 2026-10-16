"""Proteção de dados do Opera GX por arquivo AES-256-GCM independente.

Não lê, descriptografa ou exporta senhas do navegador. CSV de senhas só pode ser
incluído se o próprio usuário exportá-lo e selecioná-lo explicitamente.
Restaurar sempre para pasta de conferência; nunca sobrescreve perfil real.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
from datetime import datetime
from typing import Callable
import uuid

MAGIC = b'PCRO-GX-1'
HEADER = len(MAGIC) + 16 + 12
TAG_LENGTH = 16
BUFFER = 1024 * 1024
# Arquivos contendo dados úteis. Todos permanecem criptografados no destino.
FILES = ('Bookmarks', 'Bookmarks.bak', 'BookmarksExtras', 'History', 'History-journal',
         'Favicons', 'Preferences', 'Secure Preferences', 'Current Session',
         'Current Tabs', 'Last Session', 'Last Tabs', 'Visited Links', 'Web Data')
FOLDERS = ('Sessions', 'Extensions', 'Extension State', 'Extension Rules',
           'Local Extension Settings', 'Themes_backup', 'Preferences')
# Estes dados podem conter tokens de login, cookies e dados pessoais de sites.
EXTENDED_FOLDERS = ('Local Storage', 'IndexedDB', 'Session Storage', 'Databases')
# Estes arquivos NUNCA são copiados via descoberta automatizada.
FORBIDDEN_NAMES = {'Login Data', 'Login Data For Account', 'Cookies',
                   'Network', 'Sync Data', 'Local State', 'TransportSecurity'}


def get_profiles():
    """Encontra perfis prováveis sem abrir bancos de dados nem ler credenciais."""
    base = os.environ.get('APPDATA')
    if not base:
        return []
    folder = Path(base) / 'Opera Software'
    if not folder.is_dir():
        return []
    profiles = []
    for child in folder.iterdir():
        if not child.is_dir() or not child.name.lower().startswith('opera gx'):
            continue
        for candidate in [child, *[p for p in child.iterdir()
                                      if p.is_dir() and (p.name == 'Default' or re.fullmatch(r'Profile \d+', p.name))]]:
            if any((candidate / item).exists() for item in ('Bookmarks', 'History', 'Preferences', 'Sessions')):
                profiles.append(candidate)
    return profiles


def opera_may_be_running():
    """Conferência auxiliar; não substitui fechar completamente o navegador."""
    if os.name != 'nt':
        return False
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq opera.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, timeout=8, check=False)
        return '"opera.exe"' in out.stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_special(p: Path):
    try:
        return p.is_symlink() or p.is_junction()
    except AttributeError:
        return p.is_symlink()


def inspect_profile(profile: Path, extended: bool = False):
    """Lista apenas caminhos, sem ler o conteúdo."""
    profile = Path(profile).resolve(strict=True)
    if not profile.is_dir():
        raise ValueError('O perfil precisa ser uma pasta.')
    candidates = [profile / p for p in FILES + FOLDERS + (EXTENDED_FOLDERS if extended else ())]
    selected = []
    for path in candidates:
        if path.name in FORBIDDEN_NAMES or not path.exists() or is_special(path):
            continue
        # Rejeita sobreposição caso pasta de nome igual apareça mais de uma vez.
        if path not in selected:
            selected.append(path)
    return selected


def _kdf(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise ValueError('Use uma frase-senha com pelo menos 12 caracteres.')
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _crypto():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError('Recurso de criptografia ausente. Instale: py -m pip install cryptography') from exc


class _CipherWriter:
    def __init__(self, sink, enc):
        self.sink, self.enc = sink, enc
        self.pos = 0

    def write(self, data):
        if not data:
            return 0
        self.sink.write(self.enc.update(data))
        self.pos += len(data)
        return len(data)

    def tell(self):
        return self.pos

    def flush(self):
        self.sink.flush()


def _source_files(profile: Path, extended=False):
    profile = Path(profile).resolve(strict=True)
    for item in inspect_profile(profile, extended):
        if item.is_file() and not is_special(item):
            yield item
        elif item.is_dir():
            for base, dirs, files in os.walk(item, followlinks=False):
                dirs[:] = [d for d in dirs if d not in FORBIDDEN_NAMES and not is_special(Path(base) / d)]
                for name in files:
                    path = Path(base) / name
                    if name not in FORBIDDEN_NAMES and path.is_file() and not is_special(path):
                        yield path


def create_encrypted_backup(profile, destination_folder, password, *, extended=False,
                            password_csv=None, progress: Callable[[str], None] | None = None):
    """Gera pacote criptografado. O arquivo CSV, se houver, é de exportação MANUAL do Opera.

    Nenhum conteúdo do perfil é disponibilizado em JSON/logs; nunca inclui bancos
    de senhas/sessões via varredura automática. Mantém fontes intactas.
    """
    Cipher, algorithms, modes = _crypto()
    profile = Path(profile).resolve(strict=True)
    if not profile.is_dir():
        raise ValueError('Perfil de navegador inválido')
    destination_folder = Path(destination_folder).resolve(strict=True)
    if not destination_folder.is_dir():
        raise ValueError('A pasta de destino não existe')
    if destination_folder == profile or profile in destination_folder.parents or destination_folder in profile.parents:
        raise ValueError('Destino não pode estar dentro do perfil (nem ser seu ancestral).')
    src_files = list(_source_files(profile, extended))
    if not src_files:
        raise ValueError('Não há arquivos conhecidos para salvar nesse perfil.')
    csv = None
    if password_csv:
        csv = Path(password_csv).resolve(strict=True)
        if not csv.is_file() or csv.suffix.lower() != '.csv':
            raise ValueError('Selecione um CSV exportado manualmente pelo Opera.')
        if csv in src_files:
            raise ValueError('O CSV de senhas precisa ficar fora do perfil.')
    inputs = [(p, str(Path('profile') / p.relative_to(profile)).replace('\\', '/')) for p in src_files]
    if csv:
        inputs.append((csv, 'senhas_exportadas_MANUALMENTE.csv'))
    reserve = sum(p.stat().st_size for p, _ in inputs)
    if shutil.disk_usage(destination_folder).free < reserve + 128 * 1024 * 1024:
        raise OSError('Espaço livre insuficiente para proteger o perfil do navegador.')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = _kdf(password, salt)
    crypt = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = destination_folder / f'OperaGX-protegido-{stamp}-{uuid.uuid4().hex[:6]}.opgx'
    partial = target.with_suffix('.opgx.partial')
    total = 0
    try:
        with partial.open('xb') as file:
            file.write(MAGIC + salt + nonce)
            writer = _CipherWriter(file, crypt)
            with tarfile.open(fileobj=writer, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for source, stored in inputs:
                    if is_special(source) or not source.is_file():
                        raise OSError(f'Arquivo mudou durante o backup: {source.name}')
                    if progress:
                        progress(f'Criptografando: {stored}')
                    # tarfile.add não segue links, mas conferimos novamente acima.
                    original = source.stat()
                    archive.add(str(source), arcname=stored, recursive=False)
                    after = source.stat()
                    if original.st_size != after.st_size or original.st_mtime_ns != after.st_mtime_ns:
                        raise OSError(f'O arquivo mudou durante a cópia: {stored}. Feche o Opera GX e tente novamente.')
                    total += after.st_size
            writer.write(crypt.finalize())
            file.write(crypt.tag)
            file.flush()
            os.fsync(file.fileno())
        # Testa autenticação do pacote antes de avisar que a cópia foi criada.
        verify_encrypted_backup(partial, password)
        partial.replace(target)
        return target, len(inputs), total
    finally:
        if partial.exists():
            partial.unlink()


class _DecryptReader:
    def __init__(self, f, dec, ciphertext_length):
        self.f, self.dec, self.remaining = f, dec, ciphertext_length

    def read(self, size=-1):
        if self.remaining == 0:
            return b''
        if size is None or size < 0:
            size = BUFFER
        data = self.f.read(min(size, self.remaining))
        if not data:
            raise EOFError('Arquivo cifrado truncado')
        self.remaining -= len(data)
        return self.dec.update(data)


def _decrypt_container(path, password, on_tar):
    Cipher, algorithms, modes = _crypto()
    path = Path(path)
    size = path.stat().st_size
    if size < HEADER + TAG_LENGTH:
        raise ValueError('Arquivo de backup inválido')
    with path.open('rb') as src:
        header = src.read(HEADER)
        if header[:len(MAGIC)] != MAGIC:
            raise ValueError('Formato de backup de navegador desconhecido')
        salt = header[len(MAGIC):len(MAGIC)+16]
        nonce = header[-12:]
        src.seek(-TAG_LENGTH, os.SEEK_END)
        tag = src.read(TAG_LENGTH)
        src.seek(HEADER)
        decryptor = Cipher(algorithms.AES(_kdf(password, salt)), modes.GCM(nonce, tag)).decryptor()
        reader = _DecryptReader(src, decryptor, size - HEADER - TAG_LENGTH)
        with tarfile.open(fileobj=reader, mode='r|') as tar:
            on_tar(tar)
        while reader.read(BUFFER):
            pass
        decryptor.finalize()  # autentica todo o conteúdo antes de devolver sucesso


def verify_encrypted_backup(path, password):
    names = []
    def scan(tar):
        for m in tar:
            if not m.isfile() or m.issym() or m.islnk():
                raise ValueError('Entrada de arquivo inválida no pacote')
            names.append(m.name)
            if m.size > 100 * 1024**3:
                raise ValueError('Arquivo interno grande demais')
            f = tar.extractfile(m)
            if f:
                while f.read(BUFFER):
                    pass
    _decrypt_container(path, password, scan)
    return names


def extract_to_staging(path, target_parent, password):
    """Extrai para pasta NOVA, sem sobrescrever perfil Opera; exige autenticação AEAD."""
    target_parent = Path(target_parent).resolve(strict=True)
    if not target_parent.is_dir():
        raise ValueError('Destino da restauração deve existir.')
    new = target_parent / ('CONFERIR-OperaGX-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    new.mkdir()
    try:
        def extract(tar):
            for m in tar:
                rel = Path(m.name)
                if not m.isfile() or m.issym() or m.islnk() or rel.is_absolute() or '..' in rel.parts or m.size > 100 * 1024**3:
                    raise ValueError('Entrada insegura no pacote.')
                full = new / rel
                if not full.resolve().is_relative_to(new.resolve()):
                    raise ValueError('Caminho inseguro na restauração.')
                full.parent.mkdir(parents=True, exist_ok=True)
                reader = tar.extractfile(m)
                with full.open('xb') as dst:
                    if reader:
                        shutil.copyfileobj(reader, dst, BUFFER)
        _decrypt_container(path, password, extract)
        return new
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        raise
