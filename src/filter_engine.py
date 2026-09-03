# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/filter_engine.py
==============================================================================
Motor de classificacao de emails. Aplica as regras de negocio definidas
no relatorio original (emails_filtrados.txt) para decidir se um email
deve ser encaminhado, ignorado ou enviado para aprovacao humana.

Regras de Exclusao (Filtro Original):
- Dominios internos (@didier.com.br)
- Remetentes de ruido (uptime, noreply_gol, trocadechip, etc.)
- Palavras-chave no assunto (pesquisa, senha, agendamento, proposta, etc.)

Regras de Aprovacao (Novo):
- Se o email contiver valor financeiro (R$) acima de um limite configuravel,
  gera um PENDING_APPROVAL em vez de encaminhar direto.
==============================================================================
"""

import sys
from pathlib import Path

# --- FIX DE PATH (EXECUCAO STANDALONE) -----------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# -------------------------------------------------------------------------

import re
import unicodedata
from email.utils import parseaddr
from typing import Tuple, Optional, List, Dict

from config.settings import settings
from database.database import db


class FilterEngine:
    """Classifica emails em FORWARD, SKIP_* ou PENDING_APPROVAL."""

    # Dominios que NUNCA devem ser encaminhados (internos)
    EXCLUDED_DOMAINS = [
        "@didier.com.br",
    ]

    # Remetentes exatos que geram ruido (monitoramento, spam de operadora)
    EXCLUDED_SENDERS = [
        "lixo@didier.com.br",
        "notifications@didier.com.br",
        "alert@uptimerobot.com",
        "noreply_gol_seguranca@claro.com.br",
        "trocadechip.pme@claroatendimento.com.br",
        "no-reply@hetrixtools.com",
        "supervisoras@didier.com.br",
        "boleto.vivo@smtplw-09.com",
        "boleto.vivo@smtplw-13.com",
        "boleto.vivo@smtplw-05.com",
    ]

    # Palavras-chave que, se estiverem no ASSUNTO, indicam ruido.
    # Normalizamos (sem acento, minusculo) antes de comparar.
    EXCLUDED_SUBJECT_KEYWORDS = [
        "contratacao", "contratando", "contrata",
        "assinatura", "assinar documento",
        "proposta",
        "agendamento", "reagendamento",
        "pesquisa",
        "senha", "autenticacao", "codigo de verificacao", "codigo para autenticacao",
        "renovacao",
        "termo de quitacao",
        "fatura resumida",
        "cancelamento de servicos",
        "devolucao de equipamentos",
        "monitor is down", "monitor is up",
        "seu boletim",  # boletim periodico do odoo/CP FANI
        "undeliverable",
        "resposta automatica",
        "time backoffice",
    ]

    # Regex para capturar valores monetarios no formato brasileiro
    # Captura "R$ 1.234,56", "1.234,56", "R$1234,56", "1234,56"
    _RE_BRL = re.compile(
        r"(?:R\$\s*|brl\s*|reais\s*)?([\d][\d\.]*),(\d{2})(?:\s*(?:reais|brl))?",
        re.IGNORECASE
    )

    def __init__(self):
        self._baseline_emails = set()
        self._baseline_names = set()
        self._load_baseline()

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _normalize(text: str) -> str:
        """Remove acentos, passa para minusculo e strip."""
        if not text:
            return ""
        # NFD e remove nao-ASCII (acentos)
        nfkd = unicodedata.normalize('NFKD', text)
        ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
        return ascii_text.lower().strip()

    def _load_baseline(self) -> None:
        """Carrega a lista de emails/nomes unicos (baseline curada manualmente)."""
        # Fallback caso a constante nao exista no settings.py
        baseline_path = getattr(settings, 'BASELINE_FILE', None)
        if not baseline_path:
            baseline_path = Path(getattr(settings, 'DATA_DIR', 'data')) / "emails_unicos.txt"
        else:
            baseline_path = Path(baseline_path)
            
        if not baseline_path.exists():
            print(f"[WARN] Baseline nao encontrada: {baseline_path}")
            return
        
        with open(baseline_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().strip('"').strip()
                if not line or line.startswith("=") or "Total de emails" in line:
                    continue
                
                # Tenta extrair email se estiver no formato "Nome <email>" ou "<email>"
                name, email = parseaddr(line)
                if email and "@" in email:
                    self._baseline_emails.add(email.lower())
                else:
                    # Se nao for email valido, trata como nome de remetente
                    # (ex: "prefeitura municipal de eldorado do sul", "cra-mg")
                    norm = self._normalize(line)
                    if norm:
                        self._baseline_names.add(norm)

    # ------------------------------------------------------------------ parser
    @staticmethod
    def extract_sender_info(from_header: str) -> Tuple[str, str]:
        """Extrai nome e email do header From."""
        if not from_header:
            return "", ""
        name, email = parseaddr(from_header)
        return name.strip(), email.strip().lower()

    def extract_amounts(self, text: str) -> List[float]:
        """Extrai todos os valores em R$ encontrados no texto."""
        if not text:
            return []
        
        amounts = []
        for match in self._RE_BRL.finditer(text):
            try:
                # Grupo 1: parte inteira (com pontos), Grupo 2: centavos
                int_part = match.group(1).replace(".", "")
                dec_part = match.group(2)
                val = float(f"{int_part}.{dec_part}")
                if val > 0:
                    amounts.append(val)
            except ValueError:
                continue
        
        # Remove duplicatas mantendo ordem
        return list(dict.fromkeys(amounts))

    # ------------------------------------------------------------------ core
    def evaluate(
        self, 
        from_header: str, 
        subject: str, 
        body: str,
        message_id: str = ""
    ) -> Tuple[str, str, Optional[float]]:
        """
        Avalia o email e retorna (decisao, motivo, valor_maximo).
        Decisoes: 
          - FORWARD (encaminhar direto)
          - SKIP_INTERNAL (dominio @didier.com.br)
          - SKIP_BLACKLIST (remetente na blacklist do DB)
          - SKIP_SENDER (remetente na lista de exclusao)
          - SKIP_SUBJECT (palavra-chave bloqueada no assunto)
          - PENDING_APPROVAL (valor alto requer aprovacao humana)
        """
        sender_name, sender_email = self.extract_sender_info(from_header)
        
        # 1. Blacklist do DB (tem prioridade maxima)
        if db.is_blacklisted(sender_email):
            return "SKIP_BLACKLIST", f"Remetente na blacklist: {sender_email}", None

        # 2. Whitelist do DB (passa direto, ignora filtro de assunto/valor)
        if db.is_whitelisted(sender_email):
            amounts = self.extract_amounts(body)
            max_val = max(amounts) if amounts else None
            return "FORWARD", "Remetente na whitelist", max_val

        # 3. Dominio interno
        if any(sender_email.endswith(domain) for domain in self.EXCLUDED_DOMAINS if sender_email):
            return "SKIP_INTERNAL", f"Dominio interno: {sender_email}", None

        # 4. Remetente na lista de exclusao (ruido conhecido)
        if sender_email in self.EXCLUDED_SENDERS:
            return "SKIP_SENDER", f"Remetente excluido: {sender_email}", None

        # 5. Filtro de Assunto (palavras-chave de ruido)
        norm_subject = self._normalize(subject)
        for kw in self.EXCLUDED_SUBJECT_KEYWORDS:
            if kw in norm_subject:
                return "SKIP_SUBJECT", f"Assunto bloqueado (keyword '{kw}')", None
        
        # Verifica tambem se a palavra-chave esta no nome do remetente (ex: "Vivo Pesquisa")
        norm_sender_name = self._normalize(sender_name)
        # "pesquisa" no nome do remetente tambem eh ruido
        if "pesquisa" in norm_sender_name or "uptimerobot" in norm_sender_name:
             return "SKIP_SENDER", f"Nome do remetente bloqueado: {sender_name}", None

        # 6. Extrai valores financeiros
        full_text = f"{subject}\n{body}"
        amounts = self.extract_amounts(full_text)
        max_amount = max(amounts) if amounts else None

        # 7. Regra de Aprovacao (valor alto)
        threshold = getattr(settings, 'APPROVAL_THRESHOLD_BRL', 5000.0)
        if max_amount is not None and max_amount >= threshold:
            return "PENDING_APPROVAL", f"Valor R$ {max_amount:.2f} >= limite de aprovacao", max_amount

        # 8. Passou em tudo -> FORWARD
        return "FORWARD", "Aprovado pelas regras de filtro", max_amount

    def get_baseline_stats(self) -> Dict[str, int]:
        """Retorna estatisticas da baseline carregada."""
        return {
            "emails": len(self._baseline_emails),
            "names": len(self._baseline_names),
        }


# Instancia unica
filter_engine = FilterEngine()


# ----------------------------------------------------------------------------
# AUTO-TESTE
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE FILTER_ENGINE")
    print("=" * 70)
    
    stats = filter_engine.get_baseline_stats()
    print(f"Baseline carregada: {stats['emails']} emails, {stats['names']} nomes.")
    print("-" * 70)
    
    # Casos de teste baseados no historico real (emails_filtrados.txt)
    test_cases = [
        {
            "desc": "Fatura Claro (Deve encaminhar)",
            "from": "Fatura Claro <faturadigital@minhaclaro.com.br>",
            "subject": "Sua Fatura Digital Claro chegou",
            "body": "Sua fatura esta disponivel. Valor: R$ 1.234,56.",
            "expected": "FORWARD"
        },
        {
            "desc": "Vivo Pesquisa (Deve excluir por nome)",
            "from": "Vivo Pesquisa <vivo@pesquisa.vivo.com.br>",
            "subject": "Ola ARPEL, podemos contar com voce?",
            "body": "Responda nossa pesquisa.",
            "expected": "SKIP_SENDER"
        },
        {
            "desc": "UptimeRobot (Deve excluir por remetente)",
            "from": "UptimeRobot <alert@uptimerobot.com>",
            "subject": "Monitor is DOWN: 14120 - CLARO",
            "body": "O monitor caiu.",
            "expected": "SKIP_SENDER"
        },
        {
            "desc": "Interno Didier (Deve excluir por dominio)",
            "from": "Alex Nogueira <alex@didier.com.br>",
            "subject": "Fwd: Sua Fatura Digital Vivo chegou",
            "body": "Encaminhando a fatura.",
            "expected": "SKIP_INTERNAL"
        },
        {
            "desc": "Assunto Bloqueado (Deve excluir por palavra-chave)",
            "from": "RH <rh@empresa.com.br>",
            "subject": "Renovação de Assinatura: Microsoft 365",
            "body": "Por favor, renove.",
            "expected": "SKIP_SUBJECT"
        },
        {
            "desc": "Valor Alto (Deve exigir aprovacao)",
            "from": "Vivo Cobranças <cobrancas@vivo.com.br>",
            "subject": "Confirmação de NFe",
            "body": "Loja Vivo: Confirmação de NFe NSF COSMETICOS E PRESENTES LTDA - Valor: R$ 9.169,00",
            "expected": "PENDING_APPROVAL"
        },
        {
            "desc": "Comptar Boleto (Deve encaminhar)",
            "from": "Comptar - Gestão de Inventários",
            "subject": "Boleto COMPTAR",
            "body": "Segue boleto.",
            "expected": "FORWARD"
        }
    ]
    
    passed = 0
    for tc in test_cases:
        decision, reason, amount = filter_engine.evaluate(
            tc["from"], tc["subject"], tc["body"]
        )
        status = "✅" if decision == tc["expected"] else "❌"
        if decision == tc["expected"]:
            passed += 1
            
        val_str = f" (R$ {amount:.2f})" if amount else ""
        print(f"{status} {tc['desc']}")
        print(f"   Esperado: {tc['expected']} | Obtido: {decision}{val_str}")
        print(f"   Motivo: {reason}")
        print()

    print("-" * 70)
    print(f"Resultado: {passed}/{len(test_cases)} testes passaram.")
    if passed == len(test_cases):
        print("FILTER_ENGINE OK - pronto para os proximos modulos.")
    else:
        print("⚠️  ALGUNS TESTES FALHARAM - revisar regras.")
    print("=" * 70)