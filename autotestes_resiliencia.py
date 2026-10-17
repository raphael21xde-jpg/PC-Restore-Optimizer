"""Synthetic resilience autotests #28–#30 for PC Restore & Optimizer.

Every runner creates its own fresh TemporaryDirectory, owns only small
synthetic inputs/backups/restores and never accepts user-selected paths.
No real backups or volumes, boot files or installation functions are accessed.
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


def _check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Autoteste cancelado pelo usuário.")


def _require(value, message):
    if not value:
        raise AssertionError(message)


def _setup(root, payloads):
    originals = root / "fontes-ficticias"
    backups = root / "backups-ficticios"
    restores = root / "restauracoes-ficticias"
    for directory in (originals, backups, restores):
        directory.mkdir()
    hashes = {}
    for name, data in payloads.items():
        source = originals / name
        source.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    plan = build_plan({str(originals): "keep"}, [str(root)])
    _require(plan.count == len(payloads) and not plan.warnings,
             "Falha ao preparar plano de teste inteiramente fictício.")
    _require(plan.total == sum(map(len, payloads.values())),
             "O tamanho do plano fictício não corresponde às fontes.")
    return originals, backups, restores, plan, hashes


def _require_healthy(manifest, files, bytes_expected):
    result = verify_complete_manifest(manifest)
    _require(result["files_verified"] == files and
             result["bytes_verified"] == bytes_expected,
             "Backup fictício não passou pela verificação completa de SHA-256.")


def _expect_interrupted_rejection(manifest):
    try:
        verify_complete_manifest(manifest)
    except ValueError as error:
        if "Backup parcial, interrompido ou com erros. Não aprovado." in str(error):
            return str(error)
        raise AssertionError(f"Falha por motivo inesperado: {error}") from error
    raise AssertionError("Um backup interrompido foi aceito indevidamente.")


def _expect_error(action, contains, label):
    try:
        action()
    except (ValueError, OSError) as error:
        if contains not in str(error):
            raise AssertionError(f"{label}: erro inesperado: {error}") from error
        return str(error)
    raise AssertionError(f"{label}: proteção não recusou a operação insegura.")


def _flip(path):
    path = Path(path)
    old_size = path.stat().st_size
    with path.open("r+b") as stream:
        first = stream.read(1)
        _require(bool(first), "Arquivo de teste vazio não pode ser adulterado.")
        stream.seek(0)
        stream.write(bytes((first[0] ^ 0x01,)))
    _require(path.stat().st_size == old_size,
             "Simulação de corrupção modificou o tamanho do arquivo.")


def _source_intact(originals, hashes):
    for name, expected in hashes.items():
        _require(sha256_file(originals / name) == expected,
                 f"Fonte fictícia foi alterada inesperadamente: {name}")


def _report_base(number, plan, **details):
    return {
        "schema": f"pcro-autoteste-resiliencia-v{number}",
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "aprovado",
        "fixture_files": plan.count,
        "fixture_bytes": plan.total,
        **details,
        "real_user_backups_accessed": False,
        "physical_independence_verified": False,
        "ready_for_format": False,
        "installation_authorized": False,
    }


def _after_cleanup(result, root):
    result["temporary_data_cleaned"] = not root.exists()
    _require(result["temporary_data_cleaned"],
             "A pasta temporária do autoteste não foi removida.")
    return result


def run_midfile_autotest(*, cancelled=None):
    """#28: cancel midway through an actual multi-chunk file, then resume.

    The first file exceeds 3 MiB, forcing several 1 MiB blocks when the
    synthetic strategy inventory is used. The callback cancels after a block
    is written but before the whole file is committed.
    """
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE28-") as scratch:
        root = Path(scratch).resolve(strict=True)
        originals, backups, restores, plan, hashes = _setup(root, {
            "arquivo-01-grande.bin": b"A" * (3 * 1024 * 1024 + 29),
            "arquivo-02-pequeno.txt": b"PCRO-AUTOTESTE28-ARQUIVO-02\n",
        })
        _check_cancel(cancelled)
        stop_backup = threading.Event()
        backup_block_seen = False

        def backup_progress(index, total, done, size, filename):
            nonlocal backup_block_seen
            _check_cancel(cancelled)
            if index == 1 and 0 < done < plan.files[0].size:
                backup_block_seen = True
                stop_backup.set()

        folder, partial = copy_backup(
            plan, backups, cancelled=stop_backup, progress=backup_progress,
            strategy_inventory={}, display_name="Autoteste 28",
        )
        manifest = folder / "manifest.json"
        _check_cancel(cancelled)
        _require(stop_backup.is_set() and backup_block_seen,
                 "O cancelamento não ocorreu dentro do arquivo grande de backup.")
        _require(partial["status"] == "interrompido" and not partial["files"],
                 "Arquivo interrompido foi registrado como concluído no manifesto.")
        _require(not list(folder.rglob("*.partial-*")),
                 "A cópia cancelada deixou fragmento de transferência.")
        interrupted_rejection = _expect_interrupted_rejection(manifest)

        _, resumed = copy_backup(
            plan, backups, resume_manifest=manifest,
            display_name="Autoteste 28", strategy_inventory={},
        )
        _check_cancel(cancelled)
        _require(resumed["status"] == "concluido" and
                 resumed["resume_count"] == 1 and
                 len(resumed["files"]) == plan.count,
                 "Backup retomado não concluiu os dois arquivos.")
        _require_healthy(manifest, plan.count, plan.total)
        entries = verified_entries(manifest)

        stop_restore = threading.Event()
        restore_block_seen = False

        def restore_progress(stage, index, total, filename, copied, expected):
            nonlocal restore_block_seen
            _check_cancel(cancelled)
            if stage == "Copiando" and index == 0 and 0 < copied < expected:
                restore_block_seen = True
                stop_restore.set()

        stopped_restore = None
        try:
            restore_selected(
                manifest, list(entries), restores, cancelled=stop_restore,
                progress=restore_progress, strategy_inventory={},
            )
        except InterruptedError as error:
            stopped_restore = str(error)
        _check_cancel(cancelled)
        _require(stopped_restore is not None and restore_block_seen,
                 "A restauração não foi cancelada dentro do arquivo grande.")
        folders = list(restores.glob("TESTE-RESTAURACAO-v05-*"))
        _require(len(folders) == 1, "A restauração parcial não criou um diário único.")
        target = folders[0]
        journal_file = target / "ESTADO-RESTAURACAO.json"
        journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(journal["status"] == "cancelada_parcial" and journal["verified"] == 0,
                 "Arquivo restaurado parcialmente foi marcado como verificado.")
        _require(not list(target.rglob("*.partial-*")),
                 "O fragmento de restauração não foi removido após cancelamento.")

        folder_restored, count = restore_selected(
            manifest, list(entries), restores, resume_from=target,
            strategy_inventory={},
        )
        _check_cancel(cancelled)
        _require(folder_restored == target and count == len(entries),
                 "A retomada da restauração falhou.")
        final_journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _require(final_journal["status"] == "concluida" and
                 final_journal["resume_count"] == 1,
                 "A restauração retomada não foi concluída.")
        for relative, info in entries.items():
            file = target / relative
            _require(file.is_file() and file.stat().st_size == info["bytes"] and
                     sha256_file(file) == info["sha256"],
                     f"Arquivo restaurado divergente após retomada: {relative}")
        _require_healthy(manifest, plan.count, plan.total)
        _source_intact(originals, hashes)
        result = _report_base(
            28, plan, midfile_backup_cancelled=True,
            incomplete_file_not_marked_verified=True,
            interrupted_backup_rejected=True,
            interruption_rejection=interrupted_rejection,
            partial_backup_fragment_removed=True,
            backup_resume_sha256_verified=True,
            midfile_restore_cancelled=True,
            incomplete_restore_not_marked_verified=True,
            partial_restore_fragment_removed=True,
            restore_resume_sha256_verified=True,
            original_fixture_preserved=True,
            note=("Cancelamento controlado dentro de blocos de arquivo sintético "
                  "de 3 MiB. Não simula queda de energia ou backup real."),
        )
    return _after_cleanup(result, root)


def run_repair_autotest(*, cancelled=None):
    """#29: corrupt files between cancellation and resume; only hashes can pass."""
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE29-") as scratch:
        root = Path(scratch).resolve(strict=True)
        originals, backups, restores, plan, hashes = _setup(root, {
            "arquivo-01.bin": b"PCRO-AUTOTESTE29-A\n" * 100,
            "arquivo-02.bin": b"PCRO-AUTOTESTE29-B\n" * 100,
        })
        stop_backup = threading.Event()
        first_committed = 0

        def backup_progress(index, total, done, expected, filename):
            nonlocal first_committed
            _check_cancel(cancelled)
            if index == 1:
                first_committed += 1
                if first_committed >= 2:
                    stop_backup.set()

        backup_folder, interrupted = copy_backup(
            plan, backups, cancelled=stop_backup, progress=backup_progress,
            strategy_inventory={},
        )
        manifest = backup_folder / "manifest.json"
        _check_cancel(cancelled)
        _require(stop_backup.is_set() and interrupted["status"] == "interrompido"
                 and len(interrupted["files"]) == 1,
                 "Falha ao cancelar backup fictício entre arquivos.")
        rejection = _expect_interrupted_rejection(manifest)
        first = interrupted["files"][0]
        corrupt_backup = backup_folder / first["relative"]
        _flip(corrupt_backup)
        _require(sha256_file(corrupt_backup) != first["sha256"],
                 "Corrupção controlada não alterou o hash.")

        _, resumed = copy_backup(
            plan, backups, resume_manifest=manifest, strategy_inventory={},
        )
        _check_cancel(cancelled)
        _require(resumed["status"] == "concluido" and resumed["resume_count"] == 1
                 and len(resumed["files"]) == 2,
                 "O backup adulterado não foi reconstruído corretamente.")
        _require_healthy(manifest, plan.count, plan.total)
        entries = verified_entries(manifest)
        _require(sha256_file(corrupt_backup) == first["sha256"],
                 "O arquivo adulterado foi aceito sem ser recopiado.")

        stop_restore = threading.Event()
        def restore_progress(stage, index, total, filename, done, expected):
            _check_cancel(cancelled)
            if stage == "Arquivo verificado" and index == 1:
                stop_restore.set()

        try:
            restore_selected(
                manifest, list(entries), restores, cancelled=stop_restore,
                progress=restore_progress, strategy_inventory={},
            )
        except InterruptedError:
            pass
        _check_cancel(cancelled)
        _require(stop_restore.is_set(),
                 "A restauração de teste não foi cancelada.")
        targets = list(restores.glob("TESTE-RESTAURACAO-v05-*"))
        _require(len(targets) == 1, "Diário de restauração parcial não encontrado.")
        target = targets[0]
        journal_path = target / "ESTADO-RESTAURACAO.json"
        before = json.loads(journal_path.read_text(encoding="utf-8"))
        _require(before["status"] == "cancelada_parcial" and before["verified"] == 1,
                 "Restauração parcial foi indevidamente concluída.")
        first_key = list(entries)[0]
        damaged_restore = target / first_key
        _require(damaged_restore.is_file(),
                 "Arquivo restaurado fictício não encontrado para corrupção.")
        _flip(damaged_restore)
        _require(sha256_file(damaged_restore) != entries[first_key]["sha256"],
                 "Arquivo restaurado não foi efetivamente corrompido.")

        restored_folder, count = restore_selected(
            manifest, list(entries), restores, resume_from=target,
            strategy_inventory={},
        )
        _check_cancel(cancelled)
        _require(restored_folder == target and count == 2,
                 "Restauração retomada não concluiu todos os arquivos.")
        after = json.loads(journal_path.read_text(encoding="utf-8"))
        _require(after["status"] == "concluida" and after["resume_count"] == 1,
                 "O diário não registrou a conclusão da restauração.")
        for relative, entry in entries.items():
            _require(sha256_file(target / relative) == entry["sha256"],
                     f"Restauração adulterada foi aceita: {relative}")
        _require_healthy(manifest, plan.count, plan.total)
        _source_intact(originals, hashes)
        result = _report_base(
            29, plan,
            backup_cancelled_and_refused=True,
            incomplete_backup_rejection=rejection,
            corrupted_verified_backup_file_replaced=True,
            backup_resume_sha256_verified=True,
            restore_cancelled_and_journaled=True,
            corrupted_restored_file_replaced=True,
            restore_resume_sha256_verified=True,
            original_fixture_preserved=True,
            note=("Corrupção controlada de arquivos sintéticos após interrupção; "
                  "a retomada deve recusar hashes antigos e recopiá-los. "
                  "Não mexe em dados reais ou discos."),
        )
    return _after_cleanup(result, root)


def run_resume_guard_autotest(*, cancelled=None):
    """#30: reject modified source plans and unauthorized resume destinations."""
    _check_cancel(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE30-") as scratch:
        root = Path(scratch).resolve(strict=True)
        originals, backups, restores, plan, hashes = _setup(root, {
            "arquivo-01.txt": b"PCRO-AUTOTESTE30-A\n" * 50,
            "arquivo-02.txt": b"PCRO-AUTOTESTE30-B\n" * 50,
        })
        cancel = threading.Event()
        first_callbacks = 0

        def progress(index, total, done, size, filename):
            nonlocal first_callbacks
            _check_cancel(cancelled)
            if index == 1:
                first_callbacks += 1
                if first_callbacks >= 2:
                    cancel.set()

        partial_dir, partial = copy_backup(
            plan, backups, cancelled=cancel, progress=progress,
            strategy_inventory={},
        )
        _check_cancel(cancelled)
        partial_manifest = partial_dir / "manifest.json"
        _require(partial["status"] == "interrompido" and cancel.is_set(),
                 "Backup sintético não foi interrompido para teste de proteção.")
        partial_rejection = _expect_interrupted_rejection(partial_manifest)

        # Intentional mutation of a TEST source: changes the planned file count/size.
        source_mutated = originals / "arquivo-02.txt"
        source_mutated.write_bytes(source_mutated.read_bytes() + b"alterado somente em teste")
        new_plan = build_plan({str(originals): "keep"}, [str(root)])
        _require(new_plan.total != plan.total,
                 "A alteração da fonte não foi reconhecida pelo plano.")
        changed_plan_rejection = _expect_error(
            lambda: copy_backup(new_plan, backups, resume_manifest=partial_manifest,
                                strategy_inventory={}),
            "Backup incompatível, concluído ou plano de origem modificado",
            "Retomada com fonte modificada",
        )

        foreign_base = root / "destino-estranho-ficticio"
        foreign_base.mkdir()
        wrong_base_rejection = _expect_error(
            lambda: copy_backup(plan, foreign_base, resume_manifest=partial_manifest,
                                strategy_inventory={}),
            "A retomada deve apontar para um manifesto dentro do destino de backup.",
            "Retomada em destino de outro backup",
        )
        _require(
            json.loads(partial_manifest.read_text(encoding="utf-8"))["status"]
            == "interrompido",
            "Um pedido de retomada recusado alterou o manifesto incompleto.",
        )

        # Use a fresh synthetic plan, then interrupt restore between files.
        healthy_dir, healthy_doc = copy_backup(
            new_plan, backups, strategy_inventory={},
        )
        healthy_manifest = healthy_dir / "manifest.json"
        _require(healthy_doc["status"] == "concluido",
                 "Não foi possível criar backup saudável de teste.")
        _require_healthy(healthy_manifest, new_plan.count, new_plan.total)
        keys = list(verified_entries(healthy_manifest))
        restore_stop = threading.Event()
        def restore_progress(stage, index, total, filename, done, expected):
            _check_cancel(cancelled)
            if stage == "Arquivo verificado" and index == 1:
                restore_stop.set()

        try:
            restore_selected(
                healthy_manifest, keys, restores, cancelled=restore_stop,
                progress=restore_progress, strategy_inventory={},
            )
        except InterruptedError:
            pass
        _check_cancel(cancelled)
        _require(restore_stop.is_set(),
                 "Restauração fictícia não parou para o teste de segurança.")
        targets = list(restores.glob("TESTE-RESTAURACAO-v05-*"))
        _require(len(targets) == 1, "Diário de restauração parcial ausente.")
        target = targets[0]
        journal_path = target / "ESTADO-RESTAURACAO.json"
        journal_before = journal_path.read_bytes()
        wrong_restore_base = root / "outra-pasta-ficticia"
        wrong_restore_base.mkdir()
        wrong_restore_dest_rejection = _expect_error(
            lambda: restore_selected(
                healthy_manifest, keys, wrong_restore_base, resume_from=target,
                strategy_inventory={},
            ),
            "Destino de retomada diferente da pasta original de teste.",
            "Retomada em outra pasta de restauração",
        )

        # Another healthy manifest must not be permitted to reuse this journal.
        another_dir, second_doc = copy_backup(
            new_plan, backups, strategy_inventory={},
        )
        _require(second_doc["status"] == "concluido",
                 "Segundo manifesto fictício não foi concluído.")
        different_manifest_rejection = _expect_error(
            lambda: restore_selected(
                another_dir / "manifest.json", keys, restores, resume_from=target,
                strategy_inventory={},
            ),
            "Restauração concluída, antiga ou ligada a outro backup.",
            "Retomada com manifesto não correspondente",
        )
        _require(journal_path.read_bytes() == journal_before,
                 "Uma retomada recusada modificou o diário anterior.")
        _require_healthy(healthy_manifest, new_plan.count, new_plan.total)
        _require(sha256_file(originals / "arquivo-01.txt") == hashes["arquivo-01.txt"],
                 "A origem de teste não adulterada foi alterada.")

        result = _report_base(
            30, new_plan,
            source_change_blocks_backup_resume=True,
            modified_source_rejection=changed_plan_rejection,
            different_backup_base_blocks_resume=True,
            foreign_backup_base_rejection=wrong_base_rejection,
            interrupted_backup_still_unapproved=True,
            interrupted_backup_rejection=partial_rejection,
            different_restore_base_blocks_resume=True,
            foreign_restore_base_rejection=wrong_restore_dest_rejection,
            different_manifest_blocks_restore_resume=True,
            wrong_manifest_rejection=different_manifest_rejection,
            rejected_resume_did_not_change_journal=True,
            real_data_changed=False,
            note=("Somente um arquivo de origem fictício foi alterado "
                  "intencionalmente para verificar os bloqueios. Nenhuma "
                  "retomada de destino/manifesto estranho foi permitida. "
                  "Não verifica backups reais nem libera formatação."),
        )
    return _after_cleanup(result, root)
