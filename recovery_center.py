"""P2-08 (fatias 1 e 2): central de recuperação (parte sem Tk, somente leitura).

Procura backups (manifest.json) numa pasta escolhida, mostra cada um com nome
amigável, data, situação, quantidade e tamanho, e diz se ele pode ser
restaurado. A restauração em si é feita pela janela de restauração que já
existe (restore_ui.show_restore), nunca aqui.

Regras de segurança:
- nada aqui grava, apaga, renomeia ou move arquivos: só lista pastas e lê o
  manifest.json (até 256 MiB) e, na conferência opcional, os arquivos do backup;
- links simbólicos, junções e pontos de reparse são pulados ou recusados;
- os textos mostram só o nome da pasta do backup, nunca o caminho completo
  (que pode ter o nome de usuário) nem caminhos de dentro do backup;
- fatia 2: um backup "parcial, com erros" pode liberar só os arquivos
  conferidos (partial_ok); a lista 'errors' do manifesto (que tem caminhos)
  nunca é mostrada.
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
# P2-08 (fatia 2): motivos do botão "Restaurar só os conferidos…" (sem caminhos)
PARTIAL_OK = ('Dá para restaurar só os arquivos conferidos (sempre numa pasta nova); os que '
              'falharam ficam de fora.')
PARTIAL_COMPLETE = 'O backup está completo: use "Restaurar…".'
PARTIAL_NOT_FINISHED = ('O backup não terminou (foi interrompido ou ainda está em andamento). '
                        'Termine ou retome o backup antes de restaurar.')
PARTIAL_OLD = ('O backup não diz quantos arquivos e quantos bytes deveria ter (versão antiga do '
               'aplicativo), então não dá para saber quantos ficariam de fora.')
PARTIAL_NO_VERIFIED = ('A lista de arquivos do backup não diz, para cada arquivo, se ele foi '
                       'conferido (versão antiga do aplicativo). Por segurança, a restauração '
                       'parcial fica desligada.')
PARTIAL_SHA = 'Há arquivo marcado como conferido sem SHA-256 válido na lista do backup.'
PARTIAL_NONE = 'Nenhum arquivo deste backup foi conferido; não há o que restaurar.'
PARTIAL_COUNT = 'A quantidade de arquivos não bate com a planejada.'
PARTIAL_SIZE = 'O tamanho dos arquivos conferidos passa do tamanho planejado.'
PARTIAL_CHANGED = ('Este backup não pode mais ser restaurado só com os arquivos conferidos: '
                   '{reason} Nada foi alterado.')
CANCELLED_TEXT = 'A busca foi interrompida antes do fim.'
NO_SELECTION_TEXT = 'Nenhum backup selecionado'


def reason_detail_text(row):
    """Texto completo do motivo, mostrado abaixo da tabela (FIX-P2-08-01).

    Usa só 'restorable' e 'reason' (nunca o nome da pasta, que pode ter o nome
    de usuário), não corta o texto e não altera a linha.
    """
    if row is None:
        return NO_SELECTION_TEXT
    answer = 'Sim' if row['restorable'] else 'Não'
    return f'Pode restaurar: {answer}. Motivo: {row["reason"]}'


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool)


def partial_restore_info(doc, entries):
    """P2-08 (fatia 2): pode restaurar só os conferidos? (só leitura, sem caminhos)

    doc é o manifesto já lido; entries, os arquivos verificados (_entries).
    Devolve (liberado, conferidos, falharam, motivo). falharam = esperados -
    conferidos (None quando o manifesto não diz quantos esperava).
    """
    good = len(entries)
    expected_files = doc.get('file_count_expected')
    expected_bytes = doc.get('bytes_expected')
    bad = expected_files - good if _is_count(expected_files) else None
    status = doc.get('status')
    if status == 'concluido':
        return False, good, bad, PARTIAL_COMPLETE
    if status != 'parcial_com_erros':
        return False, good, bad, PARTIAL_NOT_FINISHED
    if not _is_count(expected_files) or not _is_count(expected_bytes) or expected_files < 1:
        return False, good, bad, PARTIAL_OLD
    files = doc.get('files')
    if not isinstance(files, list):
        return False, good, bad, PARTIAL_NO_VERIFIED
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('verified'), bool):
            return False, good, bad, PARTIAL_NO_VERIFIED
        sha = item.get('sha256')
        if item['verified'] and (not isinstance(sha, str)
                                 or not re.fullmatch('[a-fA-F0-9]{64}', sha)):
            return False, good, bad, PARTIAL_SHA
    if sum(1 for item in files if item['verified']) != good:
        return False, good, bad, PARTIAL_SHA
    if good < 1:
        return False, good, bad, PARTIAL_NONE
    if good >= expected_files or len(files) > expected_files:
        return False, good, bad, PARTIAL_COUNT
    try:
        total = sum(int(item.get('bytes') or 0) for item in entries.values())
    except (TypeError, ValueError):
        return False, good, bad, PARTIAL_SIZE
    if total > expected_bytes:
        return False, good, bad, PARTIAL_SIZE
    return True, good, bad, PARTIAL_OK


def counts_text(row):
    """'Conferidos: X · Falharam: Y' (vazio quando a linha não tem contagem)."""
    if not row or row.get('verified_files') is None:
        return ''
    if row.get('failed_files') is None:
        return f'Conferidos: {row["verified_files"]}'
    return f'Conferidos: {row["verified_files"]} · Falharam: {row["failed_files"]}'


def partial_confirmation_text(row):
    """Confirmação separada do botão "Restaurar só os conferidos…" (sem caminhos)."""
    return (f'Restaurar só os arquivos conferidos deste backup?\n\n'
            f'Vão ser restaurados {row["verified_files"]} arquivo(s) '
            f'({human_size(row.get("bytes") or 0)}). '
            f'Ficam de fora {row["failed_files"]} arquivo(s), porque eles não foram copiados '
            'ou conferidos quando o backup foi feito (por exemplo, um arquivo aberto por '
            'outro programa ou removido pelo antivírus).\n\n'
            'A restauração é feita sempre numa pasta NOVA, cada arquivo é conferido de novo '
            'pelo SHA-256, e nada é apagado nem sobrescrito. Neste modo, "Colocar no lugar '
            'original" não é oferecido.')


def partial_report_text(restored, left_out, folder_name, *, not_marked=0, passwords=0):
    """Resultado da restauração parcial: só quantidades e o NOME da pasta nova."""
    name = Path(str(folder_name).replace('\\', '/')).name
    lines = [f'Restauração parcial concluída: {restored} arquivo(s) restaurado(s) e '
             f'conferido(s) pelo SHA-256, na pasta nova "{name}".',
             f'{left_out} arquivo(s) ficaram de fora porque não tinham sido copiados ou '
             'conferidos quando o backup foi feito.']
    if not_marked:
        lines.append(f'{not_marked} arquivo(s) conferido(s) não foram marcados e também '
                     'não foram restaurados.')
    if passwords:
        lines.append(f'Atenção: {passwords} arquivo(s) restaurado(s) parecem senhas exportadas '
                     'do navegador, gravadas sem proteção. Confira a pasta nova.')
    lines.append('Nada foi apagado nem sobrescrito.')
    return '\n'.join(lines)


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


def _read_doc(manifest):
    """Lê o manifest.json uma vez (só leitura). Devolve (doc, None) ou (None, motivo)."""
    try:
        info = os.lstat(manifest)
    except OSError:
        return None, REASON_UNREADABLE
    if _is_link(info):
        return None, REASON_LINK
    if not stat.S_ISREG(info.st_mode):
        return None, REASON_NOT_FILE
    if info.st_size > MANIFEST_LIMIT:
        return None, REASON_TOO_BIG
    try:
        with open(manifest, 'rb') as handle:
            raw = handle.read(MANIFEST_LIMIT + 1)
        if len(raw) > MANIFEST_LIMIT:
            return None, REASON_TOO_BIG
        doc = json.loads(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, REASON_UNREADABLE
    if not isinstance(doc, dict) or doc.get('schema') not in SCHEMAS \
            or not isinstance(doc.get('files'), list):
        return None, REASON_SCHEMA
    return doc, None


def _refuse(row, reason):
    row['reason'] = reason
    row['partial_ok'] = False
    row['partial_reason'] = reason
    return row


def inspect_backup(manifest):
    """Resumo de um backup (só leitura). Nunca lança erro: o motivo vai em 'reason'.

    P2-08 (fatia 2): também diz quantos arquivos foram conferidos e quantos
    falharam, e se dá para restaurar só os conferidos ('partial_ok' e
    'partial_reason'). Isso não muda 'restorable' nem 'reason'.
    """
    manifest = Path(manifest)
    row = {'manifest': manifest, 'folder': manifest.parent.name, 'name': manifest.parent.name,
           'date': '', 'started': '', 'status': '', 'status_text': 'Ilegível', 'files': 0, 'bytes': 0,
           'size_text': '', 'restorable': False, 'reason': '', 'key': None,
           'signature': None, 'copies': 1, 'verified_files': None, 'failed_files': None,
           'partial_ok': False, 'partial_reason': ''}
    doc, refused = _read_doc(manifest)
    if doc is None:
        return _refuse(row, refused)
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
        return _refuse(row, REASON_ENTRIES)
    try:
        total = sum(int(item.get('bytes') or 0) for item in entries.values())
    except (TypeError, ValueError):
        return _refuse(row, REASON_ENTRIES)
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
    ok, good, bad, partial_reason = partial_restore_info(doc, entries)
    row['verified_files'] = good
    row['failed_files'] = bad
    row['partial_ok'] = ok
    row['partial_reason'] = partial_reason
    return row


def load_partial_keys(manifest):
    """Relê o manifesto e devolve as chaves dos arquivos conferidos (só leitura).

    Usado ao abrir a janela no modo "só os conferidos": se o backup não passar
    mais nas regras, lança ValueError com um texto em português, sem caminhos.
    """
    return load_partial_info(manifest)['keys']


def load_partial_info(manifest):
    """Como load_partial_keys, mas devolve {'keys', 'verified', 'failed'}."""
    doc, refused = _read_doc(Path(manifest))
    if doc is None:
        raise ValueError(PARTIAL_CHANGED.format(reason=refused))
    try:
        entries = _entries(doc)
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError(PARTIAL_CHANGED.format(reason=REASON_ENTRIES)) from None
    ok, good, bad, reason = partial_restore_info(doc, entries)
    if not ok:
        raise ValueError(PARTIAL_CHANGED.format(reason=reason))
    return {'keys': sorted(entries, key=str.casefold), 'verified': good, 'failed': bad}


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
                row['partial_ok'] = False
                row['partial_reason'] = REASON_COPIES
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
