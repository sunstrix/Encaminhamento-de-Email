# -*- coding: utf-8 -*-
"""
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: config/settings.py

Configurações centralizadas do sistema.

Carrega variáveis de ambiente do arquivo .env e fornece acesso tipado.
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


class Settings:
    """Configurações do sistema CP FANI."""

    # --- IMAP (leitura de emails) -------------------------------------------
    IMAP_SERVER: str = os.getenv("IMAP_SERVER", "imap.secureserver.net")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
    EMAIL_USER: str = os.getenv("EMAIL_USER", "")
    EMAIL_PASS: str = os.getenv("EMAIL_PASS", "")

    # --- SMTP (envio de emails) ---------------------------------------------
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.secureserver.net")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))

    # --- Destinatários ------------------------------------------------------
    APPROVAL_EMAIL: str = os.getenv("APPROVAL_EMAIL", "")
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

    # --- Paths ---------------------------------------------------------------
    DB_PATH: Path = _PROJECT_ROOT / os.getenv("DB_PATH", "data/cpfani.db")
    LOG_DIR: Path = _PROJECT_ROOT / os.getenv("LOG_DIR", "logs")

    # --- Comportamento ------------------------------------------------------
    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "60"))

    # --- Prazos -------------------------------------------------------------
    APPROVAL_REMINDER_HOURS: int = int(os.getenv("APPROVAL_REMINDER_HOURS", "24"))
    APPROVAL_EXPIRE_DAYS: int = int(os.getenv("APPROVAL_EXPIRE_DAYS", "7"))

    # ==========================================================================
    # PATCH ADITIVO DE COMPATIBILIDADE (AUDITORIA DE INTERFACE)
    # --------------------------------------------------------------------------
    # SOMENTE ADIÇÕES. Nenhuma linha existente foi removida ou alterada
    # (Regra Crítica de Preservação). Aliases mapeados a partir da auditoria
    # Select-String dos módulos src/* e database/*.
    # ==========================================================================

    # database/database.py espera DB_FILE; a fonte da verdade é DB_PATH
    DB_FILE: Path = DB_PATH

    # response_handler faz endswith(); garante o "@" para casar apenas o domínio
    APPROVER_DOMAIN: str = "@" + DOMAIN_APROVADOR

    # response_handler espera APPROVAL_TIMEOUT_DAYS; fonte da verdade é EXPIRE
    APPROVAL_TIMEOUT_DAYS: int = APPROVAL_EXPIRE_DAYS

    # Prefixo dos assuntos encaminhados ao financeiro (novo, com default seguro)
    FORWARD_SUBJECT_PREFIX: str = os.getenv(
        "FORWARD_SUBJECT_PREFIX", "[CP FANI] ENC:"
    )

    def validate(self) -> List[str]:
        """Valida campos obrigatórios. Retorna lista de campos faltantes."""
        missing = []
        if not self.EMAIL_USER:
            missing.append("EMAIL_USER")
        if not self.EMAIL_PASS:
            missing.append("EMAIL_PASS")
        if not self.APPROVAL_EMAIL:
            missing.append("APPROVAL_EMAIL")
        if not self.FINANCEIRO_EMAIL:
            missing.append("FINANCEIRO_EMAIL")
        return missing

    def summary(self) -> str:
        """Retorna resumo das configurações (sem expor senhas)."""
        return (
            f"IMAP={self.IMAP_SERVER}:{self.IMAP_PORT} "
            f"User={self.EMAIL_USER or '(vazio)'} | "
            f"SMTP={self.SMTP_SERVER}:{self.SMTP_PORT} | "
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
    print("CP FANI - AUTO-TESTE DE SETTINGS")
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

    # Teste 5: Aliases de compatibilidade (patch aditivo)
    assert settings.DB_FILE == settings.DB_PATH, "alias DB_FILE falhou"
    assert settings.APPROVER_DOMAIN == "@" + settings.DOMAIN_APROVADOR, \
        "alias APPROVER_DOMAIN falhou"
    assert settings.APPROVAL_TIMEOUT_DAYS == settings.APPROVAL_EXPIRE_DAYS, \
        "alias APPROVAL_TIMEOUT_DAYS falhou"
    assert settings.FORWARD_SUBJECT_PREFIX, "FORWARD_SUBJECT_PREFIX vazio"
    print("7. ✅ Aliases de compatibilidade OK (DB_FILE, APPROVER_DOMAIN, "
          "APPROVAL_TIMEOUT_DAYS, FORWARD_SUBJECT_PREFIX)")

    print("=" * 70)
    print("SETTINGS OK" if not missing else "SETTINGS COM AVISOS")
    print("=" * 70)