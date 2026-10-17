"""Autotestes #31-34: bounded transfer, small files, faults and restart simulation.

Strictly private synthetic TemporaryDirectory trees. The tests never accept
selected disk paths, never read existing user backups and never touch boot.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time

from backup_core import atomic_json, build_plan, copy_backup, sha256_file
from backup_features import restore_selected, verified_entries
from selective_recovery import verify_complete_manifest


def _check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Autoteste interrompido a pedido do usuário.")


def _assert(ok, message):
    if not ok:
        raise AssertionError(message)


def _setup(root):
    source = root / "fontes-ficticias"
    backup = root / "backups-ficticios"
    destination = root / "restauracoes-ficticias"
    for path in (source, backup, destination):
        path.mkdir()
    return source, backup, destination


def _plan(source, root, count):
    result = build_plan({str(source): "keep"}, [str(root)])
    _assert(result.count == count and not result.warnings,
            "A leitura das fontes fictícias foi incompleta.")
    return result


def _verify(manifest, count, total):
    report = verify_complete_manifest(manifest)
    _assert(report["files_verified"] == count and report["bytes_verified"] == total,
            "O verificador SHA-256 não confirmou todos os arquivos.")
    return verified_entries(manifest)


def _check_restored(folder, entries, cancelled):
    for relative, item in entries.items():
        _check(cancelled)
        path = folder / relative
        _assert(path.is_file() and path.stat().st_size == item["bytes"] and
                sha256_file(path, cancelled) == item["sha256"],
                f"Arquivo restaurado não corresponde ao manifesto: {relative}")


def _reject_partial(manifest):
    try:
        verify_complete_manifest(manifest)
    except ValueError as error:
        _assert("Backup parcial, interrompido ou com erros. Não aprovado." in str(error),
                f"Falha de verificação por motivo errado: {error}")
        return str(error)
    raise AssertionError("O backup incompleto foi aceito como íntegro.")


def _report(number, file_count, size, **extra):
    return {
        "schema": f"pcro-autoteste-falhas-v{number}",
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "aprovado",
        "fixture_files": file_count,
        "fixture_bytes": size,
        **extra,
        "real_user_backups_accessed": False,
        "physical_independence_verified": False,
        "ready_for_format": False,
        "installation_authorized": False,
    }


def _cleaned(report, root):
    report["temporary_data_cleaned"] = not root.exists()
    _assert(report["temporary_data_cleaned"], "Dados temporários não foram eliminados.")
    return report


def run_large_transfer_autotest(*, cancelled=None):
    """#31: 32 MiB streamed in chunks; elapsed time reported, never benchmark promise.

    The allocation stays bounded; this is NOT a 1+ GiB or physical-disk test.
    """
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE31-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source, backups, restores = _setup(root)
        payload = (b"PCRO31-SYNTHETIC-BLOCK-" * 4096)
        large = source / "arquivo-32MiB.bin"
        amount = 32 * 1024 * 1024
        expected = hashlib.sha256()
        with large.open("wb") as stream:
            remaining = amount
            while remaining:
                _check(cancelled)
                chunk = (payload * ((min(remaining, 1024 * 1024) // len(payload)) + 1))[:min(remaining, 1024 * 1024)]
                stream.write(chunk)
                expected.update(chunk)
                remaining -= len(chunk)
        plan = _plan(source, root, 1)
        _assert(plan.total == amount and sha256_file(large, cancelled) == expected.hexdigest(),
                "Falha na geração em fluxo do arquivo de teste.")
        _check(cancelled)

        start = time.perf_counter()
        folder, outcome = copy_backup(plan, backups, strategy_inventory={})
        backup_seconds = time.perf_counter() - start
        _assert(outcome["status"] == "concluido", "Backup de teste não foi concluído.")
        manifest = folder / "manifest.json"
        entries = _verify(manifest, 1, amount)
        _check(cancelled)
        start = time.perf_counter()
        restored, count = restore_selected(
            manifest, list(entries), restores, strategy_inventory={},
        )
        restore_seconds = time.perf_counter() - start
        _assert(count == 1, "Restauração de teste não concluiu o arquivo.")
        _check_restored(restored, entries, cancelled)
        _assert(sha256_file(large, cancelled) == expected.hexdigest(),
                "Fonte fictícia foi modificada.")
        report = _report(
            31, 1, amount,
            backup_sha256_verified=True, restore_sha256_verified=True,
            streamed_fixture_generation=True,
            backup_elapsed_seconds=round(backup_seconds, 4),
            restore_elapsed_seconds=round(restore_seconds, 4),
            backup_mib_per_second=round(amount / (1024*1024) / max(backup_seconds, 0.0001), 2),
            restore_mib_per_second=round(amount / (1024*1024) / max(restore_seconds, 0.0001), 2),
            original_fixture_preserved=True,
            note=("Ensaio limitado a 32 MiB; taxas variam por máquina e não medem "
                  "desempenho em vários gigabytes, uso máximo de memória ou disco físico."),
        )
    return _cleaned(report, root)


def run_many_files_autotest(*, cancelled=None):
    """#32: 1,024 tiny files in 16 folders, real backup and restore with SHA-256."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE32-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source, backups, restores = _setup(root)
        count = 1024
        original_hashes = {}
        for index in range(count):
            _check(cancelled)
            subfolder = source / f"grupo-{index % 16:02d}"
            subfolder.mkdir(exist_ok=True)
            f = subfolder / f"arquivo-{index:05d}.txt"
            data = f"PCRO32:{index:05d}:{index * 13}\n".encode()
            f.write_bytes(data)
            original_hashes[str(f.relative_to(source))] = hashlib.sha256(data).hexdigest()
        plan = _plan(source, root, count)
        _check(cancelled)
        start = time.perf_counter()
        folder, outcome = copy_backup(plan, backups, strategy_inventory={})
        backup_seconds = time.perf_counter() - start
        _assert(outcome["status"] == "concluido" and len(outcome["files"]) == count,
                "Backup de muitos arquivos não concluiu o inventário.")
        manifest = folder / "manifest.json"
        entries = _verify(manifest, count, plan.total)
        start = time.perf_counter()
        restored, restored_count = restore_selected(
            manifest, list(entries), restores, strategy_inventory={},
        )
        restore_seconds = time.perf_counter() - start
        _assert(restored_count == count, "Restauração não recuperou todos os itens.")
        _check_restored(restored, entries, cancelled)
        for relative, expected in original_hashes.items():
            _check(cancelled)
            _assert(sha256_file(source / relative, cancelled) == expected,
                    "Arquivo fictício de origem foi alterado.")
        report = _report(
            32, count, plan.total,
            groups=16, backup_sha256_verified=True, restore_sha256_verified=True,
            all_filenames_preserved=True, original_fixture_preserved=True,
            backup_elapsed_seconds=round(backup_seconds, 4),
            restore_elapsed_seconds=round(restore_seconds, 4),
            note=("1.024 arquivos artificiais em 16 pastas; tempos são indicativos "
                  "e não provam estabilidade de inventários reais maiores."),
        )
    return _cleaned(report, root)


def run_storage_fault_autotest(*, cancelled=None):
    """#33: inject space/read/write errors through opt-in TEST hooks only."""
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE33-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source, backups, restores = _setup(root)
        fixtures = {}
        for idx in range(2):
            name = f"arquivo-{idx}.bin"
            data = (f"PCRO33-{idx}".encode() * 512)
            path = source / name
            path.write_bytes(data)
            fixtures[name] = hashlib.sha256(data).hexdigest()
        plan = _plan(source, root, 2)

        def no_space(_plan_arg, _destination):
            return (4096, 4096, False)

        disk_space_error = None
        try:
            copy_backup(plan, backups, strategy_inventory={},
                        test_space_probe=no_space)
        except OSError as exc:
            disk_space_error = str(exc)
        _assert(disk_space_error is not None and "Espaço insuficiente" in disk_space_error,
                "A falta de espaço sintética não bloqueou o backup.")
        _assert(not list(backups.iterdir()),
                "Backup começou a escrever antes da pré-checagem de espaço.")

        def fault_on(event, needle, message):
            _check(cancelled)
            if event == needle:
                raise OSError(message)

        # Both failures happen only within disposable source/backup folders.
        failure_reports = {}
        for event in ("backup_before_read", "backup_after_write"):
            label = "Falha simulada de " + ("leitura" if event.endswith("read") else "gravação")
            folder, partial = copy_backup(
                plan, backups, strategy_inventory={},
                test_fault_hook=lambda stage, e=event, m=label: fault_on(stage, e, m),
            )
            _check(cancelled)
            manifest = folder / "manifest.json"
            _assert(partial["status"] == "parcial_com_erros" and bool(partial["errors"]),
                    f"Falha {event} foi marcada como backup válido.")
            _assert(label in str(partial["errors"]), f"Erro {event} não foi registrado.")
            _assert(not list(folder.rglob("*.partial-*")),
                    f"Arquivo temporário incompleto não foi removido após {event}.")
            rejection = _reject_partial(manifest)
            failure_reports[event] = rejection

        good, good_result = copy_backup(plan, backups, strategy_inventory={})
        _assert(good_result["status"] == "concluido", "Fixture de restauração inválido.")
        healthy_manifest = good / "manifest.json"
        entries = _verify(healthy_manifest, 2, plan.total)

        restore_error = None
        try:
            restore_selected(
                healthy_manifest, list(entries), restores, strategy_inventory={},
                test_fault_hook=lambda stage: fault_on(
                    stage, "restore_after_write", "Falha simulada de gravação na restauração"
                ),
            )
        except OSError as exc:
            restore_error = str(exc)
        _assert(restore_error is not None and "Falha simulada de gravação" in restore_error,
                "Falha de gravação na restauração não foi registrada.")
        folders = list(restores.glob("TESTE-RESTAURACAO-v05-*"))
        _assert(len(folders) == 1, "Diário de restauração parcial não encontrado.")
        journal = json.loads((folders[0] / "ESTADO-RESTAURACAO.json").read_text(encoding="utf-8"))
        _assert(journal["status"] == "falhou_parcial" and journal["verified"] == 0,
                "Restauração com falha foi marcada como concluída.")
        _assert(not list(folders[0].rglob("*.partial-*")),
                "Fragmento da restauração com falha não foi limpo.")
        _verify(healthy_manifest, 2, plan.total)
        for name, digest in fixtures.items():
            _assert(sha256_file(source / name) == digest, "Fonte fictícia foi alterada.")
        report = _report(
            33, 2, plan.total,
            simulated_out_of_space_blocked=True,
            simulated_read_failure_rejected=True,
            simulated_write_failure_rejected=True,
            failed_backups_marked_partial=True,
            partial_fragments_cleaned=True,
            simulated_restore_write_failure_journaled=True,
            healthy_fixture_preserved=True,
            failure_messages=failure_reports,
            note=("Falhas simuladas por injeção em funções de TESTE. Não "
                  "enche discos reais, não desconecta armazenamento, "
                  "não prova tolerância a erros físicos."),
        )
    return _cleaned(report, root)


def run_restart_recovery_autotest(*, cancelled=None):
    """#34: persist incomplete checkpoint and completed file, then resume later.

    Does NOT crash or kill the real application/OS. Simulates an interrupted
    journal after a completed write but before its recorded checkpoint.
    """
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix="PCRO-AUTOTESTE34-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source, backups, restores = _setup(root)
        hashes = {}
        for idx in range(3):
            name = f"arquivo-{idx}.txt"
            path = source / name
            data = (f"PCRO34-{idx}\n" * 100).encode()
            path.write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        plan = _plan(source, root, 3)
        backup_folder, outcome = copy_backup(plan, backups, strategy_inventory={})
        _assert(outcome["status"] == "concluido", "Backup saudável inicial não foi concluído.")
        manifest_path = backup_folder / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Emulate a lost final checkpoint. The first file is already on disk
        # but was not registered; another file is missing.
        modified = dict(original, status="em_andamento",
                        files=original["files"][:1], errors=[])
        atomic_json(manifest_path, modified)
        missing = backup_folder / original["files"][1]["relative"]
        missing.unlink()
        _assert((backup_folder / original["files"][2]["relative"]).is_file(),
                "Arquivo sem checkpoint sintético não foi criado.")
        rejection = _reject_partial(manifest_path)
        _check(cancelled)
        resumed_folder, resumed = copy_backup(
            plan, backups, resume_manifest=manifest_path,
            strategy_inventory={},
        )
        _assert(resumed_folder == backup_folder and resumed["status"] == "concluido" and
                resumed["resume_count"] == 1 and len(resumed["files"]) == 3,
                "Não foi possível reconstruir o manifesto após checkpoint ausente.")
        entries = _verify(manifest_path, 3, plan.total)

        target, count = restore_selected(
            manifest_path, list(entries), restores, strategy_inventory={},
        )
        _assert(count == 3, "Fixture de restauração não foi gerado.")
        journal_file = target / "ESTADO-RESTAURACAO.json"
        journal = json.loads(journal_file.read_text(encoding="utf-8"))
        # Emulate an unexpected shutdown after the file is committed but
        # before the journal records completion.
        journal["status"] = "em_andamento"
        journal["verified"] = 0
        journal["verified_keys"] = []
        journal.pop("error", None)
        atomic_json(journal_file, journal)
        (target / list(entries)[-1]).unlink()
        _check(cancelled)
        restored, verified = restore_selected(
            manifest_path, list(entries), restores, resume_from=target,
            strategy_inventory={},
        )
        _assert(restored == target and verified == 3, "Diário parcial não foi retomado.")
        final_journal = json.loads(journal_file.read_text(encoding="utf-8"))
        _assert(final_journal["status"] == "concluida" and
                final_journal["resume_count"] == 1 and final_journal["verified"] == 3,
                "Restauração recuperada não foi registrada como concluída.")
        _check_restored(target, entries, cancelled)
        _verify(manifest_path, 3, plan.total)
        for name, digest in hashes.items():
            _assert(sha256_file(source / name) == digest, "Fonte fictícia mudou.")
        report = _report(
            34, 3, plan.total,
            interrupted_checkpoint_rejected=True,
            interrupted_checkpoint_rejection=rejection,
            unrecorded_file_readopted_after_hash_verification=True,
            missing_backup_file_recopied=True,
            backup_resume_sha256_verified=True,
            unfinished_restore_journal_recovered=True,
            restore_resume_sha256_verified=True,
            original_fixture_preserved=True,
            note=("Simulação de checkpoint/diário perdido entre operações. "
                  "Não encerra o processo de forma abrupta, não corta energia "
                  "e não valida recuperação de falha real do Windows."),
        )
    return _cleaned(report, root)
