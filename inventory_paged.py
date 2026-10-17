"""Incremental, read-only metadata discovery with bounded work per invocation.

A session keeps an open scandir cursor between pages; it is memory-only, not
a restart-proof inventory. Call close() when the window closes. No file
contents, registry, ACL changes, deletions, writes or linked directory traversal.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import threading

from runtime_volumes import discover_drive_letters
from autotestes_bateria import _fixed_or_removable_drive

CANDIDATES = frozenset({
    "steamapps", "steam", "common", "games", "jogos", "saved games",
    "appdata", "program files", "program files (x86)", "osu!",
})


def discover_local_roots():
    """Discover fixed/removable Windows letter roots, not arbitrary user paths."""
    if os.name != "nt":
        raise RuntimeError("Inventário de unidades reais exige Windows.")
    return [Path(f"{letter}:\\") for letter in discover_drive_letters()
            if _fixed_or_removable_drive(letter) and Path(f"{letter}:\\").is_dir()]


def _count_error(item, error):
    if isinstance(error, PermissionError):
        item["access_denied"] += 1
    elif isinstance(error, FileNotFoundError):
        item["disappeared"] += 1
    else:
        item["other_errors"] += 1


def _stat_is_reparse(info):
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


class PagedMetadataScanner:
    """Observe directory entries in small, resumeable in-process pages.

    A page count is NOT a maximum total inventory size: the queue survives each
    step. Existing scandir iterator remains alive only during this session; do
    not persist it or treat a completed traversal as consistent disk snapshot.
    """

    def __init__(self, roots):
        roots = list(roots)
        if not roots or len(roots) > 32:
            raise ValueError("Informe entre 1 e 32 raízes acessíveis.")
        tokens = set()
        self.volumes = []
        self.queue = deque()
        for raw in roots:
            root = Path(raw)
            if not root.is_dir() or root.is_symlink():
                raise ValueError("Uma das raízes não é um diretório local acessível.")
            token = os.path.normcase(os.path.abspath(os.fspath(root)))
            if token in tokens:
                raise ValueError("Raiz de inventário repetida.")
            tokens.add(token)
            self.volumes.append({
                "root": str(root), "entries_examined": 0, "files": 0,
                "folders": 0, "candidate_folders": 0, "reparse_skipped": 0,
                "access_denied": 0, "disappeared": 0, "other_errors": 0,
            })
            self.queue.append((root, len(self.volumes) - 1))
        self._iterator = None
        self._current_volume = None
        self._lock = threading.Lock()
        self.closed = False
        self.pages = 0
        self.entries_examined = 0

    def _finish_directory(self):
        if self._iterator is not None:
            self._iterator.close()
        self._iterator = None
        self._current_volume = None

    def close(self):
        with self._lock:
            self.closed = True
            self._finish_directory()
            self.queue.clear()

    def snapshot(self):
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self):
        pending = len(self.queue) + (1 if self._iterator is not None else 0)
        errors = sum(v["access_denied"] + v["disappeared"] +
                     v["other_errors"] for v in self.volumes)
        reparse = sum(v["reparse_skipped"] for v in self.volumes)
        finished = (pending == 0 and not self.closed)
        return {
            "schema": "pcro-inventario-paginado-v1",
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": ("concluido_escopo_observado" if finished and not errors and not reparse
                       else "concluido_com_lacunas" if finished else "parcial"),
            "finished_current_session": finished,
            "pages": self.pages,
            "entries_examined": self.entries_examined,
            "directories_pending": pending,
            "roots_seen": len(self.volumes),
            "access_denied_count": sum(v["access_denied"] for v in self.volumes),
            "disappeared_count": sum(v["disappeared"] for v in self.volumes),
            "other_error_count": sum(v["other_errors"] for v in self.volumes),
            "reparse_points_skipped": reparse,
            "partial_coverage": True,
            "content_files_opened": 0, "writes_performed": False,
            "real_user_backups_accessed": False,
            "physical_independence_verified": False,
            "ready_for_format": False,
            "installation_authorized": False,
            "volumes": [dict(v) for v in self.volumes],
            "note": ("Cursor somente em memória e válido durante esta janela. "
                     "Páginas continuam a varredura sem teto global de entradas. "
                     "Não lê conteúdo de arquivos, não segue reparse e não prova "
                     "um retrato consistente, ACLs legíveis, saves ou dependências."),
        }

    def step(self, *, page_size=2000, cancelled=None, progress=None, on_entry=None):
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 10000:
            raise ValueError("Tamanho de página inválido.")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Inventário já está sendo processado.")
        try:
            if self.closed:
                raise ValueError("Sessão encerrada; inicie outra análise.")
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("Inventário pausado pelo usuário.")
            processed = 0
            while processed < page_size:
                if cancelled is not None and cancelled.is_set():
                    raise InterruptedError("Inventário pausado; retome esta sessão.")
                if self._iterator is None:
                    if not self.queue:
                        break
                    folder, volume_index = self.queue.popleft()
                    self._current_volume = volume_index
                    try:
                        self._iterator = os.scandir(folder)
                    except (OSError, PermissionError) as exc:
                        _count_error(self.volumes[volume_index], exc)
                        self._current_volume = None
                        continue
                try:
                    entry = next(self._iterator)
                except StopIteration:
                    self._finish_directory()
                    continue
                except OSError as exc:
                    _count_error(self.volumes[self._current_volume], exc)
                    self._finish_directory()
                    continue
                volume = self.volumes[self._current_volume]
                volume["entries_examined"] += 1
                self.entries_examined += 1
                processed += 1
                record = None
                try:
                    info = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or _stat_is_reparse(info):
                        volume["reparse_skipped"] += 1
                    elif stat.S_ISDIR(info.st_mode):
                        volume["folders"] += 1
                        candidate = entry.name.casefold() in CANDIDATES
                        if candidate:
                            volume["candidate_folders"] += 1
                        self.queue.append((Path(entry.path), self._current_volume))
                        record = (str(entry.path), "directory", 0, int(info.st_mtime_ns),
                                  int(candidate), volume["root"])
                    elif stat.S_ISREG(info.st_mode):
                        volume["files"] += 1
                        record = (str(entry.path), "file", int(info.st_size),
                                  int(info.st_mtime_ns), 0, volume["root"])
                except OSError as exc:
                    _count_error(volume, exc)
                # User-supplied record consumers run outside the file-access
                # exception handler: index write errors must fail closed.
                if record is not None and on_entry is not None:
                    on_entry(record)
                if progress is not None and processed % 512 == 0:
                    progress(self.entries_examined)
            self.pages += 1
            return self._snapshot_unlocked()
        finally:
            self._lock.release()
