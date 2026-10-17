"""#41-43: metadata coverage, non-authoritative cross-volume links, restore recovery.

#41 intentionally reads metadata of locally enumerated volumes and DOES NOT
claim a complete catalog. #42 uses only string fixtures. #43 only writes into
TemporaryDirectory and resumes there after an injected write failure.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from autotestes_bateria import _fixed_or_removable_drive
from backup_core import build_plan, copy_backup, sha256_file
from backup_features import restore_selected, verified_entries
from game_links import infer_links
from runtime_volumes import discover_drive_letters
from selective_recovery import verify_complete_manifest


def _check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Autoteste cancelado; relatório não aprovado.")


def _require(ok, reason):
    if not ok:
        raise AssertionError(reason)


def _report(number, **kwargs):
    return dict(schema=f"pcro-autoteste-bateria-v{number}",
                executed_at_utc=datetime.now(timezone.utc).isoformat(),
                status="aprovado", **kwargs,
                real_user_backups_accessed=False,
                physical_independence_verified=False,
                ready_for_format=False,
                installation_authorized=False)


CANDIDATES = frozenset((
    "steamapps", "common", "games", "jogos", "saved games",
    "program files", "program files (x86)", "osu!", "appdata",
))


def scan_metadata_extended(roots, *, cancelled=None, max_entries=12000, max_depth=5):
    """Read-only, non-following, capped BFS. Report coverage and failures.

    No file content, ACL content, backup file, configuration or registry reads.
    Directory/path strings are not recorded per item, only volume-wide totals.
    """
    if not (1 <= max_entries <= 50000 and 0 <= max_depth <= 12):
        raise ValueError("Limites de inventário inválidos.")
    _check(cancelled)
    results = []
    for raw in roots:
        _check(cancelled)
        root = Path(raw)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Volume não está acessível ou é link.")
        counts = {
            "root": str(root), "entries_examined": 0, "files": 0,
            "folders": 0, "candidate_folders": 0, "reparse_skipped": 0,
            "access_denied": 0, "disappeared": 0, "other_errors": 0,
            "depth_limited_folders": 0, "entry_limit_reached": False,
        }
        queue = deque([(root, 0)])
        while queue:
            _check(cancelled)
            folder, depth = queue.popleft()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        _check(cancelled)
                        if counts["entries_examined"] >= max_entries:
                            counts["entry_limit_reached"] = True
                            break
                        counts["entries_examined"] += 1
                        try:
                            info = entry.stat(follow_symlinks=False)
                            reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
                            if entry.is_symlink() or reparse:
                                counts["reparse_skipped"] += 1
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                counts["folders"] += 1
                                if entry.name.casefold() in CANDIDATES:
                                    counts["candidate_folders"] += 1
                                if depth >= max_depth:
                                    counts["depth_limited_folders"] += 1
                                else:
                                    queue.append((Path(entry.path), depth + 1))
                            elif stat.S_ISREG(info.st_mode):
                                counts["files"] += 1
                        except PermissionError:
                            counts["access_denied"] += 1
                        except FileNotFoundError:
                            counts["disappeared"] += 1
                        except OSError:
                            counts["other_errors"] += 1
            except PermissionError:
                counts["access_denied"] += 1
            except FileNotFoundError:
                counts["disappeared"] += 1
            except OSError:
                counts["other_errors"] += 1
            if counts["entry_limit_reached"]:
                break
        counts["partial_coverage"] = True  # bounded audit is never complete proof
        results.append(counts)
    if not results:
        raise ValueError("Nenhuma raiz local examinada.")
    return results


def run_inventory_permissions_autotest(*, cancelled=None, roots=None):
    """#41: user-triggered metadata audit; default real local Windows drives."""
    _check(cancelled)
    if roots is None:
        if os.name != "nt":
            raise RuntimeError("Auditoria de volumes reais está disponível no Windows.")
        roots = [f"{letter}:\\" for letter in discover_drive_letters()
                 if _fixed_or_removable_drive(letter)
                 and Path(f"{letter}:\\").is_dir()]
    volumes = scan_metadata_extended(roots, cancelled=cancelled)
    examined = sum(v["entries_examined"] for v in volumes)
    _require(examined > 0, "Nenhum metadado encontrado.")
    return _report(
        41, roots_seen=len(volumes), entries_examined=examined,
        permission_denied_count=sum(v["access_denied"] for v in volumes),
        disappeared_count=sum(v["disappeared"] for v in volumes),
        other_error_count=sum(v["other_errors"] for v in volumes),
        depth_limited_folders=sum(v["depth_limited_folders"] for v in volumes),
        volumes_at_entry_limit=sum(int(v["entry_limit_reached"]) for v in volumes),
        candidate_folders=sum(v["candidate_folders"] for v in volumes),
        partial_coverage=True, content_files_opened=0, writes_performed=False,
        volume_surveys=volumes, 
        note=("Auditoria ampliada mas limitada (12.000 entradas por volume, profundidade 5); "
              "erros de acesso classificados, sem abrir conteúdos, alterar ACL ou comprovar "
              "inventário completo. Não confirma dependências, saves nem backup."),
    )


def run_cross_volume_links_autotest(*, cancelled=None):
    """#42: simulate verified *association* versus unreviewed candidates."""
    _check(cancelled)
    # These are fabricated paths only, NEVER inspected on the local computer.
    catalog = {
        "game_d": {"name": "Jogo sintético D", "kind": "game",
                   "install_location": "D:\\Games\\Demo"},
        "app_f": {"name": "Programa sintético F", "kind": "app",
                  "install_location": "F:\\Apps\\Demo"},
        "ignored": {"name": "Não selecionado", "kind": "game",
                    "install_location": "G:\\Games\\Other"},
    }
    saves = {
        "game_d": ["C:\\Users\\Ficticio\\Saved Games\\Demo",
                   "G:\\Configs\\Demo"],
        "ignored": ["C:\\Users\\Ficticio\\Secret"],
    }
    approved = {
        "game_d": ["G:\\Configs\\Demo"],
        "app_f": ["C:\\Users\\Ficticio\\AppData\\Demo"],
    }
    relations = infer_links(catalog, saves, approved_paths=approved,
                            selected_keys={"game_d", "app_f"})
    _check(cancelled)
    _require(len(relations) == 3, "Número inesperado de vínculos simulados.")
    _require(all(x["relation"] == "ENTRE UNIDADES" for x in relations),
             "Dependências sintéticas entre unidades não identificadas.")
    _require(all(x["game_id"] != "ignored" and not x["backup_verified"]
                 for x in relations),
             "Item não selecionado incluído ou link falsamente marcado como backup.")
    review = [x for x in relations if x["confidence"] == "REVISAR"]
    confirmed = [x for x in relations
                 if x["confidence"] == "CONFIRMADO PELO USUÁRIO"]
    _require(len(review) == 1 and len(confirmed) == 2,
             "Associações candidatas e aprovações confundidas.")
    _require(all(x["needs_backup_if_c_formatted"] == (x["volume"] == "C:")
                 for x in relations), "Risco de dados no C: não identificado.")
    return _report(
        42, synthetic_links=3, cross_volume_candidates=3,
        unreviewed_links=1, user_approved_associations=2,
        verified_backups=0, excluded_entities_not_included=True,
        c_volume_data_requires_preservation=2,
        disk_paths_opened=0, writes_performed=False,
        note=("Relações só entre caminhos FICTÍCIOS. Aprovação manual confirma "
              "associação, NÃO a integridade dos dados. Não descobriu links reais "
              "nesta máquina e não autoriza exclusão."),
    )


def run_restore_write_recovery_autotest(*, cancelled=None):
    """#43: real engine failure injection and safe SHA-256 resume in new folder."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE43-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source, backups, destinations = (root / x for x in ("source", "backups", "restores"))
        for folder in (source, backups, destinations):
            folder.mkdir()
        originals = {}
        for index in range(3):
            _check(cancelled)
            path = source / f"arquivo-{index}.bin"
            content = (f"PCRO43-{index}\n" * 100).encode()
            path.write_bytes(content)
            originals[path] = hashlib.sha256(content).hexdigest()
        plan = build_plan({str(source): "keep"}, [str(root)], cancelled=cancelled)
        _require(plan.count == 3 and not plan.warnings,
                 "Plano sintético incompleto.")
        folder, outcome = copy_backup(plan, backups, strategy_inventory={},
                                      cancelled=cancelled)
        _require(outcome["status"] == "concluido", "Backup sintético inválido.")
        manifest = folder / "manifest.json"
        proof = verify_complete_manifest(manifest, cancelled=cancelled)
        _require(proof["files_verified"] == 3, "Manifesto inicial incompleto.")
        entries = verified_entries(manifest)

        def fail_write(stage):
            _check(cancelled)
            if stage == "restore_after_write":
                raise OSError("Falha sintética na gravação")
        failure = ""
        try:
            restore_selected(manifest, list(entries), destinations,
                             strategy_inventory={}, cancelled=cancelled,
                             test_fault_hook=fail_write)
        except OSError as exc:
            failure = str(exc)
        _require("Falha sintética na gravação" in failure,
                 "Falha de restauração não foi detectada.")
        attempts = list(destinations.glob("TESTE-RESTAURACAO-v05-*"))
        _require(len(attempts) == 1, "Diário parcial não foi localizado.")
        target = attempts[0]
        journal_file = target / "ESTADO-RESTAURACAO.json"
        journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(journal["status"] == "falhou_parcial" and journal["verified"] == 0,
                 "Falha foi indevidamente aprovada.")
        _require(not list(target.rglob("*.partial-*")),
                 "Fragmento parcial da restauração não foi limpo.")
        restored, count = restore_selected(
            manifest, list(entries), destinations, resume_from=target,
            strategy_inventory={}, cancelled=cancelled,
        )
        _require(restored == target and count == 3, "Retomada falhou.")
        final = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(final["status"] == "concluida" and final["resume_count"] == 1,
                 "Diário não registrou a retomada.")
        for relative, entry in entries.items():
            _check(cancelled)
            item = restored / relative
            _require(item.is_file() and sha256_file(item, cancelled) == entry["sha256"],
                     "Restauração final divergiu do SHA-256.")
        for path, digest in originals.items():
            _require(sha256_file(path, cancelled) == digest,
                     "Fonte fictícia original foi alterada.")
        report = _report(
            43, fixture_files=3, injected_write_error_caught=True,
            partial_journal_rejected_as_complete=True,
            abandoned_transfer_fragments_cleaned=True, resume_count=1,
            restore_sha256_verified=True, source_files_preserved=True,
            note=("Falha de gravação injetada em dados fictícios temporários. "
                  "Não testa desconexão real de disco, perda de energia ou ACL NTFS."),
        )
    report["temporary_data_cleaned"] = not root.exists()
    _require(report["temporary_data_cleaned"], "Área temporária não foi eliminada.")
    return report
