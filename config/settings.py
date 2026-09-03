# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: config/settings.py
==============================================================================
Fonte unica de verdade de configuracao. Todos os modulos (database,
filter_engine, imap_handler, smtp_handler, button_handler,
response_handler, main) importam `settings` daqui.

Decisoes tecnicas:
- Parser .env proprio (stdlib only): funciona no Windows e no Zorin sem
  instalar python-dotenv. Se a variavel existir no SO, o SO tem prioridade.
- Caminhos 100% pathlib (cross-platform): migra Windows -> Zorin sem edits.
- Timezone com fallback: ZoneInfo se disponivel, senao UTC-3 fixo (BRT sem
  horario de verao, valido no Brasil desde 2019).
- Regras de exclusao embutidas como defaults: o sistema funciona mesmo sem
  .env (modo degradado seguro).
==============================================================================
"""

import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python sem tzdata
    ZoneInfo = None

# ----------------------------------------------------------------------------
# RAIZ DO PROJETO (independente de CWD: funciona de qualquer pasta/cron)
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


# ----------------------------------------------------------------------------
# PARSER .ENV (sem dependencia externa)
# ----------------------------------------------------------------------------
def _parse_env_file(path):
    """Le .env manualmente.
    - ignora linhas vazias e comentarios (#)
    - aceita CHAVE=valor com ou sem aspas (simples/duplas)
    - NUNCA sobrescreve variavel ja exportada no sistema operacional
    """
    values = {}
    if not path or not path.exists():
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # remove aspas envolvendo o valor (ex: SENHA="@DiDier123")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            values[key] = value
    return values


_ENV = _parse_env_file(ENV_FILE)


def _get(key, default=None):
    """SO > .env > default."""
    env_val = os.environ.get(key)
    if env_val is not None and env_val.strip() != "":
        return env_val.strip()
    return _ENV.get(key, default)


def _get_bool(key, default=False):
    val = _get(key)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on", "sim")


def _get_int(key, default):
    try:
        return int(str(_get(key, default)).strip())
    except (TypeError, ValueError):
        return default


def get_timezone():
    """Timezone consciente com fallback seguro para BRT (UTC-3)."""
    nome = _get("TIMEZONE", "America/Sao_Paulo")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(nome)
        except Exception:
            pass
    return timezone(timedelta(hours=-3), name="BRT")


# ----------------------------------------------------------------------------
# CONFIGURACAO CENTRAL
# ----------------------------------------------------------------------------
class Settings:
    def __init__(self):
        # ------------------------------------------------------------ caminhos
        self.PROJECT_ROOT = PROJECT_ROOT
        self.DATA_DIR = (PROJECT_ROOT / _get("DATA_DIR", "data")).resolve()
        self.LOG_DIR = (PROJECT_ROOT / _get("LOG_DIR", "logs")).resolve()
        self.DB_FILE = (PROJECT_ROOT / _get("DB_FILE", "data/pending_emails.db")).resolve()
        self.BLACKLIST_FILE = (PROJECT_ROOT / _get("BLACKLIST_FILE", "data/blacklist.txt")).resolve()
        self.BASELINE_FILE = (PROJECT_ROOT / _get("BASELINE_FILE", "data/emails_unicos.txt")).resolve()
        self.MAIN_LOG = self.LOG_DIR / "sistema.log"

        # garante existencia (idempotente, cross-platform)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------ IMAP
        self.IMAP_SERVER = _get("IMAP_SERVER", "imap.secureserver.net")
        self.IMAP_PORT = _get_int("IMAP_PORT", 993)
        self.IMAP_USER = _get("IMAP_USER", "")
        self.IMAP_PASSWORD = _get("IMAP_PASSWORD", "")
        # Pastas varridas (imap_handler testa existencia antes de usar)
        self.IMAP_FOLDERS = [
            f.strip()
            for f in _get("IMAP_FOLDERS", "INBOX,Spam,Junk").split(",")
            if f.strip()
        ]

        # ------------------------------------------------------------ SMTP
        self.SMTP_SERVER = _get("SMTP_SERVER", "smtpout.secureserver.net")
        self.SMTP_PORT = _get_int("SMTP_PORT", 465)          # SSL direto
        self.SMTP_PORT_FALLBACK = _get_int("SMTP_PORT_FALLBACK", 587)  # STARTTLS
        self.SMTP_USER = _get("SMTP_USER", self.IMAP_USER)
        self.SMTP_PASSWORD = _get("SMTP_PASSWORD", self.IMAP_PASSWORD)
        self.SENDER_EMAIL = _get("SENDER_EMAIL", self.IMAP_USER)
        self.SENDER_NAME = _get("SENDER_NAME", "CP FANI - Encaminhamento Automatico")

        # ------------------------------------------------- destinos/aprovacao
        self.FINANCEIRO_EMAIL = _get("FINANCEIRO_EMAIL", "financeiro@didier.com.br")
        self.ADMIN_EMAIL = _get("ADMIN_EMAIL", self.IMAP_USER)
        # Qualquer endereco deste dominio pode Aprovar/Reprovar
        self.APPROVER_DOMAIN = _get("APPROVER_DOMAIN", "@didier.com.br").lower()
        self.APPROVAL_REMINDER_HOURS = _get_int("APPROVAL_REMINDER_HOURS", 24)
        self.APPROVAL_TIMEOUT_DAYS = _get_int("APPROVAL_TIMEOUT_DAYS", 7)

        # ------------------------------------------------------- agendamento
        self.START_DATE = self._parse_start_date()   # primeira varredura
        self.TIMEZONE = get_timezone()
        self.EXECUTION_INTERVAL_MINUTES = _get_int("EXECUTION_INTERVAL_MINUTES", 60)
        self.WEEKLY_REPORT_DAY = _get_int("WEEKLY_REPORT_DAY", 5)   # 0=dom..6=sab
        self.WEEKLY_REPORT_TIME = _get("WEEKLY_REPORT_TIME", "09:00")
        self.WEEKLY_ANALYZER_TIME = _get("WEEKLY_ANALYZER_TIME", "09:15")

        # ------------------------------------------------------------- modos
        self.DRY_RUN = _get_bool("DRY_RUN", False)
        self.LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()

        # ------------------------------------------- regras de negocio (filtros)
        # Remetentes externos ignorados no encaminhamento
        self.EXCLUDED_SENDERS = {
            "lixo@didier.com.br",          # interno (dominio tambem cobre)
            "notifications@didier.com.br", # interno (dominio tambem cobre)
            "alert@uptimerobot.com",
            "noreply_gol_seguranca@claro.com.br",
            "trocadechip.pme@claroatendimento.com.br",
            "no-reply@hetrixtools.com",
        }
        # Dominio interno: NUNCA encaminha (mas APROVA respostas dele)
        self.EXCLUDED_DOMAINS = {"@didier.com.br"}
        # Assuntos nao-financeiros (case-insensitive, com/sem acento)
        self.EXCLUDED_SUBJECT_KEYWORDS = {
            "contratacao", "contratação",
            "assinatura",
            "proposta",
            "agendamento",
            "pesquisa",
            "senha",
            "renovacao", "renovação",
            "reagendamento tecnico", "reagendamento técnico",
        }
        # Palavras que caracterizam email financeiro (captura fornecedores novos)
        self.FINANCIAL_KEYWORDS = {
            "boleto", "fatura", "nota fiscal", "nf-e", "nfs-e", "danfe",
            "cobranca", "cobrança", "2ª via", "2a via", "segunda via",
            "pagamento", "vencimento", "protesto",
        }

        # --------------------------------------------- protocolo de mensagens
        self.FORWARD_SUBJECT_PREFIX = "[CP FANI]"
        self.APPROVAL_SUBJECT_PREFIX = "APROVACAO NECESSARIA"
        self.REPORT_SUBJECT_PREFIX = "[CP FANI RELATORIO]"
        self.ANALYZER_SUBJECT_PREFIX = "[CP FANI LIXO]"
        self.APPROVAL_HEADER = "X-Didier-Approval"        # request | response
        self.APPROVAL_UUID_HEADER = "X-Didier-UUID"

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _parse_start_date():
        raw = str(_get("START_DATE", "2026-08-01")).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    def now(self):
        """Datetime corrente consciente no timezone configurado."""
        return datetime.now(self.TIMEZONE)

    @staticmethod
    def is_valid_email(text):
        """Valida formato de email (usado p/ filtrar baseline malformada)."""
        if not text:
            return False
        return bool(_EMAIL_RE.match(text.strip().lower()))

    @staticmethod
    def mask(secret):
        """Mascara credencial para logs/auto-teste."""
        secret = str(secret or "")
        if len(secret) <= 3:
            return "***"
        return secret[:2] + "*" * (len(secret) - 3) + secret[-1]

    def validate(self):
        """Retorna lista de erros de configuracao (vazia = OK)."""
        erros = []
        if not self.IMAP_USER or "@" not in self.IMAP_USER:
            erros.append("IMAP_USER ausente/invalido no .env")
        if not self.IMAP_PASSWORD:
            erros.append("IMAP_PASSWORD ausente no .env")
        if not self.SMTP_USER or not self.SMTP_PASSWORD:
            erros.append("SMTP_USER/SMTP_PASSWORD ausentes no .env")
        if not self.FINANCEIRO_EMAIL or "@" not in self.FINANCEIRO_EMAIL:
            erros.append("FINANCEIRO_EMAIL ausente/invalido no .env")
        if self.START_DATE is None:
            erros.append("START_DATE invalido (use YYYY-MM-DD)")
        return erros


# Instancia unica consumida por todos os modulos
settings = Settings()


# ----------------------------------------------------------------------------
# AUTO-TESTE: python config/settings.py
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE CONFIGURACAO")
    print("=" * 70)
    print(f"Raiz do projeto : {settings.PROJECT_ROOT}")
    print(f"Arquivo .env    : {'OK' if ENV_FILE.exists() else 'NAO ENCONTRADO'}")
    print(f"IMAP            : {settings.IMAP_USER} @ {settings.IMAP_SERVER}:{settings.IMAP_PORT} (senha: {settings.mask(settings.IMAP_PASSWORD)})")
    print(f"SMTP            : {settings.SMTP_USER} @ {settings.SMTP_SERVER}:{settings.SMTP_PORT} fallback {settings.SMTP_PORT_FALLBACK} (senha: {settings.mask(settings.SMTP_PASSWORD)})")
    print(f"Destino         : {settings.FINANCEIRO_EMAIL}")
    print(f"Aprovadores     : *{settings.APPROVER_DOMAIN}")
    print(f"Start date      : {settings.START_DATE}")
    print(f"Timezone        : {settings.TIMEZONE}")
    print(f"Pastas IMAP     : {', '.join(settings.IMAP_FOLDERS)}")
    print(f"Baseline        : {settings.BASELINE_FILE} ({'OK' if settings.BASELINE_FILE.exists() else 'NAO ENCONTRADA'})")
    print(f"Banco           : {settings.DB_FILE}")
    print(f"Blacklist       : {settings.BLACKLIST_FILE}")
    print(f"DRY_RUN         : {settings.DRY_RUN}")
    erros = settings.validate()
    print("-" * 70)
    if erros:
        print("ERROS DE CONFIGURACAO:")
        for e in erros:
            print(f"  [!] {e}")
    else:
        print("CONFIGURACAO VALIDA - pronto para os proximos modulos.")
    print("=" * 70)