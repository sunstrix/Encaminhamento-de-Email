# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/response_handler.py
==============================================================================
Fecha o ciclo de aprovacao humana:

1. Varre a INBOX buscando respostas com assunto APROVAR_<uuid> /
   REPROVAR_<uuid> (geradas pelos botoes mailto do button_handler).
2. Valida que o respondente pertence ao dominio aprovador
   (settings.APPROVER_DOMAIN = @didier.com.br) - multi-aprovadores.
3. APROVAR: adiciona o REMETENTE ORIGINAL a whitelist (lista de
   encaminhamento) e dispara forward imediato do email original
   para o financeiro.
4. REPROVAR: adiciona o REMETENTE ORIGINAL a blacklist (bloqueio
   permanente). O aprovador NUNCA eh bloqueado.
5. Idempotencia: respostas ja processadas sao gravadas no banco
   (decision RESPONSE_PROCESSED / RESPONSE_INVALID) e nunca reaplicadas.
6. sweep_pending(): lembrete apos 24h sem resposta; expiracao apos
   7 dias (vai para blacklist com motivo timeout).

Sem dependencia de rede nos auto-testes (injecao de dependencia).
==============================================================================
"""

import sys
import re
import email
from email.utils import parseaddr
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List

# --- FIX DE PATH (EXECUCAO STANDALONE) -----------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# -------------------------------------------------------------------------

from config.settings import settings
from database.database import Database, db
from src.imap_handler import IMAPHandler
from src.smtp_handler import get_smtp_handler


# Aceita "APROVAR_<uuid>" ou "REPROVAR_<uuid>" (case-insensitive)
_RE_RESPOSTA = re.compile(r'^(APROVAR|REPROVAR)_(.+)$', re.IGNORECASE)
# Remove prefixos de reply/forward que o cliente de email possa injetar
_RE_PREFIXO = re.compile(r'^(\s*(re|fwd|fw|enc)\s*:\s*)+', re.IGNORECASE)


class ResponseHandler:
    """Processa respostas de aprovacao/reprovacao e o ciclo de lembretes."""

    def __init__(self, imap: Optional[IMAPHandler] = None,
                 smtp=None,
                 database: Optional[Database] = None):
        # Injecao de dependencia: None = usa instancias reais em producao
        self.imap = imap
        self.smtp = smtp
        self.db = database or db

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _extract_email(from_header: str) -> str:
        """Extrai apenas o endereco de email do header From."""
        _, addr = parseaddr(from_header or "")
        return (addr or "").strip().lower()

    def _is_valid_approver(self, from_header: str) -> bool:
        """So membros do dominio aprovador podem Aprovar/Reprovar."""
        addr = self._extract_email(from_header)
        if not addr:
            return False
        return addr.endswith(settings.APPROVER_DOMAIN)

    @staticmethod
    def _clean_subject(subject: str) -> str:
        """Remove 'Re:', 'Fwd:', 'ENC:' etc. do inicio do assunto."""
        return _RE_PREFIXO.sub('', subject or "").strip()

    def _approval_mailto_target(self) -> str:
        """Mesmo destino usado nos botoes (definido no passo 11 via patch)."""
        return (getattr(settings, 'APPROVAL_EMAIL', None)
                or getattr(settings, 'ADMIN_EMAIL', None)
                or getattr(settings, 'IMAP_USER', ''))

    # ----------------------------------------------------------------- core
    def handle_response_from(self, from_header: str, subject: str,
                             response_message_id: str) -> Tuple[str, str]:
        """
        Valida o remetente e aplica a resposta.
        Retorna (acao, detalhe) onde acao eh:
        APROVADO | REPROVADO | INVALIDO | IGNORADO
        """
        if not self._is_valid_approver(from_header):
            return "INVALIDO", f"remetente fora do dominio aprovador: {from_header}"

        responder = self._extract_email(from_header)
        clean = self._clean_subject(subject)

        m = _RE_RESPOSTA.match(clean)
        if not m:
            return "IGNORADO", "assunto sem padrao APROVAR_/REPROVAR_"

        acao_botao, approval_uuid = m.group(1).upper(), m.group(2).strip()
        approval = self.db.get_approval(approval_uuid)

        if not approval:
            return "IGNORADO", f"uuid nao encontrado: {approval_uuid}"
        if approval["status"] != "PENDING":
            return "IGNORADO", f"aprovacao ja resolvida ({approval['status']})"

        sender_original = approval["sender"]

        if acao_botao == "APROVAR":
            # Entra na lista de encaminhamento (whitelist)
            self.db.add_whitelist(sender_original, added_by=responder,
                                  reason="aprovacao manual via botao")
            self.db.resolve_approval(approval_uuid, "APPROVED",
                                     resolved_by=responder)
            # Forward imediato do email original (best-effort)
            forwarded = self._forward_original(approval)
            return "APROVADO", f"whitelist={sender_original} forwarded={forwarded}"

        # REPROVAR: bloqueia o REMETENTE ORIGINAL, nunca o aprovador
        self.db.add_blacklist(sender_original, added_by=responder,
                              reason="reprovacao manual via botao")
        self.db.resolve_approval(approval_uuid, "REJECTED",
                                 resolved_by=responder)
        return "REPROVADO", f"blacklist={sender_original}"

    # ------------------------------------------------- forward do original
    def _forward_original(self, approval: Dict) -> bool:
        """Re-busca o email original no IMAP e encaminha ao financeiro."""
        if self.imap is None or self.smtp is None:
            return False
        try:
            if not self.imap.mail:
                if not self.imap.connect():
                    return False

            mid = approval["message_id"]
            status, data = self.imap.mail.search(
                None, 'HEADER', 'Message-ID', f'"{mid}"')
            if status != "OK" or not data[0]:
                print(f"[RESPONSE] Original nao localizado no IMAP: {mid}")
                return False

            eid = data[0].split()[0]
            status, msg_data = self.imap.mail.fetch(eid, '(RFC822)')
            if status != "OK":
                return False

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subj = IMAPHandler._decode_header_value(msg.get("Subject", ""))
            sender = IMAPHandler._decode_header_value(msg.get("From", ""))

            body = (
                "Encaminhamento automatico CP FANI (aprovado manualmente).\n"
                f"Aprovado por: {approval.get('resolved_by') or 'N/A'}\n"
                f"Remetente original: {sender}\n"
                f"Assunto original: {subj}\n\n"
                "O email original completo segue em anexo (email_original.eml)."
            )

            ok = self.smtp.send_email(
                [settings.FINANCEIRO_EMAIL],
                f"{settings.FORWARD_SUBJECT_PREFIX} {subj}",
                body,
                original_eml_bytes=raw,
            )
            if ok:
                self.db.mark_forwarded(mid, sender, subj,
                                       decision="FORWARDED",
                                       folder=approval.get("folder") or "INBOX")
            return ok
        except Exception as e:
            print(f"[RESPONSE ERRO] forward do original: {e}")
            return False

    # ------------------------------------------------------- varredura IMAP
    def _search_responses(self) -> List[bytes]:
        """Busca IDs de emails de resposta (UNSEEN + assunto magico)."""
        try:
            status, data = self.imap.mail.search(
                None,
                'OR (UNSEEN SUBJECT "APROVAR_") (UNSEEN SUBJECT "REPROVAR_")')
            if status == "OK":
                return data[0].split()
        except Exception as e:
            print(f"[RESPONSE] busca OR falhou, usando fallback: {e}")

        # Fallback: varre UNSEEN e filtra por assunto no Python
        ids = []
        status, data = self.imap.mail.search(None, "UNSEEN")
        if status != "OK":
            return ids
        for eid in data[0].split():
            st, md = self.imap.mail.fetch(eid, "(BODY[HEADER.FIELDS (SUBJECT)])")
            if st != "OK":
                continue
            hdr = md[0][1].decode("utf-8", "ignore")
            if "APROVAR_" in hdr or "REPROVAR_" in hdr:
                ids.append(eid)
        return ids

    def process_responses(self) -> Dict[str, int]:
        """Varre a caixa, aplica respostas validas e marca como lidas."""
        stats = {"aprovados": 0, "reprovados": 0, "invalidos": 0,
                 "ignorados": 0, "erros": 0}
        owns_imap = self.imap is None
        if owns_imap:
            self.imap = IMAPHandler()

        try:
            if not self.imap.mail and not self.imap.connect():
                return stats

            for eid in self._search_responses():
                try:
                    status, msg_data = self.imap.mail.fetch(eid, "(RFC822)")
                    if status != "OK":
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    mid = (msg.get("Message-ID") or "").strip()
                    from_h = IMAPHandler._decode_header_value(msg.get("From", ""))
                    subj = IMAPHandler._decode_header_value(msg.get("Subject", ""))

                    # Idempotencia: nunca reaplica resposta ja processada
                    if mid and self.db.is_forwarded(mid):
                        self.imap.mail.store(eid, '+FLAGS', '\\Seen')
                        continue

                    acao, detalhe = self.handle_response_from(from_h, subj, mid)
                    print(f"[RESPONSE] {acao}: {detalhe}")

                    decision = ("RESPONSE_PROCESSED" if acao in ("APROVADO", "REPROVADO")
                                else "RESPONSE_INVALID" if acao == "INVALIDO"
                                else "RESPONSE_IGNORED")
                    if mid:
                        self.db.mark_forwarded(mid, from_h, subj, decision=decision)

                    if acao == "APROVADO":
                        stats["aprovados"] += 1
                    elif acao == "REPROVADO":
                        stats["reprovados"] += 1
                    elif acao == "INVALIDO":
                        stats["invalidos"] += 1
                    else:
                        stats["ignorados"] += 1

                    self.imap.mail.store(eid, '+FLAGS', '\\Seen')
                except Exception as e:
                    print(f"[RESPONSE ERRO] ao processar resposta: {e}")
                    stats["erros"] += 1
        finally:
            if owns_imap and self.imap:
                self.imap.disconnect()

        return stats

    # --------------------------------------------- lembretes e expiracao
    def _send_reminder(self, row: Dict) -> bool:
        """Lembrete em texto puro com os mesmos links mailto (mesmo UUID)."""
        if self.smtp is None:
            return False
        target = self._approval_mailto_target()
        uuid = row["uuid"]
        texto = (
            "LEMBRETE - Aprovacao pendente CP FANI\n\n"
            f"Remetente: {row['sender']}\n"
            f"Assunto: {row['subject']}\n"
            f"Valor detectado: {row['amount_brl'] or 'N/A'}\n\n"
            "Clique e envie para decidir:\n"
            f"APROVAR: mailto:{target}?subject=APROVAR_{uuid}\n"
            f"REPROVAR: mailto:{target}?subject=REPROVAR_{uuid}\n\n"
            f"ID de Rastreamento: {uuid}\n"
            f"Sem resposta em {settings.APPROVAL_TIMEOUT_DAYS} dias, o remetente "
            "sera bloqueado automaticamente."
        )
        return self.smtp.send_email(
            [target],
            f"LEMBRETE: aprovacao pendente - {str(row['subject'])[:60]}",
            texto,
        )

    def sweep_pending(self) -> Dict[str, int]:
        """Lembrete apos 24h; expira (blacklist por timeout) apos 7 dias."""
        stats = {"lembretes": 0, "expirados": 0}
        now = datetime.now(timezone.utc)

        for row in self.db.get_pending_approvals(only_pending=True):
            try:
                created = datetime.fromisoformat(row["created_at"])
            except (TypeError, ValueError):
                continue
            idade = now - created

            if idade >= timedelta(days=settings.APPROVAL_TIMEOUT_DAYS):
                self.db.add_blacklist(
                    row["sender"], added_by="SYSTEM",
                    reason=f"timeout {settings.APPROVAL_TIMEOUT_DAYS}d sem resposta")
                self.db.resolve_approval(row["uuid"], "EXPIRED",
                                         resolved_by="SYSTEM", notes="timeout")
                stats["expirados"] += 1
                print(f"[RESPONSE] Expirado (timeout): {row['sender']}")
            elif (idade >= timedelta(hours=settings.APPROVAL_REMINDER_HOURS)
                  and not row["last_reminder_at"]):
                if self._send_reminder(row):
                    self.db.touch_reminder(row["uuid"])
                    stats["lembretes"] += 1
                    print(f"[RESPONSE] Lembrete enviado: {row['sender']}")

        return stats


# ----------------------------------------------------------------------------
# AUTO-TESTE (MOCKADO - SEM REDE, BANCO TEMPORARIO)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import shutil
    import tempfile
    import uuid as _uuid_mod

    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE RESPONSE_HANDLER")
    print("=" * 70)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cpfani_resp_test_"))
    test_db = Database(tmp_dir / "test.db")
    handler = ResponseHandler(imap=None, smtp=None, database=test_db)

    # --- Caso 1: APROVAR por aprovador valido (@didier.com.br)
    uuid1 = test_db.add_pending_approval(
        message_id="<orig1@test.local>", folder="INBOX", uid=None,
        sender="faturadigital@vivo.com.br", sender_name="Vivo",
        subject="Sua Fatura Digital Vivo chegou", received_at=None,
        amount_brl=9169.0, body_snippet="Fatura disponivel.")
    acao, det = handler.handle_response_from(
        "Leonardo Roscoe <leonardo@didier.com.br>", f"APROVAR_{uuid1}", "<r1@test.local>")
    assert acao == "APROVADO", f"Caso 1 falhou: {acao}"
    assert test_db.is_whitelisted("faturadigital@vivo.com.br"), "whitelist nao aplicada"
    print(f"1. ✅ APROVAR valido -> {det}")

    # --- Caso 2: Idempotencia (mesmo clique duas vezes)
    acao2, det2 = handler.handle_response_from(
        "carlos@didier.com.br", f"APROVAR_{uuid1}", "<r2@test.local>")
    assert acao2 == "IGNORADO", f"Caso 2 falhou: {acao2}"
    print(f"2. ✅ Clique duplicado ignorado -> {det2}")

    # --- Caso 3: REPROVAR bloqueia o remetente ORIGINAL, nao o aprovador
    uuid3 = test_db.add_pending_approval(
        message_id="<orig3@test.local>", folder="INBOX", uid=None,
        sender="spam@fornecedor-duvidoso.com", sender_name="Spam",
        subject="Boleto estranho", received_at=None,
        amount_brl=None, body_snippet="...")
    acao3, det3 = handler.handle_response_from(
        "marisa@didier.com.br", f"REPROVAR_{uuid3}", "<r3@test.local>")
    assert acao3 == "REPROVADO", f"Caso 3 falhou: {acao3}"
    assert test_db.is_blacklisted("spam@fornecedor-duvidoso.com"), "blacklist nao aplicada"
    assert not test_db.is_blacklisted("marisa@didier.com.br"), "aprovador foi bloqueado!"
    print(f"3. ✅ REPROVAR bloqueia remetente original -> {det3}")

    # --- Caso 4: Resposta de fora do dominio aprovador eh INVALIDA
    uuid4 = test_db.add_pending_approval(
        message_id="<orig4@test.local>", folder="INBOX", uid=None,
        sender="x@fornecedor.com", sender_name="X",
        subject="Boleto", received_at=None, amount_brl=None, body_snippet="...")
    acao4, det4 = handler.handle_response_from(
        "fulano@gmail.com", f"APROVAR_{uuid4}", "<r4@test.local>")
    assert acao4 == "INVALIDO", f"Caso 4 falhou: {acao4}"
    assert test_db.get_approval(uuid4)["status"] == "PENDING", "status mudou indevidamente"
    print(f"4. ✅ Resposta externa recusada -> {det4}")

    # --- Caso 5: Tolerancia a prefixo 'Re:' no assunto
    uuid5 = test_db.add_pending_approval(
        message_id="<orig5@test.local>", folder="INBOX", uid=None,
        sender="y@fornecedor.com", sender_name="Y",
        subject="Boleto Y", received_at=None, amount_brl=None, body_snippet="...")
    acao5, _ = handler.handle_response_from(
        "alex@didier.com.br", f"Re: APROVAR_{uuid5}", "<r5@test.local>")
    assert acao5 == "APROVADO", f"Caso 5 falhou: {acao5}"
    print("5. ✅ Prefixo 'Re:' tolerado")

    # Limpeza do banco temporario
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("-" * 70)
    print("RESPONSE_HANDLER OK - ciclo de aprovacao/reprovacao validado.")
    print("=" * 70)