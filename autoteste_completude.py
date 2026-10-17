"""Autoteste #26: detect missing files and incomplete backups before restore.

Uses only synthetic tiny files inside a newly created TemporaryDirectory.
No user-provided paths, existing backups, Windows volumes, or original saves
are ever used. Does not format, delete user data, or authorize installation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import tempfile

from backup_core import atomic_json, sha256_file
from selective_recovery import verify_complete_manifest, run_isolated_restore_test


_FIXTURES = {
    "teste-A.txt": b"PCRO-AUTOTESTE26-ARQUIVO-A\n",
    "teste-B.txt": b"PCRO-AUTOTESTE26-ARQUIVO-B\n",
}


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Autoteste #26 cancelado.")


def _expect_rejection(action, expected_message, step):
    """Accept only the precise guard failure the scenario is designed to test."""
    try:
        action()
    except (OSError, ValueError) as exc:
        message = str(exc)
        if expected_message not in message:
            raise AssertionError(
                f"{step}: recusado pelo motivo errado: {message}"
            ) from exc
        return message
    raise AssertionError(f"{step}: backup incompleto aceito indevidamente.")


def run_completeness_autotest(*, cancelled=None):
    """Exercise real manifest and restore guards without reading any real backup.

    Each failure case gets an independent copy of a verified synthetic backup.
    A successful result is exported via the existing UI Export report action.
    """
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE26-") as scratch:
        root = Path(scratch).resolve(strict=True)
        originals = root / "origens-ficticias"
        pristine = root / "backup-saudavel"
        originals.mkdir()
        pristine.mkdir()

        files = []
        original_hashes = {}
        for name, payload in _FIXTURES.items():
            _check_cancel(cancelled)
            source = originals / name
            source.write_bytes(payload)
            original_hashes[name] = hashlib.sha256(payload).hexdigest()
            relative = Path("C", "PCRO-AUTOTESTE26", name)
            backed_up = pristine / relative
            backed_up.parent.mkdir(parents=True, exist_ok=True)
            backed_up.write_bytes(payload)
            files.append({
                "source": str(source),
                "relative": relative.as_posix(),
                "bytes": len(payload),
                "sha256": original_hashes[name],
                "verified": True,
            })

        manifest = {
            "schema": "pc-restore-backup-v0.4",
            "status": "concluido",
            "errors": [],
            "file_count_expected": len(files),
            "bytes_expected": sum(row["bytes"] for row in files),
            "files": files,
        }
        pristine_manifest = pristine / "manifest.json"
        atomic_json(pristine_manifest, manifest)
        baseline = verify_complete_manifest(pristine_manifest, cancelled=cancelled)
        if baseline["files_verified"] != len(files):
            raise AssertionError("Backup fictício de referência não foi aprovado.")

        # Corrupt each new throwaway copy independently, never the reference.
        checks = {}
        scenarios = (
            (
                "missing_file",
                "arquivo-faltando",
                "Arquivo de backup ausente ou SHA-256 divergente",
            ),
            (
                "interrupted_manifest",
                "manifesto-interrompido",
                "Backup parcial, interrompido ou com erros. Não aprovado.",
            ),
            (
                "missing_entry",
                "entrada-ausente-no-manifesto",
                "Número de arquivos do manifesto não corresponde ao plano.",
            ),
        )
        for key, folder_name, rejection in scenarios:
            _check_cancel(cancelled)
            copy = root / folder_name
            shutil.copytree(pristine, copy)
            damaged_manifest = copy / "manifest.json"
            initial = verify_complete_manifest(damaged_manifest, cancelled=cancelled)
            if initial["files_verified"] != len(files):
                raise AssertionError("Cópia fictícia falhou antes da simulação.")

            if key == "missing_file":
                # The path is built entirely from our hard-coded fixture manifest.
                victim = copy / Path(files[0]["relative"])
                victim.unlink()
                if victim.exists():
                    raise AssertionError("Falha ao simular arquivo ausente.")
            elif key == "interrupted_manifest":
                interrupted = dict(manifest, status="interrompido")
                atomic_json(damaged_manifest, interrupted)
            elif key == "missing_entry":
                # The manifest claims two expected files but lists only one.
                shortened = dict(manifest, files=files[:1])
                atomic_json(damaged_manifest, shortened)

            _check_cancel(cancelled)
            verification_error = _expect_rejection(
                lambda: verify_complete_manifest(damaged_manifest, cancelled=cancelled),
                rejection,
                f"{key}: conferência do manifesto",
            )
            _check_cancel(cancelled)
            restore_destination = root / ("restauracao-" + folder_name)
            restore_destination.mkdir()
            restore_error = _expect_rejection(
                lambda: run_isolated_restore_test(
                    damaged_manifest, restore_destination,
                    cancelled=cancelled, test_root=root,
                ),
                rejection,
                f"{key}: proteção da restauração",
            )
            if any(restore_destination.iterdir()):
                raise AssertionError(
                    f"{key}: tentativa de restauração deixou arquivos de saída."
                )
            checks[key] = {
                "verification_rejected": True,
                "restore_blocked": True,
                "restore_output_empty": True,
                "verify_rejection": verification_error,
                "restore_rejection": restore_error,
            }

        _check_cancel(cancelled)
        unchanged = verify_complete_manifest(pristine_manifest, cancelled=cancelled)
        if unchanged["files_verified"] != len(files):
            raise AssertionError("Backup fictício saudável foi modificado.")
        if any(
            sha256_file(originals / name, cancelled) != digest
            for name, digest in original_hashes.items()
        ):
            raise AssertionError("Um arquivo de origem fictício foi alterado.")

        report = {
            "schema": "pcro-autoteste-completude-v1",
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "aprovado",
            "fixture_files": len(files),
            "fixture_bytes": manifest["bytes_expected"],
            "healthy_manifest_verified": True,
            "missing_file_detected": checks["missing_file"]["verification_rejected"],
            "interrupted_backup_rejected": checks["interrupted_manifest"]["verification_rejected"],
            "incomplete_manifest_rejected": checks["missing_entry"]["verification_rejected"],
            "unsafe_restores_blocked": all(
                value["restore_blocked"] for value in checks.values()
            ),
            "restore_outputs_empty": all(
                value["restore_output_empty"] for value in checks.values()
            ),
            "healthy_fixture_preserved": True,
            "scenarios": checks,
            "real_user_backups_accessed": False,
            "physical_independence_verified": False,
            "ready_for_format": False,
            "installation_authorized": False,
            "note": (
                "Teste sintético isolado: não comprova a integridade de backups reais, "
                "independência física, segurança para formatação ou reinstalação."
            ),
        }
    # A report is returned only if removing the private temp directory succeeded.
    report["temporary_data_cleaned"] = True
    return report
