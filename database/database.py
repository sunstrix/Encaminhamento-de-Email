# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: database/database.py
==============================================================================
Persistencia SQLite. Stdlib only (sqlite3), sem dependencias externas.
Usa `with` + WAL mode para seguranca contra quedas de energia durante o
cron hourly. Todas as operacoes sao idempotentes.

Tabelas:
- forwarded_emails : historico de Message-IDs ja encaminhados (evita duplicata)
- pending_approvals: emails com > X R$ aguardando botao APROVAR/REPROVAR
- blacklist        : remetentes que o usuario bloqueou manualmente
- whitelist        : remetentes sempre aprovados (excecao da regra de assunto)
- state            : checkpoint da ultima varredura (cron hourly + semanal)
==============================================================================
"""

import sys
from pathlib import Path

# --- FIX DE PATH (EXECUCAO STANDALONE) -----------------------------------
# Garante que a raiz do projeto esteja no sys.path para imports absolutos.
# Necessario quando o script eh executado diretamente (python database/database.py)
# em vez de como modulo (python -m database.database).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# -------------------------------------------------------------------------

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from config.settings import settings


# ----------------------------------------------------------------------------
# SCHEMA (migracoes incrementais - cada versao e um IF NOT EXISTS/ALTER)
# ----------------------------------------------------------------------------
_SCHEMA = """
-- Historico de Message-IDs ja processados.
-- Evita re-enviar email se o cron rodar duas vezes sobre o mesmo ID.
CREATE TABLE IF NOT EXISTS forwarded_emails (
    message_id   TEXT PRIMARY KEY,
    sender       TEXT NOT NULL,
    subject      TEXT,
    forwarded_at TEXT NOT NULL,      -- ISO-8601 UTC
    folder       TEXT DEFAULT 'INBOX',
    decision     TEXT DEFAULT 'FORWARDED'  -- FORWARDED | SKIPPED_DOMAIN | SKIPPED_SUBJECT | BLACKLISTED
);

CREATE INDEX IF NOT EXISTS idx_forwarded_sender ON forwarded_emails(sender);
CREATE INDEX IF NOT EXISTS idx_forwarded_at     ON forwarded_emails(forwarded_at);

-- Emails financeiros de alto valor aguardando aprovacao humana.
-- UUID eh a chave que vai no botao HTML do email de aprovacao.
CREATE TABLE IF NOT EXISTS pending_approvals (
    uuid            TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL,
    folder          TEXT NOT NULL DEFAULT 'INBOX',
    uid             INTEGER,               -- IMAP UID (fallback se Message-ID nao existir)
    sender          TEXT NOT NULL,
    sender_name     TEXT,
    subject         TEXT,
    received_at     TEXT,                  -- ISO-8601 do email original
    amount_brl      REAL,                  -- NULL se nao conseguiu extrair
    body_snippet    TEXT,                  -- primeiros 500 chars p/ contexto
    status          TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | APPROVED | REJECTED | EXPIRED | FORWARDED
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_by     TEXT,                  -- email do aprovador
    notes           TEXT,
    last_reminder_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_status    ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_pending_msgid     ON pending_approvals(message_id);
CREATE INDEX IF NOT EXISTS idx_pending_created   ON pending_approvals(created_at);

-- Blacklist de remetentes (adicionados manualmente via email-resposta "BLACKLIST").
CREATE TABLE IF NOT EXISTS blacklist (
    email       TEXT PRIMARY KEY,
    added_at    TEXT NOT NULL,
    added_by    TEXT,
    reason      TEXT
);

-- Whitelist: remetentes que SEMPRE passam, mesmo com assunto bloqueado.
CREATE TABLE IF NOT EXISTS whitelist (
    email       TEXT PRIMARY KEY,
    added_at    TEXT NOT NULL,
    added_by    TEXT,
    reason      TEXT
);

-- Estado global: ultima varredura, contadores do relatorio semanal, etc.
CREATE TABLE IF NOT EXISTS state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class Database:
    """Acesso thread-safe ao SQLite do sistema."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.DB_FILE)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Lock por instancia (SQLite suporta multi-thread via WAL,
        # mas serializamos writes para evitar SQLITE_BUSY em crons concorrentes)
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------ utils
    def _connect(self) -> sqlite3.Connection:
        """Conexao com pragmas de seguranca/performance.
        WAL: escrita nao bloqueia leitura (importante p/ relatorio rodando
        ao mesmo tempo que o cron). foreign_keys ON (defensivo).
        """
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    @contextmanager
    def _tx(self):
        """Context manager de transacao com commit/rollback automatico."""
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        """Cria tabelas/indices se nao existirem (idempotente)."""
        with self._tx() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ============================================================ forwarded
    def is_forwarded(self, message_id: str) -> bool:
        """Retorna True se o Message-ID ja foi processado (qualquer decisao)."""
        if not message_id:
            return False
        with self._tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM forwarded_emails WHERE message_id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
            return row is not None

    def mark_forwarded(
        self,
        message_id: str,
        sender: str,
        subject: str,
        decision: str = "FORWARDED",
        folder: str = "INBOX",
    ) -> None:
        """Registra o Message-ID como processado. INSERT OR IGNORE evita
        duplicatas em caso de retry.
        """
        if not message_id:
            # emails sem Message-ID sao raros; usamos UUID como chave sintetica
            message_id = f"synthetic:{uuid.uuid4().hex}"
        with self._tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO forwarded_emails
                   (message_id, sender, subject, forwarded_at, folder, decision)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    sender or "unknown",
                    subject or "",
                    self._utcnow_iso(),
                    folder,
                    decision,
                ),
            )

    def count_forwarded_since(self, since: datetime) -> int:
        """Quantos emails foram FORWARDADOS (nao SKIPPED) desde `since`."""
        iso = since.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._tx() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM forwarded_emails
                   WHERE forwarded_at >= ? AND decision = 'FORWARDED'""",
                (iso,),
            ).fetchone()
            return row[0] if row else 0

    # ============================================================ approvals
    def add_pending_approval(
        self,
        message_id: str,
        folder: str,
        uid: Optional[int],
        sender: str,
        sender_name: Optional[str],
        subject: str,
        received_at: Optional[str],
        amount_brl: Optional[float],
        body_snippet: str,
    ) -> str:
        """Cria um registro de aprovacao pendente e retorna o UUID (usado
        nos botoes HTML do email de solicitacao)."""
        approval_uuid = uuid.uuid4().hex
        now = self._utcnow_iso()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO pending_approvals
                   (uuid, message_id, folder, uid, sender, sender_name,
                    subject, received_at, amount_brl, body_snippet,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                (
                    approval_uuid,
                    message_id or f"synthetic:{uuid.uuid4().hex}",
                    folder or "INBOX",
                    uid,
                    sender or "unknown",
                    sender_name,
                    subject or "",
                    received_at,
                    amount_brl,
                    (body_snippet or "")[:500],
                    now,
                ),
            )
        return approval_uuid

    def get_pending_approvals(self, only_pending: bool = True) -> List[Dict]:
        """Lista todas as aprovacoes (pendentes por default)."""
        sql = "SELECT * FROM pending_approvals"
        if only_pending:
            sql += " WHERE status = 'PENDING'"
        sql += " ORDER BY created_at ASC"
        with self._tx() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def get_approval(self, approval_uuid: str) -> Optional[Dict]:
        if not approval_uuid:
            return None
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM pending_approvals WHERE uuid = ?",
                (approval_uuid,),
            ).fetchone()
            return dict(row) if row else None

    def resolve_approval(
        self,
        approval_uuid: str,
        new_status: str,
        resolved_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """Atualiza status (APPROVED / REJECTED / EXPIRED / FORWARDED).
        Retorna True se encontrou e atualizou.
        """
        if new_status not in ("APPROVED", "REJECTED", "EXPIRED", "FORWARDED"):
            raise ValueError(f"status invalido: {new_status}")
        now = self._utcnow_iso()
        with self._tx() as conn:
            cur = conn.execute(
                """UPDATE pending_approvals
                   SET status = ?, resolved_at = ?, resolved_by = ?, notes = ?
                   WHERE uuid = ?""",
                (new_status, now, resolved_by, notes, approval_uuid),
            )
            return cur.rowcount > 0

    def expire_old_approvals(self, timeout_days: Optional[int] = None) -> int:
        """Marca como EXPIRED aprovacoes abertas ha mais de `timeout_days`.
        Usado pelo cron daily. Retorna quantas foram expiradas.
        """
        days = timeout_days if timeout_days is not None else settings.APPROVAL_TIMEOUT_DAYS
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")
        now = self._utcnow_iso()
        with self._tx() as conn:
            cur = conn.execute(
                """UPDATE pending_approvals
                   SET status = 'EXPIRED', resolved_at = ?, resolved_by = 'SYSTEM'
                   WHERE status = 'PENDING' AND created_at < ?""",
                (now, cutoff),
            )
            return cur.rowcount

    def touch_reminder(self, approval_uuid: str) -> None:
        now = self._utcnow_iso()
        with self._tx() as conn:
            conn.execute(
                "UPDATE pending_approvals SET last_reminder_at = ? WHERE uuid = ?",
                (now, approval_uuid),
            )

    # ============================================================ blacklist
    def is_blacklisted(self, email: str) -> bool:
        if not email:
            return False
        key = email.strip().lower()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM blacklist WHERE email = ? LIMIT 1", (key,)
            ).fetchone()
            return row is not None

    def add_blacklist(
        self, email: str, added_by: Optional[str] = None, reason: Optional[str] = None
    ) -> None:
        if not email:
            return
        key = email.strip().lower()
        now = self._utcnow_iso()
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO blacklist
                   (email, added_at, added_by, reason) VALUES (?, ?, ?, ?)""",
                (key, now, added_by, reason),
            )

    def remove_blacklist(self, email: str) -> bool:
        if not email:
            return False
        key = email.strip().lower()
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM blacklist WHERE email = ?", (key,))
            return cur.rowcount > 0

    def list_blacklist(self) -> List[Dict]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM blacklist ORDER BY added_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ============================================================ whitelist
    def is_whitelisted(self, email: str) -> bool:
        if not email:
            return False
        key = email.strip().lower()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM whitelist WHERE email = ? LIMIT 1", (key,)
            ).fetchone()
            return row is not None

    def add_whitelist(
        self, email: str, added_by: Optional[str] = None, reason: Optional[str] = None
    ) -> None:
        if not email:
            return
        key = email.strip().lower()
        now = self._utcnow_iso()
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO whitelist
                   (email, added_at, added_by, reason) VALUES (?, ?, ?, ?)""",
                (key, now, added_by, reason),
            )

    # ============================================================ state (k/v)
    def set_state(self, key: str, value) -> None:
        if value is None:
            value = ""
        elif not isinstance(value, str):
            value = str(value)
        now = self._utcnow_iso()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE
                   SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, now),
            )

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT value FROM state WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default

    def get_state_dict(self) -> Dict[str, str]:
        with self._tx() as conn:
            rows = conn.execute("SELECT key, value FROM state").fetchall()
            return {r[0]: r[1] for r in rows}

    # ============================================================ manut
    def vacuum_if_needed(self, min_days: int = 30) -> None:
        """Remove registros de forwarded_emails muito antigos para nao
        deixar o banco crescer indefinidamente. Mantemos 30 dias por default.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=min_days)
        ).isoformat(timespec="seconds")
        with self._tx() as conn:
            conn.execute(
                "DELETE FROM forwarded_emails WHERE forwarded_at < ?", (cutoff,)
            )

    def stats(self) -> Dict:
        """Resumo para o relatorio semanal e auto-teste."""
        with self._tx() as conn:
            total_fwd = conn.execute(
                "SELECT COUNT(*) FROM forwarded_emails WHERE decision = 'FORWARDED'"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'PENDING'"
            ).fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'APPROVED'"
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'REJECTED'"
            ).fetchone()[0]
            bl = conn.execute("SELECT COUNT(*) FROM blacklist").fetchone()[0]
            return {
                "forwarded": total_fwd,
                "pending": pending,
                "approved": approved,
                "rejected": rejected,
                "blacklist": bl,
            }


# Instancia unica consumida pelos modulos
db = Database()


# ----------------------------------------------------------------------------
# AUTO-TESTE: python database/database.py
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE DATABASE")
    print("=" * 70)
    print(f"Arquivo SQLite: {db.db_path}")
    print(f"Existe        : {'SIM' if db.db_path.exists() else 'NAO (sera criado)'}")

    # escrita de teste
    test_uuid = db.add_pending_approval(
        message_id="<auto-test@localhost>",
        folder="INBOX",
        uid=None,
        sender="auto-test@didier.com.br",
        sender_name="Auto Test",
        subject="Teste de persistencia",
        received_at=None,
        amount_brl=123.45,
        body_snippet="Corpo de teste para validar schema.",
    )
    print(f"UUID inserido : {test_uuid}")

    db.add_blacklist("spam@test.com", added_by="auto-test", reason="self-test")
    db.set_state("last_scan", datetime.now(timezone.utc).isoformat())

    # leituras
    print(f"Blacklisted?  : {db.is_blacklisted('spam@test.com')}")
    print(f"Whitelisted?  : {db.is_whitelisted('spam@test.com')}")
    pending = db.get_pending_approvals(only_pending=True)
    print(f"Pendentes     : {len(pending)}")

    # rollback do teste: remove o que acabamos de inserir
    with db._tx() as conn:
        conn.execute("DELETE FROM pending_approvals WHERE uuid = ?", (test_uuid,))
        conn.execute("DELETE FROM blacklist WHERE email = ?", ("spam@test.com",))
        conn.execute("DELETE FROM state WHERE key = 'last_scan'")

    stats = db.stats()
    print("-" * 70)
    print("Estatisticas atuais do banco:")
    for k, v in stats.items():
        print(f"  {k:12s}: {v}")
    print("=" * 70)
    print("DATABASE OK - pronto para os proximos modulos.")
    print("=" * 70)