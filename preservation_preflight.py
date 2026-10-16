"""Bounded, read-only source-path checks before future C: backup.

Checks whether the selected path can be accessed, without enumerating full
folders, reading save contents, copying files, or marking any backup verified.
"""
from __future__ import annotations
from datetime import datetime, timezone
import ntpath
import os
from pathlib import Path
import stat
from volume_paths import volume_of
from drive_catalog import safe_to_mark

REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
MAX_PATH_CHECKS = 500


def _is_reparse_on_chain(path):
    check = Path(path)
    for folder in (check, *check.parents):
        info = os.lstat(folder)
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & REPARSE):
            return str(folder)
    return ''


def _check_one(path):
    row = {'path': path, 'volume': volume_of(path), 'status': 'REVISAR',
           'file_type': 'desconhecido', 'size_bytes': None,
           'note': 'Apenas pré-checagem; nenhum backup realizado.'}
    if row['volume'] != 'C:' or not safe_to_mark(path):
        row['status'] = 'BLOQUEADO'
        row['note'] = 'Caminho fora do C: ou raiz do sistema insegura para seleção.'
        return row
    try:
        # lstat avoids following the final symlink/reparse point.
        info = os.lstat(path)
        special = _is_reparse_on_chain(path)
        if special:
            row['status'] = 'REVISAR LINK'
            row['note'] = f'Caminho contém link/junção: {special}. Não incluí-lo automaticamente.'
        elif stat.S_ISREG(info.st_mode):
            row.update(status='LOCALIZADO', file_type='arquivo', size_bytes=int(info.st_size))
        elif stat.S_ISDIR(info.st_mode):
            row.update(status='LOCALIZADO', file_type='pasta')
            row['note'] = 'Pasta acessível por metadados; conteúdo e tamanho NÃO verificados.'
        else:
            row.update(status='REVISAR', note='Tipo de arquivo especial; verificar manualmente.')
    except FileNotFoundError:
        row.update(status='AUSENTE', note='Arquivo/pasta não encontrado neste computador.')
    except PermissionError:
        row.update(status='SEM ACESSO', note='Acesso negado; não assumir que dados foram protegidos.')
    except OSError as exc:
        row.update(status='ERRO', note=f'Falha de acesso: {type(exc).__name__}: {exc}')
    return row


def prepare_c_preflight(paths, *, limit=MAX_PATH_CHECKS):
    """Return a serializable report with bounded checks and explicit risk flags."""
    if limit < 1 or limit > MAX_PATH_CHECKS:
        raise ValueError('Limite de verificação inválido')
    normalized = {}
    for value in paths:
        if isinstance(value, str) and value.strip():
            key = ntpath.normcase(ntpath.normpath(value.replace('/', '\\')))
            normalized.setdefault(key, value)
    unique = list(normalized.values())
    checked = [_check_one(value) for value in unique[:limit]]
    return {'schema': 'pcro-c-source-preflight-v1',
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'selected_paths': len(unique), 'checked_paths': len(checked),
            'not_checked': max(0, len(unique) - len(checked)),
            'entries': checked, 'backup_verified': False,
            'restore_verified': False, 'deletions_authorized': False,
            'installation_authorized': False,
            'ready_for_format': False,
            'notice': ('Esta conferência usa apenas metadados dos caminhos e NÃO lê todos os arquivos, '
                       'não faz backup nem garante restauração. Backup e teste de recuperação '
                       'independentes ainda são obrigatórios.')}
