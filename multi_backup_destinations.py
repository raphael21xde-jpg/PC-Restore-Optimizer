"""User-selected multi-destination backup coordinator.

An explicit folder may be an internal drive, external drive, or the LOCAL
folder managed by an installed cloud-sync client. The latter does not prove
that files reached the provider. Direct cloud APIs/OAuth are NOT implemented.

Backups remain independent manifests and SHA-256 checked by selective_recovery.
Never creates partitions, formats devices, erases originals or changes EFI.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat

from backup_core import human_size
from selective_recovery import run_selected_backup, verify_complete_manifest
from volume_paths import volume_of

KINDS = ('local', 'external', 'synced_folder')
MAX_DESTINATIONS = 8
REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _resolved_folder(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Informe um destino existente.')
    candidate = Path(value)
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError('O destino precisa ser uma pasta absoluta e existente.')
    for parent in (candidate, *candidate.parents):
        try:
            st = os.lstat(parent)
        except OSError as exc:
            raise ValueError('Não foi possível validar um componente do destino.') from exc
        if stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & REPARSE):
            raise ValueError('Não é permitido utilizar link ou junção como destino.')
    return candidate.resolve(strict=True)


def _under(a, b):
    """True when path a is b or a descendant of b."""
    try:
        sa = os.path.normcase(os.path.realpath(os.fspath(a)))
        sb = os.path.normcase(os.path.realpath(os.fspath(b)))
        return os.path.commonpath((sa, sb)) == sb
    except (ValueError, OSError):
        return False


def make_multi_backup_plan(plan, destinations, *, usage=shutil.disk_usage,
                           disk_diagnostic=None):
    """Pure planning with metadata reads. Never approves safety for formatting.

    Existing run_selected_backup checks space again at copy time; this preview
    cannot reserve it. A label like 'external' comes from the user's choice,
    not trusted physical USB evidence.
    """
    if not getattr(plan, 'files', None) or getattr(plan, 'warnings', None):
        raise ValueError('Analise os arquivos primeiro; o plano precisa estar completo.')
    if not isinstance(destinations, (list, tuple)) or not 1 <= len(destinations) <= MAX_DESTINATIONS:
        raise ValueError('Selecione entre um e oito destinos distintos.')
    selected = []
    for record in destinations:
        if not isinstance(record, dict) or record.get('kind') not in KINDS:
            raise ValueError('Tipo de destino não suportado. Nuvem direta não configurada.')
        folder = _resolved_folder(record.get('path'))
        if os.name == 'nt' and volume_of(str(folder)) in ('SEM UNIDADE', 'C:'):
            # This scoped workflow backs up sources from C: only.
            raise ValueError('Nesta etapa, selecione uma pasta em outra unidade que não C:.')
        for item in plan.files:
            source = Path(item.source)
            if _under(folder, source) or _under(source, folder):
                raise ValueError('Destino contém ou está dentro de uma origem a preservar.')
            if os.name == 'nt' and volume_of(str(source)) == volume_of(str(folder)):
                raise ValueError('Origem e destino estão na mesma unidade.')
        for other in selected:
            if _under(folder, other['path']) or _under(other['path'], folder):
                raise ValueError('Destinos duplicados ou aninhados não são permitidos.')
        try:
            free = usage(folder).free
        except (OSError, ValueError) as exc:
            raise ValueError('Não foi possível ler a capacidade disponível.') from exc
        if type(free) is not int or free < 0:
            raise ValueError('Capacidade de destino inválida.')
        reserve = max(10 * 1024**3, int(free * .1))
        if plan.total > free - reserve:
            raise ValueError(
                'Sem espaço suficiente, incluindo reserva: ' + str(folder) +
                '. Necessário: ' + human_size(plan.total) + '; livres: ' +
                human_size(free) + '.')
        selected.append({
            'path': str(folder), 'kind': record['kind'],
            'bytes_free_reported': free,
            'source_size_bytes': int(plan.total),
            'cloud_upload_verified': False,
            'physical_independence_verified': False,
            'user_declared_kind': True,
            'preflight_status': 'requires_review',
        })
    # Compare with the current inventory only where available; a snapshot is
    # insufficient to certify independence, but a known conflict blocks copying.
    if isinstance(disk_diagnostic, dict):
        from backup_target_preflight import assess_backup_target
        source_letters = sorted({volume_of(str(t.source)).rstrip(':')
                                 for t in plan.files
                                 if volume_of(str(t.source)) != 'SEM UNIDADE'})
        for target in selected:
            drive = volume_of(target['path'])
            if drive == 'SEM UNIDADE':
                raise ValueError('Destino não corresponde a uma unidade Windows conhecida.')
            review = assess_backup_target(
                disk_diagnostic.get('disks', []), disk_diagnostic.get('volumes', []),
                disk_diagnostic.get('extent_mapping', {}),
                disk_diagnostic.get('spaces_membership', {}),
                target_letter=drive, source_letters=source_letters,
                expected_backup_bytes=int(plan.total))
            target['logical_disk_numbers'] = review['destination_logical_disks']
            target['preflight_status'] = review['status']
            target['preflight_issues'] = review['issues']
            if review['status'] == 'blocked':
                raise ValueError('Conflito reportado pelo diagnóstico: ' +
                                 '; '.join(review['blockers']))
    return {
        'schema': 'pcro-multi-backup-plan-v1',
        'destinations': selected, 'copies_requested': len(selected),
        'files_expected_per_copy': plan.count,
        'bytes_expected_per_copy': int(plan.total),
        'estimated_total_copy_bytes': int(plan.total) * len(selected),
        'physical_independence_verified': False,
        'cloud_upload_verified': False,
        'approved_for_format': False,
        'note': ('Tipos escolhidos pelo usuário. Capacidade é informação pontual; '
                 'cópias locais, discos externos e pastas sincronizadas não '
                 'certificam independência física nem envio à nuvem.')
    }


def run_multiple_backups(plan, multi_plan, *, cancelled=None, progress=None,
                         backup_runner=run_selected_backup):
    """Copy each selected folder separately and verify its own manifest.

    All destinations were screened by make_multi_backup_plan. A failed or
    cancelled copy stops the series and is reported, not silently skipped.
    No destination is ever marked cloud-verified or installation-ready.
    """
    targets = multi_plan.get('destinations') if isinstance(multi_plan, dict) else None
    if (multi_plan.get('schema') != 'pcro-multi-backup-plan-v1'
            or not isinstance(targets, list) or not targets):
        raise ValueError('Planejamento de múltiplos destinos inválido.')
    results = []
    for index, target in enumerate(targets, 1):
        if cancelled and cancelled.is_set():
            results.append({'path': target['path'], 'kind': target['kind'],
                            'status': 'cancelled_before_copy'})
            break
        try:
            callback = ((lambda *args: progress(index, len(targets), *args))
                        if progress else None)
            report = backup_runner(
                plan, target['path'], cancelled=cancelled, progress=callback)
            if not isinstance(report, dict) or report.get('backup_verified') is not True:
                raise OSError('O destino não retornou verificação de integridade.')
            results.append({
                'path': target['path'], 'kind': target['kind'],
                'status': 'local_copy_verified', 'manifest': report['manifest'],
                'backup_folder': report['backup_folder'],
                'files_verified': report['files_verified'],
                'bytes_verified': report['bytes_verified'],
                'cloud_upload_verified': False,
            })
        except (OSError, ValueError, InterruptedError) as exc:
            results.append({'path': target['path'], 'kind': target['kind'],
                            'status': 'failed_or_interrupted',
                            'error': str(exc)[:500]})
            break
    passed = len([x for x in results if x['status'] == 'local_copy_verified'])
    status = 'all_local_copies_verified' if passed == len(targets) else (
        'partially_verified' if passed else 'not_verified')
    return {
        'schema': 'pcro-multi-backup-result-v1',
        'completed_utc': datetime.now(timezone.utc).isoformat(),
        'status': status, 'copies_verified_locally': passed,
        'copies_requested': len(targets),
        'destinations': results,
        'cloud_upload_verified': False,
        'physical_independence_verified': False,
        'restore_test_verified': False,
        'ready_for_format': False,
        'installation_authorized': False,
        'note': ('Verificação SHA-256 de cada cópia concluída, quando indicada. '
                 'Pasta sincronizada NÃO significa que o provedor confirmou upload. '
                 'Uma cópia verificada não é prova de backup independente.')
    }
