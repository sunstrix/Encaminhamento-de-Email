#!/bin/bash
# ==============================================================================
# CP FANI - SISTEMA DE ENCAMINHAMENTO DE EMAILS
# ==============================================================================
# Script de Instalação e Setup Inicial
# Cria a estrutura de diretórios e arquivos necessária para a primeira execução.
#
# Uso: bash install.sh
# ==============================================================================

# Interrompe a execução imediatamente se qualquer comando falhar
set -e

echo "=================================================="
echo "CP FANI - Instalacao Automatizada"
echo "=================================================="

# ------------------------------------------------------------------------------
# 1. CRIAÇÃO DE DIRETÓRIOS (Idempotente)
# ------------------------------------------------------------------------------
# Garante que as pastas de logs e dados existam antes da primeira execução.
echo "[1/4] Criando estrutura de diretorios..."
mkdir -p logs
mkdir -p logs/archive
mkdir -p data
echo "  -> Diretórios criados/verificados: logs/, logs/archive/, data/"

# ------------------------------------------------------------------------------
# 2. CRIAÇÃO DE ARQUIVOS BASE (Idempotente)
# ------------------------------------------------------------------------------
# Cria os arquivos de controle apenas se não existirem, preservando conteúdo
# existente em re-execuções.
echo "[2/4] Criando arquivos de configuracao e dados base..."

# Blacklist unificada (fonte primária para o FilterEngine)
if [ ! -f "data/blacklist.txt" ]; then
    echo "# Blacklist de remetentes bloqueados (um email por linha)" > data/blacklist.txt
    echo "# Linhas iniciadas com # são ignoradas" >> data/blacklist.txt
    echo "  -> Criado: data/blacklist.txt"
else
    echo "  -> Já existe: data/blacklist.txt (mantido)"
fi

# Whitelist de remetentes confiáveis
if [ ! -f "data/whitelist.txt" ]; then
    echo "# Whitelist de remetentes confiáveis (um email por linha)" > data/whitelist.txt
    echo "  -> Criado: data/whitelist.txt"
else
    echo "  -> Já existe: data/whitelist.txt (mantido)"
fi

# Baseline de emails únicos (usado pelo FilterEngine)
if [ ! -f "data/emails_unicos.txt" ]; then
    touch data/emails_unicos.txt
    echo "  -> Criado: data/emails_unicos.txt (vazio)"
else
    echo "  -> Já existe: data/emails_unicos.txt (mantido)"
fi

# ------------------------------------------------------------------------------
# 3. CONFIGURAÇÃO DO AMBIENTE VIRTUAL PYTHON
# ------------------------------------------------------------------------------
echo "[3/4] Configurando ambiente virtual Python..."
if [ ! -d ".venv" ]; then
    echo "  -> Criando novo ambiente virtual (.venv)..."
    python3 -m venv .venv
else
    echo "  -> Ambiente virtual já existe (.venv)"
fi

# ------------------------------------------------------------------------------
# 4. INSTALAÇÃO DE DEPENDÊNCIAS
# ------------------------------------------------------------------------------
echo "[4/4] Instalando dependências do projeto..."
# Ativa o ambiente virtual
source .venv/bin/activate

# Atualiza pip e instala dependências
pip install --upgrade pip > /dev/null 2>&1 || echo "Aviso: Falha ao atualizar pip, continuando..."
pip install -r requirements.txt

echo "=================================================="
echo "✅ Instalacao concluida com sucesso!"
echo "=================================================="
echo ""
echo "PROXIMOS PASSOS:"
echo "1. Copie o modelo de configuração:"
echo "   cp .env.example .env"
echo ""
echo "2. Edite o .env com suas credenciais IMAP/SMTP:"
echo "   nano .env"
echo ""
echo "3. Ative o ambiente virtual:"
echo "   source .venv/bin/activate"
echo ""
echo "4. Teste a conexão com os servidores de email:"
echo "   python -m src.main --test-connection"
echo ""
echo "5. Execute em modo teste (sem enviar emails):"
echo "   python -m src.main --dry-run"
echo "=================================================="