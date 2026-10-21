"""P2-02: warn about and refuse restoration from an elevated (administrator) process.

When the app runs "as administrator", the folders it creates are owned by the
Administrators group. The restored copy then ends up with permissions that the
normal user account cannot fully use. The lock itself lives in elevation_guard
(no project imports) and is re-exported here; since fatia 2 the engines
(restore_selected, restore_test, restore_to_staging) also check it as their
first instruction. guarded_restore_selected checks first and forwards
allow_elevated and elevation_probe to the engine, so both use the same answer.
"""
from __future__ import annotations

import ctypes  # noqa: F401  (kept: older tests patch restore_elevation.ctypes)
import sys  # noqa: F401  (kept: older tests patch restore_elevation.sys)

from backup_features import restore_selected
from elevation_guard import (  # noqa: F401  (re-exported)
    ELEVATION_WARNING, REFUSAL_MESSAGE, ElevatedRestoreRefused, _windows_probe,
    is_process_elevated, require_not_elevated,
)


def guarded_restore_selected(manifest, choices, destination, *, allow_elevated=False,
                             elevation_probe=None, **kwargs):
    """Check elevation before any write, then call restore_selected with the same lock."""
    require_not_elevated(allow_elevated=allow_elevated, probe=elevation_probe)
    return restore_selected(manifest, choices, destination, allow_elevated=allow_elevated,
                            elevation_probe=elevation_probe, **kwargs)
