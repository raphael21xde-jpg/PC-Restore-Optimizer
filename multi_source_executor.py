"""P2-09 fatias 1 e 2b: protected multi-disk backup executor (sandbox only).

The executor reuses the verified copy engine (backup_core.copy_backup) and the
read-only multi-source guards. In this slice it refuses to run without an
explicit test_root, and the app does not call it. It never formats, never
touches EFI/BCD, never erases anything and only ever READS the sources: each
destination receives its own backup folder and manifest, verified by SHA-256.

Slice 2b: before the first destination and again before each following
one, a NEW disk inventory (from the required ``disk_collector``) must prove,
through ``physical_independence.verify_physical_independence``, that every
destination is on another physical disk than the sources. Doubt, error or
same disk means no write. The executor only reads that answer; it never
writes any safety lock and never accepts a ready-made answer from outside.
It does not authorize formatting or installing anything.

Slice 3a: the copy also requires ``authorization``, made by
``copy_authorization.authorize_copy`` from the person's confirmation of the
preview. Right before the first byte the executor rebuilds the preview and
consumes that authorization (same preview, at most 5 minutes old, one-time
token). Anything else means no write. ``test_root`` is still required.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import backup_core
from copy_authorization import consume_authorization
from multi_backup_destinations import _under
from multi_source_recheck import recheck_multi_source_preview
from physical_independence import READ_ONLY_NOTE, verify_physical_independence
from selective_recovery import (_any_reparse_ancestor, validate_target,
                                verify_complete_manifest)

PREVIEW_SCHEMA = 'pcro-multi-source-executor-preview-v1'
RESULT_SCHEMA = 'pcro-multi-source-executor-v1'
DISPLAY_NAME = 'Copia protegida de varias origens'
NOT_RELEASED = ('Executor ainda não liberado: nesta fase ele só funciona '
                'numa área de teste isolada.')

# Short Portuguese explanations. Engine messages may contain paths with the
# user name, so they are never copied into the result or the report.
PROBLEMS = {
    'interrompido': 'A cópia foi interrompida antes do fim. Ela pode ser retomada.',
    'incompleto': 'A cópia terminou com arquivos faltando ou com erro.',
    'nao_verificado': 'A conferência SHA-256 encontrou arquivo ausente ou diferente.',
    'revalidacao': ('A origem ou o destino mudou desde a prévia, ou um disco '
                    'ficou inacessível. Faça uma nova prévia.'),
    'conferencia_cancelada': ('Destino com conferência cancelada antes do fim: '
                              'a cópia foi gravada, mas não foi conferida. Ela '
                              'pode ser conferida de novo.'),
    'falha': 'Não foi possível gravar neste destino.',
    'discos': ('Não deu para confirmar que os destinos ficam em outro disco, '
               'separado da origem. Nada foi gravado neste destino.'),
}
REFUSED_DISKS = ('Cópia recusada: não deu para confirmar que os destinos '
                 'ficam em outro disco, separado da origem. Nada foi gravado.')
NO_DISK_CHECK = 'A conferência dos discos não foi feita.'
REFUSED_CONFIRM = ('Cópia recusada: falta a sua confirmação para esta prévia, '
                   'ou ela mudou ou expirou. Faça a prévia e confirme de novo. '
                   'Nada foi gravado.')


def _sandbox(test_root):
    if test_root is None:
        raise ValueError(NOT_RELEASED)
    raw = Path(test_root)
    if not raw.is_absolute():
        raise ValueError('A área de teste precisa ser um caminho absoluto.')
    if raw == Path(raw.anchor):
        raise ValueError('A área de teste não pode ser a raiz de uma unidade.')
    _any_reparse_ancestor(raw)
    sandbox = raw.resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Área de teste inválida.')
    if sandbox == Path(sandbox.anchor):
        raise ValueError('A área de teste não pode ser a raiz de uma unidade.')
    # Safest choice: only a folder strictly inside the system temp folder.
    temp = Path(tempfile.gettempdir()).resolve()
    if temp not in sandbox.parents:
        raise ValueError('A área de teste precisa ficar dentro da pasta '
                         'temporária do sistema.')
    return sandbox


def _inside(value, sandbox):
    raw = Path(value)
    if not raw.is_absolute():
        raise ValueError('Caminho não é absoluto.')
    _any_reparse_ancestor(raw)
    resolved = raw.resolve(strict=True)
    if resolved == sandbox or sandbox not in resolved.parents:
        raise ValueError('Origem ou destino fora da área de teste.')
    return resolved


def _check(plan, target_preview, sandbox, volume_lookup, usage, resume_manifests):
    """Validate everything without writing.

    Returns (sources, rows, resume map, source volumes from the recheck).
    """
    files = getattr(plan, 'files', None)
    if not files or getattr(plan, 'warnings', None):
        raise ValueError('Plano de origem ausente ou incompleto.')
    if not isinstance(target_preview, dict):
        raise ValueError('Prévia de destinos inválida.')
    requested = target_preview.get('destinations')
    if not isinstance(requested, list) or not 1 <= len(requested) <= 8:
        raise ValueError('Informe entre um e oito destinos.')

    selected = getattr(plan, 'selected', None)
    if (not isinstance(selected, (list, tuple)) or not selected
            or not all(isinstance(item, str) for item in selected)):
        raise ValueError('Plano de origem sem as pastas escolhidas.')
    sources = []
    for task in files:
        sources.append(_inside(task.source, sandbox))
    # Folders that hold sources: a destination may not be inside them, and
    # they may not be inside a destination.
    protected = sorted({str(p.parent) for p in sources} |
                       {str(_inside(item, sandbox)) for item in selected})

    folders = []
    for row in requested:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise ValueError('Destino da prévia inválido.')
        folder = _inside(row['path'], sandbox)
        if not folder.is_dir():
            raise ValueError('Destino precisa ser uma pasta existente.')
        validate_target(str(folder), test_root=str(sandbox), forbidden=protected)
        for source in sources:
            if _under(folder, source) or _under(source, folder):
                raise ValueError('O destino não pode se sobrepor à origem.')
        folders.append(folder)

    # Resume requests are checked before the recheck, so a bad request is
    # reported as such even when the sources have also changed.
    resume = {}
    if resume_manifests is not None:
        if not isinstance(resume_manifests, dict):
            raise ValueError('Lista de retomada inválida.')
        by_path = {str(folder) for folder in folders}
        for key, value in resume_manifests.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError('Lista de retomada inválida.')
            if not Path(key).is_absolute():
                raise ValueError('Destino da retomada não é absoluto.')
            folder = str(Path(key).resolve())
            if folder not in by_path:
                raise ValueError('A retomada aponta para um destino fora da prévia.')
            manifest = _inside(value, sandbox)
            if (manifest.name != 'manifest.json' or not manifest.is_file()
                    or manifest.parent.parent != Path(folder)):
                raise ValueError('Manifesto de retomada inválido para este destino.')
            if folder in resume:
                raise ValueError('Apenas um manifesto de retomada por destino.')
            resume[folder] = str(manifest)
    fresh = recheck_multi_source_preview(
        plan, target_preview, volume_lookup=volume_lookup, usage=usage)
    if len(fresh['destinations']) != len(folders):
        raise ValueError('Quantidade de destinos mudou após a revalidação.')
    rows = []
    for number, (folder, observed) in enumerate(zip(folders, fresh['destinations']), 1):
        if str(folder) != observed['path']:
            raise ValueError('Destino divergente após a revalidação.')
        rows.append({'number': number, 'path': str(folder),
                     'volume': observed['volume'], 'free_bytes': observed['free_bytes']})

    return sources, rows, resume, fresh['source_volumes']


def _disk_check(source_volumes, rows, disk_collector):
    """Fresh physical-disk check: always a new inventory, never a cached one."""
    check = verify_physical_independence(
        source_volumes, [row['volume'] for row in rows],
        collector=disk_collector)
    summary = {'veredito': check['veredito'], 'texto': check['texto']}
    return check['physical_independence_verified'] is True, summary


def preview_execution(plan, target_preview, *, test_root, volume_lookup, usage,
                      disk_collector, resume_manifests=None):
    """Show what would be copied, writing nothing at all."""
    sandbox = _sandbox(test_root)
    sources, rows, resume, source_volumes = _check(
        plan, target_preview, sandbox, volume_lookup, usage, resume_manifests)
    _, summary = _disk_check(source_volumes, rows, disk_collector)
    return _preview(plan, sources, rows, resume, summary)


def _preview(plan, sources, rows, resume, summary):
    return {
        'schema': PREVIEW_SCHEMA,
        'sources': sorted({str(p.parent) for p in sources}),
        'destinations': [dict(row, resume=row['path'] in resume) for row in rows],
        'files_per_copy': plan.count,
        'bytes_per_copy': plan.total,
        'copies': len(rows),
        'bytes_total': plan.total * len(rows),
        'physical_check': summary,
    }


def _row(base, status, *, manifest=None, files=0, size=0, problem=None):
    return {'number': base['number'], 'path': base['path'], 'volume': base['volume'],
            'status': status, 'manifest': manifest, 'files_verified': files,
            'bytes_verified': size, 'problem': problem}


def run_protected_copy(plan, target_preview, *, test_root, volume_lookup, usage,
                       disk_collector, authorization, cancelled=None,
                       resume_manifests=None, progress=None):
    """Copy the plan to every destination, one verified manifest each.

    Everything is rechecked before the first write and again before each
    destination, including a new physical-disk check. The person's
    authorization for this exact preview is consumed before the first byte.
    Stops at the first problem. Sources are only read.
    """
    sandbox = _sandbox(test_root)
    sources, rows, resume, source_volumes = _check(
        plan, target_preview, sandbox, volume_lookup, usage, resume_manifests)
    independent, summary = _disk_check(source_volumes, rows, disk_collector)
    if not independent:
        raise ValueError(REFUSED_DISKS + '\n' + summary['texto'])
    current = _preview(plan, sources, rows, resume, summary)
    if consume_authorization(authorization, current,
                             clock=time.monotonic) is not True:
        raise ValueError(REFUSED_CONFIRM)
    results = []
    reason = None
    for base in rows:
        if cancelled is not None and cancelled.is_set():
            reason = f'Cancelado pelo usuário antes do destino {base["number"]}.'
            results.append(_row(base, 'cancelado'))
            break
        if base['number'] > 1:
            try:
                fresh = recheck_multi_source_preview(
                    plan, target_preview, volume_lookup=volume_lookup, usage=usage)
            except (OSError, ValueError):
                reason = PROBLEMS['revalidacao']
                results.append(_row(base, 'nao_iniciado', problem=reason))
                break
            independent, summary = _disk_check(
                fresh['source_volumes'], rows, disk_collector)
            if not independent:
                reason = PROBLEMS['discos']
                results.append(_row(base, 'nao_iniciado', problem=reason))
                break

        def report(*args, _number=base['number']):
            if progress is not None:
                progress(_number, *args)

        try:
            folder, manifest = backup_core.copy_backup(
                plan, base['path'], cancelled=cancelled, progress=report,
                display_name=DISPLAY_NAME, resume_manifest=resume.get(base['path']))
        except (OSError, ValueError):
            reason = PROBLEMS['falha']
            results.append(_row(base, 'falha', problem=reason))
            break
        manifest_path = str(Path(folder) / 'manifest.json')
        state = manifest.get('status')
        if state != 'concluido':
            key = 'interrompido' if state == 'interrompido' else 'incompleto'
            reason = PROBLEMS[key]
            results.append(_row(base, key, manifest=manifest_path, problem=reason))
            break
        try:
            checked = verify_complete_manifest(manifest_path, cancelled=cancelled)
        except (OSError, ValueError):
            # The verifier turns a cancel while hashing into OSError, and the
            # manifest is already 'concluido', so the copy cannot be resumed:
            # a cancel here is reported as such, never as a mismatch.
            if cancelled is not None and cancelled.is_set():
                reason = PROBLEMS['conferencia_cancelada']
                results.append(_row(base, 'cancelado', manifest=manifest_path,
                                    problem=reason))
                break
            reason = PROBLEMS['nao_verificado']
            results.append(_row(base, 'nao_verificado', manifest=manifest_path,
                                problem=reason))
            break
        if checked.get('files_verified') != plan.count:
            reason = PROBLEMS['nao_verificado']
            results.append(_row(base, 'nao_verificado', manifest=manifest_path,
                                problem=reason))
            break
        results.append(_row(base, 'verificado', manifest=manifest_path,
                            files=checked['files_verified'],
                            size=checked['bytes_verified']))
    for base in rows[len(results):]:
        results.append(_row(base, 'nao_iniciado'))

    verified = sum(row['status'] == 'verificado' for row in results)
    status = ('verificado' if verified == len(rows)
              else 'parcial' if verified else 'nao_verificado')
    return {'schema': RESULT_SCHEMA, 'status': status, 'reason': reason,
            'copies_requested': len(rows), 'copies_verified': verified,
            'files_per_copy': plan.count, 'bytes_per_copy': plan.total,
            'destinations': results, 'physical_check': summary}


STATUS_TEXT = {
    'verificado': 'cópia completa e verificada (SHA-256 de cada arquivo confere)',
    'nao_verificado': 'não verificado',
    'interrompido': 'interrompido (pode ser retomado)',
    'incompleto': 'incompleto, não verificado',
    'falha': 'falhou, não verificado',
    'cancelado': 'cancelado, nada foi gravado aqui',
    'nao_iniciado': 'não iniciado, nada foi gravado aqui',
}
CHECK_CANCELLED_TEXT = ('conferência cancelada: a cópia foi gravada, mas não '
                        'conferida; ela pode ser conferida de novo')


def format_report_pt(result):
    """Plain-Portuguese report. It never shows folder paths or user names."""
    overall = {
        'verificado': 'Todas as cópias foram feitas e conferidas.',
        'parcial': 'Só parte das cópias foi feita e conferida.',
        'nao_verificado': 'Nenhuma cópia foi conferida: o backup está não verificado.',
    }.get(result.get('status'), 'Situação desconhecida: trate o backup como não verificado.')
    lines = ['RELATÓRIO DA CÓPIA PROTEGIDA', '', overall,
             f'Cópias pedidas: {result.get("copies_requested", 0)}; '
             f'conferidas: {result.get("copies_verified", 0)}.',
             f'Cada cópia tem {result.get("files_per_copy", 0)} arquivo(s), '
             f'{backup_core.human_size(int(result.get("bytes_per_copy") or 0))}.']
    if result.get('reason'):
        lines.append('Motivo da parada: ' + result['reason'])
    lines.append('')
    for row in result.get('destinations', []):
        volume = row.get('volume')
        label = f'Destino {row.get("number")}'
        if isinstance(volume, str) and len(volume) == 2 and volume[1] == ':':
            label += f' (unidade {volume})'
        text = STATUS_TEXT.get(row.get('status'), 'não verificado')
        if row.get('status') == 'cancelado' and row.get('manifest'):
            text = CHECK_CANCELLED_TEXT
        lines.append(f'- {label}: {text}.')
    lines += ['',
              'Segurança: nenhum arquivo da origem foi gravado ou apagado; '
              'a origem só foi lida.',
              'Cada destino tem a sua própria lista de arquivos (manifesto).',
              '',
              'Conferência dos discos (a última feita antes de gravar):']
    check = result.get('physical_check')
    texto = check.get('texto') if isinstance(check, dict) else None
    if isinstance(texto, str) and texto.strip():
        # The judge's closing line says nothing was copied; here it would
        # contradict the copy report, so it is left out.
        lines += [line for line in texto.splitlines() if line != READ_ONLY_NOTE]
    else:
        lines.append(NO_DISK_CHECK)
    return '\n'.join(lines)
