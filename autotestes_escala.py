"""#35–37: synthetic scale, abrupt child exit and live Tk event-loop probes.

Only parent-created disposable folders are accepted by the child entrypoint.
No process enumeration, disk changes, real source selection or real backups.
"""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

from backup_core import atomic_json, build_plan, copy_backup, sha256_file
from backup_features import restore_selected, verified_entries
from selective_recovery import verify_complete_manifest

MIB = 1024 ** 2
GIB = 1024 ** 3
CRASH_EXIT = 86


def check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError('Autoteste cancelado; nenhuma aprovação emitida.')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def peak_rss():
    """OS process-lifetime peak working set/RSS, not Python-only allocation."""
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def preflight(root, amount):
    free = shutil.disk_usage(root).free
    needed = amount * 3 + max(10 * GIB, free // 10) + 256 * MIB
    if free < needed:
        raise OSError(f'Teste não iniciado: precisa de aproximadamente {needed / GIB:.1f} GiB livres '
                      f'na área temporária; disponíveis {free / GIB:.1f} GiB.')
    return free, needed


def setup(root):
    for name in ('source', 'backups', 'restores'):
        (root / name).mkdir()


def generate(root, amount, cancelled=None):
    digest = hashlib.sha256()
    block = secrets.token_bytes(MIB)  # bounded allocation; actual writes, no sparse truncate
    with (root / 'source' / 'synthetic.bin').open('xb') as stream:
        remaining = amount
        while remaining:
            check(cancelled)
            chunk = block[:min(remaining, len(block))]
            stream.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
    atomic_json(root / 'fixture.json', {'bytes': amount, 'sha256': digest.hexdigest()})


def plan_for(root):
    plan = build_plan({str(root / 'source'): 'keep'}, [str(root)])
    require(plan.count == 1 and not plan.warnings, 'Inventário sintético inválido.')
    return plan


def verify(root, manifest, target=None):
    fixture = json.loads((root / 'fixture.json').read_text(encoding='utf-8'))
    result = verify_complete_manifest(manifest)
    require(result['files_verified'] == 1 and result['bytes_verified'] == fixture['bytes'],
            'Backup sintético incompleto.')
    entries = verified_entries(manifest)
    require(len(entries) == 1 and next(iter(entries.values()))['sha256'] == fixture['sha256'],
            'Backup divergiu do hash independente da fonte.')
    if target is not None:
        restored = target / next(iter(entries))
        require(restored.stat().st_size == fixture['bytes'] and sha256_file(restored) == fixture['sha256'],
                'Restauração divergiu do hash independente.')
    require(sha256_file(root / 'source' / 'synthetic.bin') == fixture['sha256'],
            'Fonte sintética foi alterada.')
    return entries


def common(number, **values):
    return dict(schema=f'pcro-autoteste-escala-v{number}',
                executed_at_utc=datetime.now(timezone.utc).isoformat(), status='aprovado',
                real_user_backups_accessed=False, physical_independence_verified=False,
                ready_for_format=False, installation_authorized=False, **values)


def phase(root, name):
    atomic_json(root / 'phase.json', {'phase': name})


def child(root, mode):
    """Every subprocess starts a new interpreter; crashes bypass cleanup/finally."""
    plan = plan_for(root) if mode != 'large' else None
    if mode == 'large':
        amount = 2 * GIB
        baseline = peak_rss()
        phase(root, 'Gerando arquivo sintético de 2 GiB')
        generate(root, amount)
        plan = plan_for(root)
        phase(root, 'Copiando e verificando 2 GiB')
        started = time.monotonic()
        folder, result = copy_backup(plan, root / 'backups', strategy_inventory={})
        backup_seconds = time.monotonic() - started
        require(result['status'] == 'concluido', 'Backup maior não concluído.')
        manifest = folder / 'manifest.json'
        entries = verify(root, manifest)
        phase(root, 'Restaurando e verificando 2 GiB')
        started = time.monotonic()
        target, count = restore_selected(manifest, list(entries), root / 'restores', strategy_inventory={})
        restore_seconds = time.monotonic() - started
        require(count == 1, 'Restauração maior incompleta.')
        verify(root, manifest, target)
        peak = peak_rss()
        require(peak <= 512 * MIB, 'Pico de memória do processo excedeu 512 MiB.')
        atomic_json(root / 'result.json', common(35, fixture_bytes=amount,
                    backup_sha256_verified=True, restore_sha256_verified=True,
                    original_fixture_preserved=True, backup_elapsed_seconds=round(backup_seconds, 3),
                    restore_elapsed_seconds=round(restore_seconds, 3),
                    process_peak_rss_bytes=peak, process_initial_peak_rss_bytes=baseline,
                    peak_rss_limit_bytes=512 * MIB, memory_limit_passed=True,
                    note='2 GiB no sistema de arquivos temporário; inclui cache do SO. '
                         'Pico do processo, não memória total do computador. Sem prova de durabilidade elétrica.'))
        return
    if mode.startswith('crash-'):
        event = 'backup_after_write' if mode == 'crash-backup' else 'restore_after_write'
        writes = 0
        def abrupt(stage):
            nonlocal writes
            if stage == event:
                writes += 1
                if writes == 2:
                    atomic_json(root / (mode + '.json'), {'stage': stage, 'writes': writes})
                    os._exit(CRASH_EXIT)
        if mode == 'crash-backup':
            copy_backup(plan, root / 'backups', strategy_inventory={}, test_fault_hook=abrupt)
        else:
            manifest = next((root / 'backups').glob('backup-*/manifest.json'))
            restore_selected(manifest, list(verified_entries(manifest)), root / 'restores',
                             strategy_inventory={}, test_fault_hook=abrupt)
        raise AssertionError('O subprocesso não foi encerrado durante a escrita.')
    manifest = next((root / 'backups').glob('backup-*/manifest.json'))
    if mode == 'resume-backup':
        _, result = copy_backup(plan, root / 'backups', resume_manifest=manifest, strategy_inventory={})
        require(result['status'] == 'concluido', 'Backup não retomado após saída abrupta.')
        verify(root, manifest)
    elif mode == 'resume-restore':
        target = next((root / 'restores').glob('TESTE-RESTAURACAO-*'))
        restored, count = restore_selected(manifest, list(verified_entries(manifest)), root / 'restores',
                                          resume_from=target, strategy_inventory={})
        require(count == 1, 'Restauração não retomada após saída abrupta.')
        verify(root, manifest, restored)
    else:
        raise ValueError('Modo de teste inválido.')


def launch(root, token, mode, cancelled=None, progress=None, timeout=1800):
    check(cancelled)
    interpreter = Path(sys.executable)
    if interpreter.name.lower() == 'pythonw.exe':
        interpreter = interpreter.with_name('python.exe')
    command = [str(interpreter), str(Path(__file__).resolve()), '--child', str(root), token, mode]
    started = time.monotonic()
    last_phase = None
    # File logging avoids pipe deadlocks; logs live only in this private tree.
    with (root / 'child.log').open('ab') as log:
        process = subprocess.Popen(command, cwd=Path(__file__).parent, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                check(cancelled)
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Subprocesso de teste excedeu o prazo.')
                if progress and (root / 'phase.json').is_file():
                    current = json.loads((root / 'phase.json').read_text(encoding='utf-8'))['phase']
                    if current != last_phase:
                        progress(current)
                        last_phase = current
                time.sleep(.1)
            return process.returncode
        finally:
            if process.poll() is None:
                process.kill()  # only this child handle, never user processes
            process.wait(timeout=15)


def private_root(number):
    return tempfile.TemporaryDirectory(prefix=f'PCRO-ESCALA{number}-')


def authorize(root):
    token = secrets.token_hex(24)
    (root / 'owner.token').write_text(token, encoding='utf-8')
    setup(root)
    return token


def run_gigabyte_autotest(*, cancelled=None, progress=None):
    check(cancelled)
    with private_root(35) as name:
        root = Path(name).resolve()
        free, needed = preflight(root, 2 * GIB)
        token = authorize(root)
        require(launch(root, token, 'large', cancelled, progress) == 0,
                'Teste de 2 GiB falhou no subprocesso; não aprovado.')
        report = json.loads((root / 'result.json').read_text(encoding='utf-8'))
        report.update(free_bytes_before=free, required_free_bytes=needed)
    require(not root.exists(), 'Área temporária não foi removida.')
    report['temporary_data_cleaned'] = True
    return report


def run_abrupt_exit_autotest(*, cancelled=None, progress=None):
    check(cancelled)
    with private_root(36) as name:
        root = Path(name).resolve()
        preflight(root, 8 * MIB)
        token = authorize(root)
        generate(root, 8 * MIB, cancelled)
        if progress:
            progress('Encerrando apenas o subprocesso durante a cópia sintética')
        require(launch(root, token, 'crash-backup', cancelled) == CRASH_EXIT,
                'Saída abrupta do backup não observada.')
        require((root / 'crash-backup.json').is_file(), 'Marcador da saída abrupta ausente.')
        manifest = next((root / 'backups').glob('backup-*/manifest.json'))
        require(json.loads(manifest.read_text(encoding='utf-8'))['status'] == 'em_andamento',
                'Manifesto inesperado após encerramento abrupto.')
        try:
            verify_complete_manifest(manifest)
        except ValueError as exc:
            require('Backup parcial, interrompido ou com erros. Não aprovado.' in str(exc),
                    'Rejeição por causa inesperada.')
        else:
            raise AssertionError('Backup interrompido aprovado indevidamente.')
        backup_fragments = list((root / 'backups').rglob('*.partial-*'))
        require(backup_fragments and all(p.stat().st_size > 0 for p in backup_fragments),
                'Não houve fragmento escrito antes do encerramento.')
        require(launch(root, token, 'resume-backup', cancelled) == 0, 'Retomada em novo processo falhou.')
        require(launch(root, token, 'crash-restore', cancelled) == CRASH_EXIT,
                'Saída abrupta da restauração não observada.')
        require((root / 'crash-restore.json').is_file(), 'Marcador da restauração ausente.')
        restore_folder = next((root / 'restores').glob('TESTE-RESTAURACAO-*'))
        require(json.loads((restore_folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))['status'] == 'em_andamento',
                'Diário inesperado após saída abrupta.')
        restore_fragments = list(restore_folder.rglob('*.partial-*'))
        require(restore_fragments and all(p.stat().st_size > 0 for p in restore_fragments),
                'Fragmento de restauração não observado.')
        require(launch(root, token, 'resume-restore', cancelled) == 0, 'Restauração em novo processo falhou.')
        verify(root, manifest, restore_folder)
        journal = json.loads((restore_folder / 'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
        require(journal['status'] == 'concluida', 'Diário final não concluído.')
        report = common(36, fixture_bytes=8 * MIB, child_exit_code=CRASH_EXIT,
                        backup_process_abruptly_exited=True, restore_process_abruptly_exited=True,
                        partial_manifest_rejected=True, backup_resumed_in_new_process=True,
                        restore_resumed_in_new_process=True, backup_sha256_verified=True,
                        restore_sha256_verified=True, original_fixture_preserved=True,
                        abandoned_backup_fragments=len(backup_fragments),
                        abandoned_restore_fragments=len(restore_fragments),
                        note='Saída os._exit durante escrita em subprocessos próprios. '
                             'Fragmentos abandonados podem persistir até a limpeza desta área de teste. '
                             'Não simula queda de energia, falha do SO nem perda de cache do disco.')
    require(not root.exists(), 'Área temporária não removida.')
    report['temporary_data_cleaned'] = True
    return report


def run_responsiveness_autotest(*, cancelled=None, ui_cancel=None, progress=None):
    """Worker half of #37. The real Tk event loop must invoke its cancel control."""
    check(cancelled)
    if ui_cancel is None:
        raise ValueError('Teste #37 exige a janela Tk e o controle de cancelamento de teste.')
    with private_root(37) as name:
        root = Path(name).resolve()
        preflight(root, 128 * MIB)
        setup(root)
        generate(root, 128 * MIB, cancelled)
        plan = plan_for(root)
        if progress:
            progress('Cancelamento de teste será acionado pela janela; aguarde')
        def pacing(stage):
            check(cancelled)
            if stage == 'backup_after_write':
                time.sleep(.03)  # controlled load, gives the real event loop time to run
        folder, result = copy_backup(plan, root / 'backups', cancelled=ui_cancel,
                                     strategy_inventory={}, test_fault_hook=pacing)
        require(ui_cancel.is_set() and result['status'] == 'interrompido',
                'Controle Tk não cancelou o backup sintético a tempo.')
        check(cancelled)
        folder, result = copy_backup(plan, root / 'backups', resume_manifest=folder / 'manifest.json',
                                     strategy_inventory={}, cancelled=cancelled)
        require(result['status'] == 'concluido', 'Retomada após cancelamento Tk falhou.')
        entries = verify(root, folder / 'manifest.json')
        target, count = restore_selected(folder / 'manifest.json', list(entries), root / 'restores',
                                         strategy_inventory={}, cancelled=cancelled)
        require(count == 1, 'Restauração de teste incompleta.')
        verify(root, folder / 'manifest.json', target)
        report = common(37, fixture_bytes=128 * MIB, gui_cancel_observed=True,
                        backup_sha256_verified=True, restore_sha256_verified=True,
                        original_fixture_preserved=True,
                        note='Carga sintética com pausa controlada. Mede esta janela e este período; '
                             'não certifica toda a interface nem desempenho em todos os computadores.')
    require(not root.exists(), 'Área temporária não removida.')
    report['temporary_data_cleaned'] = True
    return report


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--child':
        raise SystemExit('Use os botões de autoteste no aplicativo.')
    root = Path(sys.argv[2]).resolve(strict=True)
    token = sys.argv[3]
    if (root.parent != Path(tempfile.gettempdir()).resolve() or
            not root.name.startswith(('PCRO-ESCALA35-', 'PCRO-ESCALA36-')) or
            not secrets.compare_digest((root / 'owner.token').read_text(encoding='utf-8'), token)):
        raise SystemExit('Área de teste não autorizada.')
    child(root, sys.argv[4])
