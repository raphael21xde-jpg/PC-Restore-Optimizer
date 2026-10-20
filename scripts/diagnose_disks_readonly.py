"""Explicit, read-only disk mapping review; output has no raw disk serials.

Example (replace letters according to your machine, never assume C/D/F/G):
    py -3 scripts/diagnose_disks_readonly.py --sources C,D --targets G

This uses Get-Disk/Get-Volume/extent diagnostics in READ-ONLY mode. No writes,
backup, cleanup, Windows installation, diskpart commands or format calls.
A successfully collected report NEVER authorizes any disk operation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drive_safety_report import inspect_fresh_drive_safety


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Conferir vínculos lógicos de discos sem modificar arquivos.')
    parser.add_argument('--sources', required=True,
                        help='Letras das unidades com arquivos a preservar, ex.: C,D')
    parser.add_argument('--targets', required=True,
                        help='Letras dos destinos candidatos, ex.: G,H')
    parser.add_argument('--estimated-bytes', type=int, default=None,
                        help='Quantidade ESTIMADA de bytes; opcional, nunca aprova cópia.')
    arguments = parser.parse_args(argv)
    sources = arguments.sources.split(',')
    targets = arguments.targets.split(',')
    try:
        result = inspect_fresh_drive_safety(
            sources, targets, expected_backup_bytes=arguments.estimated_bytes)
    except (ValueError, RuntimeError, OSError):
        # Do not echo raw PowerShell exceptions: they can expose hardware
        # identifiers or local usernames in terminal/issue screenshots.
        print('DIAGNÓSTICO NÃO CONCLUÍDO: confira letras de unidades, permissões '
              'e funcionamento do PowerShell. Nenhuma operação foi autorizada.',
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
