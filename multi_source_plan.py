"""Read-only multi-source backup planning; never copies, removes or formats.

This is a preview API for explicitly selected folders on different roots.
It does not certify backup destinations, physical separation or Windows setup.
"""
from __future__ import annotations

import os
from pathlib import Path

from backup_core import build_plan, beneath, norm
from selective_recovery import _any_reparse_ancestor

MAX_FILES = 400_000


def prepare_multi_source_preview(selected_paths, allowed_roots, *, choices=None,
                                 cancelled=None):
    """Build one non-destructive file plan for multiple explicitly allowed roots.

    The caller must obtain allowed_roots from user-approved inventory scope.
    No disk root may be selected wholesale. The backup executor is deliberately
    NOT connected here: target validation must be generalized separately.
    """
    if not isinstance(selected_paths, (list, tuple)) or not selected_paths:
        raise ValueError('Selecione arquivos ou pastas a preservar.')
    if not isinstance(allowed_roots, (list, tuple)) or not allowed_roots:
        raise ValueError('Informe as unidades ou pastas autorizadas.')
    roots = []
    for value in allowed_roots:
        p = Path(value)
        if not p.is_absolute() or not p.is_dir():
            raise ValueError(f'Raiz autorizada inválida: {value}')
        _any_reparse_ancestor(p)
        roots.append(norm(p))
    selected = []
    for value in selected_paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Seleção inválida.')
        p = Path(value)
        if not p.is_absolute() or not os.path.lexists(p):
            raise ValueError(f'Fonte inexistente ou não absoluta: {value}')
        _any_reparse_ancestor(p)
        item = norm(p)
        if not any(item != root and beneath(item, root) for root in roots):
            raise ValueError(f'Origem fora das raízes autorizadas: {value}')
        selected.append(item)
    normalized_choices = {}
    for path, decision in (choices or {}).items():
        if decision not in ('keep', 'skip'):
            continue
        key = norm(path)
        if not any(key != root and beneath(key, root) for root in roots):
            raise ValueError(f'Escolha fora das raízes autorizadas: {path}')
        normalized_choices[key] = decision
    for item in selected:
        normalized_choices[item] = 'keep'
    plan = build_plan(normalized_choices, roots, cancelled=cancelled)
    if plan.warnings:
        raise ValueError('Prévia incompleta; não copiar: ' + '; '.join(plan.warnings[:8]))
    if not plan.files:
        raise ValueError('Nenhum arquivo comum selecionado.')
    if plan.count > MAX_FILES:
        raise ValueError('Limite de arquivos excedido; divida em lotes.')
    targets = [task.destination.casefold() for task in plan.files]
    if len(set(targets)) != len(targets):
        raise ValueError('Colisão de caminhos no destino entre as origens.')
    return plan
