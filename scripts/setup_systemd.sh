#!/bin/bash
# ==============================================================================
# CP FANI - Script de Instalação e Setup de Serviço (systemd user)
# SO Alvo: Zorin OS / Ubuntu / Debian
# ==============================================================================

set -e

APP_NAME="cpfani"
INSTALL_DIR="$HOME/$APP_NAME"
VENV_DIR="$INSTALL_DIR/venv"
PYTHON_BIN="python3"

echo "======================================================================"
echo " CP FANI - Instalador de Serviço Automático (Zorin/Linux)"
echo "======================================================================"

# 1. Preparar diretórios
echo "[1/6] Criando diretórios em $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"/{config,data,logs,src,database,scripts}

# 2. Copiar código (assumindo que o script está rodando de dentro da pasta do projeto)
echo "[2/6] Copiando arquivos do projeto..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cp -r "$PROJECT_ROOT/src" "$INSTALL_DIR/"
cp -r "$PROJECT_ROOT/database" "$INSTALL_DIR/"
cp -r "$PROJECT_ROOT/config" "$INSTALL_DIR/"
cp "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/" 2>/dev/null || echo "requirements.txt não encontrado, pulando..."

# 3. Criar ambiente virtual e instalar dependências
echo "[3/6] Criando ambiente virtual Python..."
$PYTHON_BIN -m venv "$VENV_DIR"
echo "[3/6] Instalando dependências (python-dotnet, etc)..."
"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
else
    "$VENV_DIR/bin/pip" install python-dotenv
fi

# 4. Configurar .env (se não existir)
if [ ! -f "$INSTALL_DIR/config/.env" ]; then
    echo "[4/6] ⚠️  AVISO: Arquivo .env não encontrado em config/.env!"
    echo "       Copie seu .env para $INSTALL_DIR/config/.env e preencha as credenciais."
else
    echo "[4/6] Arquivo .env detectado."
fi

# 5. Criar arquivos do systemd (User-level)
echo "[5/6] Configurando serviços do systemd (user)..."
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

# Service file
cat > "$SYSTEMD_USER_DIR/$APP_NAME.service" <<EOF
[Unit]
Description=CP FANI - Sistema de Encaminhamento de Emails
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/src/main.py
StandardOutput=append:$INSTALL_DIR/logs/cpfani.log
StandardError=append:$INSTALL_DIR/logs/cpfani_error.log

# Segurança básica (Sandboxing)
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR/data $INSTALL_DIR/logs
EOF

# Timer file (roda a cada hora, conforme POLL_INTERVAL_MINUTES=60)
cat > "$SYSTEMD_USER_DIR/$APP_NAME.timer" <<EOF
[Unit]
Description=Timer para CP FANI (Executa a cada hora)

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true
Unit=$APP_NAME.service

[Install]
WantedBy=timers.target
EOF

# 6. Habilitar e iniciar
echo "[6/6] Habilitando timer e configurando linger..."
systemctl --user daemon-reload
systemctl --user enable --now "$APP_NAME.timer"

# Habilitar linger para o serviço rodar mesmo sem o usuário logado na interface gráfica
if command -v loginctl &> /dev/null; then
    sudo loginctl enable-linger "$USER" 2>/dev/null || echo "⚠️  AVISO: Não foi possível habilitar linger (requer senha de sudo). Execute manualmente: sudo loginctl enable-linger $USER"
fi

echo "======================================================================"
echo " ✅ INSTALAÇÃO CONCLUÍDA!"
echo "======================================================================"
echo " O timer foi ativado e rodará a cada 1 hora."
echo " "
echo " Comandos úteis no Zorin:"
echo "   Ver status do timer:   systemctl --user status $APP_NAME.timer"
echo "   Ver logs de execução:  tail -f $INSTALL_DIR/logs/cpfani.log"
echo "   Rodar manualmente:     systemctl --user start $APP_NAME.service"
echo "   Desativar:             systemctl --user disable --now $APP_NAME.timer"
echo "======================================================================"