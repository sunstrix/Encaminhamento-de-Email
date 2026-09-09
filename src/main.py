# -*- coding: utf-8 -*-
"""
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/main.py
Orquestrador principal do sistema.

Correções Qwen (Fase 3 - Bugs Críticos):
- Remoção da chamada fantasma `filter_emails` (o IMAPHandler já filtra e retorna a decisão).
- Correção do loop de processamento para usar a chave `decision` retornada pelo IMAP.
- Remoção de qualquer injeção manual de `settings.BLACKLIST_SENDERS` (FilterEngine gerencia via arquivo).
- Encaminhamento imediato de emails com decision FORWARD para o financeiro.
- Integração robusta com ResponseHandler para processar APROVAR_/REPROVAR_.
"""
import sys
import time
import signal
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# -----------------------------------------------------------------------------
# FIX DE PATH (EXECUCAO STANDALONE)
# -----------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# -----------------------------------------------------------------------------

from config.settings import settings
from database.database import db
from src.imap_handler import IMAPHandler
from src.filter_engine import FilterEngine
from src.button_handler import ButtonHandler
from src.smtp_handler import SMTPHandler
from src.response_handler import ResponseHandler

# -----------------------------------------------------------------------------
# CONFIGURACAO DE LOGGING
# -----------------------------------------------------------------------------
def setup_logging():
    """Configura logging estruturado (console + arquivo)."""
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = settings.LOG_DIR / f"cpfani_{datetime.now():%Y%m%d}.log"
    
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Reduz verbosidade de libs externas
    logging.getLogger("imaplib").setLevel(logging.WARNING)
    logging.getLogger("smtplib").setLevel(logging.WARNING)

# -----------------------------------------------------------------------------
# GRACEFUL SHUTDOWN
# -----------------------------------------------------------------------------
class GracefulShutdown:
    """Captura sinais de terminacao para fechar conexoes limpo."""
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logging.warning(f"Sinal {signum} recebido. Encerrando apos ciclo atual...")
        self.shutdown_requested = True

# -----------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# -----------------------------------------------------------------------------
class CPFaniPipeline:
    """Orquestrador do pipeline de processamento de emails."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run or settings.DRY_RUN
        self.imap = IMAPHandler()
        # FilterEngine e ButtonHandler nao aceitam 'database' no __init__
        self.filter_engine = FilterEngine()
        self.button_handler = ButtonHandler()
        self.smtp = SMTPHandler()
        self.response_handler = ResponseHandler(
            imap=self.imap, smtp=self.smtp, database=db
        )
        logging.info(f"Pipeline inicializado (DRY_RUN={self.dry_run})")

    def test_connection(self) -> bool:
        """Testa conexões IMAP e SMTP e retorna True se ambas funcionarem."""
        success = True
        
        # Teste IMAP
        try:
            logging.info("Testando conexão IMAP...")
            if self.imap.connect():
                logging.info("✅ IMAP: Conexão bem-sucedida.")
                self.imap.disconnect()
            else:
                logging.error("❌ IMAP: Falha na conexão.")
                success = False
        except Exception as e:
            logging.error(f"❌ IMAP: Erro inesperado - {e}")
            success = False

        # Teste SMTP
        try:
            logging.info("Testando conexão SMTP...")
            import smtplib
            with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=10) as server:
                if settings.SMTP_PORT == 587:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASS)
                logging.info("✅ SMTP: Conexão e autenticação bem-sucedidas.")
        except Exception as e:
            logging.error(f"❌ SMTP: Erro na conexão ou autenticação - {e}")
            success = False
            
        return success

    def run_once(self) -> Dict[str, int]:
        """Executa o pipeline uma vez. Retorna estatisticas."""
        stats = {
            "emails_fetchados": 0,
            "emails_filtrados": 0,
            "aprovacoes_geradas": 0,
            "emails_enviados": 0,
            "respostas_processadas": 0,
            "erros": 0,
        }

        try:
            # 1. Conecta IMAP
            if not self.imap.connect():
                logging.error("Falha ao conectar IMAP")
                stats["erros"] += 1
                return stats

            # 2. Busca emails nao lidos 
            # O IMAPHandler já aplica o FilterEngine internamente e retorna a decisão.
            logging.info("Buscando e filtrando emails nao lidos...")
            emails = self.imap.fetch_and_process(search_criteria="UNSEEN", dry_run=self.dry_run)
            stats["emails_fetchados"] = len(emails)
            logging.info(f"Encontrados {len(emails)} emails nao lidos")

            # 3. Separa emails por decisão (CORREÇÃO DO BUG filter_emails)
            encaminhar = []
            pendentes = []
            bloqueados = []

            for email_data in emails:
                decision = email_data.get("decision")
                if decision == "FORWARD":
                    encaminhar.append(email_data)
                elif decision == "PENDING_APPROVAL":
                    pendentes.append(email_data)
                else: # SKIP_*
                    bloqueados.append(email_data)
                    
                # Marca como lido se não for dry run e não for PENDING_APPROVAL
                if not self.dry_run and decision != "PENDING_APPROVAL":
                    self.imap.mark_as_seen(email_data.get("imap_id"))

            stats["emails_filtrados"] = len(encaminhar) + len(pendentes)
            logging.info(
                f"Filtro: {len(encaminhar)} encaminhar, "
                f"{len(pendentes)} pendentes, "
                f"{len(bloqueados)} bloqueados"
            )

            # 4. Para emails pendentes: gera botoes de aprovacao e salva no DB
            if pendentes:
                logging.info(f"Gerando botoes para {len(pendentes)} emails...")
                for email_data in pendentes:
                    try:
                        approval = self.button_handler.create_approval_email(email_data)
                        stats["aprovacoes_geradas"] += 1
                        logging.debug(f"Aprovacao criada: {approval.get('uuid')}")
                        
                        if not self.dry_run:
                            db.add_pending_approval(
                                message_id=email_data.get("message_id"),
                                folder="INBOX",
                                uid=None,
                                sender=email_data.get("from", ""),
                                sender_name="",
                                subject=email_data.get("subject", ""),
                                received_at=email_data.get("date"),
                                amount_brl=email_data.get("amount"),
                                body_snippet=email_data.get("body", "")[:500]
                            )
                    except Exception as e:
                        logging.error(f"Erro ao criar aprovacao: {e}")
                        stats["erros"] += 1

            # 5. Encaminhamento IMEDIATO de emails aprovados pelo filtro (FORWARD)
            if not self.dry_run and encaminhar:
                logging.info(f"Encaminhando {len(encaminhar)} emails diretos para o financeiro...")
                for email_data in encaminhar:
                    try:
                        original_bytes = self.imap.search_by_message_id(email_data.get("message_id"))
                        if original_bytes:
                            # Tenta usar forward_email se existir, senão send_email
                            if hasattr(self.smtp, 'forward_email'):
                                success = self.smtp.forward_email(
                                    original_email={"bytes": original_bytes, "subject": email_data.get("subject")},
                                    to_email=settings.FINANCEIRO_EMAIL,
                                )
                            else:
                                success = self.smtp.send_email(
                                    to_addrs=[settings.FINANCEIRO_EMAIL],
                                    subject=f"{settings.FORWARD_SUBJECT_PREFIX} {email_data.get('subject', '')}",
                                    body_text="Encaminhado automaticamente pelo sistema CP FANI.",
                                    original_eml_bytes=original_bytes
                                )
                            if success:
                                stats["emails_enviados"] += 1
                                db.mark_forwarded(
                                    message_id=email_data.get("message_id"),
                                    sender=email_data.get("from", ""),
                                    subject=email_data.get("subject", ""),
                                    decision="FORWARDED"
                                )
                    except Exception as e:
                        logging.error(f"Erro ao encaminhar email direto: {e}")
                        stats["erros"] += 1

            # 6. Envia emails de aprovacao pendentes do DB (se nao for DRY_RUN)
            if not self.dry_run:
                pending_approvals = db.get_pending_approvals(only_pending=True)
                # Filtra apenas os que ainda não tiveram o email de solicitação enviado
                to_send = [a for a in pending_approvals if not a.get("last_reminder_at")]
                
                if to_send:
                    logging.info(f"Enviando {len(to_send)} emails de solicitacao de aprovacao...")
                    for approval in to_send:
                        try:
                            original = self._get_original_email(approval)
                            if original:
                                if hasattr(self.smtp, 'send_approval_request'):
                                    success = self.smtp.send_approval_request(
                                        approval=approval,
                                        original_email=original,
                                    )
                                else:
                                    success = self.smtp.send_email(
                                        to_addrs=[settings.APPROVAL_EMAIL],
                                        subject=f"[CP FANI] APROVAÇÃO: {approval.get('subject', '')}",
                                        body_text=f"Por favor, responda com APROVAR_ ou REPROVAR_.\n\nDetalhes:\n{approval}",
                                        original_eml_bytes=original.get("bytes") if isinstance(original, dict) else original
                                    )
                                if success:
                                    stats["emails_enviados"] += 1
                                    db.mark_approval_sent(approval["uuid"])
                        except Exception as e:
                            logging.error(f"Erro ao enviar aprovacao: {e}")
                            stats["erros"] += 1
            else:
                logging.info("[DRY_RUN] Pulando envio de emails")

            # 7. Processa respostas (APROVAR_/REPROVAR_)
            logging.info("Processando respostas de aprovação...")
            try:
                response_stats = self.response_handler.process_responses()
                stats["respostas_processadas"] = (
                    response_stats.get("aprovados", 0) +
                    response_stats.get("reprovados", 0) +
                    response_stats.get("invalidos", 0)
                )
                logging.info(
                    f"Respostas: {response_stats.get('aprovados', 0)} aprovados, "
                    f"{response_stats.get('reprovados', 0)} reprovados, "
                    f"{response_stats.get('invalidos', 0)} invalidos"
                )
            except Exception as e:
                logging.error(f"Erro ao processar respostas: {e}")
                stats["erros"] += 1

            # 8. Forward de emails que foram APROVADOS via resposta (status APPROVED no DB)
            if not self.dry_run:
                self._forward_approved_emails()

            # 9. Cleanup de registros antigos
            self._cleanup_old_records()

        except Exception as e:
            logging.error(f"Erro no pipeline: {e}", exc_info=True)
            stats["erros"] += 1
        finally:
            self.imap.disconnect()

        return stats

    def _get_original_email(self, approval: Dict) -> Optional[Dict]:
        """Re-busca email original do IMAP via Message-ID."""
        try:
            mid = approval.get("message_id")
            if not mid:
                return None
            
            if hasattr(self.imap, 'search_by_message_id'):
                raw_bytes = self.imap.search_by_message_id(mid)
                if raw_bytes:
                    return {"bytes": raw_bytes, "message_id": mid, "subject": approval.get("subject")}
            
            logging.warning(
                f"IMAPHandler nao possui 'search_by_message_id' ou email não encontrado. "
                f"Message-ID: {mid}"
            )
            return None
        except Exception as e:
            logging.error(f"Erro ao buscar email original: {e}")
        return None

    def _forward_approved_emails(self):
        """Encaminha emails aprovados (via resposta) para o financeiro."""
        try:
            approved = db.get_approved_not_forwarded()
            if not approved:
                return

            logging.info(f"Encaminhando {len(approved)} emails aprovados para o financeiro...")
            for approval in approved:
                try:
                    original = self._get_original_email(approval)
                    if original:
                        if hasattr(self.smtp, 'forward_email'):
                            success = self.smtp.forward_email(
                                original_email=original,
                                to_email=settings.FINANCEIRO_EMAIL,
                            )
                        else:
                            success = self.smtp.send_email(
                                to_addrs=[settings.FINANCEIRO_EMAIL],
                                subject=f"{settings.FORWARD_SUBJECT_PREFIX} {approval.get('subject', '')}",
                                body_text="Encaminhado após aprovação humana.",
                                original_eml_bytes=original.get("bytes") if isinstance(original, dict) else original
                            )
                            
                        if success:
                            db.mark_as_forwarded(approval["uuid"])
                            logging.info(f"Email encaminhado: {approval.get('subject')}")
                except Exception as e:
                    logging.error(f"Erro ao encaminhar: {e}")
        except Exception as e:
            logging.error(f"Erro no método _forward_approved_emails: {e}")

    def _cleanup_old_records(self):
        """Remove registros antigos do banco (>90 dias)."""
        try:
            cutoff = datetime.now() - timedelta(days=90)
            if hasattr(db, 'cleanup_old_approvals'):
                deleted = db.cleanup_old_approvals(cutoff)
                if deleted > 0:
                    logging.info(f"Cleanup: {deleted} registros removidos (>90 dias)")
        except Exception as e:
            logging.error(f"Erro no cleanup: {e}")

    def run_continuous(self, shutdown: GracefulShutdown):
        """Roda em modo continuo (daemon) com polling."""
        interval = settings.POLL_INTERVAL_MINUTES * 60
        logging.info(f"Modo continuo iniciado (intervalo: {settings.POLL_INTERVAL_MINUTES}min)")
        
        while not shutdown.shutdown_requested:
            stats = self.run_once()
            logging.info(
                f"Ciclo concluido: {stats['emails_fetchados']} fetchados, "
                f"{stats['aprovacoes_geradas']} aprovacoes, "
                f"{stats['respostas_processadas']} respostas"
            )
            # Aguarda proximo ciclo (com verificacao de shutdown)
            for _ in range(interval):
                if shutdown.shutdown_requested:
                    break
                time.sleep(1)
                
        logging.info("Shutdown completo")

# -----------------------------------------------------------------------------
# RELATORIO SEMANAL
# -----------------------------------------------------------------------------
def generate_weekly_report():
    """Gera relatorio semanal de estatisticas."""
    logging.info("Gerando relatorio semanal...")
    cutoff = datetime.now() - timedelta(days=7)
    
    if hasattr(db, 'get_weekly_stats'):
        stats = db.get_weekly_stats(cutoff)
    else:
        logging.warning("Método get_weekly_stats não implementado. Usando dados vazios.")
        stats = {
            "total_emails": 0, "approvals_requested": 0, "approvals_approved": 0,
            "approvals_rejected": 0, "emails_forwarded": 0, "top_whitelist": [], "top_blacklist": []
        }

    report = f"""
================================================================================
RELATORIO SEMANAL - CP FANI
Periodo: {cutoff:%d/%m/%Y} a {datetime.now():%d/%m/%Y}

RESUMO GERAL:
Emails processados: {stats['total_emails']}
Aprovacoes solicitadas: {stats['approvals_requested']}
Aprovacoes aprovadas: {stats['approvals_approved']}
Aprovacoes reprovadas: {stats['approvals_rejected']}
Emails encaminhados: {stats['emails_forwarded']}

TOP 5 REMETENTES (WHITELIST):
{chr(10).join(f"  {i+1}. {s}: {c} emails" for i, (s, c) in enumerate(stats.get('top_whitelist', [])[:5]))}

TOP 5 REMETENTES (BLACKLIST):
{chr(10).join(f"  {i+1}. {s}: {c} emails" for i, (s, c) in enumerate(stats.get('top_blacklist', [])[:5]))}

TAXA DE APROVACAO:
{(stats['approvals_approved'] / max(stats['approvals_requested'], 1) * 100):.1f}%
"""
    print(report)
    
    # Envia por email se nao for DRY_RUN
    if not settings.DRY_RUN:
        try:
            smtp = SMTPHandler()
            if hasattr(smtp, 'send_email'):
                smtp.send_email(
                    to_addrs=[settings.ADMIN_EMAIL],
                    subject="[CP FANI] Relatorio Semanal",
                    body_text=report,
                )
            logging.info("Relatorio enviado por email")
        except Exception as e:
            logging.error(f"Erro ao enviar relatorio: {e}")

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main():
    """Entry point com parse de argumentos."""
    parser = argparse.ArgumentParser(
        description="CP FANI - Sistema de Encaminhamento de Emails"
    )
    parser.add_argument(
        "--continuous", action="store_true", help="Rodar em modo continuo (daemon)",
    )
    parser.add_argument(
        "--weekly-report", action="store_true", help="Gerar relatorio semanal",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Modo teste (nao envia emails)",
    )
    parser.add_argument(
        "--test-connection", action="store_true", help="Testar conexões IMAP e SMTP e sair",
    )
    
    args = parser.parse_args()

    # Setup
    setup_logging()
    shutdown = GracefulShutdown()
    
    logging.info("=" * 70)
    logging.info("CP FANI - Sistema de Encaminhamento de Emails")
    logging.info("=" * 70)
    logging.info(f"Config: {settings.summary()}")

    # Valida credenciais
    missing = settings.validate()
    if missing and not args.dry_run and not args.test_connection:
        logging.error(f"Campos obrigatorios faltando: {missing}")
        sys.exit(1)

    # Executa comando
    if args.test_connection:
        logging.info("Executando teste de conexão...")
        pipeline = CPFaniPipeline(dry_run=True)
        success = pipeline.test_connection()
        sys.exit(0 if success else 1)
    elif args.weekly_report:
        generate_weekly_report()
    else:
        pipeline = CPFaniPipeline(dry_run=args.dry_run)
        if args.continuous:
            pipeline.run_continuous(shutdown)
        else:
            stats = pipeline.run_once()
            logging.info(f"Estatisticas finais: {stats}")
            
    logging.info("Execucao concluida")

if __name__ == "__main__":
    main()