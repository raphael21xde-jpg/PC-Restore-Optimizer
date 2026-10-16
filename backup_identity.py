"""Readable inventory of what was actually copied, not merely selected."""
import ntpath
import re


def canonical(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def inside(path, root):
    path, root = canonical(path), canonical(root)
    return path == root or path.startswith(root.rstrip('\\') + '\\')


def make_descriptors(catalog, selected):
    records = []
    for item in catalog.values():
        for path in item.get('paths', []):
            if not any(inside(path, chosen) or inside(chosen, path) for chosen in selected):
                continue
            if item.get('kind') == 'game':
                kind = item.get('path_kinds', {}).get(path)
                category = 'Configurações do jogo' if kind == 'config' else ('Save do jogo' if kind == 'save' else 'Dados do jogo')
            else:
                category = 'Dados do aplicativo'
            records.append({'name': item['name'], 'category': category, 'root': str(path)})
    for path in selected:
        if not any(inside(path, r['root']) for r in records):
            records.append({'name': ntpath.basename(str(path).rstrip('/\\')) or str(path),
                            'category': 'Arquivo ou pasta selecionada', 'root': str(path)})
    return records


def owners_for(source, records):
    matches = [r for r in records if inside(source, r['root'])]
    if not matches:
        return [{'name': ntpath.basename(str(source)), 'category': 'Arquivo sem associação', 'root': str(source)}]
    # Prefer the most specific scope; retain multiple owners of shared save folders.
    length = max(len(canonical(r['root'])) for r in matches)
    return [dict(r) for r in matches if len(canonical(r['root'])) == length]


def owner_text(owners):
    return '; '.join(dict.fromkeys(f"{r['category']}: {r['name']}" for r in owners))


def title_for(records):
    labels = list(dict.fromkeys(f"{r['category']}: {r['name']}" for r in records))
    return ' + '.join(labels[:3]) + (f' + {len(labels)-3} outros itens' if len(labels)>3 else '') or 'Backup de arquivos'


def slug(text):
    return re.sub(r'[^\w.-]+', '-', str(text), flags=re.UNICODE).strip('-.')[:70] or 'arquivos'


def inventory_text(manifest):
    lines = [manifest.get('display_name') or 'Backup de arquivos', 'Estado: ' + manifest.get('status', '?'),
             'Criado: ' + manifest.get('started', '?'), '', 'CONTEÚDO EFETIVAMENTE COPIADO E VERIFICADO:']
    groups = {}
    for file in manifest.get('files', []):
        label = owner_text(file.get('owners', [])) or 'Backup antigo — associação não registrada'
        groups.setdefault(label, []).append(file)
    for label, files in groups.items():
        lines += ['', label, f'{len(files)} arquivo(s) · {sum(f.get("bytes", 0) for f in files)} bytes']
        for f in files:
            lines.append('  Origem: ' + f.get('source', '?'))
            lines.append('  No backup: ' + f.get('relative', '?'))
    if not groups: lines.append('(Nenhum arquivo copiado)')
    if manifest.get('errors'):
        lines += ['', 'FALHAS — NÃO CONSIDERE ESTES ARQUIVOS PRESERVADOS:']
        lines += [str(e.get('source', '')) + ': ' + str(e.get('error', '')) for e in manifest['errors']]
    lines += ['', 'Dados de aplicativo não significam instalador nem reinstalação automática.',
              'Cofres de navegador são separados; não fazem parte desta cópia salvo inclusão explícita.']
    return '\n'.join(lines)
