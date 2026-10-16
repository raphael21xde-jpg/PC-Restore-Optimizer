"""Backup engine: read-only inventory + copy/verify, never delete originals or format.

Python 3.10+; only standard library. Used by GUI and headless tests.
"""
from __future__ import annotations
from backup_identity import owners_for, title_for, slug, inventory_text

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib
import json
import ntpath
import os
import shutil
import stat
import time
import uuid
from transfer_engine import choose_strategy, TransferMeter, ProgressLimiter, performance_report

CHUNK = 2 * 1024 * 1024
REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def norm(value):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(value))))


def beneath(path, ancestor):
    path, ancestor = norm(path), norm(ancestor)
    try:
        return os.path.commonpath((path, ancestor)) == ancestor
    except ValueError:
        return False


def is_reparse(path):
    try:
        info = os.lstat(path)
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & REPARSE_FLAG)
    except OSError:
        return False


def human_size(num):
    num = float(num)
    for suffix in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(num) < 1024 or suffix == 'TiB':
            return f'{num:,.1f} {suffix}' if suffix != 'B' else f'{num:,.0f} B'
        num /= 1024


def effective_choice(path, choices):
    path = norm(path)
    while True:
        if path in choices:
            return choices[path]
        parent = os.path.dirname(path)
        if parent == path:
            return 'pending'
        path = parent


def destination_relative(src):
    """Unique, relative backup namespace per volume, with no path escape."""
    src = norm(src)
    drive, tail = ntpath.splitdrive(src)
    if drive and len(drive) == 2 and drive[1] == ':':
        namespace = drive[0].upper()
        components = [c for c in tail.replace('\\', '/').split('/') if c not in ('', '.', '..')]
    else:
        # Test convenience on non-Windows, not a permitted live GUI source.
        namespace = 'TEST'
        components = [c for c in src.replace('\\', '/').split('/') if c not in ('', '.', '..')]
    return str(Path(namespace, *components))


@dataclass
class FileTask:
    source: str
    size: int
    mtime_ns: int
    destination: str


@dataclass
class Plan:
    files: list[FileTask] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total: int = 0

    @property
    def count(self):
        return len(self.files)


def build_plan(choices, allowed_roots, cancelled=None, progress=None):
    """Scan only explicit 'keep' selections; nearest explicit choice wins.

    A skipped child can be kept again by explicitly selecting a grandchild.
    Files and directories reached through symlinks/junctions are never followed.
    Errors remain warnings so the GUI prevents an incomplete backup from starting.
    """
    choices = {norm(p): s for p, s in choices.items() if s in ('keep', 'skip')}
    roots = [norm(p) for p in allowed_roots if os.path.isdir(p)]
    result = Plan(selected=sorted(p for p, s in choices.items() if s == 'keep'),
                  skipped=sorted(p for p, s in choices.items() if s == 'skip'))
    if not roots:
        result.warnings.append('Nenhuma unidade de origem acessível.')
        return result
    keep = [p for p, s in choices.items() if s == 'keep']
    keep_roots = [p for p in keep if not any(p != q and beneath(p, q) for q in keep)]
    count_scanned = 0
    listed = set()

    def is_prohibited(path):
        return not any(beneath(path, root) and norm(path) != root for root in roots)

    for root in sorted(keep_roots):
        if cancelled and cancelled.is_set():
            raise InterruptedError('Prévia cancelada')
        if is_prohibited(root):
            result.warnings.append(f'Seleção fora das unidades permitidas ou da raiz do disco: {root}')
            continue
        if not os.path.lexists(root):
            result.warnings.append(f'Item selecionado não existe mais: {root}')
            continue
        # A selected child of a reparse parent must not be traversed either.
        x = root
        while any(beneath(x, ar) for ar in roots):
            if is_reparse(x):
                result.warnings.append(f'Atalho/junção não pode ser copiado diretamente: {x}')
                break
            parent = os.path.dirname(x)
            if parent == x:
                break
            x = parent
        else:
            pass
        if any(is_reparse(a) for a in _ancestors_until(root, roots)):
            continue
        stack = [root]
        while stack:
            if cancelled and cancelled.is_set():
                raise InterruptedError('Prévia cancelada')
            path = stack.pop()
            if path in listed:
                continue
            listed.add(path)
            if is_reparse(path):
                result.warnings.append(f'Atalho/junção ignorado para evitar cópia incorreta: {path}')
                continue
            try:
                is_dir = os.path.isdir(path)
                status = effective_choice(path, choices)
                # Skip a subtree if it cannot contain a more-specific 'keep'.
                if status != 'keep' and not any(k != path and beneath(k, path) for k in keep):
                    continue
                if is_dir:
                    with os.scandir(path) as scan:
                        entries = list(scan)
                    for ent in entries:
                        stack.append(norm(ent.path))
                else:
                    if status != 'keep':
                        continue
                    st = os.stat(path, follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode):
                        result.warnings.append(f'Não é um arquivo comum: {path}')
                        continue
                    result.files.append(FileTask(path, st.st_size, st.st_mtime_ns, destination_relative(path)))
                    result.total += st.st_size
                count_scanned += 1
                if progress and count_scanned % 250 == 0:
                    progress(count_scanned)
            except (PermissionError, OSError) as exc:
                result.warnings.append(f'Sem acesso a {path}: {exc}')
    result.files.sort(key=lambda item: item.source.casefold())
    return result


def _ancestors_until(path, roots):
    current = norm(path)
    while True:
        yield current
        if current in roots:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent


def free_space(folder):
    return shutil.disk_usage(str(folder)).free


def reserve_bytes(free):
    # Reserve the greater of 10 GiB and 10% of currently available space.
    return max(10 * 1024**3, int(free * .10))


def check_space(plan, destination):
    free = free_space(destination)
    buffer = reserve_bytes(free)
    return free, buffer, plan.total <= free - buffer


def sha256_file(path, cancelled=None):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while True:
            if cancelled and cancelled.is_set():
                raise InterruptedError('Operação interrompida')
            data = stream.read(CHUNK)
            if not data:
                return digest.hexdigest()
            digest.update(data)


def atomic_json(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _plan_fingerprint(plan):
    """Exact source/path/size/timestamp binding for safe interrupted-job resume."""
    body = [(str(t.source), str(t.destination), int(t.size), int(t.mtime_ns)) for t in plan.files]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def copy_backup(plan, backup_base, cancelled=None, progress=None, planned_disks=(),
                display_name=None, item_descriptors=None, *, resume_manifest=None):
    """Verified isolated backup with progress throttling and opt-in safe resume.

    Existing v0.4 manifests remain readable. Resume is allowed ONLY for v0.5.19
    interrupted jobs whose exact plan fingerprint matches. Neither routine
    deletes or modifies originals; resume may replace only files inside its own
    incomplete backup directory after independently verifying their hashes.
    """
    if not plan.files:
        raise ValueError('Nenhum arquivo selecionado para o backup.')
    if plan.warnings:
        raise ValueError('Corrija os problemas de leitura antes do backup.')
    backup_base = Path(backup_base).resolve()
    backup_base.mkdir(parents=True, exist_ok=True)
    digest_plan = _plan_fingerprint(plan)
    item_descriptors = list(item_descriptors or [])
    display_name = display_name or title_for(item_descriptors)
    resume = resume_manifest is not None
    if resume:
        manifest_path = Path(resume_manifest).resolve(strict=True)
        folder = manifest_path.parent
        if manifest_path.name != 'manifest.json' or not beneath(folder, backup_base) or folder == backup_base:
            raise ValueError('A retomada deve apontar para um manifesto dentro do destino de backup.')
        if is_reparse(folder):
            raise ValueError('Pasta de backup com link ou junção não pode ser retomada.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if (manifest.get('schema') != 'pc-restore-backup-v0.4' or
            manifest.get('engine_version') != '0.5.19' or
            manifest.get('status') not in ('em_andamento', 'interrompido', 'parcial_com_erros') or
            manifest.get('plan_fingerprint') != digest_plan):
            raise ValueError('Backup incompatível, concluído ou plano de origem modificado. Faça novo backup.')
        existing = {}
        for item in manifest.get('files', []):
            key = item.get('relative')
            if key in existing:
                raise ValueError('Manifesto com caminhos duplicados.')
            existing[key] = item
        if any(k not in {t.destination for t in plan.files} for k in existing):
            raise ValueError('Manifesto não corresponde aos caminhos do plano atual.')
        # Reserve space for not-yet-verified files; files from the manifest
        # might still need re-copying if the checksum check finds corruption.
        pending = sum(t.size for t in plan.files if t.destination not in existing)
        free = free_space(backup_base)
        reserve = reserve_bytes(free)
        if pending > max(0, free-reserve):
            raise OSError(f'Espaço insuficiente para retomar ({human_size(pending)} pendentes).')
        manifest['resume_count'] = int(manifest.get('resume_count', 0))+1
        manifest['errors'] = []
        manifest['status'] = 'em_andamento'
    else:
        free, reserve, adequate = check_space(plan, backup_base)
        if not adequate:
            raise OSError(f'Espaço insuficiente ({human_size(free)} livres; reserva {human_size(reserve)}).')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        folder = backup_base / f'backup-{stamp}-{slug(display_name)}-{uuid.uuid4().hex[:6]}'
        folder.mkdir()
        manifest_path = folder / 'manifest.json'
        manifest = dict(schema='pc-restore-backup-v0.4', engine_version='0.5.19',
                        started=datetime.now().isoformat(), display_name=str(display_name or '')[:300],
                        item_descriptors=item_descriptors, planned_disks=list(planned_disks),
                        plan_fingerprint=digest_plan, status='em_andamento',
                        bytes_expected=plan.total, file_count_expected=plan.count,
                        files=[], errors=[], resume_count=0)
        existing = {}
    strategy = choose_strategy(plan.files[0].source, backup_base)
    manifest['transfer_strategy'] = strategy.description
    atomic_json(manifest_path, manifest)  # checkpoint before writing the first file
    meter = TransferMeter(plan.total, plan.count)
    notify = ProgressLimiter(progress)
    copied = 0
    completed = 0
    stopped = False
    last_checkpoint = time.monotonic()
    try:
        for index, task in enumerate(plan.files, 1):
            temp = None
            try:
                if cancelled and cancelled.is_set():
                    stopped = True
                    break
                source = Path(task.source)
                if is_reparse(source):
                    raise OSError('Fonte virou um link/junção após a conferência')
                current = os.stat(source, follow_symlinks=False)
                if current.st_size != task.size or current.st_mtime_ns != task.mtime_ns:
                    raise OSError('Arquivo mudou desde a conferência; gere nova prévia')
                destination = folder / task.destination
                if not beneath(destination, folder):
                    raise ValueError('Destino fora da pasta de backup.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Do not trust junctions added between interrupted runs.
                ancestor = destination.parent
                while ancestor != folder:
                    if is_reparse(ancestor):
                        raise ValueError('Junção encontrada no destino do backup.')
                    ancestor = ancestor.parent
                entry = existing.get(task.destination)
                if entry is not None and entry.get('verified') is True and entry.get('bytes') == task.size:
                    if (destination.is_file() and not is_reparse(destination) and
                        sha256_file(destination, cancelled) == entry.get('sha256')):
                        copied += task.size
                        completed += 1
                        notify.send(index, plan.count, copied, plan.total, str(source), force=True)
                        continue
                # A crash may leave an already-written atomic file before the
                # next manifest checkpoint. Adopt it only after verifying BOTH
                # source and destination, without trusting its filename alone.
                if entry is None and destination.is_file() and not is_reparse(destination):
                    if destination.stat().st_size == task.size:
                        source_hash = sha256_file(source, cancelled)
                        destination_hash = sha256_file(destination, cancelled)
                        if source_hash == destination_hash:
                            new_entry = {'source': str(source), 'relative': task.destination,
                                         'bytes': task.size, 'sha256': destination_hash,
                                         'verified': True, 'owners': owners_for(source, item_descriptors)}
                            manifest['files'].append(new_entry)
                            existing[task.destination] = new_entry
                            copied += task.size
                            completed += 1
                            notify.send(index, plan.count, copied, plan.total, str(source), force=True)
                            continue
                temp = destination.with_name(destination.name + '.partial-' + uuid.uuid4().hex[:8])
                dig = hashlib.sha256()
                size_read = 0
                with open(source, 'rb') as src, open(temp, 'xb') as dst:
                    while True:
                        if cancelled and cancelled.is_set():
                            raise InterruptedError('Backup interrompido')
                        data = src.read(strategy.chunk)
                        if not data:
                            break
                        dst.write(data)
                        dig.update(data)
                        size_read += len(data)
                        notify.send(index, plan.count, copied + size_read, plan.total, str(source))
                    dst.flush()
                    os.fsync(dst.fileno())
                after = os.stat(source, follow_symlinks=False)
                if (after.st_size != task.size or after.st_mtime_ns != task.mtime_ns or size_read != task.size):
                    raise OSError('Fonte alterada enquanto copiava; arquivo não validado')
                copy_digest = sha256_file(temp, cancelled)
                if copy_digest != dig.hexdigest():
                    raise OSError('SHA-256 não corresponde ao arquivo original')
                os.replace(temp, destination)
                temp = None
                try:
                    shutil.copystat(source, destination, follow_symlinks=False)
                except OSError:
                    pass
                new_entry = {'source': str(source), 'relative': task.destination,
                             'bytes': size_read, 'sha256': copy_digest,
                             'verified': True, 'owners': owners_for(source, item_descriptors)}
                if entry is not None:
                    # Replacement of verified metadata for a corrupt interrupted copy.
                    manifest['files'] = [x for x in manifest['files'] if x.get('relative') != task.destination]
                manifest['files'].append(new_entry)
                existing[task.destination] = new_entry
                copied += size_read
                completed += 1
                notify.send(index, plan.count, copied, plan.total, str(source), force=True)
                if completed % 512 == 0 or time.monotonic()-last_checkpoint > 15:
                    atomic_json(manifest_path, manifest)
                    last_checkpoint = time.monotonic()
            except InterruptedError:
                stopped = True
                break
            except (OSError, ValueError) as err:
                manifest['errors'].append({'source': task.source, 'error': str(err)})
            finally:
                if temp is not None:
                    try:
                        Path(temp).unlink(missing_ok=True)
                    except OSError:
                        pass
        manifest['status'] = ('interrompido' if stopped else
                              ('concluido' if not manifest['errors'] and len(manifest['files']) == plan.count
                               else 'parcial_com_erros'))
    except Exception as exc:
        manifest['status'] = 'parcial_com_erros'
        manifest['errors'].append({'error': repr(exc)})
    finally:
        manifest['finished'] = datetime.now().isoformat()
        manifest['bytes_verified'] = sum(int(x.get('bytes') or 0) for x in manifest['files'])
        manifest['performance'] = meter.snapshot(bytes_done=copied, files_done=completed)
        atomic_json(manifest_path, manifest)
        try:
            (folder / 'DESEMPENHO-BACKUP.txt').write_text(
                performance_report(manifest['performance'],manifest['status'],
                                   manifest.get('transfer_strategy','desconhecido'),'BACKUP'), encoding='utf-8')
        except OSError:
            pass
        try:
            (folder / 'CONTEUDO-DO-BACKUP.txt').write_text(inventory_text(manifest), encoding='utf-8')
        except OSError as error:
            manifest['inventory_warning'] = str(error)
            atomic_json(manifest_path, manifest)
    return folder, manifest


def restore_test(manifest_file, destination_root, limit=50*1024**2):
    """Restore one small verified file into a NEW folder on the backup drive."""
    manifest_file = Path(manifest_file).resolve()
    data = json.loads(manifest_file.read_text(encoding='utf-8'))
    if data.get('schema') != 'pc-restore-backup-v0.4':
        raise ValueError('Manifesto não pertence ao backup v0.4.')
    options = sorted((item for item in data.get('files', []) if item.get('verified') and item.get('bytes', limit+1) <= limit), key=lambda i: i['bytes'])
    if not options:
        raise ValueError('Nenhum arquivo verificado de até 50 MiB para restaurar no teste.')
    item = options[0]
    relative = Path(item['relative'])
    origin = (manifest_file.parent / relative).resolve()
    if not beneath(origin, manifest_file.parent.resolve()):
        raise ValueError('Caminho inválido no manifesto.')
    if not origin.is_file() or is_reparse(origin):
        raise OSError('Arquivo de backup ausente ou inválido.')
    target_folder = Path(destination_root) / ('teste-restauracao-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:5])
    restored = target_folder / relative
    restored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origin, restored)
    if sha256_file(restored) != item['sha256'] or sha256_file(origin) != item['sha256']:
        raise OSError('O teste de restauração não passou na verificação SHA-256.')
    return restored
