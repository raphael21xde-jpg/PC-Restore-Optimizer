"""Textos puros das telas de Visão Geral, Preservação e Instalação (sem tkinter).

Mantém a montagem de frases e a leitura da unidade do sistema separadas de
`workflow_ui.py`, permitindo testar os textos em ambientes sem `tkinter`.
"""
from __future__ import annotations

import os
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
