# -*- coding: utf-8 -*-
"""
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: config/settings.py

Configurações centralizadas do sistema.

Carrega variáveis de ambiente do arquivo .env e fornece acesso tipado.

Histórico de patches (Fase 2 — auditoria Claude):
- #4: Leitura dupla IMAP_USER/SMTP_USER com fallback para EMAIL_USER
- #5: Fallback APPROVAL_EMAIL -> SENDER_EMAIL -> EMAIL_USER
- #6: Leitura de DB_FILE como fonte primária, DB_PATH como fallback
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv


# --- CARREGAMENTO DO .ENV ---------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


def _env_or(*keys: str, default: str = "") -> str:
    """Retorna o valor da primeira variável de ambiente não-vazia entre `keys`.

    Útil para unificar nomes divergentes entre .env e código sem quebrar
    interfaces existentes.
    """
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default


class Settings:
    """Configurações do sistema CP FANI."""

    # =========================================================================
    # IMAP (leitura de emails) — Bug #4
    # ---------------------------------------------------------------------------
    # Fonte primária: IMAP_USER/IMAP_PASS (nomenclatura real do .env)
    # Fallback:       EMAIL_USER/EMAIL_PASS (nomenclatura legada do código)
    # =========================================================================
    IMAP_SERVER: str = os.getenv("IMAP_SERVER", "imap.secureserver.net")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))

    EMAIL_USER: str = _env_or("IMAP_USER", "EMAIL_USER", default="")
    EMAIL_PASS: str = _env_or("IMAP_PASS", "EMAIL_PASS", default="")

    # =========================================================================
    # SMTP (envio de emails) — Bug #4
    # ---------------------------------------------------------------------------
    # Fonte primária: SMTP_USER/SMTP_PASS (permite conta SMTP diferente do IMAP)
    # Fallback:       IMAP_USER/EMAIL_USER (mesma conta para leitura e envio)
    # =========================================================================
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.secureserver.net")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))

    SMTP_USER: str = _env_or("SMTP_USER", "IMAP_USER", "EMAIL_USER", default="")
    SMTP_PASS: str = _env_or("SMTP_PASS", "IMAP_PASS", "EMAIL_PASS", default="")

    # =========================================================================
    # Destinatários — Bug #5
    # ---------------------------------------------------------------------------
    # APPROVAL_EMAIL com fallback em cascata:
    #   1) APPROVAL_EMAIL (se explicitamente definido)
    #   2) SENDER_EMAIL   (identidade de envio da organização)
    #   3) EMAIL_USER     (própria conta IMAP, para ambientes de teste)
    # =========================================================================
    APPROVAL_EMAIL: str = _env_or(
        "APPROVAL_EMAIL", "SENDER_EMAIL", "IMAP_USER", "EMAIL_USER", default=""
    )
    FINANCEIRO_EMAIL: str = os.getenv("FINANCEIRO_EMAIL", "")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "")

    # --- Domínios e filtros -------------------------------------------------
    DOMAIN_APROVADOR: str = os.getenv("DOMAIN_APROVADOR", "didier.com.br")

    # Whitelist de remetentes confiáveis (um por linha no .env)
    WHITELIST_SENDERS: List[str] = [
        s.strip() for s in os.getenv("WHITELIST_SENDERS", "").split("\n")
        if s.strip()
    ]

    # Blacklist de remetentes bloqueados
    BLACKLIST_SENDERS: List[str] = [
        s.strip() for s in os.getenv("BLACKLIST_SENDERS", "").split("\n")
        if s.strip()
    ]

    # Keywords que indicam spam/bloqueio no assunto
    BLOCK_KEYWORDS: List[str] = [
        s.strip() for s in os.getenv("BLOCK_KEYWORDS", "").split("\n")
        if s.strip()
    ]

    # =========================================================================
    # Paths — Bug #6
    # ---------------------------------------------------------------------------
    # Fonte primária: DB_FILE (nomenclatura real do .env)
    # Fallback:       DB_PATH (nomenclatura legada do código)
    # =========================================================================
    _DB_RELATIVE: str = _env_or("DB_FILE", "DB_PATH", default="data/cpfani.db")
    DB_PATH: Path = _PROJECT_ROOT / _DB_RELATIVE
    LOG_DIR: Path = _PROJECT_ROOT / os.getenv("LOG_DIR", "logs")

    # --- Comportamento ------------------------------------------------------
    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "60"))

    # --- Prazos -------------------------------------------------------------
    APPROVAL_REMINDER_HOURS: int = int(os.getenv("APPROVAL_REMINDER_HOURS", "24"))
    APPROVAL_EXPIRE_DAYS: int = int(os.getenv("APPROVAL_EXPIRE_DAYS", "7"))

    # =========================================================================
    # PATCH ADITIVO DE COMPATIBILIDADE (AUDITORIA DE INTERFACE — FASE 1)
    # ---------------------------------------------------------------------------
    # Aliases mantidos. Nenhum método existente foi removido.
    # =========================================================================

    # database/database.py espera DB_FILE; fonte da verdade é DB_PATH
    DB_FILE: Path = DB_PATH

    # response_handler faz endswith(); garante o "@" para casar só o domínio
    APPROVER_DOMAIN: str = "@" + DOMAIN_APROVADOR

    # response_handler espera APPROVAL_TIMEOUT_DAYS; fonte da verdade é EXPIRE
    APPROVAL_TIMEOUT_DAYS: int = APPROVAL_EXPIRE_DAYS

    # Prefixo dos assuntos encaminhados ao financeiro
    FORWARD_SUBJECT_PREFIX: str = os.getenv(
        "FORWARD_SUBJECT_PREFIX", "[CP FANI] ENC:"
    )

    def validate(self) -> List[str]:
        """Valida campos obrigatórios. Retorna lista de campos faltantes."""
        missing = []
        if not self.EMAIL_USER:
            missing.append("EMAIL_USER (ou IMAP_USER)")
        if not self.EMAIL_PASS:
            missing.append("EMAIL_PASS (ou IMAP_PASS)")
        if not self.SMTP_USER:
            missing.append("SMTP_USER (ou IMAP_USER/EMAIL_USER)")
        if not self.SMTP_PASS:
            missing.append("SMTP_PASS (ou IMAP_PASS/EMAIL_PASS)")
        if not self.APPROVAL_EMAIL:
            missing.append(
                "APPROVAL_EMAIL (ou SENDER_EMAIL/EMAIL_USER como fallback)"
            )
        if not self.FINANCEIRO_EMAIL:
            missing.append("FINANCEIRO_EMAIL")
        return missing

    def summary(self) -> str:
        """Retorna resumo das configurações (sem expor senhas)."""
        smtp_same_as_imap = (
            self.SMTP_USER == self.EMAIL_USER and self.SMTP_PASS == self.EMAIL_PASS
        )
        smtp_label = self.SMTP_USER or "(vazio)"
        if smtp_same_as_imap and self.SMTP_USER:
            smtp_label += " (mesma do IMAP)"

        return (
            f"IMAP={self.IMAP_SERVER}:{self.IMAP_PORT} "
            f"User={self.EMAIL_USER or '(vazio)'} | "
            f"SMTP={self.SMTP_SERVER}:{self.SMTP_PORT} "
            f"User={smtp_label} | "
            f"Aprovador={self.APPROVAL_EMAIL or '(vazio)'} | "
            f"Financeiro={self.FINANCEIRO_EMAIL or '(vazio)'} | "
            f"Domínio={self.DOMAIN_APROVADOR} | "
            f"Whitelist={len(self.WHITELIST_SENDERS)} | "
            f"Blacklist={len(self.BLACKLIST_SENDERS)} | "
            f"Keywords={len(self.BLOCK_KEYWORDS)} | "
            f"DRY_RUN={self.DRY_RUN} | "
            f"DB={self.DB_PATH.name}"
        )


# Instância global
settings = Settings()


# --- AUTO-TESTE -------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE SETTINGS (Fase 2)")
    print("=" * 70)

    # Teste 1: Carregamento
    print(f"1. Project root: {_PROJECT_ROOT}")
    print(f"2. .env exists: {_ENV_FILE.exists()}")

    # Teste 2: Validação
    missing = settings.validate()
    if missing:
        print(f"3. ⚠️  Campos faltando: {missing}")
    else:
        print("3. ✅ Todos os campos obrigatórios preenchidos")

    # Teste 3: Summary
    print(f"4. Summary: {settings.summary()}")

    # Teste 4: Paths
    print(f"5. DB path: {settings.DB_PATH}")
    print(f"6. Log dir: {settings.LOG_DIR}")

    # Teste 5: Aliases de compatibilidade (Fase 1)
    assert settings.DB_FILE == settings.DB_PATH, "alias DB_FILE falhou"
    assert settings.APPROVER_DOMAIN == "@" + settings.DOMAIN_APROVADOR, \
        "alias APPROVER_DOMAIN falhou"
    assert settings.APPROVAL_TIMEOUT_DAYS == settings.APPROVAL_EXPIRE_DAYS, \
        "alias APPROVAL_TIMEOUT_DAYS falhou"
    assert settings.FORWARD_SUBJECT_PREFIX, "FORWARD_SUBJECT_PREFIX vazio"
    print("7. ✅ Aliases Fase 1 OK (DB_FILE, APPROVER_DOMAIN, "
          "APPROVAL_TIMEOUT_DAYS, FORWARD_SUBJECT_PREFIX)")

    # Teste 6: Correções da Fase 2 (Claude)
    print("-" * 70)
    print("CORREÇÕES FASE 2 (Claude):")
    print(f"  #4 IMAP_USER  -> EMAIL_USER = {settings.EMAIL_USER or '(vazio)'}")
    print(f"  #4 SMTP_USER  -> SMTP_USER  = {settings.SMTP_USER or '(vazio)'}")
    print(f"  #5 APPROVAL_EMAIL (fallback) = {settings.APPROVAL_EMAIL or '(vazio)'}")
    print(f"  #6 DB_FILE    -> DB_PATH    = {settings.DB_PATH.name}")
    print("-" * 70)

    print("=" * 70)
    print("SETTINGS OK" if not missing else "SETTINGS COM AVISOS")
    print("=" * 70)