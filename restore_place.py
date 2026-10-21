"""P2-01: colocar arquivos conferidos de volta no lugar original.

Duas etapas, sempre nesta ordem:

1. ``plan_placement`` monta a PREVIA (somente leitura). Para cada arquivo
   verificado do manifesto diz o que vai acontecer: ``novo`` (nao existe no
   destino), ``igual`` (mesmo SHA-256, nao mexe), ``renomear`` (existe e e
   diferente: o atual sera guardado com ``.antes-pcro-AAAAMMDD``),
   ``ignorado`` (``desktop.ini``), ``precisa_admin`` (Program Files,
   Program Files (x86) e ProgramData) ou ``bloqueado`` (destino inseguro,
   por exemplo uma pasta ou link no lugar do arquivo).
2. ``place_files`` executa a previa ja confirmada pela pessoa.

Decisoes (P2-01, 21/10/2026):

* A pasta de conferencia e CONSERVADA: o app copia, nao move. Mover pela
  pasta de conferencia levaria junto a DACL dela (a licao do osu!) e
  deixaria o backup conferido sem a copia boa. A pessoa apaga a pasta de
  conferencia por conta propria, quando quiser.
* Cada arquivo e escrito primeiro em ``<destino>.pcro-partial`` criado do
  zero na pasta final, por isso herda as permissoes da pasta. So depois do
  SHA-256 conferido ele ganha o nome final com ``os.replace``.
* O arquivo que ja existia e diferente nunca e apagado: e renomeado para
  ``<nome>.antes-pcro-AAAAMMDD`` (``-2``, ``-3``... se o nome ja existir).
* Em falha, o unico arquivo que o app pode descartar e o ``.pcro-partial``
  que ele mesmo criou. Um ``.pcro-partial`` que ja estava la fica intacto.
* Destinos protegidos sao pulados, salvo ``allow_protected=True``. Mesmo
  assim o app nunca pede elevacao: sem permissao, o arquivo vira falha no
  relatorio.
* O diario JSON e gravado de forma atomica depois de cada arquivo. Uma
  nova execucao com o mesmo plano pula o que ja foi colocado e conferido.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re

from backup_core import CHUNK, atomic_json, beneath, is_reparse, norm, sha256_file
from backup_features import safe_relative, verified_entries

JOURNAL_SCHEMA = 'pcro-placement-journal-v1'
PARTIAL_SUFFIX = '.pcro-partial'
ASIDE_INFIX = '.antes-pcro-'
CATEGORIES = ('novo', 'igual', 'renomear', 'ignorado', 'precisa_admin', 'bloqueado')
PROTECTED_VARS = ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'ProgramData')
IGNORED_NAMES = {'desktop.ini'}
ADMIN_MESSAGE = ('Sem permissão para gravar neste destino: ele precisa de administrador. '
                 'O app não pede elevação; o arquivo continua na pasta de conferência.')


@dataclass
class PlacementItem:
    key: str
    source: str
    target: Path
    staged: Path
    sha256: str
    size: int
    category: str
    existing: str = ''   # novo / igual / renomear (estado do destino na previa)
    reason: str = ''


@dataclass
class PlacementPlan:
    manifest_path: Path
    staging_folder: Path
    today: _dt.date
    items: list = field(default_factory=list)

    @property
    def stamp(self):
        return self.today.strftime('%Y%m%d')

    def counts(self):
        totals = {name: 0 for name in CATEGORIES}
        for item in self.items:
            totals[item.category] += 1
        return totals

    def fingerprint(self):
        body = [(i.key, str(i.target), i.sha256.lower()) for i in self.items]
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()


def _original_path(source):
    """Caminho original do manifesto: absoluto e sem '..', '.' ou fluxo NTFS."""
    if not isinstance(source, str) or not source or '\x00' in source:
        raise ValueError('Origem original ausente ou inválida no manifesto.')
    if not os.path.isabs(source):
        raise ValueError('Origem original sem caminho absoluto no manifesto.')
    rest = os.path.splitdrive(source)[1]
    parts = [p for p in re.split(r'[\\/]+', rest) if p]
    if not parts or any(p in ('.', '..') or ':' in p for p in parts):
        raise ValueError('Origem original insegura no manifesto.')
    return source


def _map_target(source, target_map):
    if not target_map:
        return Path(source)
    best = None
    for original, replacement in target_map.items():
        if beneath(source, original) and (best is None or len(norm(original)) > len(norm(best[0]))):
            best = (original, replacement)
    if best is None:
        raise ValueError('Origem fora do mapa de destino: ' + source)
    relative = os.path.relpath(os.path.abspath(source), os.path.abspath(best[0]))
    if relative in ('.', '') or relative.startswith('..'):
        raise ValueError('Destino inseguro depois do mapa: ' + source)
    target = Path(best[1]) / relative
    if not beneath(target, best[1]):
        raise ValueError('Destino escapa da pasta mapeada: ' + source)
    return target


def _protected(paths, environ):
    roots = [environ.get(name) for name in PROTECTED_VARS]
    return any(root and beneath(p, root) for root in roots for p in paths)


def _destination_state(target, expected_sha, cancelled=None):
    """Return (state, reason) without changing anything."""
    parent = target.parent
    if parent.exists() and (is_reparse(parent) or not parent.is_dir()):
        return 'bloqueado', 'A pasta de destino é um link, junção ou não é uma pasta.'
    if not os.path.lexists(target):
        return 'novo', ''
    if is_reparse(target) or not target.is_file():
        return 'bloqueado', 'Já existe uma pasta ou link com este nome no destino.'
    if sha256_file(target, cancelled).lower() == expected_sha.lower():
        return 'igual', ''
    return 'renomear', ''


def plan_placement(manifest_path, staging_folder, *, target_map=None, today=None, environ=None):
    """Monta a prévia (somente leitura) de onde cada arquivo conferido vai ficar.

    ``staging_folder`` é a pasta de conferência: o arquivo de cada entrada está
    em ``staging_folder / entry['relative']``. O destino é ``entry['source']``,
    ou, com ``target_map``, a mesma posição dentro de outra raiz.
    """
    manifest_path = Path(manifest_path)
    staging = Path(staging_folder).resolve(strict=True)
    environ = os.environ if environ is None else environ
    plan = PlacementPlan(manifest_path=manifest_path.resolve(strict=True), staging_folder=staging,
                         today=today or _dt.date.today())
    seen_targets = set()
    for key, entry in sorted(verified_entries(manifest_path).items()):
        relative = safe_relative(entry.get('relative'))
        staged = staging / relative
        if not beneath(staged, staging):
            raise ValueError('Arquivo de conferência fora da pasta de conferência.')
        source = _original_path(entry.get('source'))
        target = _map_target(source, target_map)
        marker = norm(target)
        if marker in seen_targets:
            raise ValueError('Dois arquivos do manifesto apontam para o mesmo destino.')
        seen_targets.add(marker)
        item = PlacementItem(key=key, source=source, target=target, staged=staged,
                             sha256=entry['sha256'], size=int(entry.get('bytes', 0) or 0),
                             category='novo')
        if target.name.lower() in IGNORED_NAMES:
            item.category, item.reason = 'ignorado', 'desktop.ini é recriado pelo Windows.'
        elif is_reparse(staged) or not staged.is_file():
            item.category, item.reason = 'bloqueado', 'Arquivo ausente ou inválido na pasta de conferência.'
        else:
            item.existing, item.reason = _destination_state(target, item.sha256)
            if item.existing == 'bloqueado':
                item.category = 'bloqueado'
            elif _protected((source, target), environ):
                item.category = 'precisa_admin'
                item.reason = 'Pasta do sistema: só com confirmação e permissão de administrador.'
            else:
                item.category = item.existing
        plan.items.append(item)
    return plan


def _aside_name(target, stamp):
    base = target.name + ASIDE_INFIX + stamp
    candidate = target.with_name(base)
    number = 2
    while os.path.lexists(candidate):
        candidate = target.with_name(f'{base}-{number}')
        number += 1
    return candidate


def _write_chunk(stream, data):
    stream.write(data)


def _copy_and_verify(item, partial, cancelled=None, test_after_copy_hook=None):
    """Copy staged -> partial (new file, exclusive create) and check SHA-256."""
    info = os.stat(item.staged)
    with open(item.staged, 'rb') as reader, open(partial, 'xb') as writer:
        while True:
            if cancelled and cancelled.is_set():
                raise InterruptedError('Operação cancelada.')
            data = reader.read(CHUNK)
            if not data:
                break
            _write_chunk(writer, data)
        writer.flush()
        os.fsync(writer.fileno())
    os.utime(partial, ns=(info.st_atime_ns, info.st_mtime_ns))
    if test_after_copy_hook:
        test_after_copy_hook(partial)
    if sha256_file(partial, cancelled).lower() != item.sha256.lower():
        raise OSError('SHA-256 da cópia não confere com o manifesto; o destino não foi alterado.')


def _load_journal(journal_path, plan):
    base = {'schema': JOURNAL_SCHEMA, 'manifest_path': str(plan.manifest_path),
            'staging_folder': str(plan.staging_folder), 'fingerprint': plan.fingerprint(),
            'status': 'em_andamento', 'done': {}, 'failures': [], 'in_progress': None}
    if not journal_path.exists():
        return base
    if is_reparse(journal_path) or not journal_path.is_file():
        raise ValueError('Diário da colocação inseguro.')
    data = json.loads(journal_path.read_text(encoding='utf-8'))
    if (data.get('schema') != JOURNAL_SCHEMA or data.get('fingerprint') != base['fingerprint'] or
            data.get('manifest_path') != base['manifest_path'] or
            data.get('staging_folder') != base['staging_folder'] or
            not isinstance(data.get('done'), dict)):
        raise ValueError('O diário pertence a outra colocação. Escolha um diário novo.')
    data['status'] = 'em_andamento'
    data['failures'] = []
    return data


def _discard_own_partial(partial):
    try:
        os.unlink(partial)
    except FileNotFoundError:
        pass


def place_files(plan, *, confirmed_preview=False, allow_protected=False, journal_path,
                cancelled=None, progress=None, test_after_copy_hook=None):
    """Coloca os arquivos da prévia no destino. Nunca apaga, nunca move da conferência."""
    if not confirmed_preview:
        raise ValueError('Mostre a prévia e peça confirmação antes de colocar os arquivos.')
    if journal_path is None:
        raise ValueError('Informe onde gravar o diário da colocação.')
    journal_path = Path(journal_path)
    if beneath(journal_path.resolve(), plan.staging_folder):
        raise ValueError('O diário não pode ficar dentro da pasta de conferência.')
    by_key = {item.key: item for item in plan.items}
    journal = _load_journal(journal_path, plan)
    pending = journal.get('in_progress')
    if isinstance(pending, dict) and pending.get('key') in by_key:
        # Sobra de uma execução interrompida: este .pcro-partial foi criado pelo app.
        expected = str(by_key[pending['key']].target) + PARTIAL_SUFFIX
        if pending.get('partial') == expected:
            _discard_own_partial(expected)
    journal['in_progress'] = None
    result = {'status': 'em_andamento', 'placed': [], 'renamed': [], 'equal': [], 'ignored': [],
              'skipped_protected': [], 'resumed': [], 'failures': [], 'journal': str(journal_path)}

    def fail(item, message):
        record = {'key': item.key, 'target': str(item.target), 'error': message}
        result['failures'].append(record)
        journal['failures'].append(record)

    total = len(plan.items)
    cancelled_run = False
    for index, item in enumerate(plan.items, 1):
        if cancelled and cancelled.is_set():
            cancelled_run = True
            break
        try:
            done = journal['done'].get(item.key)
            if item.category == 'ignorado':
                result['ignored'].append(item.key)
            elif item.category == 'bloqueado':
                fail(item, item.reason or 'Destino bloqueado.')
            elif item.category == 'precisa_admin' and not allow_protected:
                result['skipped_protected'].append(item.key)
            elif (done and item.target.is_file() and not is_reparse(item.target) and
                  sha256_file(item.target, cancelled).lower() == item.sha256.lower()):
                result['resumed'].append(item.key)
            else:
                _place_one(item, plan, journal, journal_path, result, fail, cancelled,
                           test_after_copy_hook)
        except InterruptedError:
            cancelled_run = True
            break
        atomic_json(journal_path, journal)
        if progress:
            progress(index, total, item.key)
    if cancelled_run:
        result['status'] = 'cancelado'
    elif result['failures']:
        result['status'] = 'concluido_com_falhas'
    else:
        result['status'] = 'concluido'
    journal['status'] = result['status']
    journal['in_progress'] = None
    atomic_json(journal_path, journal)
    return result


def _place_one(item, plan, journal, journal_path, result, fail, cancelled, hook):
    state, reason = _destination_state(item.target, item.sha256, cancelled)
    if state == 'bloqueado':
        fail(item, reason)
        return
    if state == 'igual':
        result['equal'].append(item.key)
        journal['done'][item.key] = {'action': 'igual', 'target': str(item.target),
                                     'sha256': item.sha256}
        return
    partial = Path(str(item.target) + PARTIAL_SUFFIX)
    created = False
    try:
        item.target.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(partial):
            fail(item, 'Já existe um arquivo .pcro-partial que não foi criado por esta colocação; '
                       'nada foi alterado.')
            return
        journal['in_progress'] = {'key': item.key, 'partial': str(partial)}
        atomic_json(journal_path, journal)
        created = True
        _copy_and_verify(item, partial, cancelled, hook)
        aside = None
        if state == 'renomear':
            aside = _aside_name(item.target, plan.stamp)
            os.rename(item.target, aside)
        try:
            os.replace(partial, item.target)
        except OSError:
            if aside is not None and not os.path.lexists(item.target):
                os.rename(aside, item.target)
            raise
        created = False
        if os.stat(item.target).st_size != os.stat(item.staged).st_size:
            raise OSError('Tamanho do arquivo colocado não confere.')
        entry = {'action': 'renomear' if aside else 'novo', 'target': str(item.target),
                 'sha256': item.sha256}
        if aside:
            entry['aside'] = str(aside)
            result['renamed'].append({'key': item.key, 'target': str(item.target),
                                      'aside': str(aside)})
        result['placed'].append(item.key)
        journal['done'][item.key] = entry
    except InterruptedError:
        raise
    except PermissionError:
        fail(item, ADMIN_MESSAGE)
    except FileExistsError:
        created = False
        fail(item, 'Já existe um arquivo .pcro-partial que não foi criado por esta colocação; '
                   'nada foi alterado.')
    except OSError as error:
        fail(item, str(error))
    finally:
        if created:
            _discard_own_partial(partial)
        journal['in_progress'] = None


def placement_report(plan, result):
    """Relatório em texto simples para mostrar na tela e salvar."""
    counts = plan.counts()
    lines = ['Colocar no lugar original — relatório', '',
             f'Manifesto: {plan.manifest_path}',
             f'Pasta de conferência: {plan.staging_folder}',
             f'Situação: {result.get("status", "?")}', '', 'Prévia por classe:']
    lines += [f'  {name}: {counts[name]}' for name in CATEGORIES]
    lines += ['', 'Resultado:',
              f'  colocados: {len(result.get("placed", []))}',
              f'  iguais (não mexidos): {len(result.get("equal", []))}',
              f'  já conferidos (retomada): {len(result.get("resumed", []))}',
              f'  ignorados: {len(result.get("ignored", []))}',
              f'  protegidos pulados: {len(result.get("skipped_protected", []))}']
    renamed = result.get('renamed', [])
    if renamed:
        lines += ['', 'Arquivos antigos guardados (nunca apagados):']
        lines += [f'  {r["target"]} -> {r["aside"]}' for r in renamed]
    failures = result.get('failures', [])
    lines += ['', f'Falhas: {len(failures)}']
    lines += [f'  {f["key"]}: {f["error"]}' for f in failures]
    lines += ['', 'A pasta de conferência foi conservada; apague-a só quando tiver certeza.']
    return '\n'.join(lines) + '\n'
