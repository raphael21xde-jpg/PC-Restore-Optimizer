"""Read-only full SHA-256 audit of completed backups before any Windows reinstall.

Never claims a clean install is safe: physical-disk redundancy, verified browser
credentials, verified restores, Windows boot layout and recovery media require
separate human checks. No disk writes except an explicitly exported report.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import os
import re
from backup_core import sha256_file, is_reparse
from backup_features import read_manifest, safe_relative

HEX_SHA = re.compile(r'^[a-fA-F0-9]{64}$')


def audit_backup(manifest_file, on_progress=None, cancelled=None):
    manifest_file = Path(manifest_file).resolve(strict=True)
    if manifest_file.name != 'manifest.json':
        raise ValueError('Selecione um manifest.json de backup.')
    manifest = read_manifest(manifest_file)
    root = manifest_file.parent
    result = {
        'schema': 'pcro-full-backup-audit-1',
        'at_utc': datetime.now(timezone.utc).isoformat(),
        'manifest': str(manifest_file),
        'backup_status': manifest.get('status'),
        'expected': manifest.get('file_count_expected'),
        'listed': len(manifest['files']),
        'checked': 0, 'valid': 0, 'bytes_verified': 0,
        'errors': [], 'notes': [
            'Uma auditoria de cópia NÃO substitui teste real de restauração.',
            'O programa NÃO garante que programas instalados ou sessões de login serão restaurados.',
            'Cofres de navegador e senhas precisam de conferência separada.',
            'Backup no mesmo disco físico não fornece redundância contra falha desse disco.',
            'Confira partição EFI e boot ANTES de considerar reinstalação do Windows.',
        ],
        'approved_for_format': False,
    }
    if manifest.get('status') != 'concluido':
        result['errors'].append('Backup não está marcado como concluído.')
    expected = manifest.get('file_count_expected')
    if type(expected) is not int or expected <= 0 or expected != len(manifest['files']):
        result['errors'].append('Quantidade de arquivos não corresponde ao manifesto.')
    if manifest.get('errors'):
        result['errors'].append('Manifesto contém erros do backup original.')
    names = set()
    for index, item in enumerate(manifest['files'], 1):
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Auditoria interrompida; não foi concluída.')
        result['checked'] += 1
        if not isinstance(item, dict):
            result['errors'].append(f'Entrada {index}: registro inválido.')
            continue
        try:
            rel = safe_relative(item.get('relative'))
            rel_name = rel.as_posix().casefold()
            if rel_name in names:
                raise ValueError('Caminho duplicado no manifesto.')
            names.add(rel_name)
            if item.get('verified') is not True:
                raise ValueError('Originalmente não verificado.')
            sha = item.get('sha256')
            if not isinstance(sha, str) or not HEX_SHA.fullmatch(sha):
                raise ValueError('SHA-256 inválido.')
            size = item.get('bytes')
            if type(size) is not int or size < 0:
                raise ValueError('Tamanho inválido.')
            path = root
            for part in rel.parts:
                path = path / part
                if is_reparse(path):
                    raise ValueError('Atalho/junção não permitido na cópia.')
            resolved = path.resolve(strict=True)
            if os.path.commonpath([str(root), str(resolved)]) != str(root):
                raise ValueError('Arquivo saiu da pasta de backup.')
            if not resolved.is_file() or resolved.stat().st_size != size:
                raise ValueError('Arquivo ausente ou tamanho diferente.')
            if sha256_file(resolved, cancelled) != sha.lower():
                raise ValueError('SHA-256 divergente (arquivo alterado/corrompido).')
            result['valid'] += 1
            result['bytes_verified'] += size
        except InterruptedError:
            raise
        except (ValueError, OSError) as e:
            result['errors'].append(f"{str(item.get('relative', index))[:160]}: {str(e)[:240]}")
        if on_progress:
            on_progress(index, len(manifest['files']))
    result['integrity_ok'] = not result['errors'] and result['valid'] == result['listed']
    result['summary'] = ('ÍNTEGRO: todos os arquivos do manifesto conferem por SHA-256.' if result['integrity_ok']
                         else f"INCOMPLETO: {len(result['errors'])} problemas encontrados.")
    return result


def audit_text(r):
    lines = ['AUDITORIA INTEGRAL DO BACKUP — SOMENTE LEITURA', '',
             f"Resultado: {r['summary']}",
             f"Arquivos: {r['valid']} válidos de {r['listed']} | bytes conferidos: {r['bytes_verified']:,}",
             f"Manifesto: {r['manifest']}", '',
             'PRONTIDÃO PARA FORMATAR: NÃO AUTORIZADA AUTOMATICAMENTE',
             'A formatação NÃO faz parte desta versão.', '',
             'ETAPAS EXTERNAS OBRIGATÓRIAS:']
    lines += [f'  [ ] {item}' for item in r['notes']]
    if r['errors']:
        lines += ['', 'PROBLEMAS ENCONTRADOS:']
        lines += [f'  ! {error}' for error in r['errors'][:60]]
    return '\n'.join(lines)
