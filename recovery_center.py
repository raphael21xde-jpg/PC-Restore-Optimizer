"""P2-08 (fatia 1): central de recuperação (parte sem Tk, somente leitura).

Procura backups (manifest.json) numa pasta escolhida, mostra cada um com nome
amigável, data, situação, quantidade e tamanho, e diz se ele pode ser
restaurado. A restauração em si é feita pela janela de restauração que já
existe (restore_ui.show_restore), nunca aqui.

Regras de segurança:
- nada aqui grava, apaga, renomeia ou move arquivos: só lista pastas e lê o
  manifest.json (até 256 MiB) e, na conferência opcional, os arquivos do backup;
- links simbólicos, junções e pontos de reparse são pulados ou recusados;
- os textos mostram só o nome da pasta do backup, nunca o caminho completo
  (que pode ter o nome de usuário) nem caminhos de dentro do backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

from after_format import identity_from
from backup_core import human_size
from backup_features import SCHEMAS, backup_labels, friendly_backup_name, safe_relative
from selective_recovery import verify_complete_manifest

MANIFEST_NAME = 'manifest.json'
MANIFEST_LIMIT = 256 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 500

STATUS_TEXT = {
    'concluido': 'Concluído',
    'em_andamento': 'Não terminou (em andamento)',
    'interrompido': 'Interrompido',
    'parcial_com_erros': 'Parcial, com erros',
}
REASON_OK = 'Pronto para restaurar.'
REASON_LINK = 'O manifest.json é um atalho (link); por segurança ele não é aberto.'
REASON_NOT_FILE = 'O manifest.json não é um arquivo comum.'
REASON_TOO_BIG = 'O manifest.json é grande demais (mais de 256 MiB); por segurança não é aberto.'
REASON_UNREADABLE = 'O manifest.json está estragado ou não pôde ser lido.'
REASON_SCHEMA = 'Formato de backup desconhecido; este aplicativo não sabe restaurá-lo.'
REASON_ENTRIES = 'A lista de arquivos do backup tem caminhos ou SHA-256 inválidos.'
REASON_ERRORS = 'O backup terminou com erros; alguns arquivos não foram copiados.'
REASON_COUNT = 'A quantidade de arquivos não bate com a planejada; o backup está incompleto.'
REASON_SIZE = 'O tamanho total não bate com o planejado; o backup está incompleto.'
REASON_OLD = ('Backup de uma versão antiga do aplicativo: ele não diz quantos arquivos deveria '
              'ter, então a central não consegue confirmar que está completo. Por segurança, '
              'restaurar por aqui fica desligado. Os arquivos continuam guardados.')
REASON_COPIES = ('Há cópias diferentes deste mesmo backup em outras pastas. Confira qual é a '
                 'certa antes de restaurar.')
CANCELLED_TEXT = 'A busca foi interrompida antes do fim.'


def _cancel_check(cancelled):
    if cancelled is None:
        return lambda: False
    if hasattr(cancelled, 'is_set'):
        return cancelled.is_set
    return cancelled


def _is_link(info):
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, 'st_file_attributes', 0) or 0) & reparse)


def _safe_dir(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not _is_link(info)


def _manifest_in(entries_by_name):
    entry = entries_by_name.get(MANIFEST_NAME)
    if entry is None:
        return None
    try:
        if entry.is_symlink():
            return None
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        return None
    return Path(entry.path)


def find_backups(folder, *, max_entries=DEFAULT_MAX_ENTRIES, cancelled=None):
    """Procura manifest.json na pasta e nas subpastas de 1 nível (só leitura).

    Devolve {'manifests', 'truncated', 'cancelled', 'warnings'}. max_entries é
    o total de itens de pasta olhados; passou disso, para e avisa.
    """
    is_cancelled = _cancel_check(cancelled)
    result = {'manifests': [], 'truncated': False, 'cancelled': False, 'warnings': []}
    folder = Path(folder)
    if not _safe_dir(folder):
        result['warnings'].append('A pasta não existe, não pôde ser aberta ou é um atalho '
                                  '(link). Clique em "Escolher pasta".')
        return result
    seen = [0]
    limit = max(0, int(max_entries))

    def listing(path):
        items = {}
        subdirs = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if is_cancelled():
                        result['cancelled'] = True
                        return items, subdirs
                    seen[0] += 1
                    if seen[0] > limit:
                        result['truncated'] = True
                        return items, subdirs
                    items[entry.name.casefold()] = entry
                    try:
                        if entry.is_symlink():
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(info.st_mode) and not _is_link(info):
                        subdirs.append(entry.path)
        except OSError:
            pass
        return items, subdirs

    items, subdirs = listing(folder)
    found = _manifest_in(items)
    if found is not None:
        result['manifests'].append(found)
    for sub in sorted(subdirs, key=str.casefold):
        if result['cancelled'] or result['truncated']:
            break
        if is_cancelled():
            result['cancelled'] = True
            break
        sub_items, _ignored = listing(sub)  # nível 1: não desce mais
        found = _manifest_in(sub_items)
        if found is not None:
            result['manifests'].append(found)
    if result['truncated']:
        result['warnings'].append(
            f'A pasta tem muitos itens; a busca parou depois de {limit} para não demorar. '
            'Pode haver backups que não apareceram: escolha a pasta de um backup específico.')
    if result['cancelled']:
        result['warnings'].append(CANCELLED_TEXT)
    return result


def _entries(doc):
    """Arquivos verificados do manifesto já lido (mesmas regras de verified_entries)."""
    entries = {}
    for item in doc['files']:
        if not isinstance(item, dict) or item.get('verified') is not True:
            continue
        rel = safe_relative(item.get('relative'))
        sha = item.get('sha256', '')
        if not isinstance(sha, str) or not re.fullmatch('[a-fA-F0-9]{64}', sha):
            raise ValueError('SHA-256 ausente ou inválido no manifesto.')
        key = rel.as_posix()
        if key in entries:
            raise ValueError('Arquivo duplicado no manifesto.')
        entries[key] = item
    return entries


def _date_text(value):
    if not isinstance(value, str) or not value:
        return ''
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return ''


def _signature(entries):
    body = sorted((key, int(item.get('bytes') or 0), str(item.get('sha256', '')).lower())
                  for key, item in entries.items())
    text = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def inspect_backup(manifest):
    """Resumo de um backup (só leitura). Nunca lança erro: o motivo vai em 'reason'."""
    manifest = Path(manifest)
    row = {'manifest': manifest, 'folder': manifest.parent.name, 'name': manifest.parent.name,
           'date': '', 'started': '', 'status': '', 'status_text': 'Ilegível', 'files': 0, 'bytes': 0,
           'size_text': '', 'restorable': False, 'reason': '', 'key': None,
           'signature': None, 'copies': 1}
    try:
        info = os.lstat(manifest)
    except OSError:
        row['reason'] = REASON_UNREADABLE
        return row
    if _is_link(info):
        row['reason'] = REASON_LINK
        return row
    if not stat.S_ISREG(info.st_mode):
        row['reason'] = REASON_NOT_FILE
        return row
    if info.st_size > MANIFEST_LIMIT:
        row['reason'] = REASON_TOO_BIG
        return row
    try:
        with open(manifest, 'rb') as handle:
            raw = handle.read(MANIFEST_LIMIT + 1)
        if len(raw) > MANIFEST_LIMIT:
            row['reason'] = REASON_TOO_BIG
            return row
        doc = json.loads(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        row['reason'] = REASON_UNREADABLE
        return row
    if not isinstance(doc, dict) or doc.get('schema') not in SCHEMAS \
            or not isinstance(doc.get('files'), list):
        row['reason'] = REASON_SCHEMA
        return row
    try:
        labels = backup_labels(manifest.parent.parent)
    except Exception:
        labels = {}
    row['name'] = str(friendly_backup_name(manifest, doc, labels))[:200]
    row['date'] = _date_text(doc.get('started'))
    if isinstance(doc.get('started'), str):
        row['started'] = doc['started']
    status = doc.get('status')
    row['status'] = status if isinstance(status, str) else ''
    row['status_text'] = STATUS_TEXT.get(status, 'Situação desconhecida')
    try:
        entries = _entries(doc)  # o manifesto é lido uma vez só por inspeção
    except (OSError, ValueError, TypeError, AttributeError):
        row['reason'] = REASON_ENTRIES
        return row
    try:
        total = sum(int(item.get('bytes') or 0) for item in entries.values())
    except (TypeError, ValueError):
        row['reason'] = REASON_ENTRIES
        return row
    row['files'] = len(entries)
    row['bytes'] = total
    row['size_text'] = human_size(total)
    row['signature'] = _signature(entries)
    identity = identity_from(manifest.parent.name, doc)
    if identity is not None:
        row['key'] = '|'.join((identity['folder'], identity['started'],
                               identity['plan_fingerprint']))
    expected_files = doc.get('file_count_expected')
    expected_bytes = doc.get('bytes_expected')
    if status != 'concluido':
        row['reason'] = (f'O backup não terminou ({row["status_text"].lower()}); '
                         'restaure só de um backup concluído.')
    elif doc.get('errors'):
        row['reason'] = REASON_ERRORS
    elif doc.get('file_count_expected') is None or doc.get('bytes_expected') is None:
        row['reason'] = REASON_OLD
    elif (not isinstance(expected_files, int) or expected_files < 1
          or len(entries) != expected_files or len(doc['files']) != expected_files):
        row['reason'] = REASON_COUNT
    elif not isinstance(expected_bytes, int) or total != expected_bytes:
        row['reason'] = REASON_SIZE
    else:
        row['restorable'] = True
        row['reason'] = REASON_OK
    return row


def group_copies(rows):
    """Junta cópias do mesmo backup (mesma identidade) em pastas diferentes.

    Se as cópias tiverem conteúdo diferente (lista de arquivos, tamanhos ou
    SHA-256), todas ficam sem "restaurar" e com o motivo "cópias diferentes".
    Devolve uma lista nova; as linhas de entrada não são alteradas.
    """
    rows = [dict(row) for row in rows]
    groups = {}
    for row in rows:
        if row.get('key'):
            groups.setdefault(row['key'], []).append(row)
    for members in groups.values():
        for row in members:
            row['copies'] = len(members)
        if len(members) < 2:
            continue
        signatures = {row.get('signature') for row in members}
        if len(signatures) > 1:
            for row in members:
                row['restorable'] = False
                row['reason'] = REASON_COPIES
    return rows


def scan(folder, *, max_entries=DEFAULT_MAX_ENTRIES, cancelled=None):
    """find_backups + inspect_backup + group_copies (só leitura)."""
    is_cancelled = _cancel_check(cancelled)
    found = find_backups(folder, max_entries=max_entries, cancelled=cancelled)
    rows = []
    for manifest in found['manifests']:
        if is_cancelled():
            if CANCELLED_TEXT not in found['warnings']:
                found['warnings'].append(CANCELLED_TEXT)
            found['cancelled'] = True
            break
        rows.append(inspect_backup(manifest))
    rows = group_copies(rows)
    rows.sort(key=lambda row: row['started'], reverse=True)  # mais novo primeiro
    return {'rows': rows, 'truncated': found['truncated'], 'cancelled': found['cancelled'],
            'warnings': found['warnings']}


def verify_backup(manifest, cancelled=None):
    """Confere de novo o SHA-256 de cada arquivo do backup (opcional, só leitura).

    Devolve (aprovado, texto em português). O texto só leva o nome da pasta do
    backup, nunca caminhos.
    """
    manifest = Path(manifest)
    name = manifest.parent.name
    try:
        info = os.lstat(manifest)
        refused = (_is_link(info) or not stat.S_ISREG(info.st_mode)
                   or info.st_size > MANIFEST_LIMIT)
    except Exception:
        return False, f'Não foi possível abrir o backup "{name}". Nada foi alterado.'
    if refused:
        return False, (f'O manifest.json do backup "{name}" não é um arquivo comum ou é grande '
                       'demais; por segurança ele não é conferido.')
    try:
        result = verify_complete_manifest(manifest, cancelled=cancelled)
    except InterruptedError:
        return False, 'Conferência interrompida antes do fim. Nada foi alterado.'
    except ValueError:
        return False, (f'O backup "{name}" não passou na conferência: ele não terminou, tem '
                       'erros ou a lista de arquivos não bate com a planejada. Nada foi alterado.')
    except OSError:
        return False, (f'O backup "{name}" não passou na conferência: um arquivo está faltando '
                       'ou foi alterado (SHA-256 diferente). Nada foi alterado.')
    except Exception:
        return False, (f'Não foi possível conferir o backup "{name}". Nada foi alterado.')
    return True, (f'Backup "{name}" conferido: {result["files_verified"]} arquivo(s), '
                  f'{human_size(result["bytes_verified"])}, todos com o SHA-256 igual ao '
                  'do manifesto. Nada foi alterado.')
