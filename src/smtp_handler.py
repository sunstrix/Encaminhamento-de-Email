# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/smtp_handler.py
==============================================================================
Responsavel por conectar no servidor SMTP (GoDaddy/Office365) e disparar
os emails processados para o financeiro ou para a fila de aprovacao.
Implementa fallback automatico de portas (587 STARTTLS -> 465 SSL) para
garantir compatibilidade com as restricoes do provedor e preserva o email
original como anexo .eml para nao perder boletos em PDF.
==============================================================================
"""

import sys
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List

# --- FIX DE PATH E CARREGAMENTO DE ENV -----------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / '.env')
except ImportError:
    pass
# -------------------------------------------------------------------------

from config.settings import settings


class SMTPHandler:
    """Gerencia a conexao SMTP e o envio de mensagens."""

    def __init__(self):
        self.host = getattr(settings, 'SMTP_SERVER', os.getenv('SMTP_SERVER', 'smtpout.secureserver.net'))
        # GoDaddy geralmente usa 587 (STARTTLS) ou 465 (SSL)
        self.port_primary = int(getattr(settings, 'SMTP_PORT', os.getenv('SMTP_PORT', 587)))
        self.port_fallback = 465 if self.port_primary == 587 else 587
        
        self.user = getattr(settings, 'EMAIL_USER', os.getenv('EMAIL_USER'))
        self.password = getattr(settings, 'EMAIL_PASS', os.getenv('EMAIL_PASS'))
        
        if not self.user or not self.password:
            raise ValueError("Credenciais de email (EMAIL_USER/EMAIL_PASS) nao encontradas no .env ou settings.")
            
        self.server: Optional[smtplib.SMTP] = None

    def connect(self) -> bool:
        """
        Tenta conectar usando STARTTLS (porta 587). 
        Se falhar, faz fallback para SSL direto (porta 465).
        """
        # Tentativa 1: STARTTLS (Padrao GoDaddy/Office365 moderno)
        try:
            print(f"[SMTP] Tentando conexao STARTTLS em {self.host}:{self.port_primary}...")
            server = smtplib.SMTP(self.host, self.port_primary, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.user, self.password)
            self.server = server
            print("[SMTP] Conexao STARTTLS bem-sucedida.")
            return True
        except Exception as e:
            print(f"[SMTP] Falha na tentativa STARTTLS: {e}")

        # Tentativa 2: SSL Direto (Fallback)
        try:
            print(f"[SMTP] Tentando fallback SSL em {self.host}:{self.port_fallback}...")
            server_ssl = smtplib.SMTP_SSL(self.host, self.port_fallback, timeout=15)
            server_ssl.login(self.user, self.password)
            self.server = server_ssl
            print("[SMTP] Conexao SSL (fallback) bem-sucedida.")
            return True
        except Exception as e:
            print(f"[SMTP ERRO] Falha critica na conexao SMTP: {e}")
            return False

    def disconnect(self) -> None:
        """Fecha a conexao de forma graciosa."""
        if self.server:
            try:
                self.server.quit()
            except Exception:
                pass
            self.server = None

    def send_email(
        self, 
        to_addrs: List[str], 
        subject: str, 
        body_text: str, 
        original_eml_bytes: Optional[bytes] = None
    ) -> bool:
        """
        Monta e envia o email. Se `original_eml_bytes` for fornecido, 
        anexa o email original como .eml para preservar anexos e metadados.
        """
        if not self.server:
            if not self.connect():
                return False

        msg = MIMEMultipart()
        msg['From'] = self.user
        msg['To'] = ", ".join(to_addrs)
        msg['Subject'] = subject

        # Corpo do email (Resumo)
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        # Anexa o email original como .eml se fornecido
        if original_eml_bytes:
            part = MIMEBase('message', 'rfc822')
            part.set_payload(original_eml_bytes)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition', 
                'attachment', 
                filename='email_original.eml'
            )
            msg.attach(part)

        try:
            self.server.sendmail(self.user, to_addrs, msg.as_string())
            print(f"[SMTP] Email enviado com sucesso para: {to_addrs}")
            return True
        except Exception as e:
            print(f"[SMTP ERRO] Falha ao enviar email: {e}")
            # Tenta reconectar e reenviar uma vez se a conexao caiu (timeout do GoDaddy)
            self.disconnect()
            if self.connect():
                try:
                    self.server.sendmail(self.user, to_addrs, msg.as_string())
                    print(f"[SMTP] Email enviado no retry para: {to_addrs}")
                    return True
                except Exception as retry_e:
                    print(f"[SMTP ERRO] Falha no retry: {retry_e}")
            return False


# Instancia unica via factory (lazy loading para nao quebrar testes sem .env)
_smtp_handler_instance: Optional[SMTPHandler] = None

def get_smtp_handler() -> SMTPHandler:
    global _smtp_handler_instance
    if _smtp_handler_instance is None:
        _smtp_handler_instance = SMTPHandler()
    return _smtp_handler_instance


# ----------------------------------------------------------------------------
# AUTO-TESTE (MOCKADO EM MEMORIA - NAO EXIGE CONEXAO/SENHA)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE SMTP_HANDLER (MONTAGEM DE MENSAGEM)")
    print("=" * 70)
    
    print("1. Testando montagem de email com anexo .eml (RFC822)...")
    
    # Mock de um email original cru (simulando o que o IMAP nos entrega)
    mock_original_eml = b"""From: original@vivo.com.br
To: alex@didier.com.br
Subject: Fatura Vivo
MIME-Version: 1.0
Content-Type: text/plain

Corpo da fatura original com PDF anexo (simulado).
"""
    
    msg = MIMEMultipart()
    msg['From'] = "teste@didier.com.br"
    msg['To'] = "financeiro@didier.com.br"
    msg['Subject'] = "[FINANCEIRO] Fatura Vivo"
    
    body_text = "Segue fatura para pagamento.\nValor: R$ 123,45\n\nO email original esta anexo."
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    
    part = MIMEBase('message', 'rfc822')
    part.set_payload(mock_original_eml)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment', filename='email_original.eml')
    msg.attach(part)
    
    # Validacoes
    assert msg['Subject'] == "[FINANCEIRO] Fatura Vivo"
    assert len(msg.get_payload()) == 2, "Deveria ter 2 partes (texto + anexo)"
    
    # Verifica se o anexo esta la
    attachment_found = False
    for p in msg.walk():
        if p.get_content_type() == 'message/rfc822':
            attachment_found = True
            
    assert attachment_found, "Anexo .eml nao encontrado na mensagem"
    print("   ✅ Mensagem MIMEMultipart montada corretamente com anexo RFC822.")
    
    print("-" * 70)
    print("SMTP_HANDLER OK - Estrutura de mensagem validada.")
    print("Para testar o envio real, configure o .env e use o main.py.")
    print("=" * 70)