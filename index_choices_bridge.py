"""Review and explicitly import PCRO index *choices* into an application's preview.

Never reads source files, triggers a backup, or carries destructive settings.
The actual backup plan must always be recalculated by the existing engine.
"""
from __future__ import annotations

import json
import ntpath
import os
from pathlib import Path
import re

from backup_core import norm

SCHEMA = "pcro-index-choices-v1"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_CHOICES = 4000
MAPPING = {"preservar": "keep", "nao_copiar": "skip"}


def is_legacy_system_choice(path):
    """Identify obsolete Recycle Bin paths regardless of drive or casing.

    Such historical decisions may be viewed in the index but must never be
    reintroduced into app.choices (whether preserve OR do-not-copy).
    """
    parts = ntpath.normcase(ntpath.normpath(str(path))).split("\\")
    return any(part in ("$recycle.bin", "recycler") for part in parts)


def _validate_path(path):
    if not isinstance(path, str) or not 4 <= len(path) <= 4096:
        raise ValueError("Escolha contém caminho inválido.")
    if "\x00" in path or "/" in path:
        raise ValueError("Caminho Windows inválido ou não absoluto.")
    if not re.match(r"^[A-Za-z]:\\", path) or not ntpath.isabs(path):
        raise ValueError("São permitidos somente caminhos absolutos de unidades locais.")
    if path.startswith("\\\\") or path.startswith("\\\\?\\"):
        raise ValueError("Caminhos UNC e de dispositivo não são aceitos.")
    if ":" in path[2:]:
        raise ValueError("Fluxos NTFS alternativos não são aceitos.")
    parts = path[3:].split("\\")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts):
        raise ValueError("Caminho contém componentes inseguros.")
    name = ntpath.normcase(ntpath.normpath(path))
    if name == ntpath.normcase(ntpath.splitdrive(path)[0] + "\\"):
        raise ValueError("A raiz de um disco não pode ser importada como arquivo.")
    return name


def read_index_choices(path):
    """Parse a bounded index export without checking or altering source paths."""
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON ausente ou grande demais para importação segura.")
    doc = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError("JSON não corresponde à exportação de escolhas do índice PCRO.")
    if doc.get("ready_for_format") is not False or doc.get("installation_authorized") is True:
        raise ValueError("Arquivo contém sinalização incompatível de segurança.")
    if doc.get("verified_backup") is not False or doc.get("contains_file_contents") is not False:
        raise ValueError("Esta importação aceita somente intenções, não backups.")
    choices = doc.get("choices")
    if not isinstance(choices, dict) or len(choices) > MAX_CHOICES:
        raise ValueError("Máximo de 4.000 escolhas por importação.")
    result = {}
    for path, decision in choices.items():
        name = _validate_path(path)
        if is_legacy_system_choice(name):
            raise ValueError("Escolhas históricas da Lixeira não podem ser importadas; retire-as do JSON.")
        if decision not in MAPPING:
            raise ValueError("Escolha não reconhecida; exclusão nunca é permitida.")
        if name in result:
            raise ValueError("Caminhos duplicados após normalização.")
        result[name] = MAPPING[decision]
    return {"choices": result, "source_state": str(doc.get("index_state", "parcial")),
            "complete_backup": False, "installation_authorized": False}


def preview_import(app, parsed):
    if not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), dict):
        raise ValueError("Prévia de escolhas inválida.")
    selected = parsed["choices"]
    current = {ntpath.normcase(ntpath.normpath(str(k))): v
               for k, v in app.choices.items()}
    return {
        "total": len(selected),
        "keep": sum(x == "keep" for x in selected.values()),
        "skip": sum(x == "skip" for x in selected.values()),
        "conflicts": sum(k in current and current[k] != v for k, v in selected.items()),
        "unchanged": sum(k in current and current[k] == v for k, v in selected.items()),
        "source_state": parsed.get("source_state", "parcial"),
        "ready_for_format": False,
    }


def apply_imported_choices(app, parsed):
    """Only call after user confirms a preview; no filesystem reads/copies."""
    if getattr(app, "busy", False) or getattr(app, "deep_scan_running", False):
        raise RuntimeError("Finalize outras operações antes de importar escolhas.")
    preview = preview_import(app, parsed)
    # Validate ALL paths and choices before the first application change.
    changes = {}
    for path, decision in parsed["choices"].items():
        name = _validate_path(path)
        if is_legacy_system_choice(name):
            raise ValueError("Escolha histórica da Lixeira bloqueada antes de alterar o plano.")
        if decision not in ("keep", "skip"):
            raise ValueError("Decisão inválida.")
        changes[norm(path)] = decision
    app.choices.update(changes)
    app.personal_paths.update(changes)
    app._on_change()  # invalidates previous plan and persists review decisions
    return dict(preview, applied=len(changes),
                backup_started=False, installation_authorized=False)
