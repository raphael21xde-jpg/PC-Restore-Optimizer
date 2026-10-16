"""Pure Windows volume-letter normalization."""
import ntpath
import re

def volume_of(path):
    """Return Windows drive identity independent of the interpreter platform.

    UNC paths and paths with no drive are never silently assigned to C:.
    """
    text = str(path or '').replace('/', '\\')
    drive, _ = ntpath.splitdrive(text)
    if re.fullmatch(r'[A-Za-z]:', drive):
        return drive.upper()
    return 'SEM UNIDADE'


def drive_root(drive):
    if not re.fullmatch(r'[A-Za-z]:', str(drive)):
        raise ValueError('Aba não representa uma unidade Windows local')
    return drive.upper() + '\\'


