# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/main.py
==============================================================================
Orquestrador principal do sistema.

Modos de operacao:
-单次 execucao (via cron): python src/main.py
- Modo continuo (daemon): python src/main.py --continuous
- Modo DRY_RUN: DRY_RUN=true python src/main.py
- Relatorio semanal: python src/main.py --weekly-report

Pipeline:
1. Conecta IMAP
2. Busca emails nao lidos
3. Aplica FilterEngine (whitelist/blacklist/keywords)
4. Para emails pendentes: gera botoes com ButtonHandler
5. Envia emails de aprovacao com SMTPHandler
6. Processa respostas com ResponseHandler
7. Cleanup de registros antigos (>90 dias)

==============================================================================
"""

import sys
import signal
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# --- FIX DE PATH (EXECUCAO STANDALONE) -----------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# -------------------------------------------------------------------------

from config.settings import settings
from database.database import db
from src.imap_handler import IMAPHandler
from src.filter_engine import FilterEngine
from src.button_handler import ButtonHandler
from src.smtp_handler import SMTPHandler
from src.response_handler import ResponseHandler


# --- CONFIGURACAO DE LOGGING -----------------------------------------------
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


# --- GRACEFUL SHUTDOWN -----------------------------------------------------
class GracefulShutdown:
    """Captura sinais de terminacao para fechar conexoes limpo."""
    
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logging.warning(f"Sinal {signum} recebido. Encerrando apos ciclo atual...")
        self.shutdown_requested = True


# --- PIPELINE PRINCIPAL ----------------------------------------------------
class CPFaníPipeline:
    """Orquestrador do pipeline de processamento de emails."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run or settings.DRY_RUN
        self.imap = IMAPHandler()
        self.filter_engine = FilterEngine(database=db)
        self.button_handler = ButtonHandler(database=db)
        self.smtp = SMTPHandler()
        self.response_handler = ResponseHandler(
            imap=self.imap, smtp=self.smtp, database=db
        )
        
        logging.info(f"Pipeline inicializado (DRY_RUN={self.dry_run})")
    
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
            logging.info("Buscando emails nao lidos...")
            emails = self.imap.fetch_unseen_emails()
            stats["emails_fetchados"] = len(emails)
            logging.info(f"Encontrados {len(emails)} emails nao lidos")
            
            # 3. Aplica filtro
            logging.info("Aplicando filtro...")
            filtered = self.filter_engine.filter_emails(emails)
            stats["emails_filtrados"] = len(filtered["encaminhar"])
            logging.info(
                f"Filtro: {len(filtered['encaminhar'])} encaminhar, "
                f"{len(filtered['pendentes'])} pendentes, "
                f"{len(filtered['bloqueados'])} bloqueados"
            )
            
            # 4. Para emails pendentes: gera botoes de aprovacao
            if filtered["pendentes"]:
                logging.info(f"Gerando botoes para {len(filtered['pendentes'])} emails...")
                for email in filtered["pendentes"]:
                    try:
                        approval = self.button_handler.create_approval_email(email)
                        stats["aprovacoes_geradas"] += 1
                        logging.debug(f"Aprovacao criada: {approval['uuid']}")
                    except Exception as e:
                        logging.error(f"Erro ao criar aprovacao: {e}")
                        stats["erros"] += 1
            
            # 5. Envia emails de aprovacao (se nao for DRY_RUN)
            if not self.dry_run:
                pending_approvals = db.get_pending_approvals(only_pending=True)
                logging.info(f"Enviando {len(pending_approvals)} emails de aprovacao...")
                for approval in pending_approvals:
                    try:
                        # Busca email original para reenviar
                        original = self._get_original_email(approval)
                        if original:
                            success = self.smtp.send_approval_request(
                                approval=approval,
                                original_email=original,
                            )
                            if success:
                                stats["emails_enviados"] += 1
                                db.mark_approval_sent(approval["uuid"])
                    except Exception as e:
                        logging.error(f"Erro ao enviar aprovacao: {e}")
                        stats["erros"] += 1
            else:
                logging.info("[DRY_RUN] Pulando envio de emails")
            
            # 6. Processa respostas (APROVAR_/REPROVAR_)
            logging.info("Processando respostas...")
            response_stats = self.response_handler.process_responses()
            stats["respostas_processadas"] = (
                response_stats["aprovados"] +
                response_stats["reprovados"] +
                response_stats["invalidos"]
            )
            logging.info(
                f"Respostas: {response_stats['aprovados']} aprovados, "
                f"{response_stats['reprovados']} reprovados, "
                f"{response_stats['invalidos']} invalidos"
            )
            
            # 7. Forward imediato de emails aprovados
            if not self.dry_run:
                self._forward_approved_emails()
            
            # 8. Cleanup de registros antigos
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
            
            # Busca por Message-ID
            emails = self.imap.search_by_message_id(mid)
            if emails:
                return emails[0]
        except Exception as e:
            logging.error(f"Erro ao buscar email original: {e}")
        return None
    
    def _forward_approved_emails(self):
        """Encaminha emails aprovados para o financeiro."""
        approved = db.get_approved_not_forwarded()
        if not approved:
            return
        
        logging.info(f"Encaminhando {len(approved)} emails aprovados...")
        for approval in approved:
            try:
                original = self._get_original_email(approval)
                if original:
                    success = self.smtp.forward_email(
                        original_email=original,
                        to_email=settings.FINANCEIRO_EMAIL,
                    )
                    if success:
                        db.mark_as_forwarded(approval["uuid"])
                        logging.info(f"Email encaminhado: {approval['subject']}")
            except Exception as e:
                logging.error(f"Erro ao encaminhar: {e}")
    
    def _cleanup_old_records(self):
        """Remove registros antigos do banco (>90 dias)."""
        try:
            cutoff = datetime.now() - timedelta(days=90)
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


# --- RELATORIO SEMANAL -----------------------------------------------------
def generate_weekly_report():
    """Gera relatorio semanal de estatisticas."""
    logging.info("Gerando relatorio semanal...")
    
    cutoff = datetime.now() - timedelta(days=7)
    stats = db.get_weekly_stats(cutoff)
    
    report = f"""
================================================================================
RELATORIO SEMANAL - CP FANI
Periodo: {cutoff:%d/%m/%Y} a {datetime.now():%d/%m/%Y}
================================================================================

RESUMO GERAL:
- Emails processados: {stats['total_emails']}
- Aprovacoes solicitadas: {stats['approvals_requested']}
- Aprovacoes aprovadas: {stats['approvals_approved']}
- Aprovacoes reprovadas: {stats['approvals_rejected']}
- Emails encaminhados: {stats['emails_forwarded']}

TOP 5 REMETENTES (WHITELIST):
{chr(10).join(f"  {i+1}. {s}: {c} emails" for i, (s, c) in enumerate(stats['top_whitelist'][:5]))}

TOP 5 REMETENTES (BLACKLIST):
{chr(10).join(f"  {i+1}. {s}: {c} emails" for i, (s, c) in enumerate(stats['top_blacklist'][:5]))}

TAXA DE APROVACAO:
  {(stats['approvals_approved'] / max(stats['approvals_requested'], 1) * 100):.1f}%

================================================================================
"""
    
    print(report)
    
    # Envia por email se nao for DRY_RUN
    if not settings.DRY_RUN:
        try:
            smtp = SMTPHandler()
            smtp.send_email(
                to=[settings.ADMIN_EMAIL],
                subject="[CP FANI] Relatorio Semanal",
                body=report,
            )
            logging.info("Relatorio enviado por email")
        except Exception as e:
            logging.error(f"Erro ao enviar relatorio: {e}")


# --- CLI -------------------------------------------------------------------
def main():
    """Entry point com parse de argumentos."""
    parser = argparse.ArgumentParser(
        description="CP FANI - Sistema de Encaminhamento de Emails"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Rodar em modo continuo (daemon)",
    )
    parser.add_argument(
        "--weekly-report",
        action="store_true",
        help="Gerar relatorio semanal",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo teste (nao envia emails)",
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
    if missing and not args.dry_run:
        logging.error(f"Campos obrigatorios faltando: {missing}")
        sys.exit(1)
    
    # Executa comando
    if args.weekly_report:
        generate_weekly_report()
    else:
        pipeline = CPfaníPipeline(dry_run=args.dry_run)
        if args.continuous:
            pipeline.run_continuous(shutdown)
        else:
            stats = pipeline.run_once()
            logging.info(f"Estatisticas finais: {stats}")
    
    logging.info("Execucao concluida")


if __name__ == "__main__":
    main()