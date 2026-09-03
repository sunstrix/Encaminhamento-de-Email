# -*- coding: utf-8 -*-
"""
==============================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
Arquivo: src/button_handler.py
==============================================================================
Responsavel por gerar o corpo HTML com botoes interativos (via mailto)
para a fila de aprovacao manual. Como clientes de email bloqueiam forms
e scripts, usamos links mailto com UUIDs unicos que serao lidos
posteriormente pelo response_handler.
==============================================================================
"""

import sys
import uuid
from pathlib import Path
from typing import Optional

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

class ButtonHandler:
    """Gera templates HTML com botoes de aprovacao baseados em mailto."""

    def __init__(self, approval_email: Optional[str] = None):
        """
        Inicializa o handler. 
        Se approval_email for fornecido (ex: em testes), usa ele. 
        Caso contrario, busca no settings (.env).
        """
        if approval_email:
            self.approval_email = approval_email
        else:
            self.approval_email = getattr(settings, 'APPROVAL_EMAIL', getattr(settings, 'EMAIL_USER', ''))
            
        if not self.approval_email:
            raise ValueError("Nenhum email de aprovacao (APPROVAL_EMAIL ou EMAIL_USER) configurado no .env ou passado via parametro.")

    def generate_approval_email(
        self, 
        from_header: str, 
        subject: str, 
        body_snippet: str,
        amount: Optional[float],
        reason: str
    ) -> tuple[str, str]:
        """
        Gera o HTML e o UUID unico para o email de aprovacao.
        Retorna: (html_body, uuid)
        """
        email_uuid = str(uuid.uuid4())
        
        # Formatacao de moeda PT-BR (R$ 1.234,56)
        if amount is not None:
            amount_str = f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            amount_str = "Nao identificado"
        
        # Limita o tamanho do body para o preview no email de aprovacao
        snippet = body_snippet[:500] + "..." if len(body_snippet) > 500 else body_snippet
        snippet = snippet.replace("\n", "<br>").replace("\r", "")
        
        approve_link = f"mailto:{self.approval_email}?subject=APROVAR_{email_uuid}"
        reject_link = f"mailto:{self.approval_email}?subject=REPROVAR_{email_uuid}"
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; margin: 0;">
          <div style="max-width: 600px; margin: auto; background: #ffffff; padding: 25px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <h2 style="color: #d9534f; text-align: center; margin-top: 0;">⚠️ Aprovação Financeira Necessária</h2>
            <p style="font-size: 14px; color: #555;">O robô CP FANI interceptou um e-mail que requer sua validação antes de ser encaminhado ao financeiro.</p>
            
            <div style="background-color: #f9f9f9; padding: 15px; border-left: 4px solid #f0ad4e; margin: 20px 0; border-radius: 4px;">
              <p style="margin: 5px 0;"><strong>De:</strong> {from_header}</p>
              <p style="margin: 5px 0;"><strong>Assunto:</strong> {subject}</p>
              <p style="margin: 5px 0;"><strong>Valor Detectado:</strong> <span style="color: #d9534f; font-weight: bold;">{amount_str}</span></p>
              <p style="margin: 5px 0;"><strong>Motivo da Retenção:</strong> {reason}</p>
            </div>

            <div style="background-color: #eeeeee; padding: 15px; border-radius: 4px; font-size: 13px; color: #333; max-height: 150px; overflow-y: auto;">
              <strong>Prévia do Corpo do E-mail:</strong><br>
              {snippet}
            </div>

            <p style="text-align: center; margin-top: 30px;">
              <a href="{approve_link}" style="background-color: #5cb85c; color: white; padding: 14px 28px; text-align: center; text-decoration: none; display: inline-block; border-radius: 4px; font-size: 16px; font-weight: bold; margin: 5px;">✅ APROVAR</a>
              <a href="{reject_link}" style="background-color: #d9534f; color: white; padding: 14px 28px; text-align: center; text-decoration: none; display: inline-block; border-radius: 4px; font-size: 16px; font-weight: bold; margin: 5px;">❌ REPROVAR</a>
            </p>
            
            <hr style="border: 0; border-top: 1px solid #eee; margin: 30px 0;">
            
            <p style="font-size: 11px; color: #888; text-align: center; margin: 0;">
              ID de Rastreamento: <code>{email_uuid}</code><br>
              O e-mail original completo (com anexos) está anexado a esta mensagem.<br>
              Para aprovar, basta clicar no botão e enviar o e-mail que será aberto pelo seu cliente de e-mail.
            </p>
          </div>
        </body>
        </html>
        """
        
        return html.strip(), email_uuid


# Instancia unica via factory (lazy loading para nao quebrar testes sem .env)
_button_handler_instance: Optional[ButtonHandler] = None

def get_button_handler() -> ButtonHandler:
    global _button_handler_instance
    if _button_handler_instance is None:
        _button_handler_instance = ButtonHandler()
    return _button_handler_instance


# ----------------------------------------------------------------------------
# AUTO-TESTE (INJECAO DE DEPENDENCIA PARA BYPASSAR O .ENV)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CP FANI - AUTO-TESTE DE BUTTON_HANDLER (GERADOR DE HTML)")
    print("=" * 70)
    
    print("1. Testando geracao de template HTML com UUID (Mockado)...")
    
    # Injeta o email de teste diretamente no construtor, ignorando o settings.py
    bh = ButtonHandler(approval_email="teste@didier.com.br")
    
    html, uid = bh.generate_approval_email(
        from_header="Vivo Cobranças <cobrancas@vivo.com.br>",
        subject="Fatura Vivo - Vencimento 10/10",
        body_snippet="Prezado cliente, sua fatura no valor de R$ 15.400,00 está disponível para download em nosso portal.",
        amount=15400.00,
        reason="Valor excede o limite de R$ 5.000,00 para aprovacao automatica."
    )
    
    assert "APROVAR_" + uid in html, "Link de aprovacao nao contem o UUID"
    assert "REPROVAR_" + uid in html, "Link de reprovacao nao contem o UUID"
    assert "R$ 15.400,00" in html, "Formatacao de moeda falhou"
    assert "Vivo Cobranças" in html, "Header nao inserido"
    assert "<html>" in html, "Estrutura HTML invalida"
    
    print(f"   UUID Gerado: {uid}")
    print("   ✅ Template HTML montado corretamente com links mailto e formatacao PT-BR.")
    
    print("-" * 70)
    print("BUTTON_HANDLER OK - Gerador de aprovacao validado.")
    print("=" * 70)