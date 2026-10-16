"""Inventário de saves/configurações para o PC Restore 0.5.2: somente leitura.

Identificações de confiança alta usam localização conhecida + pasta com arquivos.
Heurísticas e cópias de Steam userdata são apenas *candidatas*; não se
promete cobertura total, Steam Cloud nem autenticidade de saves desconhecidos.
"""
from __future__ import annotations
from collections import deque
from pathlib import Path
import os
import re
import stat
import unicodedata

KNOWN = {
    'Terraria': [('documents', 'My Games/Terraria')],
    'Stardew Valley': [('appdata', 'StardewValley/Saves')],
    'Hollow Knight': [('localappdata', 'Team Cherry/Hollow Knight')],
    'Celeste': [('appdata', 'Celeste/Saves'), ('home', 'AppData/Local/Celeste/Saves')],
    'Elden Ring': [('appdata', 'EldenRing')],
    'Dark Souls III': [('appdata', 'DarkSoulsIII')],
    'Sekiro': [('appdata', 'Sekiro')],
    'Baldur’s Gate 3': [('localappdata', "Larian Studios/Baldur's Gate 3/PlayerProfiles")],
    'The Witcher 3': [('documents', 'The Witcher 3/gamesaves')],
    'Cyberpunk 2077': [('userprofile', 'Saved Games/CD Projekt Red/Cyberpunk 2077')],
    'Kingdom Come: Deliverance': [('userprofile', 'Saved Games/kingdomcome/saves')],
    'Fallout 4': [('documents', 'My Games/Fallout4/Saves')],
    'Fallout 76': [('documents', 'My Games/Fallout 76')],
    'Skyrim': [('documents', 'My Games/Skyrim Special Edition/Saves')],
    'God of War': [('userprofile', 'Saved Games/God of War')],
    'God of War Ragnarök': [('userprofile', 'Saved Games/God of War Ragnarök'),
                             ('userprofile', 'Saved Games/God of War Ragnarok')],
    'Red Dead Redemption 2': [('documents', 'Rockstar Games/Red Dead Redemption 2/Profiles')],
    'Stray': [('localappdata', 'Hk_project/Saved/SaveGames')],
    'R.E.P.O.': [('locallow', 'semiwork/Repo/saves')],
}

# Configurações locais: não equivalem a progresso/salvamento de campanha.
CONFIG_FOLDERS = {
    'Fortnite': [('localappdata', 'FortniteGame/Saved/Config/WindowsClient')],
    'Overwatch': [('documents', 'Overwatch/Settings')],
}
# Títulos cujo progresso principal está nos servidores. Dados locais ainda podem
# incluir ajustes pessoais e devem ser guardados separadamente, quando existirem.
ONLINE_PROGRESS = ('Fortnite', 'Overwatch', 'Overwatch 2')
# Apenas onde o AppID + localização de saves foi documentado especificamente.
KNOWN_STEAM_REMOTE = {'1182900': 'A Plague Tale: Requiem'}

# Aliases explícitos, sem inferir que jogos diferentes da mesma série são iguais.
ALIASES = {
    'The Witcher 3': ('The Witcher 3 Wild Hunt', 'Witcher 3', 'Witcher 3 Wild Hunt'),
    'Skyrim': ('The Elder Scrolls V Skyrim', 'Skyrim Special Edition', 'Skyrim Anniversary Edition'),
    'Baldur’s Gate 3': ('Baldurs Gate 3',),
    'Dark Souls III': ('Dark Souls 3',),
    'God of War Ragnarök': ('God of War Ragnarok',),
    'R.E.P.O.': ('REPO', 'R E P O'),
    'Counter-Strike 2': ('Counter Strike 2', 'CS2'),
    'Red Dead Redemption 2': ('Red Dead 2', 'RDR2'),
}
# Somente palavras de *edição*, não franquias ou nomes de expansões desconhecidos.
EDITION_WORDS = {
    'remastered', 'remaster', 'complete', 'edition', 'definitive', 'enhanced',
    'ultimate', 'deluxe', 'gold', 'goty', 'game', 'of', 'the', 'year',
    'directors', 'cut', 'special', 'anniversary', 'steam', 'pc', 'version',
}
SAVE_NAMES = {'save', 'saves', 'saved', 'savegame', 'savegames', 'gamesaves', 'profile', 'profiles',
              'playerprofiles', 'player', 'players', 'worlds'}
IGNORED = {'temp', 'cache', 'gpucache', 'code cache', 'node_modules', 'windows', 'microsoft',
           'google', 'discord', 'opera software', 'mozilla', 'nvidia', 'packages',
           'program files', 'program files (x86)', 'steamapps', 'steam', 'backups'}


def _tokens(value):
    normal = unicodedata.normalize('NFKD', str(value).casefold())
    normal = ''.join(c for c in normal if not unicodedata.combining(c))
    return re.findall(r'[a-z0-9]+', normal)


def same_game(known_name, installed_name):
    """Conservador: nome completo/alias + possíveis sufixos de edição."""
    title = _tokens(installed_name)
    if not title:
        return False
    for alias in (known_name, *ALIASES.get(known_name, ())):
        base = _tokens(alias)
        if title == base:
            return True
        if len(title) > len(base) and title[:len(base)] == base:
            if all(token in EDITION_WORDS for token in title[len(base):]):
                return True
    return False


def _safe_directory(path):
    try:
        obj = os.stat(path, follow_symlinks=False)
        return (stat.S_ISDIR(obj.st_mode) and
                not bool(getattr(obj, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))
    except OSError:
        return False


def _has_files(folder, depth=2):
    """Existência de dados, nunca leitura de conteúdo. Limites contra pastas enormes."""
    pending = [(folder, 0)]
    examined = 0
    while pending and examined < 180:
        path, level = pending.pop()
        try:
            with os.scandir(path) as items:
                for item in items:
                    examined += 1
                    if examined > 180:
                        return False  # não presumir sucesso se busca excedeu limite
                    if item.is_symlink():
                        continue
                    if item.is_file(follow_symlinks=False):
                        return True
                    if level < depth and item.is_dir(follow_symlinks=False) and _safe_directory(item.path):
                        pending.append((item.path, level+1))
        except OSError:
            return False
    return False


def _windows_documents(home):
    """Pasta Documentos real (registro) com alternativas seguras para OneDrive."""
    output = []
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                path, _ = winreg.QueryValueEx(key, 'Personal')
                if isinstance(path, str):
                    output.append(Path(os.path.expandvars(path)))
        except (OSError, ImportError):
            pass
    output += [home / 'Documents', home / 'OneDrive' / 'Documents']
    for env in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        if os.getenv(env):
            output.append(Path(os.environ[env]) / 'Documents')
    return list(dict.fromkeys(output))


def _roots():
    home = Path(os.getenv('USERPROFILE', str(Path.home())))
    local = Path(os.getenv('LOCALAPPDATA', str(home/'AppData/Local')))
    return dict(home=[home], userprofile=[home], documents=_windows_documents(home),
                appdata=[Path(os.getenv('APPDATA', str(home/'AppData/Roaming')))],
                localappdata=[local], locallow=[local.parent/'LocalLow'])


def _local_saves(roots):
    found, seen = [], set()
    for game, candidates in KNOWN.items():
        for key, suffix in candidates:
            for root in roots.get(key, []):
                path = root / Path(suffix)
                label = str(path).casefold()
                if label not in seen and _safe_directory(path) and _has_files(path, depth=4 if game == 'Stray' else 2):
                    found.append(dict(game=game, path=str(path), source='save local conhecido',
                                      confidence='alta', data_kind='save', launcher=None, appid=None))
                    seen.add(label)
    return found


def _local_configurations(roots):
    """Configurações de Fortnite/Overwatch, sem alegar save local."""
    found = []
    for game, candidates in CONFIG_FOLDERS.items():
        for key, suffix in candidates:
            for base in roots.get(key, []):
                path = Path(base) / suffix
                if _safe_directory(path) and _has_files(path, 2):
                    found.append(dict(game=game, path=str(path),
                                      source='configurações locais conhecidas',
                                      confidence='alta', data_kind='config',
                                      launcher=None, appid=None))
    return found


def progress_is_online(name):
    return any(same_game(title, name) for title in ONLINE_PROGRESS)


def _steam_client_roots():
    sources = [Path(os.getenv('ProgramFiles(x86)', 'C:/Program Files (x86)'))/'Steam',
               Path(os.getenv('ProgramFiles', 'C:/Program Files'))/'Steam']
    for drive in 'CDEFGHIJKLMNOP':
        sources += [Path(f'{drive}:/Steam'), Path(f'{drive}:/SteamLibrary')]
    return [p for p in dict.fromkeys(sources) if _safe_directory(p/'userdata')]


def _steam_userdata(games, steam_roots=None):
    """Steam userdata/<account>/<appid>/remote; cópia local possível, NÃO cloud garantida."""
    installs = [g for g in (games or []) if g.get('launcher', 'Steam').casefold() == 'steam'
                and re.fullmatch(r'\d+', str(g.get('appid', '')))]
    roots = steam_roots if steam_roots is not None else (_steam_client_roots() if os.name == 'nt' else [])
    found, seen = [], set()
    for client in roots:
        user_data = Path(client)/'userdata'
        if not _safe_directory(user_data):
            continue
        try:
            accounts = list(user_data.iterdir())[:100]
        except OSError:
            continue
        for game in installs:
            for account in accounts:
                if not account.name.isdigit() or not _safe_directory(account):
                    continue
                path = account / str(game['appid']) / 'remote'
                ident = str(path).casefold()
                if ident in seen or not _safe_directory(path) or not _has_files(path, 1):
                    continue
                documented = KNOWN_STEAM_REMOTE.get(str(game['appid']))
                is_known = bool(documented and same_game(documented, game['game']))
                found.append(dict(game=game['game'], path=str(path),
                    source=('save Steam local por AppID (confirmar perfil)' if is_known else
                            'Steam userdata local (conferir conteúdo)'),
                    confidence='alta' if is_known else 'possivel',
                    data_kind='save', launcher='Steam', appid=str(game['appid'])))
                seen.add(ident)
    return found


def _generic_candidates(roots, games, excluded):
    """Varredura rasa e controlada em pastas de usuário; somente sugestões.

    Não percorre discos inteiros, Program Files ou pastas de backup. Usa jogo
    instalado como referência para evitar uma lista gigante de pastas alheias.
    """
    if not games:
        return []
    anchors = []
    for doc in roots.get('documents', []):
        anchors.extend((doc, doc/'My Games'))
    for home in roots.get('userprofile', []):
        anchors.append(home/'Saved Games')
    for kind in ('appdata', 'localappdata', 'locallow'):
        anchors.extend(roots.get(kind, []))
    found, seen = [], set()
    excluded = [Path(p) for p in excluded]
    visited = 0
    for anchor in dict.fromkeys(anchors):
        if not _safe_directory(anchor):
            continue
        queue = deque([(anchor, 0, None)])  # caminho, profundidade, jogo associado
        while queue and visited < 5000:
            folder, depth, owner = queue.popleft()
            if depth >= 3:
                continue
            try:
                with os.scandir(folder) as entries:
                    children = [e for e in entries if e.is_dir(follow_symlinks=False) and not e.is_symlink()]
            except OSError:
                continue
            for item in children[:800]:
                visited += 1
                if visited >= 5000:
                    break
                if not _safe_directory(item.path):
                    continue
                if item.name.casefold() in IGNORED:
                    continue
                path = Path(item.path)
                related = owner
                if related is None:
                    candidates = [g for g in games if (same_game(g['game'], item.name) or same_game(item.name, g['game']))]
                    if len(candidates) == 1:
                        related = candidates[0]
                if related is None:
                    if depth < 2:
                        queue.append((path, depth+1, None))
                    continue
                # Não propor diretório contendo um local conhecido já preservável.
                if not any(path == k or path in k.parents or k in path.parents for k in excluded):
                    if _has_files(path, 1) and str(path).casefold() not in seen:
                        found.append(dict(game=related['game'], path=str(path),
                            source='pasta com nome semelhante (conferir)', confidence='possivel', data_kind='save',
                            launcher=related.get('launcher'), appid=str(related.get('appid', ''))))
                        seen.add(str(path).casefold())
                if item.name.casefold().replace(' ', '') in SAVE_NAMES and depth < 3:
                    # Paths filhos exatos são preferíveis à pasta maior se identificáveis.
                    pass
                if depth < 2:
                    queue.append((path, depth+1, related))
    return found


def _steam_user_configs(games, steam_roots):
    """CS2: dados de configuração por conta; não classificá-los como save.

    Inclui pastas reais em 730/local/cfg e 730/remote. Para evitar relacionar
    dados de outro jogo, exige instalação do CS2 e a identidade Steam 730.
    """
    if not any(g.get('launcher', 'Steam').casefold() == 'steam' and
               str(g.get('appid', '')) == '730' and
               same_game('Counter-Strike 2', g.get('game', '')) for g in (games or [])):
        return []
    found = []
    for root in steam_roots:
        accounts_folder = Path(root) / 'userdata'
        if not _safe_directory(accounts_folder):
            continue
        try:
            accounts = list(accounts_folder.iterdir())[:100]
        except OSError:
            continue
        for account in accounts:
            if not account.name.isdigit() or not _safe_directory(account):
                continue
            for suffix in ('730/local/cfg', '730/remote'):
                path = account / suffix
                if not _safe_directory(path) or not _has_files(path, 1):
                    continue
                found.append(dict(game='Counter-Strike 2', path=str(path),
                                  source='configurações CS2 por conta Steam',
                                  confidence='alta', data_kind='config',
                                  launcher='Steam', appid='730'))
    return found


def _steam_install_custom_cfgs(games):
    """Configuração personalizada CS2 na pasta da instalação Steam.

    Não copia toda a pasta cfg com os arquivos padrão do jogo. Somente
    autoexec.cfg ou o arquivo MRS.cfg indicado pelo usuário.
    Outros *.cfg continuam fora do backup até verificação.
    """
    found = []
    for game in games or []:
        if (game.get('launcher', 'Steam').casefold() != 'steam' or
                str(game.get('appid', '')) != '730' or
                not same_game('Counter-Strike 2', game.get('game', ''))):
            continue
        library = game.get('library')
        if not library:
            continue
        # Nas versões Steam, library aponta para a pasta contendo steamapps.
        lib = Path(library)
        if not _safe_directory(lib/'steamapps'):
            continue
        cfg = lib/'steamapps'/'common'/'Counter-Strike Global Offensive'/'game'/'csgo'/'cfg'
        if not _safe_directory(cfg):
            continue
        try:
            items = list(cfg.iterdir())[:500]
        except OSError:
            continue
        for item in items:
            name = item.name.casefold()
            if not ((name == 'autoexec.cfg' or
                     name == 'mrs.cfg') and
                    item.is_file() and not item.is_symlink()):
                continue
            try:
                if item.stat().st_size > 4 * 1024 * 1024:
                    continue
            except OSError:
                continue
            found.append(dict(game='Counter-Strike 2', path=str(item),
                              source='arquivo cfg personalizado CS2',
                              confidence='alta', data_kind='config',
                              launcher='Steam', appid='730'))
    return found


def _wallpaper_engine_user_data(games, steam_roots):
    """Wallpaper Engine: preservar preferências e criações próprias, NÃO toda a instalação.

    Workshop é gerenciado pela Steam e pode ser muito grande; não incluímos
    automaticamente a pasta workshop/content/431960. Steam userdata/431960 é
    sugestão para conferência por conta, nunca prova de sincronização Steam Cloud.
    """
    found, seen = [], set()
    installed = [g for g in (games or []) if g.get('launcher', 'Steam').casefold() == 'steam'
                 and str(g.get('appid')) == '431960' and same_game('Wallpaper Engine', g.get('game',''))]
    for game in installed:
        library = game.get('library')
        if not library:
            continue
        lib = Path(library)
        if not _safe_directory(lib/'steamapps'):
            continue
        for name in ('wallpaper_engine', 'Wallpaper Engine'):
            base = lib/'steamapps'/'common'/name
            if not _safe_directory(base):
                continue
            # Somente arquivos de configuração claramente identificados.
            for config in ('config.json', 'config.json.bak', 'config_backup.json'):
                file = base/config
                try:
                    if file.is_file() and not file.is_symlink() and file.stat().st_size <= 8*1024*1024:
                        path = str(file)
                        if path.casefold() not in seen:
                            seen.add(path.casefold())
                            found.append(dict(game='Wallpaper Engine', path=path,
                               source='configuração pessoal Wallpaper Engine (revisar)',
                               confidence='alta', data_kind='config', launcher='Steam', appid='431960'))
                except OSError:
                    continue
            personal = base/'projects'/'myprojects'
            if _safe_directory(personal) and _has_files(personal, 4):
                path = str(personal)
                if path.casefold() not in seen:
                    seen.add(path.casefold())
                    found.append(dict(game='Wallpaper Engine', path=path,
                       source='projetos pessoais Wallpaper Engine (revisar tamanho)',
                       confidence='alta', data_kind='config', launcher='Steam', appid='431960'))
    for game in installed:
        library=game.get('library')
        if not library:
            continue
        workshop=Path(library)/'steamapps'/'workshop'/'content'/'431960'
        if _safe_directory(workshop):
            path=str(workshop)
            if path.casefold() not in seen:
                seen.add(path.casefold())
                found.append(dict(game='Wallpaper Engine',path=path,
                   source='conteúdo Workshop (redownload pela Steam; pode ser muito grande)',
                   confidence='possivel', data_kind='config',launcher='Steam',appid='431960'))
    for root in steam_roots:
        userdir = Path(root)/'userdata'
        if not _safe_directory(userdir):
            continue
        try:
            accounts=list(userdir.iterdir())[:100]
        except OSError:
            continue
        if not installed:
            continue
        for account in accounts:
            if not account.name.isdigit() or not _safe_directory(account):
                continue
            candidate = account/'431960'/'remote'
            if _safe_directory(candidate) and _has_files(candidate, 2):
                path=str(candidate)
                if path.casefold() not in seen:
                    seen.add(path.casefold())
                    found.append(dict(game='Wallpaper Engine', path=path,
                      source='Steam userdata Wallpaper Engine (confirmar conta)',
                      confidence='possivel', data_kind='config', launcher='Steam', appid='431960'))
    return found


def find_game_saves(games=None, *, roots=None, steam_roots=None):
    """Lista caminhos de alta confiança e candidatos; não escolhe nem copia nada."""
    roots = roots if roots is not None else _roots()
    known = _local_saves(roots) + _local_configurations(roots)
    steam_clients = steam_roots if steam_roots is not None else (_steam_client_roots() if os.name == 'nt' else [])
    userdata = _steam_userdata(games, steam_clients)
    config = (_steam_user_configs(games, steam_clients) + _steam_install_custom_cfgs(games)
              + _wallpaper_engine_user_data(games, steam_clients))
    generic = _generic_candidates(roots, games, [x['path'] for x in known+userdata+config])
    combined = known + config + userdata + generic
    seen, result = set(), []
    for item in combined:
        key = str(item['path']).casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def associate_saves(installed, candidates):
    """Retorna (locais confiáveis, locais possíveis) para 1 jogo instalado.

    Identidade launcher/appid tem prioridade; coincidência de nome sozinha só
    é aceita para locais KNOWN. Pasta genérica requer conferência humana.
    """
    confirmed, possible = [], []
    for item in candidates:
        ident = (item.get('launcher') and item.get('appid') and
                 str(item.get('launcher')).casefold() == str(installed.get('launcher', 'Steam')).casefold()
                 and str(item.get('appid')) == str(installed.get('appid')))
        named = same_game(item['game'], installed['game']) or same_game(installed['game'], item['game'])
        if not ident and not named:
            continue
        path = item['path']
        target = confirmed if item.get('confidence') == 'alta' and named else possible
        if path not in target:
            target.append(path)
    return confirmed, possible


def find_steam_installs():
    """List games from known Steam libraries without scanning whole disks."""
    if os.name != 'nt':
        return []
    libraries = set()
    roots = [Path(os.getenv('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam',
             Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'Steam']
    for drive in 'CDEFGHIJKLMNOP':
        roots.extend([Path(f'{drive}:/Steam'), Path(f'{drive}:/SteamLibrary')])
    for root in roots:
        if (root / 'steamapps').is_dir():
            libraries.add(root)
    for lib in list(libraries):
        vdf = lib / 'steamapps/libraryfolders.vdf'
        try:
            text = vdf.read_text(encoding='utf-8-sig', errors='replace')
            for match in re.findall(r'"path"\s+"([^"]+)"', text, flags=re.IGNORECASE):
                p = Path(match.replace('\\\\', '\\'))
                if (p / 'steamapps').is_dir():
                    libraries.add(p)
        except OSError:
            continue
    output, seen = [], set()
    for lib in sorted(libraries):
        for manifest in (lib / 'steamapps').glob('appmanifest_*.acf'):
            try:
                data = manifest.read_text(encoding='utf-8-sig', errors='replace')
                name = re.search(r'"name"\s+"([^"]+)"', data, re.IGNORECASE)
                app_id = re.search(r'"appid"\s+"(\d+)"', data, re.IGNORECASE)
                if name and app_id and app_id.group(1) not in seen:
                    output.append({'game': name.group(1), 'appid': app_id.group(1), 'library': str(lib)})
                    seen.add(app_id.group(1))
            except OSError:
                continue
    return sorted(output, key=lambda i: i['game'].casefold())


def find_epic_installs():
    """Jogos Epic pelo inventário local .item; nunca inicia o launcher."""
    if os.name != 'nt':
        return []
    import json
    base = Path(os.getenv('PROGRAMDATA', 'C:/ProgramData')) / 'Epic' / 'EpicGamesLauncher' / 'Data' / 'Manifests'
    games=[]
    if base.is_dir():
        for item in base.glob('*.item'):
            try:
                if item.stat().st_size > 2*1024*1024:
                    continue
                data=json.loads(item.read_text(encoding='utf-8-sig'))
                name=data.get('DisplayName')
                if name and data.get('InstallLocation'):
                    games.append({'game':name,'appid':str(data.get('CatalogItemId') or data.get('AppName') or item.stem),
                                  'library':data.get('InstallLocation'),'launcher':'Epic'})
            except (OSError,ValueError,TypeError):
                continue
    return games


def find_gog_installs():
    """Jogos GOG com chaves de instalação registradas (quando presentes)."""
    if os.name!='nt':
        return []
    import winreg
    result=[]
    for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        for sub in (r'SOFTWARE\GOG.com\Games',r'SOFTWARE\WOW6432Node\GOG.com\Games'):
            try:
                root=winreg.OpenKey(hive,sub)
            except OSError:
                continue
            with root:
                for n in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        gid=winreg.EnumKey(root,n)
                        with winreg.OpenKey(root,gid) as key:
                            name=winreg.QueryValueEx(key,'gameName')[0]
                            try:loc=winreg.QueryValueEx(key,'path')[0]
                            except OSError:loc=''
                            if name:
                                result.append({'game':name,'appid':str(gid),'library':str(loc),'launcher':'GOG'})
                    except OSError:
                        continue
    return result


def find_installed_games():
    """Une launchers suportados; o catálogo não é exaustivo."""
    out=[];seen=set()
    for source,records in [('Steam',find_steam_installs()),('Epic',find_epic_installs()),('GOG',find_gog_installs())]:
        for game in records:
            item=dict(game);item.setdefault('launcher',source)
            key=(source, str(item.get('appid')))
            if key in seen:
                continue
            seen.add(key);out.append(item)
    return sorted(out,key=lambda d:d['game'].casefold())
