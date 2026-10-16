"""Read-only index of verified backup entries for the grouped restore selector.

Only the UI layout/selection uses this index. The original relative paths remain
unchanged and are passed to backup_features.restore_selected for safe recovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ntpath
from pathlib import PurePosixPath
from backup_identity import inside

PAGE_SIZE = 160


@dataclass
class RestoreNode:
    name: str
    kind: str  # root, app, category, folder, file
    parent: 'RestoreNode | None' = None
    key: str | None = None
    children: dict[str, 'RestoreNode'] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)
    bytes: int = 0
    search: str = ''
    uid: int = 0

    @property
    def count(self):
        return len(self.keys)


@dataclass
class RestoreIndex:
    root: RestoreNode
    files: dict[str, RestoreNode]
    bytes_by_key: dict[str, int]
    nodes: dict[int, RestoreNode]

    def search_counts(self, term: str) -> dict[int, int]:
        """Return counts by node; include whole branches if group/category matches."""
        term = term.casefold().strip()
        if not term:
            return {n.uid: n.count for n in self.nodes.values()}
        hits: dict[int, int] = {}
        for node in self.files.values():
            current = node
            matches = term in node.search
            if not matches:
                ancestor = node.parent
                while ancestor is not None and ancestor.kind != 'root':
                    if term in ancestor.name.casefold():
                        matches = True
                        break
                    ancestor = ancestor.parent
            if matches:
                while current is not None:
                    hits[current.uid] = hits.get(current.uid, 0) + 1
                    current = current.parent
        return hits


_CATEGORIES = (
    ('Músicas e beatmaps', {'songs', 'beatmaps', 'beatmap', 'tracks'}),
    ('Skins e personalizações', {'skins', 'skin'}),
    ('Saves e progresso', {'saves', 'savegames', 'savedgames', 'saved games', 'save', 'userdata'}),
    ('Capturas e replays', {'screenshots', 'replays', 'replay', 'screenshots'}),
    ('Configurações', {'config', 'configs', 'configuration', 'settings', 'preferences'}),
)


def _source_parts(entry, key):
    source = entry.get('source')
    if isinstance(source, str) and source.strip():
        return [p for p in source.replace('\\', '/').split('/') if p]
    return [p for p in key.replace('\\', '/').split('/') if p]


def _osu_identity(parts):
    low = [p.casefold() for p in parts]
    if any(p in ('osu!lazer', 'osu! lazer', 'ppy.osu', 'ppy.osu!', 'osu-lazer') or p.startswith('osu!lazer') for p in low):
        return 'osu! lazer'
    # Exact component match: 'osuserver', 'osumedia' and similar are not osu!.
    if any(p in ('osu!', 'osu', 'osu!stable') for p in low):
        return 'osu! clássico'
    return None


def _ownership(entry, key):
    parts = _source_parts(entry, key)
    owners = entry.get('owners') or []
    owners = [o for o in owners if isinstance(o, dict) and isinstance(o.get('name'), str)]
    trusted = [o for o in owners if o.get('category') not in ('Arquivo sem associação', 'Arquivo ou pasta selecionada')]
    osu = _osu_identity(parts)

    # Recorded application/game ownership takes priority. Generic selected folders
    # may be reclassified only when the source path has explicit osu evidence.
    if trusted:
        titles = list(dict.fromkeys(o['name'].strip() for o in trusted if o['name'].strip()))
        title = ' + '.join(titles) or 'Aplicativo identificado'
        kinds = {o.get('category', '').casefold() for o in trusted}
        label = 'Jogo' if any('jogo' in k for k in kinds) else 'Aplicativo'
        if osu and all('osu' in t.casefold() for t in titles):
            # The owner may contain an explicit edition even if a parent folder
            # happens to have the generic name 'osu!'. Prefer that evidence.
            if any('lazer' in t.casefold() for t in titles):
                title = 'osu! lazer'
            elif any('clássico' in t.casefold() or 'stable' in t.casefold() for t in titles):
                title = 'osu! clássico'
            else:
                title = osu
        root = trusted[0].get('root')
        return f'{label}: {title}', root, trusted[0].get('category', '')
    if osu:
        return 'Jogo: ' + osu, None, ''
    # Steam/Xbox installation folders provide useful evidence of grouping,
    # but the label deliberately says "pasta", not confirmed installed game.
    lower = [p.casefold() for p in parts]
    for start, marker, label in ((('steamapps', 'common'), 'Steam', 'Pasta Steam'),
                                 (('xboxgames',), 'Xbox', 'Pasta Xbox Games')):
        width = len(start)
        for i in range(len(lower) - width):
            if tuple(lower[i:i + width]) == start and i + width < len(parts):
                game = parts[i + width]
                if game.casefold() not in ('content', 'metadata', 'desktop.ini'):
                    prefix = '/'.join(parts[:i + width + 1])
                    return f'{label}: {game}', prefix, ''
    if owners:
        owner = owners[0]
        if owner.get('category') == 'Arquivo ou pasta selecionada':
            name = owner.get('name', '').strip()
            if name:
                path = str(owner.get('root') or '').strip()
                # Same-name folders on different drives must never merge.
                return 'Pasta selecionada: ' + name + (f' — {path}' if path else ''), path, ''
    return 'Arquivos sem associação confirmada', None, ''


def _category(entry, key, explicit_category):
    parts = [p.casefold() for p in _source_parts(entry, key)]
    cat = explicit_category.casefold()
    if 'save' in cat: return 'Saves e progresso'
    if 'configura' in cat: return 'Configurações'
    for name, markers in _CATEGORIES:
        if any(p in markers for p in parts[:-1]):
            return name
    if 'aplicativo' in cat: return 'Dados do aplicativo'
    if 'jogo' in cat: return 'Dados do jogo'
    return 'Outros arquivos'


def _folder_parts(entry, key, root):
    """Use original directories, never derive a destination from UI labels."""
    source = entry.get('source')
    if isinstance(source, str) and root and inside(source, root):
        try:
            relative = ntpath.relpath(source, root)
            base = ntpath.basename(str(root).rstrip('/\\'))
            if relative == '.':
                return [], ntpath.basename(source)
            pieces = [p for p in relative.replace('\\', '/').split('/') if p]
            return ([base] if base else []) + pieces[:-1], pieces[-1]
        except (ValueError, TypeError):
            pass
    pieces = list(PurePosixPath(key.replace('\\', '/')).parts)
    # Drop OS-specific parent directories for clearly identified osu folders.
    # Example: C:/Games/osu!/Songs/set/map.osz -> Songs/set/map.osz.
    for i, component in enumerate(pieces[:-1]):
        if component.casefold() in ('osu!', 'osu', 'ppy.osu', 'ppy.osu!', 'osu!lazer', 'osu! lazer'):
            return pieces[i + 1:-1], pieces[-1]
    return pieces[:-1], pieces[-1]


def build_restore_index(entries: dict[str, dict]) -> RestoreIndex:
    root = RestoreNode('Arquivos verificados', 'root')
    nodes = {0: root}
    root.uid = 0
    files = {}
    sizes = {}
    next_id = 1

    def child(parent, name, kind):
        nonlocal next_id
        token = kind + ':' + name.casefold()
        if token not in parent.children:
            node = RestoreNode(name, kind, parent=parent, uid=next_id)
            next_id += 1
            parent.children[token] = node
            nodes[node.uid] = node
        return parent.children[token]

    for key, entry in sorted(entries.items(), key=lambda p: p[0].casefold()):
        if not isinstance(entry, dict):
            continue
        title, owner_root, explicit = _ownership(entry, key)
        category = _category(entry, key, explicit)
        folders, filename = _folder_parts(entry, key, owner_root)
        app = child(root, title, 'app')
        current = child(app, category, 'category')
        for dirname in folders:
            current = child(current, dirname, 'folder')
        file_node = child(current, filename, 'file')
        # Each verified manifest key is represented exactly once. Case-insensitive
        # filenames can coexist in a backup produced on a case-sensitive disk.
        if file_node.key is not None:
            file_node = child(current, filename + ' [' + key + ']', 'file')
        file_node.key = key
        file_node.search = (key + ' ' + str(entry.get('source', '')) + ' ' + title + ' ' + category).casefold()
        files[key] = file_node
        try: size = max(0, int(entry.get('bytes', 0)))
        except (TypeError, ValueError): size = 0
        sizes[key] = size
        ancestor = file_node
        while ancestor is not None:
            ancestor.keys.append(key)
            ancestor.bytes += size
            ancestor = ancestor.parent
    return RestoreIndex(root, files, sizes, nodes)


def sorted_children(node):
    return sorted(node.children.values(), key=lambda n:(n.kind == 'file', n.name.casefold()))
