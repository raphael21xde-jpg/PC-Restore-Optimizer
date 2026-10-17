"""Complementos v0.5: rótulos não destrutivos e restauração seletiva isolada.
Compatível com manifestos v0.4. Não substitui arquivos originais.
"""
from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
import time
import uuid
from transfer_engine import choose_strategy, TransferMeter, ProgressLimiter, performance_report
from backup_core import atomic_json, is_reparse, sha256_file

LABEL_FILE = 'rotulos-v05.json'
SCHEMAS = {'pc-restore-backup-v0.4', 'pc-restore-backup-v0.5'}


def read_manifest(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') not in SCHEMAS or not isinstance(data.get('files'), list):
        raise ValueError('Manifesto de backup incompatível.')
    return data


def backup_labels(base):
    file = Path(base) / LABEL_FILE
    if not file.is_file():
        return {}
    try:
        value = json.loads(file.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def set_backup_label(manifest_path, label):
    manifest_path = Path(manifest_path)
    read_manifest(manifest_path)
    label = ' '.join(str(label).split())[:100]
    if not label:
        raise ValueError('O nome não pode ficar vazio.')
    parent = manifest_path.parent.parent
    labels = backup_labels(parent)
    labels[manifest_path.parent.name] = label
    atomic_json(parent / LABEL_FILE, labels)
    return label


def friendly_backup_name(manifest_path, data, labels=None):
    return (labels or {}).get(Path(manifest_path).parent.name) or data.get('display_name') or Path(manifest_path).parent.name


def safe_relative(text):
    """Reject path traversal, absolute paths, NTFS alternate streams and device names."""
    if not isinstance(text, str) or not text or '\x00' in text:
        raise ValueError('Caminho de restauração inválido.')
    w = PureWindowsPath(text)
    if w.is_absolute() or w.drive or text.startswith(('/', '\\')):
        raise ValueError('Caminho absoluto proibido no manifesto.')
    parts = text.replace('\\', '/').split('/')
    if any(x in ('', '.', '..') or ':' in x for x in parts):
        raise ValueError('Caminho inseguro no manifesto.')
    if any(re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', x) for x in parts):
        raise ValueError('Nome reservado do Windows no manifesto.')
    return Path(*parts)


def verified_entries(manifest_path):
    doc = read_manifest(manifest_path)
    entries = {}
    for item in doc['files']:
        if not isinstance(item, dict) or item.get('verified') is not True:
            continue
        rel = safe_relative(item.get('relative'))
        sha = item.get('sha256', '')
        if not isinstance(sha, str) or not re.fullmatch('[a-fA-F0-9]{64}', sha):
            raise ValueError('SHA-256 ausente ou inválido no manifesto.')
        k = rel.as_posix()
        if k in entries:
            raise ValueError('Arquivo duplicado no manifesto.')
        entries[k] = item
    return entries


def resume_information(folder, manifest_path):
    """Read a v0.5.19 partial restore journal; never follow a journal-supplied target."""
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir() or not folder.name.startswith('TESTE-RESTAURACAO-v05-'):
        raise ValueError('Escolha uma pasta de restauração criada por este aplicativo.')
    journal_file = folder/'ESTADO-RESTAURACAO.json'
    if not journal_file.is_file() or is_reparse(journal_file):
        raise ValueError('Registro de restauração não encontrado ou inseguro.')
    data = json.loads(journal_file.read_text(encoding='utf-8'))
    manifest_path = Path(manifest_path).resolve(strict=True)
    if (data.get('engine_version') != '0.5.19' or
        data.get('manifest_path') != str(manifest_path) or
        data.get('status') not in ('em_andamento','cancelada_parcial','falhou_parcial') or
        not isinstance(data.get('keys'), list) or not data['keys']):
        raise ValueError('Restauração concluída, antiga ou ligada a outro backup. Inicie teste novo.')
    entries = verified_entries(manifest_path)
    if len(set(data['keys'])) != len(data['keys']) or any(x not in entries for x in data['keys']):
        raise ValueError('Itens de retomada não correspondem ao manifesto atual.')
    return data


def restore_selected(manifest_path, choices, destination_parent, max_total_bytes=None, *,
                     cancelled=None, progress=None, resume_from=None,
                     strategy_inventory=None):
    """Restore verified files in an isolated folder; v0.5.19 resumes only its own journal.

    Verified destinations are rehashed when resuming; corrupt/uncertain files
    are recopied into fresh .partial files before atomic replace. Never writes
    to the backup itself or to the original source paths.
    """
    if cancelled and cancelled.is_set():
        raise InterruptedError('Restauração cancelada antes de iniciar.')
    manifest_path = Path(manifest_path).resolve(strict=True)
    backup_root = manifest_path.parent
    destination_parent = Path(destination_parent).resolve(strict=True)
    if not destination_parent.is_dir():
        raise ValueError('Destino de conferência inválido.')
    entries = verified_entries(manifest_path)
    choices = list(dict.fromkeys(choices))
    if not choices:
        raise ValueError('Selecione pelo menos um arquivo para testar.')
    if any(choice not in entries for choice in choices):
        raise ValueError('Seleção não existe entre os arquivos verificados.')
    if max_total_bytes is not None and sum(int(entries[c].get('bytes', 0)) for c in choices) > max_total_bytes:
        raise ValueError('Seleção excede o limite de tamanho para o teste.')
    if resume_from:
        target = Path(resume_from).resolve(strict=True)
        if target.parent != destination_parent or target == backup_root or target == destination_parent:
            raise ValueError('Destino de retomada diferente da pasta original de teste.')
        journal = resume_information(target, manifest_path)
        if journal['keys'] != choices:
            raise ValueError('A retomada exige exatamente a seleção original, na mesma ordem.')
        journal['resume_count'] = int(journal.get('resume_count', 0))+1
        journal['status'] = 'em_andamento'
        journal.pop('error', None)
    else:
        target = Path(tempfile.mkdtemp(prefix='TESTE-RESTAURACAO-v05-', dir=destination_parent))
        journal = {'status':'em_andamento', 'engine_version':'0.5.19',
                   'manifest_path':str(manifest_path), 'keys':choices, 'requested':len(choices),
                   'verified':0, 'verified_keys':[], 'resume_count':0}
    journal_file = target/'ESTADO-RESTAURACAO.json'
    atomic_json(journal_file, journal)
    byte_total = sum(int(entries[c].get('bytes') or 0) for c in choices)
    meter = TransferMeter(byte_total, len(choices))
    limiter = ProgressLimiter(progress)
    strategy = choose_strategy(backup_root, target, inventory=strategy_inventory)
    journal['transfer_strategy'] = strategy.description
    last_checkpoint = time.monotonic()
    copied_total = 0
    try:
        for index,choice in enumerate(choices):
            if cancelled and cancelled.is_set():
                raise InterruptedError('Restauração cancelada')
            if progress: progress('Conferindo arquivo do backup', index, len(choices), str(choice), 0, 0)
            relative = safe_relative(choice)
            candidate = backup_root
            for component in relative.parts:
                candidate = candidate/component
                if is_reparse(candidate):
                    raise ValueError(f'Link ou junção proibido no backup: {choice}')
            original = candidate.resolve(strict=True)
            if not original.is_relative_to(backup_root) or not original.is_file():
                raise ValueError('Arquivo de backup inseguro ou ausente.')
            expected = entries[choice]['sha256'].lower()
            restored = target/relative
            # Prevent writes redirected via junctions/symlinks on resumed folders.
            ancestor = restored.parent
            while ancestor != target:
                if is_reparse(ancestor):
                    raise ValueError('Pasta de restauração contém junção ou atalho inseguro.')
                ancestor = ancestor.parent
            restored.parent.mkdir(parents=True, exist_ok=True)
            total = int(entries[choice].get('bytes') or 0)
            if restored.exists() or is_reparse(restored):
                if is_reparse(restored) or not restored.is_file():
                    raise ValueError('Arquivo de destino é um link ou item inválido.')
                if restored.stat().st_size == total and sha256_file(restored,cancelled) == expected:
                    copied_total += total
                    journal['verified'] = index+1
                    if choice not in journal['verified_keys']: journal['verified_keys'].append(choice)
                    if progress: progress('Arquivo já verificado (retomada)',index+1,len(choices),choice,total,total)
                    continue
            partial = restored.with_name(restored.name+'.partial-'+uuid.uuid4().hex[:8])
            digest = hashlib.sha256()
            copied = 0
            try:
                with original.open('rb') as src, partial.open('xb') as dst:
                    while True:
                        if cancelled and cancelled.is_set(): raise InterruptedError('Restauração cancelada')
                        chunk = src.read(strategy.chunk)
                        if not chunk: break
                        dst.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                        limiter.send('Copiando',index,len(choices),choice,copied,total,force=copied==len(chunk))
                    dst.flush()
                    os.fsync(dst.fileno())
                if copied != total or digest.hexdigest() != expected:
                    raise OSError('SHA-256 ou tamanho não corresponde ao backup: '+choice)
                if progress: progress('Verificando arquivo restaurado',index,len(choices),choice,copied,total)
                if sha256_file(partial,cancelled) != expected:
                    raise OSError('Restauração não passou na conferência SHA-256: '+choice)
                partial.replace(restored)
                copied_total += copied
                journal['verified'] = index+1
                if choice not in journal['verified_keys']: journal['verified_keys'].append(choice)
                if progress: progress('Arquivo verificado',index+1,len(choices),choice,copied,total)
                if (index+1) % 512 == 0 or time.monotonic()-last_checkpoint > 15:
                    atomic_json(journal_file,journal)
                    last_checkpoint = time.monotonic()
            finally:
                try: partial.unlink(missing_ok=True)
                except OSError: pass
        journal['status'] = 'concluida'
        journal['performance'] = meter.snapshot(bytes_done=copied_total,files_done=len(choices))
        atomic_json(journal_file,journal)
        try:
            (target/'DESEMPENHO-RESTAURACAO.txt').write_text(
                performance_report(journal['performance'],journal['status'],
                                   journal.get('transfer_strategy','desconhecido'),'RESTAURACAO'),
                                   encoding='utf-8')
        except OSError:
            pass
        return target,len(choices)
    except Exception as exc:
        journal['status'] = 'cancelada_parcial' if isinstance(exc,InterruptedError) else 'falhou_parcial'
        journal['error'] = str(exc)
        journal['performance'] = meter.snapshot(bytes_done=copied_total, files_done=journal['verified'])
        try: atomic_json(journal_file,journal)
        except OSError: pass
        message=f'{exc}\nPasta parcial (não considerar restauração completa): {target}'
        if isinstance(exc,InterruptedError):raise InterruptedError(message) from exc
        raise OSError(message) from exc
