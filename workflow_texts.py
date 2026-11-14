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

