"""Textos puros das telas de Visão Geral, Preservação e Instalação (sem tkinter).

Mantém a montagem de frases e a leitura da unidade do sistema separadas de
`workflow_ui.py`, permitindo testar os textos em ambientes sem `tkinter`.
"""
from __future__ import annotations

import os
from volume_paths import volume_of
from windows_drive import _get, _letter, windows_drive


def system_drive(environ=None) -> str:
    """Unidade do Windows para os textos de tela (padrão 'C:').

    Reaproveita `windows_drive` (e `_letter`/`_get` de `windows_drive.py` quando
    só `SystemDrive` está presente no dicionário de ambiente).
    """
    env = os.environ if environ is None else environ
    confirmed, _warning = windows_drive(env)
    if confirmed:
        return confirmed
    return _letter(_get(env, 'SystemDrive')) or 'C:'


def overview_intro_text(drive: str | None = None) -> str:
    d = system_drive() if drive is None else drive
    return (
        f'Escolha o que manter em cada unidade. Prepare o {d} antes de reinstalar o Windows: '
        f'o que não for copiado dele não entra no backup e se perde quando o instalador formatar o {d}. '
        'O app não apaga nenhum arquivo dos outros discos e unidades.'
    )


def preservation_intro_text(drive: str | None = None) -> str:
    d = system_drive() if drive is None else drive
    return (
        f'{d} exige cópia verificada antes de reinstalar. O app não apaga nenhum arquivo, nem os itens pendentes. '
        f'O que ficar pendente ou desmarcado no {d} não entra no backup e se perde quando o instalador '
        f'formatar o {d}. O app não apaga nenhum arquivo dos outros discos e unidades.'
    )


def installation_steps(drive: str | None = None) -> list[tuple[str, str, str]]:
    d = system_drive() if drive is None else drive
    return [
        ('01', f'Preservar o {d}', 'Copiar e verificar arquivos pessoais, saves e configurações antes de o instalador apagar a partição do sistema.'),
        ('02', 'Vincular saves', f'Revisar dados do {d} associados a jogos instalados em outros discos ou unidades; o app não apaga nenhum arquivo desses discos; o que é do {d} só se salva com a cópia.'),
        ('03', 'Conferir os discos', 'Não alterar Storage Spaces nem volumes dinâmicos; revisar toda dependência de inicialização.'),
        ('04', 'EFI independente', 'Planejar EFI no SSD de instalação, mantendo a EFI antiga até testar o novo boot com segurança.'),
        ('05', 'Preparar Windows 11', 'Confirmar mídia oficial, edição/ativação, drivers, disco físico e plano de recuperação.'),
        ('06', 'Recuperar e testar', 'Reinstalar aplicativos e devolver saves aos caminhos originais. Validar Steam, osu! e navegadores.'),
    ]


def withdraw_choice_hint(drive: str | None = None) -> str:
    """Dica ao lado do botão 'Retirar do backup (não apaga)' na tela Preservação (FIX-P4-01-15)."""
    d = system_drive() if drive is None else drive
    return (
        'Selecione um caminho acima para retirar somente sua marcação '
        f'(no {d}, o item fica fora do backup e se perde quando o instalador formatar o {d}).'
    )


def withdraw_loss_warning(drive: str | None = None) -> str:
    """Aviso de perda na formatação para itens da unidade do Windows (FIX-P4-01-15)."""
    d = system_drive() if drive is None else drive
    return f'No {d}, este item fica fora do backup e se perde quando o instalador formatar o {d}. '


def withdraw_confirmation_text(
    path: str,
    *,
    linked: bool = False,
    drive: str | None = None,
) -> str:
    """Texto da pergunta ao retirar um caminho marcado na tela Preservação (FIX-P4-01-15)."""
    d = system_drive() if drive is None else drive
    notice = (
        '\n\nPor ser um dado associado a jogo, a escolha será '
        'marcada como NÃO PRESERVAR para que não volte automaticamente. '
        'A associação continuará disponível para revisão.'
        if linked else ''
    )
    loss = withdraw_loss_warning(d) if volume_of(path) == d else ''
    return (
        'Retirar este caminho do conjunto de arquivos a copiar?\n\n'
        + str(path)
        + notice
        + '\n\nO arquivo original NÃO será apagado. '
        + loss
        + 'Nenhuma cópia, limpeza ou formatação será realizada.'
    )


def browser_dest_label_text(dest: str) -> str:
    """Rótulo do destino atual na aba 'Navegadores' (FIX-P4-01-13)."""
    return f'Destino atual: {dest}   •   Sem sobrescrever perfis originais'


def preview_drives(plan: dict, *, drive: str | None = None) -> list[str]:
    """Lista ordenada de unidades para a prévia da Preservação (FIX-P4-01-14).

    Montada somente a partir do plano e da unidade do Windows (`drive`, ou
    `system_drive()` quando `drive` é `None`), somente leitura, sem consultar
    nem alterar discos: unidade do Windows primeiro, `system_volume` do plano
    (se for outro), unidades com entradas (`entries`), candidatos de remoção
    (`removal_candidates`), raízes de varredura (`scan_roots`) e volumes de
    jogos/apps (`selection_metrics.games_apps_by_display_volume`). Unidades fora
    do plano (e diferentes da unidade do Windows) não aparecem.
    """
    raw_drive = str(system_drive() if drive is None else drive)
    d = volume_of(raw_drive + '\\')
    if d == 'SEM UNIDADE':
        d = raw_drive.upper()
    found: set[str] = set()
    if volume_of(d + '\\') != 'SEM UNIDADE':
        found.add(volume_of(d + '\\'))
    sys_vol = str(plan.get('system_volume') or '')
    if volume_of(sys_vol + '\\') != 'SEM UNIDADE':
        found.add(volume_of(sys_vol + '\\'))
    for entry in plan.get('entries', ()) or ():
        vol = str(entry.get('drive') or '') if isinstance(entry, dict) else ''
        if volume_of(vol + '\\') != 'SEM UNIDADE':
            found.add(volume_of(vol + '\\'))
    for path in plan.get('removal_candidates', ()) or ():
        vol = volume_of(path)
        if vol != 'SEM UNIDADE':
            found.add(vol)
    for root in plan.get('scan_roots', ()) or ():
        vol = volume_of(root)
        if vol != 'SEM UNIDADE':
            found.add(vol)
    metrics = plan.get('selection_metrics') or {}
    for vol in (metrics.get('games_apps_by_display_volume') or {}):
        if volume_of(str(vol) + '\\') != 'SEM UNIDADE':
            found.add(volume_of(str(vol) + '\\'))
    return sorted(found, key=lambda v: (0 if v == d else 1, v))


def preview_drive_rows(plan: dict, *, drive: str | None = None) -> list[dict]:
    """Monta os blocos por unidade da prévia da Preservação a partir do plano (FIX-P4-01-14).

    Somente leitura: nunca apaga nada.
    """
    entries_all = list(plan.get('entries', ()) or ())
    removal_all = [str(p) for p in (plan.get('removal_candidates', ()) or ()) if p]
    scan_roots = [str(r) for r in (plan.get('scan_roots', ()) or ()) if r]
    stats = plan.get('selection_metrics') or {}
    by_vol = stats.get('games_apps_by_display_volume') or {}
    rows: list[dict] = []
    for vol in preview_drives(plan, drive=drive):
        entries = [e for e in entries_all if isinstance(e, dict) and e.get('drive') == vol]
        removed = [p for p in removal_all if volume_of(p) == vol]
        entity_count = int(by_vol.get(vol, 0))
        scanned = any(volume_of(r) == vol for r in scan_roots)
        excess = max(0, len(entries) - 150) + max(0, len(removed) - 75)
        rows.append({
            'drive': vol,
            'header': f'{vol}  •  {len(entries)} caminho(s), {entity_count} jogo(s)/app(s)',
            'scan_status': 'Varredura atual: ' + ('sim' if scanned else 'não confirmada'),
            'entries': entries[:150],
            'removed': removed[:75],
            'excess': excess,
        })
    return rows

