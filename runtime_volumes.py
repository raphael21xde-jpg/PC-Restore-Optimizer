"""Descoberta de unidades Windows sem letras fixas. Somente leitura."""
import os
import ctypes

def discover_drive_letters():
    """Enumera volumes com letra acessíveis neste momento, sem assumir C/D/F/G."""
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
    """Nunca presume que um disco específico é seguro como destino."""
    return ""
