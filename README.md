# 📧 Sistema de Encaminhamento de Emails - CP Fani

> **Sistema de Fallback para encaminhamento automático de emails financeiros**
> 
> Projeto privado - CP Fani / Didier
> 
> Versão: 1.0.0  
> Data: Setembro 2026  
> Ambiente: Zorin OS (Linux)

---

## 📋 Índice

1. [Visão Geral](#-visão-geral)
2. [Arquitetura do Sistema](#-arquitetura-do-sistema)
3. [Regras de Negócio](#-regras-de-negócio)
4. [Fluxo de Funcionamento](#-fluxo-de-funcionamento)
5. [Estrutura do Projeto](#-estrutura-do-projeto)
6. [Pré-requisitos](#-pré-requisitos)
7. [Instalação no Zorin OS](#-instalação-no-zorin-os)
8. [Configuração](#-configuração)
9. [Scripts do Sistema](#-scripts-do-sistema)
10. [Mensagens do Sistema](#-mensagens-do-sistema)
11. [Fluxo de Aprovação e Reprovação](#-fluxo-de-aprovação-e-reprovação)
12. [Banco de Dados](#-banco-de-dados)
13. [Deploy e Automação](#-deploy-e-automação)
14. [Manutenção](#-manutenção)
15. [Troubleshooting](#-troubleshooting)
16. [Roadmap](#-roadmap)

---

## 🎯 Visão Geral

Este sistema é um **fallback temporário** para encaminhamento automático de emails financeiros recebidos na conta `alex@didier.com.br` para o setor financeiro (`financeiro@didier.com.br`), enquanto as operadoras não finalizam a migração dos envios.

### Problema Resolvido

- **1931 emails** acumulados nos últimos 2 anos
- Dificuldade de triagem manual
- Múltiplos fornecedores enviando faturas, boletos e NFS-e
- Necessidade de controle de aprovação/reprovação

### Solução Implementada

- Filtro automático de emails por regras configuráveis
- Encaminhamento em lote para o financeiro
- Botões de **Aprovar** e **Reprovar** em cada email
- Bloqueio permanente de remetentes reprovados
- Sistema de logs detalhado

---

## 🏗️ Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    SERVIDOR ZORIN OS                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐    ┌──────────────────┐              │
│  │   Cron Job       │───▶│  email_forwarder │              │
│  │  (a cada 1h)     │    │     .py          │              │
│  └──────────────────┘    └────────┬─────────┘              │
│                                   │                         │
│                                   ▼                         │
│                         ┌──────────────────┐               │
│                         │   IMAP Server    │               │
│                         │  (alex@didier)   │               │
│                         └────────┬─────────┘               │
│                                  │                          │
│                                  ▼                          │
│                    ┌──────────────────────┐                │
│                    │   Filter Engine      │                │
│                    │  - Domínios          │                │
│                    │  - Remetentes        │                │
│                    │  - Assuntos          │                │
│                    │  - Blacklist         │                │
│                    └──────────┬───────────┘                │
│                               │                             │
│                               ▼                             │
│                    ┌──────────────────────┐                │
│                    │   SMTP Relay         │                │
│                    │ (financeiro@didier)  │                │
│                    └──────────┬───────────┘                │
│                               │                             │
│                               ▼                             │
│                    ┌──────────────────────┐                │
│                    │  SQLite Database     │                │
│                    │  - Emails enviados   │                │
│                    │  - Aprovados         │                │
│                    │  - Reprovados        │                │
│                    └──────────────────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Componentes

1. **email_forwarder.py**: Script principal que orquestra todo o processo
2. **config.py**: Configurações centralizadas
3. **filters.py**: Motor de filtros e regras
4. **handlers.py**: Processadores de emails
5. **database.py**: Camada de persistência SQLite
6. **blacklist.txt**: Lista de emails bloqueados
7. **pending_emails.db**: Banco SQLite com status dos emails

---

## 📜 Regras de Negócio

### 1. Critérios de Filtragem

Um email é considerado **FINANCEIRO** se atender a qualquer um destes critérios:

#### ✅ Incluídos (Encaminhados)
- Faturas de operadoras (Vivo, Claro, TIM, Oi)
- Boletos bancários
- NFS-e e NF-e de fornecedores
- Cobranças de serviços
- Comprovantes de pagamento
- Contratos e propostas financeiras

#### ❌ Excluídos (Ignorados)
- Domínio `@didier.com.br` (emails internos)
- Remetentes específicos:
  - `lixo@didier.com.br`
  - `notifications@didier.com.br`
  - `alert@uptimerobot.com`
  - `NoReply_GOL_seguranca@claro.com.br`
  - `trocadechip.pme@claroatendimento.com.br`
  - `no-reply@hetrixtools.com`
- Assuntos contendo:
  - "contratação", "contratacao"
  - "assinatura"
  - "proposta"
  - "agendamento"
  - "pesquisa"
  - "senha"
  - "renovação", "renovacao"
  - "reagendamento técnico", "reagendamento tecnico"

### 2. Período de Coleta

- **Primeiro envio**: Emails a partir de **01/08/2026**
- **Envios subsequentes**: Apenas emails novos desde a última execução
- **Histórico**: Não reprocessar emails já encaminhados

### 3. Botões de Ação

Cada email encaminhado contém dois botões:

| Botão | Ação | Efeito |
|-------|------|--------|
| ✅ **Aprovar** | Confirma que o email é financeiro | Marca como aprovado no banco, mantém na lista de encaminhamento |
| ❌ **Reprovar** | Indica que o email NÃO deve ser encaminhado | Adiciona o **remetente de origem** à blacklist permanente |

**IMPORTANTE**: O email reprovado é o **remetente original** (ex: `faturadigital@vivo.com.br`), NÃO o `alex@didier.com.br`.

### 4. Quem Pode Aprovar/Reprovar

Qualquer pessoa com email `@didier.com.br` pode aprovar ou reprovar:
- `leonardo@didier.com.br`
- `carlos@didier.com.br`
- `marisa@didier.com.br`
- `nice@didier.com.br`
- `suzana@didier.com.br`
- etc.

O sistema identifica o remetente da resposta e registra quem aprovou/reprovou.

---

## 🔄 Fluxo de Funcionamento

### Fluxo Principal

```
1. Cron Job executa a cada 1 hora
   ↓
2. Conecta via IMAP em alex@didier.com.br
   ↓
3. Busca emails não lidos desde 01/08/2026
   ↓
4. Aplica filtros de exclusão
   ↓
5. Verifica blacklist (não encaminha reprovados)
   ↓
6. Verifica se já foi encaminhado (evita duplicidade)
   ↓
7. Encaminha para financeiro@didier.com.br
   ↓
8. Adiciona botões de Aprovar/Reprovar
   ↓
9. Marca como lido no IMAP
   ↓
10. Registra no banco SQLite
```

### Fluxo de Aprovação

```
1. Usuário clica em "Aprovar" no email
   ↓
2. Email é enviado para approve@cp-fani.local
   ↓
3. Script detecta aprovação
   ↓
4. Marca email como "approved" no banco
   ↓
5. Mantém remetente na whitelist
   ↓
6. Envia confirmação ao usuário
```

### Fluxo de Reprovação

```
1. Usuário clica em "Reprovar" no email
   ↓
2. Email é enviado para reject@cp-fani.local
   ↓
3. Script detecta reprovação
   ↓
4. Extrai email do remetente ORIGINAL
   ↓
5. Adiciona remetente à blacklist permanente
   ↓
6. Marca email como "rejected" no banco
   ↓
7. Envia confirmação ao usuário
   ↓
8. Futuros emails desse remetente serão ignorados
```

---

## 📁 Estrutura do Projeto

```
encaminhamento-email/
│
├── README.md                          # Este arquivo
├── .env                               # Variáveis de ambiente (NÃO commitar)
├── .env.example                       # Template de variáveis
├── .gitignore                         # Arquivos ignorados pelo Git
│
├── config/
│   ├── __init__.py
│   ├── settings.py                    # Configurações do sistema
│   └── filters.py                     # Regras de filtro
│
├── src/
│   ├── __init__.py
│   ├── main.py                        # Ponto de entrada
│   ├── email_forwarder.py             # Lógica principal
│   ├── imap_handler.py                # Conexão IMAP
│   ├── smtp_handler.py                # Envio SMTP
│   ├── filter_engine.py               # Motor de filtros
│   ├── button_handler.py              # Processamento de botões
│   └── response_handler.py            # Processamento de respostas
│
├── database/
│   ├── __init__.py
│   ├── models.py                      # Modelos SQLAlchemy
│   ├── database.py                    # Conexão com banco
│   └── migrations/                    # Migrações do banco
│       └── 001_initial_schema.sql
│
├── data/
│   ├── pending_emails.db              # Banco SQLite (gerado)
│   ├── blacklist.txt                  # Lista de emails bloqueados
│   └── whitelist.txt                  # Lista de emails aprovados
│
├── logs/
│   ├── forwarder.log                  # Log principal
│   ├── errors.log                     # Log de erros
│   └── archive/                       # Logs antigos
│
├── templates/
│   ├── email_template.html            # Template HTML do email
│   └── email_template.txt             # Template texto do email
│
├── scripts/
│   ├── install.sh                     # Script de instalação
│   ├── setup_cron.sh                  # Configuração do cron
│   └── backup.sh                      # Script de backup
│
├── tests/
│   ├── test_filters.py                # Testes de filtros
│   ├── test_forwarder.py              # Testes do forwarder
│   └── fixtures/                      # Dados de teste
│       └── sample_emails.txt
│
└── docs/
    ├── architecture.md                # Documentação de arquitetura
    ├── api.md                         # Documentação da API interna
    └── troubleshooting.md             # Guia de troubleshooting
```

---

## ⚙️ Pré-requisitos

### Sistema Operacional
- **Zorin OS 17** ou superior
- Alternativas: Ubuntu 22.04+, Debian 12+

### Software Necessário
- Python 3.10 ou superior
- pip (gerenciador de pacotes Python)
- SQLite 3.35 ou superior
- Git (para versionamento)
- Cron (já incluso no Zorin OS)

### Dependências Python
```
python-dotenv==1.0.0
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
python-dateutil==2.8.2
jinja2==3.1.2
```

---

## 🚀 Instalação no Zorin OS

### Passo 1: Clonar o Repositório

```bash
cd ~/Projects
git clone <URL_DO_REPOSITORIO_PRIVADO> encaminhamento-email
cd encaminhamento-email
```

### Passo 2: Criar Ambiente Virtual

```bash
# Criar ambiente virtual
python3 -m venv venv

# Ativar ambiente virtual
source venv/bin/activate

# Verificar Python
python --version  # Deve mostrar Python 3.10+
```

### Passo 3: Instalar Dependências

```bash
# Atualizar pip
pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt
```

### Passo 4: Configurar Variáveis de Ambiente

```bash
# Copiar template
cp .env.example .env

# Editar variáveis
nano .env
```

### Passo 5: Criar Estrutura de Diretórios

```bash
mkdir -p logs logs/archive data
chmod 755 logs data
```

### Passo 6: Inicializar Banco de Dados

```bash
python -m database.database --init
```

### Passo 7: Testar Conexão

```bash
python -m src.main --test-connection
```

### Passo 8: Configurar Cron Job

```bash
# Editar crontab
crontab -e

# Adicionar linha (executa a cada 1 hora)
0 * * * * cd /home/usuario/Projects/encaminhamento-email && /home/usuario/Projects/encaminhamento-email/venv/bin/python -m src.main >> logs/cron.log 2>&1
```

---

## 🔧 Configuração

### Arquivo .env

```env
# ==============================================================================
# CONFIGURAÇÕES IMAP (CONTA DE ORIGEM)
# ==============================================================================
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=alex@didier.com.br
IMAP_PASSWORD=sua_senha_aqui
IMAP_USE_SSL=true

# ==============================================================================
# CONFIGURAÇÕES SMTP (ENVIO PARA FINANCEIRO)
# ==============================================================================
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=alex@didier.com.br
SMTP_PASSWORD=sua_senha_aqui
SMTP_USE_TLS=true

# ==============================================================================
# CONFIGURAÇÕES DO SISTEMA
# ==============================================================================
DESTINATION_EMAIL=financeiro@didier.com.br
APPROVE_EMAIL=approve@cp-fani.local
REJECT_EMAIL=reject@cp-fani.local

# Data inicial para busca (formato: YYYY-MM-DD)
START_DATE=2026-08-01

# Intervalo de execução em minutos (padrão: 60)
EXECUTION_INTERVAL=60

# Número máximo de emails por execução (0 = ilimitado)
MAX_EMAILS_PER_RUN=0

# Modo de teste (true = não envia emails, apenas simula)
DRY_RUN=false

# ==============================================================================
# CONFIGURAÇÕES DE BANCO DE DADOS
# ==============================================================================
DATABASE_PATH=data/pending_emails.db

# ==============================================================================
# CONFIGURAÇÕES DE LOG
# ==============================================================================
LOG_LEVEL=INFO
LOG_FILE=logs/forwarder.log
LOG_MAX_SIZE=10485760
LOG_BACKUP_COUNT=5

# ==============================================================================
# CONFIGURAÇÕES DE BLACKLIST
# ==============================================================================
BLACKLIST_FILE=data/blacklist.txt
WHITELIST_FILE=data/whitelist.txt
```

### Arquivo requirements.txt

```txt
python-dotenv==1.0.0
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
python-dateutil==2.8.2
jinja2==3.1.2
schedule==1.2.0
tenacity==8.2.3
```

---

## 💻 Scripts do Sistema

### 1. src/main.py - Ponto de Entrada

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Encaminhamento de Emails - CP Fani
Ponto de entrada principal do sistema
"""

import os
import sys
import logging
import argparse
from datetime import datetime

# Adicionar diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.email_forwarder import EmailForwarder
from src.response_handler import ResponseHandler
from config.settings import Settings


def setup_logging():
    """Configura o sistema de logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Criar diretório de logs se não existir
    os.makedirs('logs', exist_ok=True)
    
    # Configurar logging para arquivo
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('logs/forwarder.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(
        description='Sistema de Encaminhamento de Emails - CP Fani'
    )
    parser.add_argument(
        '--test-connection',
        action='store_true',
        help='Testa conexão IMAP/SMTP sem processar emails'
    )
    parser.add_argument(
        '--process-responses',
        action='store_true',
        help='Processa apenas respostas de aprovação/reprovação'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Modo de teste (não envia emails)'
    )
    
    args = parser.parse_args()
    
    # Configurar logging
    logger = setup_logging()
    logger.info("=" * 80)
    logger.info("INICIANDO SISTEMA DE ENCAMINHAMENTO DE EMAILS")
    logger.info(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
    try:
        # Carregar configurações
        settings = Settings()
        
        if args.test_connection:
            logger.info("MODO: Teste de Conexão")
            forwarder = EmailForwarder(settings)
            forwarder.test_connection()
            logger.info("✓ Conexão testada com sucesso")
            return
        
        if args.process_responses:
            logger.info("MODO: Processamento de Respostas")
            handler = ResponseHandler(settings)
            handler.process_responses()
            logger.info("✓ Respostas processadas")
            return
        
        # Modo normal: processar emails
        logger.info("MODO: Processamento Completo")
        forwarder = EmailForwarder(settings, dry_run=args.dry_run)
        
        # Processar emails
        stats = forwarder.process_emails()
        
        # Log estatísticas
        logger.info("=" * 80)
        logger.info("ESTATÍSTICAS DA EXECUÇÃO")
        logger.info(f"Emails encontrados: {stats['found']}")
        logger.info(f"Emails filtrados: {stats['filtered']}")
        logger.info(f"Emails encaminhados: {stats['forwarded']}")
        logger.info(f"Emails ignorados: {stats['ignored']}")
        logger.info(f"Erros: {stats['errors']}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"ERRO CRÍTICO: {str(e)}", exc_info=True)
        sys.exit(1)
    
    logger.info("SISTEMA FINALIZADO COM SUCESSO")


if __name__ == "__main__":
    main()
```

### 2. src/email_forwarder.py - Lógica Principal

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Email Forwarder - Lógica principal de encaminhamento
"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

from src.imap_handler import IMAPHandler
from src.smtp_handler import SMTPHandler
from src.filter_engine import FilterEngine
from src.button_handler import ButtonHandler
from database.database import Database


class EmailForwarder:
    """Classe principal de encaminhamento de emails"""
    
    def __init__(self, settings, dry_run: bool = False):
        self.settings = settings
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)
        
        # Inicializar handlers
        self.imap = IMAPHandler(settings)
        self.smtp = SMTPHandler(settings)
        self.filter_engine = FilterEngine(settings)
        self.button_handler = ButtonHandler(settings)
        self.db = Database(settings.DATABASE_PATH)
        
        self.logger.info("EmailForwarder inicializado")
    
    def test_connection(self):
        """Testa conexão IMAP e SMTP"""
        self.logger.info("Testando conexão IMAP...")
        self.imap.connect()
        self.imap.disconnect()
        self.logger.info("✓ Conexão IMAP OK")
        
        self.logger.info("Testando conexão SMTP...")
        self.smtp.connect()
        self.smtp.disconnect()
        self.logger.info("✓ Conexão SMTP OK")
    
    def process_emails(self) -> Dict[str, int]:
        """Processa emails da caixa de entrada"""
        stats = {
            'found': 0,
            'filtered': 0,
            'forwarded': 0,
            'ignored': 0,
            'errors': 0
        }
        
        try:
            # Conectar ao IMAP
            self.imap.connect()
            
            # Buscar emails
            emails = self.imap.fetch_emails_since(self.settings.START_DATE)
            stats['found'] = len(emails)
            self.logger.info(f"Encontrados {stats['found']} emails")
            
            # Processar cada email
            for email_data in emails:
                try:
                    result = self._process_single_email(email_data)
                    stats[result] += 1
                except Exception as e:
                    self.logger.error(f"Erro ao processar email: {str(e)}")
                    stats['errors'] += 1
            
            # Desconectar
            self.imap.disconnect()
            
        except Exception as e:
            self.logger.error(f"Erro no processamento: {str(e)}")
            stats['errors'] += 1
        
        return stats
    
    def _process_single_email(self, email_data: Dict) -> str:
        """Processa um único email"""
        # Extrair informações do email
        from_addr = email_data.get('from', '')
        subject = email_data.get('subject', '')
        message_id = email_data.get('message_id', '')
        
        self.logger.debug(f"Processando: {subject} de {from_addr}")
        
        # Verificar se já foi processado
        if self.db.is_email_processed(message_id):
            self.logger.debug(f"Email já processado: {message_id}")
            return 'ignored'
        
        # Aplicar filtros
        if not self.filter_engine.should_forward(email_data):
            self.logger.debug(f"Email filtrado: {subject}")
            self.db.mark_as_filtered(message_id)
            return 'filtered'
        
        # Verificar blacklist
        if self.filter_engine.is_blacklisted(from_addr):
            self.logger.debug(f"Remetente na blacklist: {from_addr}")
            self.db.mark_as_blacklisted(message_id)
            return 'ignored'
        
        # Encaminhar email
        if not self.dry_run:
            self._forward_email(email_data)
        
        # Marcar como processado
        self.db.mark_as_forwarded(message_id, from_addr, subject)
        
        # Marcar como lido no IMAP
        if not self.dry_run:
            self.imap.mark_as_read(email_data.get('uid'))
        
        self.logger.info(f"✓ Encaminhado: {subject}")
        return 'forwarded'
    
    def _forward_email(self, email_data: Dict):
        """Encaminha email para o financeiro com botões"""
        # Criar mensagem com botões
        message = self.button_handler.create_forward_message(email_data)
        
        # Enviar via SMTP
        self.smtp.send_email(
            to=self.settings.DESTINATION_EMAIL,
            subject=f"[CP FANI] {email_data.get('subject', 'Sem Assunto')}",
            message=message
        )
```

### 3. src/filter_engine.py - Motor de Filtros

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filter Engine - Motor de filtros para classificação de emails
"""

import re
from typing import Dict, List
import logging


class FilterEngine:
    """Motor de filtros para classificação de emails"""
    
    # Domínios excluídos
    EXCLUDED_DOMAINS = [
        '@didier.com.br'
    ]
    
    # Remetentes excluídos
    EXCLUDED_SENDERS = [
        'lixo@didier.com.br',
        'notifications@didier.com.br',
        'alert@uptimerobot.com',
        'noreply_gol_seguranca@claro.com.br',
        'trocadechip.pme@claroatendimento.com.br',
        'no-reply@hetrixtools.com',
    ]
    
    # Palavras-chave no assunto que indicam NÃO financeiro
    EXCLUDED_SUBJECT_KEYWORDS = [
        'contratação', 'contratacao',
        'assinatura',
        'proposta',
        'agendamento',
        'pesquisa',
        'senha',
        'renovação', 'renovacao',
        'reagendamento técnico', 'reagendamento tecnico',
    ]
    
    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.blacklist = self._load_blacklist()
        self.logger.info(f"FilterEngine inicializado com {len(self.blacklist)} emails na blacklist")
    
    def _load_blacklist(self) -> List[str]:
        """Carrega blacklist do arquivo"""
        try:
            with open(self.settings.BLACKLIST_FILE, 'r') as f:
                return [line.strip().lower() for line in f if line.strip()]
        except FileNotFoundError:
            self.logger.warning(f"Arquivo de blacklist não encontrado: {self.settings.BLACKLIST_FILE}")
            return []
    
    def should_forward(self, email_data: Dict) -> bool:
        """Verifica se o email deve ser encaminhado"""
        from_addr = email_data.get('from', '').lower()
        subject = email_data.get('subject', '').lower()
        
        # Extrair email do remetente
        email_match = re.search(r'<([^>]+)>', from_addr)
        sender_email = email_match.group(1) if email_match else from_addr
        
        # Verificar domínios excluídos
        for domain in self.EXCLUDED_DOMAINS:
            if domain in sender_email:
                self.logger.debug(f"Domínio excluído: {domain}")
                return False
        
        # Verificar remetentes excluídos
        for sender in self.EXCLUDED_SENDERS:
            if sender in sender_email:
                self.logger.debug(f"Remetente excluído: {sender}")
                return False
        
        # Verificar palavras-chave no assunto
        for keyword in self.EXCLUDED_SUBJECT_KEYWORDS:
            if keyword in subject:
                self.logger.debug(f"Palavra-chave excluída: {keyword}")
                return False
        
        return True
    
    def is_blacklisted(self, from_addr: str) -> bool:
        """Verifica se o remetente está na blacklist"""
        # Extrair email
        email_match = re.search(r'<([^>]+)>', from_addr.lower())
        sender_email = email_match.group(1) if email_match else from_addr.lower()
        
        return sender_email in self.blacklist
    
    def add_to_blacklist(self, email_addr: str):
        """Adiciona email à blacklist"""
        email_addr = email_addr.lower().strip()
        
        if email_addr not in self.blacklist:
            self.blacklist.append(email_addr)
            
            # Salvar no arquivo
            with open(self.settings.BLACKLIST_FILE, 'a') as f:
                f.write(f"{email_addr}\n")
            
            self.logger.info(f"✓ Adicionado à blacklist: {email_addr}")
```

### 4. src/button_handler.py - Processamento de Botões

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Button Handler - Cria e processa botões de Aprovar/Reprovar
"""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Template
import logging


class ButtonHandler:
    """Handler para botões de aprovação/reprovação"""
    
    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        
        # Templates HTML e texto
        self.html_template = self._load_template('templates/email_template.html')
        self.text_template = self._load_template('templates/email_template.txt')
    
    def _load_template(self, path: str) -> str:
        """Carrega template do arquivo"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            self.logger.warning(f"Template não encontrado: {path}")
            return ""
    
    def create_forward_message(self, email_data: dict) -> MIMEMultipart:
        """Cria mensagem de encaminhamento com botões"""
        msg = MIMEMultipart('alternative')
        
        # Dados do email original
        original_from = email_data.get('from', 'Desconhecido')
        original_subject = email_data.get('subject', 'Sem Assunto')
        original_date = email_data.get('date', '')
        original_body = email_data.get('body', '')
        message_id = email_data.get('message_id', '')
        
        # Links de ação
        approve_url = f"mailto:{self.settings.APPROVE_EMAIL}?subject=APPROVE:{message_id}"
        reject_url = f"mailto:{self.settings.REJECT_EMAIL}?subject=REJECT:{message_id}"
        
        # Renderizar templates
        context = {
            'original_from': original_from,
            'original_subject': original_subject,
            'original_date': original_date,
            'original_body': original_body,
            'approve_url': approve_url,
            'reject_url': reject_url,
            'message_id': message_id,
        }
        
        if self.html_template:
            html_content = Template(self.html_template).render(**context)
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        if self.text_template:
            text_content = Template(self.text_template).render(**context)
            msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        else:
            # Fallback: criar texto simples
            text_content = self._create_text_fallback(context)
            msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        
        return msg
    
    def _create_text_fallback(self, context: dict) -> str:
        """Cria versão texto simples como fallback"""
        return f"""
================================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
================================================================================

⚠️ ATENÇÃO: MIGRAÇÃO EM ANDAMENTO

Prezados,

Informamos que já foi solicitada junto às operadoras a migração do envio de
faturas e boletos diretamente para o email financeiro@didier.com.br.

Este sistema funciona como um FALLBACK TEMPORÁRIO enquanto a migração não é
concluída.

================================================================================
AÇÕES DISPONÍVEIS
================================================================================

Você pode aprovar ou reprovar este email:

✅ APROVAR: Confirma que este email é financeiro e deve continuar sendo
   encaminhado para você.

❌ REPROVAR: Indica que este email NÃO deve ser encaminhado. O remetente
   original será bloqueado permanentemente.

================================================================================
EMAIL ORIGINAL
================================================================================

De: {context['original_from']}
Data: {context['original_date']}
Assunto: {context['original_subject']}

--------------------------------------------------------------------------------

{context['original_body']}

================================================================================
COMO RESPONDER
================================================================================

Para APROVAR: Responda este email com o assunto "APROVAR"
Para REPROVAR: Responda este email com o assunto "REPROVAR"

Qualquer pessoa com email @didier.com.br pode aprovar ou reprovar.

================================================================================
ID do Email: {context['message_id']}
================================================================================
"""
```

### 5. src/response_handler.py - Processamento de Respostas

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Response Handler - Processa respostas de aprovação/reprovação
"""

import re
import logging
from datetime import datetime
from database.database import Database
from src.filter_engine import FilterEngine


class ResponseHandler:
    """Handler para processar respostas de aprovação/reprovação"""
    
    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.db = Database(settings.DATABASE_PATH)
        self.filter_engine = FilterEngine(settings)
    
    def process_responses(self):
        """Processa emails de resposta (aprovação/reprovação)"""
        self.logger.info("Iniciando processamento de respostas")
        
        # Conectar ao IMAP
        from src.imap_handler import IMAPHandler
        imap = IMAPHandler(self.settings)
        imap.connect()
        
        # Buscar emails de resposta
        responses = imap.search_responses()
        
        for response in responses:
            try:
                self._process_single_response(response)
            except Exception as e:
                self.logger.error(f"Erro ao processar resposta: {str(e)}")
        
        imap.disconnect()
        self.logger.info(f"Processadas {len(responses)} respostas")
    
    def _process_single_response(self, response: dict):
        """Processa uma única resposta"""
        subject = response.get('subject', '').upper()
        from_addr = response.get('from', '')
        body = response.get('body', '')
        
        # Verificar se é resposta válida (deve ser @didier.com.br)
        if not self._is_valid_responder(from_addr):
            self.logger.warning(f"Resposta de remetente inválido: {from_addr}")
            return
        
        # Extrair message_id do email original
        message_id = self._extract_message_id(body, subject)
        
        if not message_id:
            self.logger.warning("Não foi possível extrair message_id da resposta")
            return
        
        # Determinar ação
        if 'APROVAR' in subject or 'APPROVE' in subject:
            self._handle_approval(message_id, from_addr)
        elif 'REPROVAR' in subject or 'REJECT' in subject:
            self._handle_rejection(message_id, from_addr)
        else:
            self.logger.warning(f"Resposta sem ação válida: {subject}")
    
    def _is_valid_responder(self, from_addr: str) -> bool:
        """Verifica se o remetente é válido (@didier.com.br)"""
        email_match = re.search(r'<([^>]+)>', from_addr.lower())
        sender_email = email_match.group(1) if email_match else from_addr.lower()
        
        return '@didier.com.br' in sender_email
    
    def _extract_message_id(self, body: str, subject: str) -> str:
        """Extrai message_id do email original"""
        # Tentar extrair do corpo do email
        id_match = re.search(r'ID do Email:\s*([^\s]+)', body)
        if id_match:
            return id_match.group(1)
        
        # Tentar extrair do assunto
        id_match = re.search(r'APPROVE:(.+)|REJECT:(.+)', subject)
        if id_match:
            return id_match.group(1) or id_match.group(2)
        
        return None
    
    def _handle_approval(self, message_id: str, responder: str):
        """Processa aprovação"""
        self.logger.info(f"Aprovação recebida de {responder} para {message_id}")
        
        # Atualizar banco de dados
        self.db.mark_as_approved(message_id, responder)
        
        self.logger.info(f"✓ Email aprovado: {message_id}")
    
    def _handle_rejection(self, message_id: str, responder: str):
        """Processa reprovação"""
        self.logger.info(f"Reprovação recebida de {responder} para {message_id}")
        
        # Buscar email original no banco
        original_email = self.db.get_email_by_message_id(message_id)
        
        if not original_email:
            self.logger.error(f"Email original não encontrado: {message_id}")
            return
        
        # Extrair remetente original
        original_from = original_email.get('from_addr', '')
        
        # Adicionar à blacklist
        self.filter_engine.add_to_blacklist(original_from)
        
        # Atualizar banco de dados
        self.db.mark_as_rejected(message_id, responder)
        
        self.logger.info(f"✓ Email reprovado e remetente bloqueado: {original_from}")
```

### 6. database/database.py - Camada de Persistência

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database - Camada de persistência SQLite
"""

import sqlite3
from datetime import datetime
from typing import Optional, Dict
import logging


class Database:
    """Classe de acesso ao banco de dados"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_database()
    
    def _init_database(self):
        """Inicializa o banco de dados"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Criar tabela de emails processados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                from_addr TEXT,
                subject TEXT,
                status TEXT DEFAULT 'pending',
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejected_by TEXT,
                rejected_at TIMESTAMP
            )
        ''')
        
        # Criar índice
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_message_id 
            ON processed_emails(message_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_status 
            ON processed_emails(status)
        ''')
        
        conn.commit()
        conn.close()
        
        self.logger.info(f"Banco de dados inicializado: {self.db_path}")
    
    def is_email_processed(self, message_id: str) -> bool:
        """Verifica se o email já foi processado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id FROM processed_emails WHERE message_id = ?',
            (message_id,)
        )
        
        result = cursor.fetchone()
        conn.close()
        
        return result is not None
    
    def mark_as_forwarded(self, message_id: str, from_addr: str, subject: str):
        """Marca email como encaminhado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO processed_emails 
            (message_id, from_addr, subject, status)
            VALUES (?, ?, ?, 'forwarded')
        ''', (message_id, from_addr, subject))
        
        conn.commit()
        conn.close()
    
    def mark_as_filtered(self, message_id: str):
        """Marca email como filtrado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO processed_emails 
            (message_id, status)
            VALUES (?, 'filtered')
        ''', (message_id,))
        
        conn.commit()
        conn.close()
    
    def mark_as_blacklisted(self, message_id: str):
        """Marca email como bloqueado (remetente na blacklist)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO processed_emails 
            (message_id, status)
            VALUES (?, 'blacklisted')
        ''', (message_id,))
        
        conn.commit()
        conn.close()
    
    def mark_as_approved(self, message_id: str, approved_by: str):
        """Marca email como aprovado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE processed_emails 
            SET status = 'approved', 
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
        ''', (approved_by, message_id))
        
        conn.commit()
        conn.close()
    
    def mark_as_rejected(self, message_id: str, rejected_by: str):
        """Marca email como reprovado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE processed_emails 
            SET status = 'rejected',
                rejected_by = ?,
                rejected_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
        ''', (rejected_by, message_id))
        
        conn.commit()
        conn.close()
    
    def get_email_by_message_id(self, message_id: str) -> Optional[Dict]:
        """Busca email pelo message_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT message_id, from_addr, subject, status
            FROM processed_emails
            WHERE message_id = ?
        ''', (message_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'message_id': row[0],
                'from_addr': row[1],
                'subject': row[2],
                'status': row[3]
            }
        
        return None
    
    def get_statistics(self) -> Dict:
        """Retorna estatísticas do sistema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Total de emails
        cursor.execute('SELECT COUNT(*) FROM processed_emails')
        stats['total'] = cursor.fetchone()[0]
        
        # Por status
        cursor.execute('''
            SELECT status, COUNT(*) 
            FROM processed_emails 
            GROUP BY status
        ''')
        
        for row in cursor.fetchall():
            stats[row[0]] = row[1]
        
        conn.close()
        
        return stats
```

---

## 📧 Mensagens do Sistema

### Mensagem Inicial (Incluída em Todos os Emails)

```
================================================================================
SISTEMA DE ENCAMINHAMENTO DE EMAILS - CP FANI
================================================================================

⚠️ ATENÇÃO: MIGRAÇÃO EM ANDAMENTO

Prezados,

Informamos que já foi solicitada junto às operadoras a migração do envio de
faturas e boletos diretamente para o email financeiro@didier.com.br.

Este sistema funciona como um FALLBACK TEMPORÁRIO enquanto a migração não é
concluída.

Durante este período, vocês receberão emails encaminhados automaticamente
desta conta (alex@didier.com.br) para análise.

================================================================================
AÇÕES DISPONÍVEIS
================================================================================

Para cada email encaminhado, vocês podem:

✅ APROVAR: Confirma que este email é financeiro e deve continuar sendo
   encaminhado para você. O remetente será mantido na lista de encaminhamento.

❌ REPROVAR: Indica que este email NÃO deve ser encaminhado. O remetente
   original será bloqueado permanentemente e não receberá mais emails.

Qualquer pessoa com email @didier.com.br pode aprovar ou reprovar.

================================================================================
```

### Mensagem de Confirmação de Aprovação

```
================================================================================
✅ EMAIL APROVADO COM SUCESSO
================================================================================

O email foi marcado como aprovado no sistema.

Detalhes:
- Aprovado por: [email do aprovador]
- Data/Hora: [timestamp]
- Remetente original: [email do remetente]

O remetente continuará sendo encaminhado para o financeiro.

================================================================================
```

### Mensagem de Confirmação de Reprovação

```
================================================================================
❌ EMAIL REPROVADO COM SUCESSO
================================================================================

O email foi marcado como reprovado no sistema.

Detalhes:
- Reprovado por: [email do reprovador]
- Data/Hora: [timestamp]
- Remetente original: [email do remetente]

O remetente foi ADICIONADO À BLACKLIST e não será mais encaminhado.

================================================================================
```

---

## ✅❌ Fluxo de Aprovação e Reprovação

### Fluxo Detalhado de Aprovação

```
1. Usuário recebe email encaminhado
   ↓
2. Usuário clica em "Aprovar" ou responde com assunto "APROVAR"
   ↓
3. Email é enviado para approve@cp-fani.local
   ↓
4. ResponseHandler detecta a resposta
   ↓
5. Valida se remetente é @didier.com.br
   ↓
6. Extrai message_id do email original
   ↓
7. Atualiza banco de dados:
   - status = 'approved'
   - approved_by = [email do aprovador]
   - approved_at = [timestamp]
   ↓
8. Remetente original é mantido na whitelist
   ↓
9. Futuros emails desse remetente serão encaminhados
```

### Fluxo Detalhado de Reprovação

```
1. Usuário recebe email encaminhado
   ↓
2. Usuário clica em "Reprovar" ou responde com assunto "REPROVAR"
   ↓
3. Email é enviado para reject@cp-fani.local
   ↓
4. ResponseHandler detecta a resposta
   ↓
5. Valida se remetente é @didier.com.br
   ↓
6. Extrai message_id do email original
   ↓
7. Busca email original no banco de dados
   ↓
8. Extrai remetente ORIGINAL (não alex@didier.com.br)
   ↓
9. Adiciona remetente à blacklist permanente
   ↓
10. Atualiza banco de dados:
    - status = 'rejected'
    - rejected_by = [email do reprovador]
    - rejected_at = [timestamp]
    ↓
11. Futuros emails desse remetente serão IGNORADOS
```

### Exemplo Prático

**Cenário**: Email de `faturadigital@vivo.com.br` é encaminhado

**Aprovação**:
- Leonardo responde: "APROVAR"
- Sistema marca como aprovado
- Próximos emails da Vivo continuarão sendo encaminhados

**Reprovação**:
- Carlos responde: "REPROVAR"
- Sistema adiciona `faturadigital@vivo.com.br` à blacklist
- Próximos emails da Vivo serão IGNORADOS (não encaminhados)

---

## 🗄️ Banco de Dados

### Schema do Banco (SQLite)

```sql
-- Tabela de emails processados
CREATE TABLE processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    from_addr TEXT,
    subject TEXT,
    status TEXT DEFAULT 'pending',
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_by TEXT,
    approved_at TIMESTAMP,
    rejected_by TEXT,
    rejected_at TIMESTAMP
);

-- Índices para performance
CREATE INDEX idx_message_id ON processed_emails(message_id);
CREATE INDEX idx_status ON processed_emails(status);
CREATE INDEX idx_from_addr ON processed_emails(from_addr);
```

### Status Possíveis

| Status | Descrição |
|--------|-----------|
| `pending` | Email aguardando processamento |
| `forwarded` | Email encaminhado com sucesso |
| `filtered` | Email filtrado (não atende critérios) |
| `blacklisted` | Email ignorado (remetente na blacklist) |
| `approved` | Email aprovado por usuário |
| `rejected` | Email reprovado por usuário |

### Consultas Úteis

```sql
-- Estatísticas gerais
SELECT status, COUNT(*) as total
FROM processed_emails
GROUP BY status;

-- Emails aprovados por usuário
SELECT approved_by, COUNT(*) as total
FROM processed_emails
WHERE status = 'approved'
GROUP BY approved_by;

-- Emails reprovados por usuário
SELECT rejected_by, COUNT(*) as total
FROM processed_emails
WHERE status = 'rejected'
GROUP BY rejected_by;

-- Emails recentes (últimos 7 dias)
SELECT *
FROM processed_emails
WHERE processed_at >= datetime('now', '-7 days')
ORDER BY processed_at DESC;
```

---

## 🚀 Deploy e Automação

### Script de Instalação (install.sh)

```bash
#!/bin/bash
# Script de instalação do Sistema de Encaminhamento de Emails

set -e

echo "=========================================="
echo "Instalando Sistema de Encaminhamento"
echo "=========================================="

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 não encontrado. Instalando..."
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv
fi

# Criar ambiente virtual
echo "📦 Criando ambiente virtual..."
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
echo "📦 Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

# Criar diretórios
echo "📁 Criando diretórios..."
mkdir -p logs logs/archive data
chmod 755 logs data

# Inicializar banco de dados
echo "🗄️ Inicializando banco de dados..."
python -m database.database --init

# Configurar cron
echo "⏰ Configurando cron job..."
(crontab -l 2>/dev/null; echo "0 * * * * cd $(pwd) && $(pwd)/venv/bin/python -m src.main >> logs/cron.log 2>&1") | crontab -

echo "=========================================="
echo "✅ Instalação concluída!"
echo "=========================================="
echo ""
echo "Próximos passos:"
echo "1. Edite o arquivo .env com suas credenciais"
echo "2. Teste a conexão: python -m src.main --test-connection"
echo "3. Execute manualmente: python -m src.main"
echo ""
```

### Script de Backup (backup.sh)

```bash
#!/bin/bash
# Script de backup do sistema

BACKUP_DIR="backups"
DATE=$(date +%Y%m%d_%H%M%S)

echo "🔄 Iniciando backup..."

# Criar diretório de backup
mkdir -p $BACKUP_DIR

# Backup do banco de dados
echo "📦 Backup do banco de dados..."
cp data/pending_emails.db $BACKUP_DIR/pending_emails_$DATE.db

# Backup da blacklist
echo "📦 Backup da blacklist..."
cp data/blacklist.txt $BACKUP_DIR/blacklist_$DATE.txt

# Compactar
echo "📦 Compactando..."
tar -czf $BACKUP_DIR/backup_$DATE.tar.gz data/

# Remover backups antigos (manter últimos 30 dias)
echo "🧹 Limpando backups antigos..."
find $BACKUP_DIR -name "backup_*.tar.gz" -mtime +30 -delete

echo "✅ Backup concluído: $BACKUP_DIR/backup_$DATE.tar.gz"
```

### Configuração do Cron

```bash
# Editar crontab
crontab -e

# Adicionar as seguintes linhas:

# Executar a cada 1 hora
0 * * * * cd /home/usuario/Projects/encaminhamento-email && /home/usuario/Projects/encaminhamento-email/venv/bin/python -m src.main >> logs/cron.log 2>&1

# Backup diário às 2h da manhã
0 2 * * * cd /home/usuario/Projects/encaminhamento-email && ./scripts/backup.sh >> logs/backup.log 2>&1

# Limpar logs antigos semanalmente (domingo às 3h)
0 3 * * 0 cd /home/usuario/Projects/encaminhamento-email && find logs -name "*.log" -mtime +30 -delete
```

---

## 🔧 Manutenção

### Monitoramento

```bash
# Ver logs em tempo real
tail -f logs/forwarder.log

# Ver estatísticas do banco
python -c "from database.database import Database; import json; db = Database('data/pending_emails.db'); print(json.dumps(db.get_statistics(), indent=2))"

# Ver blacklist
cat data/blacklist.txt

# Ver emails recentes no banco
sqlite3 data/pending_emails.db "SELECT * FROM processed_emails ORDER BY processed_at DESC LIMIT 10;"
```

### Limpeza de Logs

```bash
# Remover logs com mais de 30 dias
find logs -name "*.log" -mtime +30 -delete

# Compactar logs antigos
gzip logs/archive/*.log
```

### Adicionar/Remover da Blacklist Manualmente

```bash
# Adicionar à blacklist
echo "email@example.com" >> data/blacklist.txt

# Remover da blacklist
sed -i '/email@example.com/d' data/blacklist.txt

# Ver blacklist
cat data/blacklist.txt
```

### Reset do Sistema

```bash
# ATENÇÃO: Isso removerá todos os dados!

# Parar cron
crontab -e
# Remover linha do cron

# Limpar banco
rm data/pending_emails.db
python -m database.database --init

# Limpar blacklist (opcional)
> data/blacklist.txt

# Limpar logs
rm logs/*.log

# Reiniciar cron
crontab -e
# Adicionar linha do cron novamente
```

---

## 🐛 Troubleshooting

### Problema: Erro de Conexão IMAP

**Sintoma**:
```
ERROR: IMAP connection failed: [Errno 111] Connection refused
```

**Solução**:
1. Verificar credenciais no `.env`
2. Verificar se IMAP está habilitado no Gmail
3. Verificar firewall: `sudo ufw allow 993/tcp`
4. Testar conexão: `python -m src.main --test-connection`

### Problema: Emails Não Estão Sendo Encaminhados

**Sintoma**: Emails chegam mas não são encaminhados

**Solução**:
1. Verificar logs: `tail -f logs/forwarder.log`
2. Verificar filtros em `src/filter_engine.py`
3. Verificar se remetente está na blacklist: `grep "email@example.com" data/blacklist.txt`
4. Verificar data inicial: `START_DATE` no `.env`

### Problema: Botões Não Funcionam

**Sintoma**: Usuário clica em aprovar/reprovar mas nada acontece

**Solução**:
1. Verificar se emails de resposta estão chegando
2. Verificar configuração de `APPROVE_EMAIL` e `REJECT_EMAIL` no `.env`
3. Verificar logs de resposta: `grep "ResponseHandler" logs/forwarder.log`
4. Testar manualmente: enviar email com assunto "APROVAR" para o sistema

### Problema: Banco de Dados Corrompido

**Sintoma**: Erros de SQLite

**Solução**:
```bash
# Fazer backup
cp data/pending_emails.db data/pending_emails.db.backup

# Verificar integridade
sqlite3 data/pending_emails.db "PRAGMA integrity_check;"

# Se corrompido, recriar
rm data/pending_emails.db
python -m database.database --init
```

### Problema: Cron Não Está Executando

**Sintoma**: Sistema não executa automaticamente

**Solução**:
```bash
# Verificar se cron está ativo
systemctl status cron

# Verificar crontab
crontab -l

# Ver logs do cron
grep CRON /var/log/syslog

# Testar manualmente
cd /home/usuario/Projects/encaminhamento-email
./venv/bin/python -m src.main
```

### Problema: Permissão Negada

**Sintoma**: `Permission denied` ao executar scripts

**Solução**:
```bash
# Dar permissão de execução
chmod +x scripts/*.sh

# Verificar permissões dos diretórios
chmod 755 logs data

# Verificar proprietário
sudo chown -R usuario:usuario .
```

---

## 🗺️ Roadmap

### Versão 1.1 (Próximas Semanas)

- [ ] Interface web para gerenciamento
- [ ] Dashboard de estatísticas
- [ ] Notificações por Telegram/Slack
- [ ] Suporte a múltiplas contas de email

### Versão 1.2 (Próximos Meses)

- [ ] API REST para integrações
- [ ] Sistema de regras customizáveis via interface
- [ ] Relatórios automáticos semanais
- [ ] Integração com ERP

### Versão 2.0 (Futuro)

- [ ] Machine Learning para classificação automática
- [ ] Detecção de fraudes em boletos
- [ ] OCR para extração de dados de PDFs
- [ ] Integração com sistemas contábeis

---

## 📞 Suporte

Para dúvidas ou problemas:

1. Consulte este README
2. Verifique os logs em `logs/forwarder.log`
3. Entre em contato com a equipe de TI
4. Abra uma issue no repositório (se aplicável)

---

## 📄 Licença

Projeto privado - CP Fani / Didier  
Todos os direitos reservados © 2026

---

## 📝 Changelog

### Versão 1.0.0 (Setembro 2026)
- ✨ Sistema inicial de encaminhamento
- ✨ Filtros de domínio, remetente e assunto
- ✨ Botões de Aprovar/Reprovar
- ✨ Blacklist permanente
- ✨ Banco de dados SQLite
- ✨ Sistema de logs
- ✨ Automação via cron

---

**Fim do Documento**