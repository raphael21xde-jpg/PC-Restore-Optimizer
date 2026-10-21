"""P2-06: arquivos de senhas exportados do navegador, salvos sem proteção.

Quando a pessoa exporta as senhas do Chrome, Edge, Firefox ou Opera, o
navegador grava um arquivo .csv com todas as senhas em texto puro (qualquer
um que abrir o arquivo consegue ler). Este módulo só procura esses arquivos
PELO NOME, sem abrir nem ler o conteúdo, e monta um aviso em português.

Regras de segurança:
- nunca abre, lê, copia, move ou apaga nada; só lista nomes de pastas;
- não segue links simbólicos nem junções;
- limita a profundidade e a quantidade de itens olhados.

Sem imports do projeto, para qualquer tela ou motor poder usar.
"""
from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

# Nomes que costumam indicar senhas exportadas (sem diferenciar maiúsculas).
PATTERNS = ('*password*', '*senha*', '*logins*', '*credenciais*', '*credentials*')
EXTENSIONS = ('.csv',)

MAX_DEPTH = 2
MAX_ENTRIES = 20000
ALERT_LIMIT = 20

TITLE = 'ARQUIVOS DE SENHAS SEM PROTEÇÃO'


@dataclass
class ScanResult:
    """Resultado da busca: arquivos achados e se a busca parou antes do fim."""
    findings: list = field(default_factory=list)
    incomplete: bool = False


def is_password_export(name):
    """True quando o nome parece um arquivo de senhas exportado (.csv)."""
    lowered = str(name).casefold()
    if not lowered.endswith(EXTENSIONS):
        return False
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in PATTERNS)


def user_folders(env=None):
    """Documentos, Downloads e Área de Trabalho da pessoa (inclusive no OneDrive).

    Usa só a variável USERPROFILE (e OneDrive, se existir) de ``env``; não
    confere se as pastas existem. Sem USERPROFILE, devolve lista vazia.
    """
    env = os.environ if env is None else env
    profile = env.get('USERPROFILE')
    if not profile:
        return []
    names = ('Documents', 'Downloads', 'Desktop')
    onedrive_names = ('Documents', 'Documentos', 'Desktop', 'Área de Trabalho')
    folders = [Path(profile) / name for name in names]
    onedrive_roots = [Path(profile) / 'OneDrive']
    if env.get('OneDrive'):
        onedrive_roots.append(Path(env['OneDrive']))
    for root in onedrive_roots:
        folders += [root / name for name in onedrive_names]
    unique = []
    seen = set()
    for folder in folders:
        marker = os.path.normcase(str(folder))
        if marker not in seen:
            seen.add(marker)
            unique.append(folder)
    return unique


def _is_link(entry):
    """Link simbólico ou junção (reparse point no Windows)."""
    try:
        if entry.is_symlink():
            return True
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True  # sem conseguir conferir, trata como link e não entra
    attributes = getattr(info, 'st_file_attributes', 0)
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return bool(attributes & reparse)


def find_password_exports(folders, *, max_depth=MAX_DEPTH, max_entries=MAX_ENTRIES,
                          scandir=os.scandir):
    """Procura arquivos de senhas pelo nome nas pastas dadas.

    ``max_depth`` 0 olha só a própria pasta; 2 desce até duas subpastas.
    Para depois de ``max_entries`` itens olhados e marca ``incomplete``.
    """
    result = ScanResult()
    seen = 0
    pending = [(Path(folder), 0) for folder in folders]
    visited = set()
    while pending:
        folder, depth = pending.pop(0)
        marker = os.path.normcase(str(folder))
        if marker in visited:
            continue
        visited.add(marker)
        try:
            with scandir(folder) as entries:
                for entry in entries:
                    seen += 1
                    if seen > max_entries:
                        result.incomplete = True
                        return result
                    if _is_link(entry):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if depth < max_depth:
                            pending.append((Path(entry.path), depth + 1))
                    elif is_file and is_password_export(entry.name):
                        result.findings.append(Path(entry.path))
        except OSError:
            continue  # pasta inexistente ou sem permissão: segue com as outras
    return result


def _as_path(item):
    if isinstance(item, (str, os.PathLike)):
        return Path(item)
    destination = getattr(item, 'destination', None) or getattr(item, 'source', None)
    return Path(destination) if destination else None


def scan_paths(paths):
    """Filtra uma lista já conhecida de caminhos (texto, Path ou FileTask).

    Só olha o nome; não toca no disco.
    """
    found = []
    for item in paths:
        path = _as_path(item)
        if path is not None and is_password_export(path.name):
            found.append(path)
    return found


def alert_lines(findings, incomplete=False):
    """Linhas do aviso em português. Lista vazia quando não há nada a avisar."""
    findings = list(findings)
    if not findings and not incomplete:
        return []
    lines = []
    if findings:
        lines.append(f'{len(findings)} arquivo(s) parecem senhas exportadas do navegador, '
                     'gravadas sem proteção (qualquer pessoa que abrir consegue ler):')
        for path in findings[:ALERT_LIMIT]:
            path = Path(path)
            lines.append(f'  ! {path.name}  (pasta: {path.parent})')
        if len(findings) > ALERT_LIMIT:
            lines.append(f'  e mais {len(findings) - ALERT_LIMIT} arquivo(s).')
        lines.append('O que fazer: importe esse arquivo no navegador ou num gerenciador de '
                     'senhas e depois apague-o você mesmo, sem esquecer de esvaziar a '
                     'Lixeira. O app nunca apaga nem abre esses arquivos.')
    if incomplete:
        lines.append('A busca parou antes do fim porque as pastas têm muitos arquivos; '
                     'pode haver outros arquivos de senhas.')
    return lines
