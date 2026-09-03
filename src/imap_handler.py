# -- coding: utf-8 --
"""
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/imap_handler.py
Responsavel por conectar no servidor IMAP (GoDaddy/Office365), buscar
emails nao lidos (ou recentes), fazer o parse robusto (decodificacao de
headers e extracao de corpo multipart) e entregar para o FilterEngine.

Refatoracao Qwen (Fase 1):
- Fix #3: Fetch com (BODY.PEEK[]) para evitar marcacao automatica de leitura.
- Fix #4: Remocao do store('\Seen') cego e adicao de mark_as_seen() seletivo.
- Fix #7: Aplicacao do filtro START_DATE no search_criteria do IMAP.
"""
import sys
import os
import imaplib
import email
from email.header import decode_header
from pathlib import Path
from typing import List, Dict, Optional

# --- FIX DE PATH E CARREGAMENTO DE ENV -----------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Garante que o .env seja lido antes de qualquer acesso a os.getenv
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / '.env')
except ImportError:
    pass  # Se nao tiver python-dotenv, confia que o main.py ou o settings ja carregou
# -------------------------------------------------------------------------

from config.settings import settings
from src.filter_engine import filter_engine


class IMAPHandler:
    """Gerencia a conexao IMAP e o parse de mensagens."""

    def __init__(self):
        # Tenta pegar do settings, senao pega direto do os.environ (.env)
        self.server = getattr(settings, 'IMAP_SERVER', os.getenv('IMAP_SERVER', 'imap.secureserver.net'))
        self.port = int(getattr(settings, 'IMAP_PORT', os.getenv('IMAP_PORT', 993)))
        self.user = getattr(settings, 'EMAIL_USER', os.getenv('EMAIL_USER'))
        self.password = getattr(settings, 'EMAIL_PASS', os.getenv('EMAIL_PASS'))

        if not self.user or not self.password:
            raise ValueError("Credenciais de email (EMAIL_USER/EMAIL_PASS) nao encontradas no .env ou settings.")

        self.mail: Optional[imaplib.IMAP4_SSL] = None

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _decode_header_value(value: str) -> str:
        """Decodifica headers MIME (ex: =?utf-8?Q?...) de forma robusta."""
        if not value:
            return ""
        decoded_parts = decode_header(value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                # Tenta o charset informado, senao utf-8, senao latin-1 (comum no BR)
                charset = charset or 'utf-8'
                try:
                    result.append(part.decode(charset, errors='ignore'))
                except LookupError:
                    result.append(part.decode('latin-1', errors='ignore'))
            else:
                result.append(str(part))
        return "".join(result).strip()

    @staticmethod
    def _get_body(msg: email.message.Message) -> str:
        """Extrai o corpo do email, preferindo text/plain, fallback para text/html."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get('Content-Disposition', ''))

                # Pula anexos
                if 'attachment' in cdispo:
                    continue

                if ctype == 'text/plain':
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            body += payload.decode(charset, errors='ignore')
                    except Exception:
                        pass
                elif ctype == 'text/html' and not body:
                    # Fallback: se nao achou plain text, pega o HTML
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            body += payload.decode(charset, errors='ignore')
                    except Exception:
                        pass
        else:
            # Nao é multipart
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='ignore')
            except Exception:
                pass
        return body

    def _build_search_criteria(self, base_criteria: str = "UNSEEN") -> str:
        """
        Combina o criterio base com o filtro de START_DATE se configurado (Bug #7).
        O padrao IMAP para datas no comando SEARCH é DD-Mon-YYYY (ex: 01-Aug-2026).
        """
        criteria = [base_criteria]
        start_date = getattr(settings, 'START_DATE', None)
        
        if start_date:
            imap_date = start_date.strftime("%d-%b-%Y")
            criteria.append(f"SINCE {imap_date}")
            
        return " ".join(criteria)

    # ------------------------------------------------------------------ core

    def connect(self) -> bool:
        """Conecta e autentica no servidor IMAP."""
        try:
            print(f"[IMAP] Conectando a {self.server}:{self.port}...")
            self.mail = imaplib.IMAP4_SSL(self.server, self.port)
            self.mail.login(self.user, self.password)
            self.mail.select('inbox')
            print("[IMAP] Login bem-sucedido. INBOX selecionada.")
            return True
        except imaplib.IMAP4.error as e:
            print(f"[IMAP ERRO] Falha na autenticacao ou conexao: {e}")
            return False
        except Exception as e:
            print(f"[IMAP ERRO] Inesperado: {e}")
            return False

    def disconnect(self) -> None:
        """Fecha a conexao de forma graciosa."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass
            self.mail = None

    def mark_as_seen(self, imap_id: bytes) -> bool:
        """
        Marca um email especifico como lido (SEEN) apos decisao do pipeline (Bug #4).
        O orquestrador (main.py) deve chamar este metodo apenas para emails
        FORWARD ou SKIP_*, mantendo PENDING_APPROVAL como UNSEEN.
        """
        if not self.mail:
            return False
        try:
            self.mail.store(imap_id, '+FLAGS', '\\Seen')
            return True
        except Exception as e:
            print(f"[IMAP ERRO] Falha ao marcar como lido o ID {imap_id}: {e}")
            return False

    def fetch_and_process(self, search_criteria: str = "UNSEEN", dry_run: bool = False) -> List[Dict]:
        """
        Busca emails, parseia e avalia no FilterEngine.
        Retorna lista de dicionarios com os resultados prontos para o SMTP/DB.
        
        Refatoracao Qwen:
        - Utiliza BODY.PEEK[] para nao alterar flags no servidor durante o fetch (Bug #3).
        - Nao marca como lido automaticamente; delega ao orquestrador (Bug #4).
        """
        if not self.mail:
            if not self.connect():
                return []

        results = []
        final_criteria = self._build_search_criteria(search_criteria)

        try:
            print(f"[IMAP] Buscando emails com criterio: {final_criteria}")
            status, messages = self.mail.search(None, final_criteria)

            if status != 'OK':
                print("[IMAP] Nenhum email encontrado ou erro na busca.")
                return []

            email_ids = messages[0].split()
            print(f"[IMAP] {len(email_ids)} email(s) encontrado(s).")

            for e_id in email_ids:
                try:
                    # FIX #3: Busca o corpo completo sem marcar como lido (PEEK)
                    status, msg_data = self.mail.fetch(e_id, '(BODY.PEEK[])')
                    if status != 'OK':
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Extrai metadados
                    message_id = msg.get("Message-ID", "").strip()
                    from_header = self._decode_header_value(msg.get("From", ""))
                    subject = self._decode_header_value(msg.get("Subject", ""))
                    date_str = msg.get("Date", "")
                    body = self._get_body(msg)

                    # Avalia no motor de regras
                    decision, reason, amount = filter_engine.evaluate(
                        from_header=from_header,
                        subject=subject,
                        body=body,
                        message_id=message_id
                    )

                    results.append({
                        "imap_id": e_id,  # Mantido como bytes para uso futuro no mark_as_seen
                        "message_id": message_id,
                        "from": from_header,
                        "subject": subject,
                        "date": date_str,
                        "body": body,
                        "decision": decision,
                        "reason": reason,
                        "amount": amount,
                    })
                    
                    # FIX #4: Removido o store automatico. 
                    # O main.py agora decide quando chamar self.mark_as_seen(e_id).

                except Exception as e:
                    print(f"[IMAP ERRO] Falha ao processar email ID {e_id}: {e}")
                    continue

        except Exception as e:
            print(f"[IMAP ERRO CRITICO] Falha no loop de busca: {e}")

        return results


# ----------------------------------------------------------------------------
# AUTO-TESTE (MOCKADO EM MEMORIA - NAO EXIGE CONEXAO/SENHA)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE IMAP_HANDLER (PARSER + REGRAS QWEN)")
    print("=" * 70)

    # Nao testamos conexao real aqui para nao depender de rede/senha no CI.
    # Testamos a robustez do PARSER com um email mockado.
    mock_raw_email = b"""From: =?utf-8?Q?Vivo_Pesquisa?= <vivo@pesquisa.vivo.com.br>
To: alex@didier.com.br
Subject: =?utf-8?Q?Ol=C3=A1_ARPEL=2C_podemos_contar_com_voc=C3=AA=3F?=
Message-ID: <mock123@test.com>
Date: Thu, 03 Sep 2026 10:00:00 -0300
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset="utf-8"

Ola cliente, responda nossa pesquisa.
Valor do premio: R$ 500,00.

--boundary123
Content-Type: text/html; charset="utf-8"

<html><body><h1>Ola cliente</h1><p>Valor do premio: R$ 500,00.</p></body></html>

--boundary123--
"""

    print("1. Testando parseamento de Email Mockado (Multipart + UTF-8 QP)...")
    msg = email.message_from_bytes(mock_raw_email)

    # Chamamos os metodos estaticos diretamente, sem instanciar a classe
    from_h = IMAPHandler._decode_header_value(msg.get("From"))
    subj = IMAPHandler._decode_header_value(msg.get("Subject"))
    body = IMAPHandler._get_body(msg)

    print(f"   From decodificado: {from_h}")
    print(f"   Subject decodificado: {subj}")
    print(f"   Body extraido (tamanho): {len(body)} chars")

    assert "Vivo Pesquisa" in from_h, "Falha ao decodificar From"
    assert "Olá ARPEL" in subj, "Falha ao decodificar Subject Quoted-Printable"
    assert "R$ 500,00" in body, "Falha ao extrair corpo"
    print("   ✅ Parser de headers e corpo OK.")

    print("\n2. Testando integracao com FilterEngine...")
    decision, reason, amount = filter_engine.evaluate(from_h, subj, body)
    print(f"   Decisao: {decision} | Motivo: {reason}")
    assert decision == "SKIP_SENDER", f"Esperado SKIP_SENDER, obtido {decision}"
    print("   ✅ Integracao OK.")

    print("\n3. Testando construcao de criterios de busca (START_DATE - Bug #7)...")
    
    class DummyIMAP(IMAPHandler):
        def __init__(self):
            pass  # Evita conectar no servidor durante o teste
            
    dummy = DummyIMAP()
    original_start_date = getattr(settings, 'START_DATE', None)
    
    # Testa com START_DATE definido (Simula o valor do .env)
    from datetime import datetime
    settings.START_DATE = datetime(2026, 8, 1)
    criteria = dummy._build_search_criteria("UNSEEN")
    print(f"   Com START_DATE: {criteria}")
    assert "SINCE 01-Aug-2026" in criteria, "Falha ao incluir filtro de data"
    
    # Testa sem START_DATE
    settings.START_DATE = None
    criteria = dummy._build_search_criteria("UNSEEN")
    print(f"   Sem START_DATE: {criteria}")
    assert criteria == "UNSEEN", "Falha ao manter criterio base"
    
    # Restaura o estado original
    settings.START_DATE = original_start_date
    print("   ✅ Criterios de busca e START_DATE OK.")

    print("-" * 70)
    print("IMAP_HANDLER OK - Parser robusto validado e correcoes Qwen aplicadas.")
    print("Para testar a conexao real, rode o main.py com seu .env configurado.")
    print("=" * 70)