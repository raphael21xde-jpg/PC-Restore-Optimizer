"""Inventário conservador de dados de aplicativos instalados, SEM copiar/ler conteúdo.

Não existe localização universal para configurações. Heurísticas dão apenas
candidatos, nunca cópia automática. Locais conhecidos podem ter dados privados:
revisar sempre a prévia antes de copiar e manter backup em mídia controlada.
"""
from __future__ import annotations
from pathlib import Path
import os
import re
import stat
import unicodedata
from collections import deque
from scan_scope import in_scope

# Pastas conhecidas, mas NÃO automaticamente aprovadas: perfis de periféricos
# podem armazenar identificadores de dispositivo, login e tokens.
APP_HINTS = {
    'logitech g hub': [('localappdata', 'LGHUB'), ('appdata', 'LGHUB')],
    'logitech gaming software': [('localappdata', 'Logitech/Logitech Gaming Software')],
    'razer synapse': [('programdata', 'Razer/Synapse3'), ('localappdata', 'Razer'),
                      ('appdata', 'Razer/Synapse3')],
    'corsair icue': [('appdata', 'Corsair/CUE'), ('appdata', 'Corsair/CUE5'),
                     ('localappdata', 'Corsair/CUE'), ('localappdata', 'Corsair/CUE5')],
    'steelseries gg': [('appdata', 'SteelSeries'), ('programdata', 'SteelSeries')],
    'hyperx ngenuity': [],  # UWP: identificações de pacote verificadas abaixo
    'msi center': [('programdata', 'MSI')],
    'nzxt cam': [('appdata', 'NZXT CAM')],
    'elgato stream deck': [('appdata', 'Elgato/StreamDeck')],
    'obs studio': [('appdata', 'obs-studio')],
    'discord': [('appdata', 'discord')],
}

# Pasta inteira de perfil de navegador ou cache do app NÃO é um backup de
# configurações seguro; precisa de tratamento especializado / criptografia.
BLOCKED_NAMES = {
    'cache', 'caches', 'code cache', 'gpucache', 'temp', 'tmp', 'logs',
    'node_modules', 'cookies', 'network', 'login data', 'local state',
    'user data', 'userdata', 'credentials', 'credential', 'secrets',
    'tokens', 'session storage', 'indexeddb', 'service worker',
    'opera software', 'google', 'mozilla', 'microsoft',
}
BLOCKED_EXACT = {'packages', 'program files', 'program files (x86)', 'windows'}
# Correspondências de família UWP específicas; nunca selecionadas automaticamente.
UWP_HINTS = {'hyperx ngenuity': ('ngenuity',), 'msi center': ('msicenter',),
             'razer synapse': ('razersynapse',)}


def normalized_name(value):
    s = unicodedata.normalize('NFKD', str(value).casefold())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', s)


def matching_app_folder(app_name, folder_name):
    """Exige nome completo; nunca casa apenas 'Razer' ou 'Software'."""
    a, b = normalized_name(app_name), normalized_name(folder_name)
    if len(a) < 5 or len(b) < 5:
        return False
    # Aceita sufixos de versão, não atalhos por nome parcial.
    if b == a:
        return True
    return b.startswith(a) and bool(re.fullmatch(r'(?:v?\d[\da-z.]*)+', b[len(a):]))


def _safe_dir(path):
    try:
        info = os.stat(path, follow_symlinks=False)
        return stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return False


def _safe_file(path):
    try:
        info = os.stat(path, follow_symlinks=False)
        return stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return False


def _has_files(path, depth=2, limit=250):
    if _safe_file(path):
        return True
    if not _safe_dir(path):
        return False
    pending = deque([(Path(path), 0)])
    scanned = 0
    while pending and scanned < limit:
        folder, level = pending.popleft()
        try:
            with os.scandir(folder) as records:
                for entry in records:
                    scanned += 1
                    if scanned >= limit:
                        return False
                    if entry.is_symlink():
                        continue
                    if entry.name.casefold() in BLOCKED_NAMES:
                        continue
                    if _safe_file(entry.path):
                        return True
                    if level < depth and entry.name.casefold() not in BLOCKED_NAMES and _safe_dir(entry.path):
                        pending.append((Path(entry.path), level+1))
        except OSError:
            return False
    return False


def _roots():
    home = Path(os.getenv('USERPROFILE', str(Path.home())))
    local = Path(os.getenv('LOCALAPPDATA', str(home / 'AppData/Local')))
    roaming = Path(os.getenv('APPDATA', str(home / 'AppData/Roaming')))
    program = Path(os.getenv('PROGRAMDATA', 'C:/ProgramData'))
    return {'appdata': [roaming], 'localappdata': [local],
            'locallow': [local.parent / 'LocalLow'], 'programdata': [program],
            'documents': [home / 'Documents', home / 'OneDrive/Documents']}


def _sensitive(path, anchor):
    try:
        pieces = Path(path).relative_to(Path(anchor)).parts
    except ValueError:
        return True
    return any(x.casefold() in BLOCKED_NAMES for x in pieces)


def find_app_data(apps, *, roots=None, allowed_roots=None):
    """Retorna evidências, não garantias. Só retorna 'possivel' para aplicativos.

    Não lê dados pessoais, não percorre unidades inteiras nem segue atalhos.
    Locais de perfil inteiros jamais viram backups automáticos.
    """
    roots = roots if roots is not None else _roots()
    if allowed_roots is not None:
        roots = {kind: [path for path in paths if in_scope(path, allowed_roots)]
                 for kind, paths in roots.items()}
    candidates = []
    seen = set()
    apps = [a for a in (apps or []) if a.get('name') and isinstance(a.get('name'), str)]
    def add(app, path, source, anchor):
        path = Path(path)
        if (allowed_roots is not None and not in_scope(path, allowed_roots)) or path.name.casefold() in BLOCKED_EXACT or _sensitive(path, anchor):
            return
        if not _has_files(path):
            return
        key = (app.get('id') or app['name'].casefold(), str(path).casefold())
        if key in seen:
            return
        seen.add(key)
        candidates.append({'app': app['name'], 'app_id': app.get('id', ''),
                           'path': str(path), 'confidence': 'possivel',
                           'source': source, 'data_kind': 'config'})
    for app in apps:
        simple_name = normalized_name(app['name'])
        for title, hints in APP_HINTS.items():
            if simple_name == normalized_name(title) or simple_name.startswith(normalized_name(title)):
                for kind, suffix in hints:
                    if suffix.casefold() == 'packages':
                        continue  # Apps Store precisam identificação de pacote por registro
                    for root in roots.get(kind, []):
                        add(app, Path(root) / Path(suffix), 'pasta conhecida de aplicativo (revisar)', root)
        # Pasta de nome exatamente igual ao aplicativo, sem pesquisar subpastas alheias.
        for kind in ('appdata', 'localappdata', 'locallow', 'programdata', 'documents'):
            for root in roots.get(kind, []):
                if not _safe_dir(root):
                    continue
                try:
                    with os.scandir(root) as entries:
                        children = [e for i, e in enumerate(entries) if i < 800 and
                                    e.is_dir(follow_symlinks=False) and not e.is_symlink()]
                except OSError:
                    continue
                for child in children:
                    if child.name.casefold() in BLOCKED_NAMES or child.name.casefold() in BLOCKED_EXACT:
                        continue
                    if matching_app_folder(app['name'], child.name):
                        add(app, Path(child.path), f'pasta {kind} com nome correspondente (revisar)', root)
    # Apps da Microsoft Store (somente famílias com identidade suficientemente
    # específica); não percorrer todos os dados de todas as packages.
    for app in apps:
        name = normalized_name(app['name'])
        for title, fragments in UWP_HINTS.items():
            if not (name == normalized_name(title) or name.startswith(normalized_name(title))):
                continue
            for local in roots.get('localappdata', []):
                packages = Path(local)/'Packages'
                if not _safe_dir(packages):
                    continue
                try:
                    with os.scandir(packages) as entries:
                        families = [e for i,e in enumerate(entries) if i<1200 and
                                    e.is_dir(follow_symlinks=False) and not e.is_symlink()]
                except OSError:
                    continue
                for family in families:
                    fname = normalized_name(family.name.split('_')[0])
                    if not any(fragment in fname for fragment in fragments):
                        continue
                    for sub in ('LocalState', 'RoamingState', 'Settings'):
                        path = Path(family.path)/sub
                        if _safe_dir(path) and _has_files(path):
                            add(app, path, 'Microsoft Store: pasta de estado do pacote (revisar)', path.parent)
    return candidates


def associate_app_data(app, candidates):
    """Não casa por nome sozinho quando IDs de registro estão disponíveis."""
    result = []
    for item in candidates:
        if item.get('app_id') and app.get('id'):
            matched = item['app_id'] == app['id']
        else:
            matched = normalized_name(item.get('app', '')) == normalized_name(app.get('name', ''))
        if matched and item['path'] not in result:
            result.append(item['path'])
    return result
