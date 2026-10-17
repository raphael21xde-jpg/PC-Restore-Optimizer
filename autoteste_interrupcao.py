"""Autoteste #27: cancellation and SHA-256 verified resumptions.

Only tiny synthetic sources, backup and restore directories owned by one fresh
TemporaryDirectory are used. No user-selected paths or existing backups are
read or modified. The test never authorizes formatting or installation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from backup_core import build_plan, copy_backup, sha256_file
from backup_features import restore_selected, verified_entries
from selective_recovery import verify_complete_manifest


_FIXTURES = {
    "arquivo-01.bin": b"PCRO-AUTOTESTE27-PRIMEIRO\n" * 64,
    "arquivo-02.bin": b"PCRO-AUTOTESTE27-SEGUNDO\n" * 96,
}


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Autoteste #27 cancelado pelo usuário.")


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _expect_incomplete(manifest):
    try:
        verify_complete_manifest(manifest)
    except ValueError as exc:
        if "Backup parcial, interrompido ou com erros. Não aprovado." not in str(exc):
            raise AssertionError(f"Backup interrompido rejeitado pelo motivo errado: {exc}") from exc
        return str(exc)
    raise AssertionError("Backup interrompido foi indevidamente aceito como completo.")


def run_interruption_autotest(*, cancelled=None):
    """Exercise real backup/restore cancellation, resume and integrity checks.

    Cancellation is deterministic: the callback sets the same threading.Event
    interface used by the UI after the first file has been verified. The next
    file is then refused. The interrupted copy is not certified as complete.
    Both resumptions revalidate contents using the real SHA-256 verifier.
    """
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE27-") as scratch:
        root = Path(scratch).resolve(strict=True)
        sources = root / "fontes-ficticias"
        backup_base = root / "backups-ficticios"
        restore_base = root / "restauracoes-ficticias"
        for directory in (sources, backup_base, restore_base):
            directory.mkdir()
        original_hashes = {}
        for name, payload in _FIXTURES.items():
            _check_cancel(cancelled)
            file = sources / name
            file.write_bytes(payload)
            original_hashes[name] = hashlib.sha256(payload).hexdigest()
        plan = build_plan({str(sources): "keep"}, [str(root)])
        _require(not plan.warnings, "A análise fictícia apresentou avisos.")
        _require(plan.count == 2, "A análise fictícia não encontrou os dois arquivos.")
        _require(plan.total == sum(len(payload) for payload in _FIXTURES.values()),
                 "A análise fictícia não conferiu os tamanhos.")
        _check_cancel(cancelled)

        backup_cancel = threading.Event()
        backup_first_callbacks = 0

        def backup_progress(index, total, bytes_done, bytes_expected, filename):
            nonlocal backup_first_callbacks
            _check_cancel(cancelled)
            if index == 1:
                backup_first_callbacks += 1
                if backup_first_callbacks == 2:
                    backup_cancel.set()

        backup_folder, partial = copy_backup(
            plan, backup_base, cancelled=backup_cancel,
            progress=backup_progress, display_name="Autoteste #27 fictício",
        )
        backup_manifest = backup_folder / "manifest.json"
        _check_cancel(cancelled)
        _require(backup_cancel.is_set() and backup_first_callbacks == 2,
                 "O cancelamento do backup não foi acionado na transferência.")
        _require(partial["status"] == "interrompido" and
                 len(partial["files"]) == 1 and partial["files"][0]["verified"] is True,
                 "O backup cancelado não preservou corretamente seu estado parcial.")
        _require(partial["file_count_expected"] == 2,
                 "O manifesto perdeu a contagem de arquivos esperados.")
        _require(not list(backup_folder.rglob("*.partial-*")),
                 "A cópia interrompida deixou arquivo de transferência parcial.")
        interrupted_rejection = _expect_incomplete(backup_manifest)

        # A new, non-cancelled call resumes ONLY the private interrupted backup.
        resumed_folder, completed = copy_backup(
            plan, backup_base, resume_manifest=backup_manifest,
            display_name="Autoteste #27 fictício",
        )
        _check_cancel(cancelled)
        _require(resumed_folder == backup_folder and completed["status"] == "concluido",
                 "A retomada não concluiu o mesmo backup fictício.")
        _require(completed["resume_count"] == 1 and
                 len(completed["files"]) == 2 and not completed["errors"],
                 "A retomada do backup perdeu arquivos ou registrou erro.")
        backup_check = verify_complete_manifest(backup_manifest, cancelled=cancelled)
        _require(backup_check["files_verified"] == 2 and
                 backup_check["bytes_verified"] == plan.total,
                 "A integridade SHA-256 do backup retomado falhou.")
        entries = verified_entries(backup_manifest)
        _require(len(entries) == 2, "O manifesto final contém arquivos incompletos.")
        for rel, item in entries.items():
            _check_cancel(cancelled)
            copy = backup_folder / rel
            _require(sha256_file(copy, cancelled) == item["sha256"],
                     f"Backup retomado inválido: {rel}")

        # Interrupt an isolated restore after the first completed/verified file.
        restore_cancel = threading.Event()
        restoration_first_complete = 0

        def restore_progress(stage, index, total, filename, done, size):
            nonlocal restoration_first_complete
            _check_cancel(cancelled)
            if stage == "Arquivo verificado" and index == 1:
                restoration_first_complete += 1
                restore_cancel.set()

        choice_keys = list(entries)
        interrupted_exception = None
        try:
            restore_selected(
                backup_manifest, choice_keys, restore_base,
                cancelled=restore_cancel, progress=restore_progress,
            )
        except InterruptedError as exc:
            interrupted_exception = str(exc)
        _check_cancel(cancelled)
        _require(interrupted_exception is not None and restore_cancel.is_set() and
                 restoration_first_complete == 1,
                 "A restauração não foi interrompida após o primeiro arquivo.")
        partial_restore_folders = list(
            restore_base.glob("TESTE-RESTAURACAO-v05-*")
        )
        _require(len(partial_restore_folders) == 1,
                 "A restauração interrompida não deixou exatamente um diário isolado.")
        partial_restore = partial_restore_folders[0]
        journal_file = partial_restore / "ESTADO-RESTAURACAO.json"
        cancelled_journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(cancelled_journal["status"] == "cancelada_parcial" and
                 cancelled_journal["verified"] == 1,
                 "A restauração incompleta foi marcada incorretamente.")
        _require(not (partial_restore / "DESEMPENHO-RESTAURACAO.txt").exists(),
                 "Restauração incompleta recebeu relatório de sucesso.")

        # Resume the existing isolated folder, re-hashing previously copied files.
        restored_folder, restored_count = restore_selected(
            backup_manifest, choice_keys, restore_base, resume_from=partial_restore,
        )
        _check_cancel(cancelled)
        _require(restored_folder == partial_restore and restored_count == 2,
                 "A retomada da restauração não recuperou os dois arquivos.")
        final_journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(final_journal["status"] == "concluida" and
                 final_journal["resume_count"] == 1 and
                 set(final_journal["verified_keys"]) == set(choice_keys),
                 "A retomada da restauração não foi registrada corretamente.")
        for relative, item in entries.items():
            _check_cancel(cancelled)
            restored = restored_folder / relative
            _require(restored.is_file() and restored.stat().st_size == item["bytes"]
                     and sha256_file(restored, cancelled) == item["sha256"],
                     f"Restauração retomada falhou na conferência SHA-256: {relative}")

        _require(verify_complete_manifest(backup_manifest, cancelled=cancelled)
                 ["files_verified"] == 2,
                 "A restauração modificou o backup sintético saudável.")
        for name, expected_sha in original_hashes.items():
            _require(sha256_file(sources / name, cancelled) == expected_sha,
                     f"Um arquivo de origem fictício foi modificado: {name}")
        _check_cancel(cancelled)
        result = {
            "schema": "pcro-autoteste-interrupcao-v1",
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "aprovado",
            "fixture_files": plan.count,
            "fixture_bytes": plan.total,
            "backup_cancel_requested_during_operation": True,
            "backup_manifest_marked_interrupted": True,
            "incomplete_backup_rejected": True,
            "incomplete_backup_rejection": interrupted_rejection,
            "backup_resume_count": completed["resume_count"],
            "backup_resumed_and_sha256_verified": True,
            "restore_cancel_requested_during_operation": True,
            "restore_journal_marked_partial": True,
            "restore_resume_count": final_journal["resume_count"],
            "restore_resumed_and_sha256_verified": True,
            "no_backup_transfer_partials_left": True,
            "original_fixture_preserved": True,
            "real_user_backups_accessed": False,
            "physical_independence_verified": False,
            "ready_for_format": False,
            "installation_authorized": False,
            "note": (
                "Autoteste determinístico de cancelamento entre arquivos e retomada, "
                "somente em dados fictícios temporários. Verifica os motores de backup, "
                "restauração e SHA-256, mas não testa interrupção elétrica, "
                "dados reais, discos físicos nem libera formatação."
            ),
        }
    result["temporary_data_cleaned"] = not root.exists()
    _require(result["temporary_data_cleaned"],
             "A área temporária do autoteste não foi removida.")
    return result
