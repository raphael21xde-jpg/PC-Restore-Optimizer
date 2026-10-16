"""Descoberta de letras de unidade Windows sem configuração fixa. Somente leitura."""
import ctypes
import os

def discover_drive_letters():
    """Retorna letras atualmente informadas pelo Windows."""
    if os.name != "nt":
        return ()
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        if not mask:
            return ()
        return tuple(chr(65 + i) for i in range(26) if mask & (1 << i))
    except (AttributeError, OSError):
        return ()

def choose_backup_destination(letters):
    """Destino jamais definido somente pela letra de unidade."""
    return ""
