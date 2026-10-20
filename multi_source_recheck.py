"""Pre-execution read-only guard for multi-source backup previews.

A successful check is NOT permission to format or write to originals. The
copy engine still needs its own source/target checks at actual I/O time.
"""
from __future__ import annotations

from pathlib import Path

from selective_recovery import _any_reparse_ancestor
from multi_source_targets import preview_multi_source_targets, diagnostic_fingerprint


def recheck_multi_source_preview(plan, target_preview, *, volume_lookup,
                                 usage, disk_diagnostic=None):
    """Reject changes to source metadata or destination safety since preview."""
    if not isinstance(target_preview, dict) or target_preview.get('schema') != 'pcro-multi-source-target-preview-v1':
        raise ValueError('Prévia de destino ausente ou inválida.')
    if target_preview.get('backup_verified') is not False or target_preview.get('installation_authorized') is not False:
        raise ValueError('Prévia não pode autorizar cópia nem instalação.')
    expected_fingerprint = target_preview.get('disk_diagnostic_sha256')
    if expected_fingerprint is not None:
        if disk_diagnostic is None:
            raise ValueError('Diagnóstico atualizado obrigatório para revalidação.')
        if diagnostic_fingerprint(disk_diagnostic) != expected_fingerprint:
            raise ValueError('Diagnóstico de discos alterado; refaça a prévia.')
    elif disk_diagnostic is not None:
        raise ValueError('Prévia antiga sem diagnóstico; refaça a prévia.')
    files = getattr(plan, 'files', None)
    if not files or getattr(plan, 'warnings', None):
        raise ValueError('Plano incompleto.')
    for task in files:
        source = Path(task.source)
        _any_reparse_ancestor(source)
        try:
            st = source.stat()
        except OSError as exc:
            raise ValueError('Fonte desapareceu ou tornou-se inacessível.') from exc
        if not source.is_file() or st.st_size != task.size or st.st_mtime_ns != task.mtime_ns:
            raise ValueError('Fonte modificada depois do planejamento.')
    original = target_preview.get('destinations')
    if not isinstance(original, list) or not original:
        raise ValueError('Nenhum destino na prévia.')
    paths = [row.get('path') for row in original if isinstance(row, dict)]
    if len(paths) != len(original) or any(not isinstance(p, str) for p in paths):
        raise ValueError('Destino da prévia inválido.')
    fresh = preview_multi_source_targets(plan, paths, usage=usage,
                                         volume_lookup=volume_lookup,
                                         disk_diagnostic=disk_diagnostic)
    if fresh['source_volumes'] != target_preview.get('source_volumes'):
        raise ValueError('Unidades de origem mudaram desde a prévia.')
    for old, current in zip(original, fresh['destinations']):
        if old.get('path') != current['path'] or old.get('volume') != current['volume']:
            raise ValueError('Destino ou unidade mudou desde a prévia.')
    return fresh
