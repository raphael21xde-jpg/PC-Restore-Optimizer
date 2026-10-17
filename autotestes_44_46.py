"""#44-46 verify pagination, cancellation/resume and fail-closed coverage.

Fixtures are created exclusively inside TemporaryDirectory trees.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from inventory_paged import PagedMetadataScanner


def _check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Teste cancelado; sem aprovação.")


def _require(condition, note):
    if not condition:
        raise AssertionError(note)


def _report(number, **payload):
    return {
        "schema": f"pcro-autoteste-bateria-v{number}",
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "aprovado",
        **payload,
        "real_user_backups_accessed": False,
        "physical_independence_verified": False,
        "ready_for_format": False,
        "installation_authorized": False,
    }


def _all_pages(scanner, *, cancelled=None, size=31):
    steps = []
    while True:
        _check(cancelled)
        result = scanner.step(page_size=size, cancelled=cancelled)
        steps.append(result)
        if result["finished_current_session"]:
            return steps
        _require(len(steps) < 1000, "O cursor nunca terminou.")


def run_paged_inventory_autotest(*, cancelled=None):
    """#44: scan beyond one page, including nested folders, with exact counts."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE44-") as temp:
        root = Path(temp) / "volume"
        root.mkdir()
        hashes = {}
        for index in range(120):
            _check(cancelled)
            parent = root / f"grupo-{index % 6:02d}"
            parent.mkdir(exist_ok=True)
            file = parent / f"arquivo-{index:04d}.dat"
            data = f"PCRO44/{index}".encode()
            file.write_bytes(data)
            hashes[file] = hashlib.sha256(data).hexdigest()
        scanner = PagedMetadataScanner([root])
        try:
            pages = _all_pages(scanner, cancelled=cancelled, size=17)
        finally:
            scanner.close()
        last = pages[-1]
        _require(len(pages) >= 3 and last["entries_examined"] == 126,
                 "Paginação perdeu entradas ou contou itens repetidos.")
        _require(last["directories_pending"] == 0 and last["finished_current_session"],
                 "Varredura não terminou.")
        _require(last["volumes"][0]["files"] == 120 and last["volumes"][0]["folders"] == 6,
                 "Arquivos/pastas sintéticos não foram enumerados corretamente.")
        _require(last["status"] == "concluido_escopo_observado",
                 "Escopo limpo não foi reconhecido.")
        for file, digest in hashes.items():
            _check(cancelled)
            _require(hashlib.sha256(file.read_bytes()).hexdigest() == digest,
                     "Arquivo sintético foi modificado.")
        report = _report(44, fixture_files=120, fixture_dirs=6,
                         entries_examined=126, pages_used=len(pages),
                         no_global_entry_cutoff=True, no_duplicates=True,
                         originals_preserved=True, read_only=True)
    report["temporary_data_cleaned"] = not root.exists()
    _require(report["temporary_data_cleaned"], "Arquivos temporários permaneceram.")
    return report


def run_pause_resume_inventory_autotest(*, cancelled=None):
    """#45: pausing the scanner never loses the current directory cursor."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE45-") as temp:
        root = Path(temp) / "volume"
        root.mkdir()
        for index in range(101):
            (root / f"item-{index:04d}.txt").write_text(str(index), encoding="utf-8")
        scanner = PagedMetadataScanner([root])
        try:
            first = scanner.step(page_size=13, cancelled=cancelled)
            _require(first["entries_examined"] == 13 and not first["finished_current_session"],
                     "Primeira página não foi preservada.")
            stop = threading.Event()
            stop.set()
            try:
                scanner.step(page_size=13, cancelled=stop)
            except InterruptedError:
                pass
            else:
                raise AssertionError("Cancelamento aceito indevidamente.")
            mid = scanner.snapshot()
            _require(mid["entries_examined"] == 13 and mid["directories_pending"] == 1,
                     "Pausa invalidou o cursor.")
            stop.clear()
            pages = _all_pages(scanner, cancelled=cancelled, size=19)
            last = pages[-1]
            _require(last["entries_examined"] == 101 and last["volumes"][0]["files"] == 101,
                     "Retomada duplicou ou ignorou arquivos.")
        finally:
            scanner.close()
        report = _report(45, fixture_files=101, pause_was_safe=True,
                         resume_without_duplicates=True, cursor_stayed_in_memory=True,
                         pause_report_not_complete=True,
                         pages_after_resume=len(pages))
    report["temporary_data_cleaned"] = not root.exists()
    _require(report["temporary_data_cleaned"], "Área temporária não foi limpa.")
    return report


def run_gaps_inventory_autotest(*, cancelled=None):
    """#46: inaccessible folder and junctions remain explicit gaps."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE46-") as temp:
        root = Path(temp) / "volume"
        root.mkdir()
        blocked = root / "sem-permissao"
        blocked.mkdir()
        accessible = root / "SteamApps"
        accessible.mkdir()
        marker = accessible / "original.txt"
        marker.write_text("preservado", encoding="utf-8")
        link_created = False
        outside = Path(temp) / "fora"
        outside.mkdir()
        (outside / "nao-ler.txt").write_text("fora", encoding="utf-8")
        try:
            (root / "atalho").symlink_to(outside, target_is_directory=True)
            link_created = True
        except (OSError, NotImplementedError):
            pass  # Windows CI often runs without symlink privilege.
        original_scandir = os.scandir

        def blocked_directory(path):
            if Path(path) == blocked:
                raise PermissionError("Proibido no teste sintético")
            return original_scandir(path)

        scanner = PagedMetadataScanner([root])
        try:
            with patch("inventory_paged.os.scandir", side_effect=blocked_directory):
                pages = _all_pages(scanner, cancelled=cancelled, size=2)
            last = pages[-1]
        finally:
            scanner.close()
        _require(last["finished_current_session"]
                 and last["status"] == "concluido_com_lacunas"
                 and last["partial_coverage"], "Lacuna foi falsamente aprovada.")
        _require(last["access_denied_count"] == 1,
                 "Erro de permissão não foi registrado.")
        _require(last["volumes"][0]["candidate_folders"] == 1,
                 "Pasta candidata não foi reconhecida.")
        _require(not link_created or last["reparse_points_skipped"] == 1,
                 "Link/junção não foi ignorado.")
        _require(marker.read_text(encoding="utf-8") == "preservado",
                 "Arquivo original foi alterado.")
        report = _report(46, injected_permission_error_recorded=True,
                         incomplete_inventory_never_certified=True,
                         reparse_tested=link_created,
                         reparse_followed=False, real_backups_untouched=True,
                         originals_preserved=True)
    report["temporary_data_cleaned"] = not root.exists()
    _require(report["temporary_data_cleaned"], "Dados temporários não limpos.")
    return report
