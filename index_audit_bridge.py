"""Read saved PCRO SQLite decisions without editing the index or touching source files.

An index records historical metadata and choices, NOT a verified backup.
Loading its decisions never applies them to the active preservation plan.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3

from index_choices_bridge import MAX_CHOICES, MAPPING, _validate_path, is_legacy_system_choice
from inventory_index import SCHEMA as INDEX_SCHEMA


def read_saved_index_choices(filename):
    """Return a bounded, validated preview compatible with the existing importer.

    Uses SQLite's read-only URI mode. Querying the indexed decision column
    avoids traversing/reindexing the source disks, even for very large indexes.
    Invalid or excessive choices reject the entire preview.
    """
    file = Path(filename)
    if not file.is_file() or file.is_symlink():
        raise ValueError("Selecione um arquivo SQLite existente, sem link simbólico.")
    uri = file.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
            schema = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if not schema or schema[0] != INDEX_SCHEMA:
                raise ValueError("Arquivo não é um índice SQLite do PCRO.")
            state = db.execute("SELECT value FROM meta WHERE key='state'").fetchone()
            rows = db.execute(
                "SELECT path, decision FROM records "
                "WHERE decision IN ('preservar','nao_copiar') "
                "ORDER BY path LIMIT ?", (MAX_CHOICES + 1,)
            ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError("Índice não pôde ser consultado em modo somente leitura.") from exc
    if len(rows) > MAX_CHOICES:
        raise ValueError("Índice contém mais de 4.000 escolhas; revise/exporte em grupos menores.")
    choices = {}
    ignored_system_choices = []
    seen = set()
    for path, decision in rows:
        normalized = _validate_path(path)
        if normalized in seen:
            raise ValueError("Caminhos duplicados após normalização no índice.")
        seen.add(normalized)
        if is_legacy_system_choice(normalized):
            # Keep this evidence visible, but never apply it or change SQLite.
            ignored_system_choices.append({
                "path": normalized,
                "decision": MAPPING[decision],
                "reason": "Lixeira do Windows: escolha histórica não importável",
            })
            continue
        choices[normalized] = MAPPING[decision]
    return {
        "choices": choices,
        "ignored_system_choices": ignored_system_choices,
        "source_state": str(state[0] if state else "parcial"),
        "source_kind": "sqlite-index-readonly",
        "complete_backup": False,
        "installation_authorized": False,
        "ready_for_format": False,
    }
