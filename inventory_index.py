"""A user-owned, searchable SQLite index of file *metadata*, not a backup.

Only an explicitly chosen NEW index database and an explicitly chosen NEW
selection export are written. No source file contents are opened, no deletion,
formatting, restore or Windows changes. Persistent index is a historical
observation: it cannot certify consistency or completeness after a restart.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from inventory_paged import PagedMetadataScanner

SCHEMA = "pcro-file-index-v1"
VALID_DECISIONS = {"preservar", "nao_copiar", "revisar"}


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _safe_file_destination(path):
    path = Path(path)
    if not path.parent.is_dir() or path.is_symlink():
        raise ValueError("Pasta de destino inexistente ou caminho simbólico.")
    parent = path.parent
    # Do not let a redirected parent silently move inventory/exports.
    while parent != parent.parent:
        if parent.is_symlink():
            raise ValueError("Destino dentro de pasta simbólica não permitido.")
        parent = parent.parent
    return path


class FileMetadataIndex:
    """SQLite metadata rows with explicit per-file review decisions."""

    def __init__(self, path, *, create=False):
        self.path = _safe_file_destination(path)
        if create:
            # Exclusive creation: never silently overwrite an existing index.
            with open(self.path, "xb"):
                pass
        elif not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        try:
            if create:
                self.conn.executescript("""
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE records (
                        path TEXT PRIMARY KEY,
                        volume_root TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK(kind IN ('file','directory')),
                        bytes INTEGER NOT NULL CHECK(bytes >= 0),
                        mtime_ns INTEGER NOT NULL,
                        candidate INTEGER NOT NULL CHECK(candidate IN (0, 1)),
                        decision TEXT NOT NULL DEFAULT 'revisar'
                            CHECK(decision IN ('preservar','nao_copiar','revisar'))
                    );
                    CREATE INDEX records_volume ON records(volume_root);
                    CREATE INDEX records_decision ON records(decision);
                """)
                self.conn.executemany("INSERT INTO meta(key,value) VALUES (?,?)", [
                    ("schema", SCHEMA), ("created_at_utc", _utc()),
                    ("state", "parcial"), ("entries_observed", "0"),
                    ("partial_coverage", "true"), ("ready_for_format", "false"),
                ])
                self.conn.commit()
            else:
                cur = self.conn.execute(
                    "SELECT value FROM meta WHERE key='schema'")
                value = cur.fetchone()
                if not value or value[0] != SCHEMA:
                    raise ValueError("Não é um índice de metadados PCRO compatível.")
        except Exception:
            self.conn.close()
            raise

    def close(self):
        self.conn.close()

    def add_page(self, records, snapshot):
        """Commit only finished page results. SQLite rolls back failed commits."""
        rows = []
        for record in records:
            path, kind, size, timestamp, candidate, root = record
            if kind not in ("file", "directory") or size < 0:
                raise ValueError("Registro de metadados inválido.")
            rows.append((str(path), str(root), kind, int(size), int(timestamp),
                         int(bool(candidate))))
        with self.conn:
            self.conn.executemany(
                """INSERT INTO records
                   (path,volume_root,kind,bytes,mtime_ns,candidate)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET
                     volume_root=excluded.volume_root, kind=excluded.kind,
                     bytes=excluded.bytes, mtime_ns=excluded.mtime_ns,
                     candidate=excluded.candidate""", rows)
            # A finished in-memory traversal is never proof of universal
            # coverage; errors/links are exposed in the observation summary.
            state = ("terminado_com_lacunas" if snapshot["finished_current_session"]
                     else "parcial")
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('state',?)",
                (state,))
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('last_snapshot',?)",
                (json.dumps(snapshot, ensure_ascii=False),))
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('updated_at_utc',?)",
                (_utc(),))
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('entries_observed',?)",
                (str(snapshot["entries_examined"]),))

    def set_status(self, state):
        if state not in ("parcial", "interrompido", "falhou", "terminado_com_lacunas"):
            raise ValueError("Estado de índice inválido.")
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('state',?)", (state,))

    def metadata(self):
        return dict(self.conn.execute("SELECT key,value FROM meta"))

    def search(self, term="", *, limit=100, offset=0):
        if not (1 <= limit <= 300 and 0 <= offset <= 10_000_000):
            raise ValueError("Limites de visualização inválidos.")
        term = str(term or "")[:300]
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return [
            dict(path=row[0], kind=row[1], bytes=row[2],
                 decision=row[3], volume_root=row[4])
            for row in self.conn.execute(
                """SELECT path,kind,bytes,decision,volume_root FROM records
                   WHERE path LIKE ? ESCAPE '\\'
                   ORDER BY path LIMIT ? OFFSET ?""",
                ("%" + escaped + "%", limit, offset),
            )
        ]

    def set_decision(self, path, decision):
        if decision not in VALID_DECISIONS:
            raise ValueError("Decisão inválida: nunca significa exclusão.")
        with self.conn:
            row = self.conn.execute(
                "SELECT kind FROM records WHERE path=?", (str(path),)
            ).fetchone()
            if not row or row[0] not in ("file", "directory"):
                raise ValueError("Selecione um arquivo ou pasta realmente inventariado.")
            self.conn.execute("UPDATE records SET decision=? WHERE path=?",
                              (decision, str(path)))

    def decision_counts(self):
        return dict(self.conn.execute(
            "SELECT decision,COUNT(*) FROM records GROUP BY decision"))

    def export_choices(self, path):
        """Export a plan preview; NO automatic backup, deletion or formatting."""
        target = _safe_file_destination(path)
        if target.resolve(strict=False) == self.path.resolve(strict=False):
            raise ValueError("Exportação não pode sobrescrever o índice.")
        choices = dict(self.conn.execute(
            "SELECT path,decision FROM records WHERE decision != 'revisar' "
            "ORDER BY path"))
        if len(choices) > 4000:
            raise ValueError("Há mais de 4.000 escolhas. Exporte em grupos menores.")
        folders = [row[0] for row in self.conn.execute(
            "SELECT path FROM records WHERE kind='directory' "
            "AND decision != 'revisar' ORDER BY path")]
        payload = {
            "schema": "pcro-index-choices-v1",
            "created_at_utc": _utc(),
            "index_file": str(self.path),
            "index_state": self.metadata().get("state", "parcial"),
            "choices": choices,
            "selected_directories": folders,
            "decision_descriptions": {
                "preservar": "Candidato escolhido para futura cópia após nova validação",
                "nao_copiar": "Não incluir na cópia, NÃO significa excluir do computador",
            },
            "verified_backup": False,
            "contains_file_contents": False,
            "ready_for_format": False,
            "installation_authorized": False,
            "note": ("Regras de pastas podem abranger arquivos não observados "
                     "ou alterados desde a varredura. Arquivos com escolha "
                     "individual prevalecem sobre a escolha da pasta. "
                     "Esta exportação não inicia backup nem valida a integridade "
                     "dos conteúdos. Revise e recalcule o plano antes da cópia."),
        }
        # Exclusive creation, never replace a user's file even on repeat export.
        with open(target, "x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        return payload


def index_roots(roots, output_path, *, cancelled=None, progress=None, page_size=2000):
    """Build a new user-named index from metadata of local roots.

    On cancellation or exception, the incomplete index remains marked partial.
    It is never renamed or presented as a verified backup.
    """
    if not isinstance(page_size, int) or not 1 <= page_size <= 10000:
        raise ValueError("Tamanho de página fora do limite.")
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Varredura cancelada antes de criar o índice.")
    db = FileMetadataIndex(output_path, create=True)
    scanner = None
    # The user may store the index on one of the scanned drives. Do not
    # index our own changing database or SQLite temporary sidecars.
    own_files = {
        os.path.normcase(os.path.abspath(str(db.path) + suffix))
        for suffix in ("", "-journal", "-wal", "-shm")
    }
    def collect(record, batch):
        name = os.path.normcase(os.path.abspath(record[0]))
        if name not in own_files:
            batch.append(record)
    try:
        scanner = PagedMetadataScanner(roots)
        while True:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("Inventário interrompido; índice parcial preservado.")
            batch = []
            try:
                result = scanner.step(page_size=page_size, cancelled=cancelled,
                                      on_entry=lambda record: collect(record, batch))
            except InterruptedError:
                db.set_status("interrompido")
                raise
            db.add_page(batch, result)
            if progress is not None:
                progress(result["entries_examined"], result["directories_pending"])
            if result["finished_current_session"]:
                return {
                    "schema": "pcro-index-report-v1",
                    "status": "concluido_com_lacunas",
                    "index_file": str(db.path),
                    "entries_examined": result["entries_examined"],
                    "indexed_files": db.conn.execute(
                        "SELECT COUNT(*) FROM records WHERE kind='file'").fetchone()[0],
                    "indexed_directories": db.conn.execute(
                        "SELECT COUNT(*) FROM records WHERE kind='directory'").fetchone()[0],
                    "access_denied_count": result["access_denied_count"],
                    "reparse_points_skipped": result["reparse_points_skipped"],
                    "partial_coverage": True,
                    "source_files_read": 0,
                    "writes_only_to_chosen_index": True,
                    "ready_for_format": False,
                    "installation_authorized": False,
                }
    except BaseException:
        if scanner is not None:
            try:
                db.set_status("interrompido" if cancelled is not None
                              and cancelled.is_set() else "falhou")
            except sqlite3.Error:
                pass
        raise
    finally:
        if scanner is not None:
            scanner.close()
        db.close()
