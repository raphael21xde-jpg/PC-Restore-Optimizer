"""P2-05: bibliotecas de launchers de jogos nas unidades locais (somente leitura).

Procura, só olhando nomes de pastas e arquivos, as bibliotecas de Steam, Epic,
EA, Ubisoft, Riot e Rockstar, e devolve um guia em português para religar cada
uma depois de formatar. Nada aqui grava, apaga, renomeia ou executa programas:
o único conteúdo lido é o campo "name" dos appmanifest da Steam (até 64 KiB).

Sem Tk: a tela fica em launcher_guide_ui.py.
"""
from __future__ import annotations

import os
import re
import stat
from collections import deque
from game_saves import _safe_directory
from windows_drive import windows_drive

STEAM = 'Steam'
EPIC = 'Epic Games'
EA = 'EA app'
UBISOFT = 'Ubisoft Connect'
RIOT = 'Riot Games'
ROCKSTAR = 'Rockstar Games'
LAUNCHERS = (STEAM, EPIC, EA, UBISOFT, RIOT, ROCKSTAR)

HIGH = 'alta'
PROBABLE = 'provável'

MANIFEST_LIMIT = 64 * 1024
# Pastas do sistema puladas na raiz de cada unidade (nunca guardam bibliotecas).
SKIP_AT_ROOT = {name.casefold() for name in (
    'Windows', 'Users', 'ProgramData', '$Recycle.Bin', 'System Volume Information',
    'Recovery', '$WinREAgent')}
RIOT_SKIP = {'riot client'}
ROCKSTAR_SKIP = {'launcher', 'social club'}
SYSTEM_DRIVE_WARNING = (
    'Está no disco do Windows: se você formatar este disco, esta pasta será apagada pelo '
    'instalador — faça backup antes.')
_NAME = re.compile(r'"name"\s+"([^"\r\n]*)"', re.IGNORECASE)

LAUNCHER_GUIDES = {
    STEAM: (
        'Steam: biblioteca em "{path}".\n\n'
        'Depois de formatar e instalar a Steam:\n'
        '1. Abra a Steam e entre na sua conta.\n'
        '2. Vá em Steam > Configurações > Armazenamento.\n'
        '3. Clique na lista de unidades e escolha "Adicionar unidade".\n'
        '4. Escolha a pasta "{path}".\n'
        '5. A Steam reconhece os jogos que já estão lá. Se algum aparecer como '
        '"não instalado", clique em Instalar: ela confere os arquivos e só baixa o que faltar.'),
    EPIC: (
        'Epic Games: jogos em "{path}".\n\n'
        'Atenção: a Epic não tem um botão para "adicionar pasta". Ela pode querer baixar '
        'os jogos de novo. Para tentar aproveitar o que já está no disco:\n'
        '1. Não mexa nas pastas dos jogos nem na pasta oculta ".egstore" de cada uma.\n'
        '2. Abra a Epic Games, entre na sua conta e clique em Instalar no jogo.\n'
        '3. Em "Local de instalação", escolha a pasta-mãe "{path}" (a pasta que CONTÉM '
        'a pasta do jogo, não a do próprio jogo).\n'
        '4. A Epic confere os arquivos que já existem ("Verificando").\n'
        '5. Se ela começar a baixar tudo do zero, cancele a instalação: nada se perde, '
        'os arquivos continuam no disco.'),
    EA: (
        'EA app: jogos em "{path}".\n\n'
        'Depois de formatar e instalar o EA app:\n'
        '1. Entre na sua conta e abra a página do jogo na sua biblioteca.\n'
        '2. Clique nos três pontinhos (ou em "Gerenciar") e escolha "Localizar jogo".\n'
        '3. Aponte para a pasta do jogo dentro de "{path}".\n'
        '4. O EA app confere os arquivos e só baixa o que faltar.'),
    UBISOFT: (
        'Ubisoft Connect: jogos em "{path}".\n\n'
        'Depois de formatar e instalar o Ubisoft Connect:\n'
        '1. Entre na sua conta e abra a página do jogo.\n'
        '2. Em vez de "Baixar", clique em "Localizar jogo" (ou "Localizar jogo instalado").\n'
        '3. Aponte para a pasta do jogo dentro de "{path}".\n'
        '4. O Ubisoft Connect confere os arquivos e só baixa o que faltar.'),
    RIOT: (
        'Riot Games: jogos em "{path}".\n\n'
        'Depois de formatar e instalar o Riot Client:\n'
        '1. Entre na sua conta e abra a página do jogo.\n'
        '2. Se aparecer a opção "Localizar jogo" (ou "Escolher local de instalação"), '
        'aponte para a pasta do jogo dentro de "{path}".\n'
        '3. O Riot Client confere os arquivos e só baixa o que faltar.'),
    ROCKSTAR: (
        'Rockstar Games: jogos em "{path}".\n\n'
        'Depois de formatar e instalar o Rockstar Games Launcher:\n'
        '1. Entre na sua conta e vá em Configurações > "Meus jogos instalados".\n'
        '2. Escolha o jogo e clique em "Localizar jogo".\n'
        '3. Aponte para a pasta do jogo dentro de "{path}".\n'
        '4. O launcher confere os arquivos e só baixa o que faltar.'),
}


def guide_for(launcher, path):
    """Passo a passo (texto) para religar a biblioteca depois de formatar."""
    template = LAUNCHER_GUIDES.get(launcher)
    if template is None:
        return f'Biblioteca em "{path}". Use a opção "Localizar jogo" do launcher.'
    return template.format(path=path)


def _empty():
    return {'libraries': [], 'truncated': False, 'warnings': []}


def _on_windows():
    return os.name == 'nt'


def _default_roots(warnings):
    if not _on_windows():
        return []
    try:
        from deep_discovery import local_drives
        return list(local_drives())
    except Exception:  # inventário de volumes indisponível: não inventa unidades
        warnings.append('Não foi possível listar as unidades deste computador.')
        return []


def _list(path):
    """Entradas da pasta como (nome, caminho, é_pasta, é_arquivo, tamanho).

    Links simbólicos e pontos de reparse (junções) ficam de fora. No Windows,
    DirEntry.stat(follow_symlinks=False) já traz st_file_attributes da própria
    listagem (sem abrir o item), então a checagem de junção não custa uma
    chamada a mais por entrada.
    """
    out = []
    try:
        with os.scandir(path) as items:
            for item in items:
                try:
                    if item.is_symlink():
                        continue
                    st = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    continue
                if (getattr(st, 'st_file_attributes', 0) or 0) & _REPARSE:
                    continue
                out.append((item.name, item.path, stat.S_ISDIR(st.st_mode),
                            stat.S_ISREG(st.st_mode), st.st_size))
    except OSError:
        return None
    return out


_REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _steam_games(steamapps_entries, budget):
    """Lê só o campo "name" dos appmanifest_*.acf (máx. 64 KiB cada)."""
    names = []
    for name, path, _is_dir, is_file, size in sorted(steamapps_entries, key=lambda e: e[0].casefold()):
        if not is_file or not name.casefold().startswith('appmanifest_') \
                or not name.casefold().endswith('.acf'):
            continue
        if budget[0] <= 0:
            break
        if size > MANIFEST_LIMIT:
            continue
        budget[0] -= 1
        try:
            with open(path, 'rb') as handle:
                data = handle.read(MANIFEST_LIMIT + 1)
        except OSError:
            continue
        if len(data) > MANIFEST_LIMIT:
            continue
        match = _NAME.search(data.decode('utf-8', errors='replace'))
        if match and match.group(1).strip():
            names.append(match.group(1).strip())
    return sorted(set(names), key=str.casefold)


def _subfolders(entries, skip=()):
    return sorted((name for name, _path, is_dir, _f, _size in entries
                   if is_dir and name.casefold() not in skip), key=str.casefold)


def _cancel_check(cancelled):
    if cancelled is None:
        return lambda: False
    if hasattr(cancelled, 'is_set'):
        return cancelled.is_set
    return cancelled


def _walk_dirs(root, *, max_depth, max_dirs, on_dir, is_cancelled):
    """Largura, sem seguir links/junções. on_dir(path, entries) -> True para não descer.

    Devolve None se terminou, 'limite' se passou de max_dirs pastas nesta
    unidade, 'cancelada' se o cancelamento foi pedido (checado a cada pasta).
    """
    queue = deque([(root, 0)])
    scanned = 0
    while queue:
        if is_cancelled():
            return 'cancelada'
        if scanned >= max_dirs:
            return 'limite'
        path, depth = queue.popleft()
        entries = _list(path)
        scanned += 1
        if entries is None:
            continue
        if on_dir(path, entries):
            continue
        if depth >= max_depth:
            continue
        for name, child, is_dir, _is_file, _size in sorted(entries, key=lambda e: e[0].casefold()):
            if not is_dir:
                continue
            if depth == 0 and name.casefold() in SKIP_AT_ROOT:
                continue
            queue.append((child, depth + 1))
    return None


def _case_key(path):
    """Chave só para comparar caminhos (no Windows ignora maiúsculas). Nunca é mostrada."""
    return os.path.normcase(os.path.abspath(str(path)))


def _drive_key(path):
    return os.path.normcase(str(path)).rstrip('\\/')


UNKNOWN_SYSTEM_DRIVE_WARNING = (
    'Não deu para confirmar qual é o disco do Windows, então nenhuma biblioteca foi '
    'marcada como fora dele. Confira você mesmo em qual disco cada pasta está: o que '
    'estiver no disco do Windows precisa de backup.')


def _default_system_drive(warnings):
    """(unidade, conhecida). Fora do Windows: (None, True), nada a marcar.

    No Windows a letra vem de windows_drive (SystemRoot conferido com
    SystemDrive). Se não der para confirmar: (None, False) e um aviso.
    """
    if not _on_windows():
        return None, True
    letter, _warning = windows_drive()
    if letter is None:
        warnings.append(UNKNOWN_SYSTEM_DRIVE_WARNING)
        return None, False
    return letter, True


def detect_launchers(roots=None, *, max_depth=4, max_dirs=20000, max_manifests=300,
                     cancelled=None, system_drive=None):
    """Procura bibliotecas de jogos. Somente leitura; nunca executa nada.

    roots=None: no Windows usa as unidades locais (deep_discovery.local_drives);
    fora do Windows devolve resultado vazio. max_dirs vale POR unidade.
    cancelled: threading.Event ou função sem argumentos; checado a cada pasta.
    system_drive: unidade do Windows (padrão: windows_drive(), que confere
    %SystemRoot% com %SystemDrive%); as bibliotecas nela recebem
    on_system_drive=True. Se no Windows não der para confirmar a unidade, todas
    recebem on_system_drive=None ("confira") e há um aviso em warnings.
    """
    is_cancelled = _cancel_check(cancelled)
    result = _empty()
    known = True
    if system_drive is None:
        system_drive, known = _default_system_drive(result['warnings'])
    system_key = _drive_key(system_drive) if system_drive else None
    if roots is None:
        roots = _default_roots(result['warnings'])
    # A chave (_case_key) só serve para comparar; a busca e o que aparece usam a
    # grafia original. Mesma unidade escrita de dois jeitos é buscada uma vez só.
    seen_roots = []  # (chave, raiz com a grafia original)
    seen_keys = set()
    for root in roots:
        key = _case_key(root)
        if key not in seen_keys:
            seen_keys.add(key)
            seen_roots.append((key, os.path.abspath(str(root))))
    found = {}  # (launcher, chave do caminho) -> biblioteca; vale a primeira grafia
    limit = max(0, int(max_dirs))
    incomplete = []
    interrupted = False
    manifests = [max(0, int(max_manifests))]

    def add(launcher, path, root, games, confidence):
        key = (launcher, _case_key(path))
        lib = found.setdefault(key, {'launcher': launcher, 'path': str(path), 'root': str(root),
                                     'games': [], 'confidence': confidence,
                                     'on_system_drive': (bool(system_key) and
                                                         _drive_key(root) == system_key)
                                     if known else None})
        lib['games'] = sorted(set(lib['games']) | set(games), key=str.casefold)

    for _key, root in seen_roots:
        if not _safe_directory(root):
            continue

        def on_dir(path, entries, root=root):
            base = os.path.basename(os.path.normpath(path))
            parent = os.path.dirname(os.path.normpath(path))
            name = base.casefold()
            names = {n.casefold(): (is_dir, is_file) for n, _c, is_dir, is_file, _s in entries}
            if name == 'steamapps' and (
                    names.get('libraryfolders.vdf', (False, False))[1] or any(
                        n.startswith('appmanifest_') and n.endswith('.acf') and f
                        for n, (_d, f) in names.items())):
                add(STEAM, parent, root, _steam_games(entries, manifests), HIGH)
                return True
            if names.get('.egstore', (False, False))[0]:
                add(EPIC, parent, root, [base], HIGH)
                return True
            if names.get('__installer', (False, False))[0]:
                add(EA, parent, root, [base], HIGH)
                return True
            if names.get('uplay_install.state', (False, False))[1]:
                add(UBISOFT, parent, root, [base], HIGH)
                return True
            if name == 'games' and os.path.basename(parent).casefold() == 'ubisoft game launcher':
                add(UBISOFT, path, root, _subfolders(entries), HIGH)
                return True
            if name == 'riot games':
                add(RIOT, path, root, _subfolders(entries, RIOT_SKIP), PROBABLE)
                return True
            if name == 'rockstar games':
                add(ROCKSTAR, path, root, _subfolders(entries, ROCKSTAR_SKIP), PROBABLE)
                return True
            return False

        outcome = _walk_dirs(root, max_depth=max_depth, max_dirs=limit, on_dir=on_dir,
                             is_cancelled=is_cancelled)
        if outcome == 'cancelada':
            interrupted = True
            break
        if outcome == 'limite':
            incomplete.append(root)  # segue para a próxima unidade

    if incomplete:
        result['truncated'] = True
        result['warnings'].append(
            f'A busca ficou incompleta em: {", ".join(incomplete)} (passou de {limit} pastas; '
            'parou ali para não demorar demais). Pode haver bibliotecas que não apareceram.')
    if interrupted:
        result['truncated'] = True
        result['warnings'].append('A busca foi interrompida antes do fim.')
    if manifests[0] <= 0:
        result['warnings'].append(
            'Há muitos jogos da Steam; nem todos os nomes foram listados.')
    result['libraries'] = sorted(found.values(), key=lambda lib: (
        LAUNCHERS.index(lib['launcher']), lib['path'].casefold()))
    return result
