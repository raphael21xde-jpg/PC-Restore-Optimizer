"""Dry-run-only preservation and reinstall preparation planner.

An explicit 'não preservar' is NOT permission to delete; this module contains
no deletion, partitioning, formatting or boot manipulation functionality.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from volume_paths import volume_of

SYSTEM_VOLUMES = {'C:'}


def classify_choices(choices, system_volume='C:', *, scanned_roots=(), removal_candidates=()):
    entries = []
    counts = Counter()
    seen = set()
    for raw, choice in sorted(choices.items(), key=lambda p: str(p[0]).casefold()):
        if choice not in ('keep', 'skip', 'pending'):
            continue
        drive = volume_of(raw)
        token = (str(raw).casefold(), choice)
        if token in seen:
            continue
        seen.add(token)
        if choice == 'keep':
            action = 'COPIAR E VERIFICAR ANTES DO WINDOWS' if drive == system_volume else 'MANTER NO LOCAL'
        elif choice == 'skip':
            action = 'NÃO PRESERVAR NO PLANO (NÃO É EXCLUSÃO)'
        else:
            action = 'PENDENTE — NÃO EXCLUIR'
        entries.append({'path': str(raw), 'drive': drive, 'choice': choice, 'action': action})
        counts[(drive, choice)] += 1
    removal = sorted(str(p) for p in removal_candidates if p)
    warnings = [
        'Este relatório não executa nem autoriza exclusões, limpeza ou formatação.',
        'Arquivos sem escolha ou fora do inventário permanecem protegidos por padrão.',
        'Arquivos selecionados no volume do Windows exigem cópia independente, verificação e ensaio de restauração.',
        'Saves e dados vinculados a jogos em outros volumes devem ser revisados separadamente.',
        'Partições EFI, volumes dinâmicos e Storage Spaces exigem validação física antes de qualquer alteração.',
    ]
    return {
        'schema': 'pcro-preservation-dry-run-v1',
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'system_volume': system_volume,
        'scan_roots': list(scanned_roots),
        'entries': entries,
        'counts': [{'drive': disk, 'decision': decision, 'items': n}
                   for (disk, decision), n in sorted(counts.items())],
        'requires_verified_backup': [e['path'] for e in entries if e['drive'] == system_volume and e['choice'] == 'keep'],
        'removal_candidates': removal,
        'deletions_authorized': False,
        'installation_authorized': False,
        'warnings': warnings,
        'readiness': 'BLOQUEADO — plano informativo, backups e instalação não validados',
    }


def summarize(plan):
    stats = Counter(e['choice'] for e in plan['entries'])
    c = len(plan['requires_verified_backup'])
    return (f"{stats['keep']} caminho(s) marcados para manter; {stats['skip']} marcado(s) para não preservar "
            f"(não excluídos); {c} seleções do C: exigem cópia verificada. "
            'Formatação e exclusão desativadas.')
