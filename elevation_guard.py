"""P2-02: the administrator lock shared by every restore engine.

This module has no imports from the project, so the engines (backup_features,
backup_core, browser_vault) can use it without import cycles. It only *reads*
whether the process is elevated; it never changes permissions, never elevates
and never writes anything.
"""
from __future__ import annotations

import ctypes
import sys

ELEVATION_WARNING = (
    'Atenção: o aplicativo está aberto como administrador. A restauração fica '
    'bloqueada porque a pasta nova seria criada com permissões de administrador, '
    'e seu usuário normal poderia não conseguir usar ou alterar os arquivos '
    'restaurados. Feche o aplicativo e abra de novo como usuário normal: '
    "abra pelo atalho normal, sem usar 'Executar como administrador'."
)

REFUSAL_MESSAGE = (
    'Restauração recusada: o aplicativo está rodando como administrador. '
    'Assim a pasta restaurada ficaria com permissões erradas (de administrador) '
    'e seu usuário normal poderia não conseguir abrir ou alterar os arquivos. '
    'Feche o aplicativo e abra de novo como usuário normal: '
    "abra pelo atalho normal, sem usar 'Executar como administrador'. "
    'Nada foi criado no destino.'
)


class ElevatedRestoreRefused(PermissionError):
    """Raised before any write when restoration would run elevated."""

    def __init__(self, message: str = REFUSAL_MESSAGE):
        super().__init__(message)


def _windows_probe() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def is_process_elevated(probe=None) -> bool:
    """Return True only when the process is confirmed elevated.

    ``probe`` is injectable for tests. Outside Windows, or when the check
    fails, the answer is False (the check is advisory and read-only).
    """
    try:
        if probe is not None:
            return bool(probe())
        if sys.platform != 'win32':
            return False
        return _windows_probe()
    except Exception:
        return False


def require_not_elevated(*, allow_elevated=False, probe=None) -> None:
    """Raise ElevatedRestoreRefused when elevated, unless allow_elevated is True.

    Only the literal ``True`` releases the guard; 1, 'yes' and similar values
    do not.
    """
    if allow_elevated is True:
        return
    if is_process_elevated(probe):
        raise ElevatedRestoreRefused()
