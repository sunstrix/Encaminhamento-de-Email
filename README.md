# 📧 Sistema de Encaminhamento de Emails — CP FANI

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![SQLite](https://img.shields.io/badge/SQLite-3.39+-003B57?logo=sqlite)
![Status](https://img.shields.io/badge/Status-Produção-brightgreen)
![Plataforma](https://img.shields.io/badge/Plataforma-Windows%20%7C%20Linux-lightgrey)
![Licença](https://img.shields.io/badge/Licença-MIT-green)

Sistema de **fallback automático** para encaminhamento de e-mails financeiros. Monitora uma caixa de entrada via IMAP, aplica regras de filtro, identifica valores monetários e encaminha automaticamente para o setor financeiro — com fluxo de **aprovação humana** para e-mails de alto valor ou suspeitos.

---

## 🎯 Objetivo

O sistema automatiza o processamento de e-mails recebidos, resolvendo o problema de e-mails financeiros importantes que se perdem na caixa de entrada. Ele permite:

- Monitorar uma conta de e-mail via IMAP em intervalos regulares;
- Filtrar automaticamente remetentes confiáveis, internos, ruídos e spam;
- Extrair valores monetários (R$) do corpo dos e-mails;
- Encaminhar e-mails aprovados diretamente para o financeiro;
- Exigir **aprovação humana** para e-mails com valor acima de um limite configurável;
- Manter blacklist/whitelist gerenciáveis por arquivo e banco de dados;
- Gerar relatório semanal de estatísticas;
- Registrar tudo em logs com auditoria completa.

---

## 🏗️ Arquitetura

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Cron Job    │────▶│  main.py     │────▶│ IMAP Handler │
│  (hourly)    │     │ Orquestrador │     │  (leitura)   │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │                    │
                            ▼                    ▼
                     ┌──────────────┐     ┌──────────────┐
                     │ Filter Engine│◀────│ SQLite DB    │
                     │ (regras)     │     │ (persistência)│
                     └──────┬───────┘     └──────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
       ┌──────────────┐           ┌──────────────┐
       │ SMTP Handler │           │ Response     │
       │ (envio)      │           │ Handler      │
       └──────────────┘           │ (aprovação)  │
                                  └──────────────┘
```

| Componente | Responsabilidade |
| :--- | :--- |
| `main.py` | Orquestra o pipeline completo, CLI e ciclo contínuo |
| `imap_handler.py` | Conecta ao IMAP, busca e-mails não lidos e faz o parse |
| `filter_engine.py` | Aplica regras de negócio e classifica cada e-mail |
| `smtp_handler.py` | Envia e-mails de aprovação e encaminha para o financeiro |
| `response_handler.py` | Processa respostas APROVAR_/REPROVAR_ do aprovador |
| `button_handler.py` | Gera o corpo HTML com botões de aprovação |
| `database.py` | Persistência SQLite (aprovações, blacklist, whitelist, histórico) |
| `settings.py` | Configurações centralizadas via `.env` |

---

## 🛠️ Stack Técnica

| Componente | Tecnologia | Observação |
| :--- | :--- | :--- |
| Linguagem | Python | ≥ 3.10 |
| Configuração | python-dotenv | Carrega variáveis do `.env` |
| Datas | python-dateutil | Parse de datas RFC 2822 dos headers |
| Templates | jinja2 | Renderização de e-mails (opcional) |
| HTML | beautifulsoup4 | Extração de texto de e-mails HTML |
| Banco de dados | SQLite | Stdlib (`sqlite3`), sem servidor externo |
| IMAP / SMTP | imaplib / smtplib | Stdlib do Python |

---

## 📂 Estrutura do Projeto

```
Encaminhamento-de-Email/
 ├── README.md                  # Documentação do projeto
 ├── requirements.txt           # Dependências Python
 ├── .env.example               # Modelo de configuração (copie para .env)
 ├── .gitignore                 # Arquivos ignorados pelo Git
 ├── config/
 │   ├── __init__.py
 │   └── settings.py            # Configurações centralizadas
 ├── database/
 │   ├── __init__.py
 │   └── database.py            # Persistência SQLite
 ├── data/                      # Dados locais (criada na instalação)
 │   ├── blacklist.txt          # Blacklist unificada de remetentes
 │   ├── whitelist.txt          # Whitelist de remetentes
 │   ├── emails_unicos.txt      # Baseline de e-mails únicos
 │   └── pending_emails.db      # Banco SQLite (gerado automaticamente)
 ├── logs/                      # Logs de execução
 │   └── archive/               # Logs antigos
 └── src/
     ├── __init__.py
     ├── main.py                # Orquestrador principal
     ├── imap_handler.py        # Leitura via IMAP
     ├── filter_engine.py       # Motor de regras
     ├── smtp_handler.py        # Envio via SMTP
     ├── response_handler.py    # Processamento de respostas
     └── button_handler.py      # Geração de botões de aprovação
```

---

## ▶️ Instalação e Configuração

### 1. Pré-requisitos

- **Python 3.10 ou superior** instalado e adicionado ao PATH;
- Uma conta de e-mail com **acesso IMAP e SMTP** habilitado;
- Sistema operacional Windows ou Linux.

### 2. Clonar o repositório

```powershell
git clone https://github.com/sunstrix/Encaminhamento-de-Email.git
cd Encaminhamento-de-Email
```

### 3. Criar e ativar o ambiente virtual

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Se houver bloqueio de execução de scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

**Linux / Mac:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instalar as dependências

```powershell
pip install -r requirements.txt
```

### 5. Criar a estrutura de pastas e arquivos locais

```powershell
New-Item -ItemType Directory -Force -Path "logs", "logs/archive", "data"
New-Item -ItemType File -Force -Path "data/blacklist.txt", "data/whitelist.txt"
```

### 6. Configurar o arquivo `.env`

Copie o modelo e edite com suas credenciais:

```powershell
Copy-Item .env.example .env
notepad .env
```

> ⚠️ **IMPORTANTE:** Nunca commite o arquivo `.env` no Git. Ele já está no `.gitignore`.

---

## 🔐 Configuração de Credenciais

### Gmail (obrigatório usar Senha de App)

O Gmail **não permite** mais autenticação com a senha normal da conta. Você precisa gerar uma **Senha de App**:

1. Acesse sua conta Google: https://myaccount.google.com/security
2. Habilite a **Verificação em duas etapas** (obrigatório para gerar senha de app);
3. Acesse: https://myaccount.google.com/apppasswords
4. Selecione o app "E-mail" e o dispositivo "Outro (nome personalizado)";
5. Clique em **Gerar** e copie a senha de 16 caracteres;
6. Use essa senha no `.env` em `IMAP_PASS` e `SMTP_PASS`.

Configuração típica para Gmail no `.env`:

```ini
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

### GoDaddy / Office365 / Outros

Use as configurações fornecidas pelo seu provedor. Exemplo para GoDaddy:

```ini
IMAP_SERVER=imap.secureserver.net
IMAP_PORT=993
SMTP_SERVER=smtpout.secureserver.net
SMTP_PORT=465
```

### Variáveis essenciais do `.env`

| Variável | Descrição | Obrigatória |
| :--- | :--- | :--- |
| `IMAP_SERVER` | Servidor IMAP | ✅ |
| `IMAP_USER` | Conta que será monitorada | ✅ |
| `IMAP_PASS` | Senha ou Senha de App | ✅ |
| `SMTP_SERVER` | Servidor SMTP | ✅ |
| `FINANCEIRO_EMAIL` | Destinatário final dos e-mails aprovados | ✅ |
| `APPROVAL_EMAIL` | Quem recebe os pedidos de aprovação | ✅ |
| `START_DATE` | Data inicial para buscar e-mails (AAAA-MM-DD) | ✅ |
| `DB_PATH` | Caminho do banco SQLite | ✅ |

---

## 📋 Fluxo de Aprovação

```
E-mail recebido
      │
      ▼
  ┌───────────────┐
  │  Filtro       │
  └───────┬───────┘
          │
    ┌─────┴──────────────────────────────┐
    ▼                                    ▼
FORWARD                          PENDING_APPROVAL
(encaminha direto)               (valor alto / suspeito)
    │                                    │
    ▼                                    ▼
Financeiro                        E-mail enviado ao
recebe o e-mail                   aprovador com botões
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                        APROVAR_              REPROVAR_
                        (encaminha)           (descarta)
                              │
                              ▼
                        Financeiro
                        recebe o e-mail
```

1. E-mails com valor **abaixo** do limite são encaminhados diretamente;
2. E-mails com valor **acima** do limite geram um pedido de aprovação;
3. O aprovador recebe um e-mail com o contexto e o valor detectado;
4. O aprovador responde com `APROVAR_` ou `REPROVAR_`;
5. O sistema processa a resposta e executa a ação correspondente.

---

## 🚀 Como Usar

### Testar a conexão (diagnóstico)

Verifica se as credenciais IMAP e SMTP estão corretas:

```powershell
python -m src.main --test-connection
```

### Execução em modo teste (não envia nada)

Ideal para validar as regras de filtro sem enviar e-mails:

```powershell
python -m src.main --dry-run
```

### Execução única

Processa a caixa de entrada uma vez e finaliza:

```powershell
python -m src.main
```

### Modo contínuo (daemon)

Fica em execução constante, verificando a caixa no intervalo definido em `POLL_INTERVAL_MINUTES`:

```powershell
python -m src.main --continuous
```

### Relatório semanal

Gera e exibe as estatísticas dos últimos 7 dias:

```powershell
python -m src.main --weekly-report
```

---

## 🧪 Testes de Integração

Após a instalação, siga este roteiro para validar o sistema de ponta a ponta:

### Passo 1 — Configurar conta de teste

Edite o `.env` com uma conta de e-mail de teste (recomendado não usar a conta de produção).

### Passo 2 — Validar conexão

```powershell
python -m src.main --test-connection
```

Resultado esperado: `✅ IMAP: Conexão bem-sucedida` e `✅ SMTP: Conexão bem-sucedida`.

### Passo 3 — Executar em modo seco

```powershell
python -m src.main --dry-run
```

Verifique os logs para confirmar que os e-mails estão sendo classificados corretamente.

### Passo 4 — Testar o fluxo de aprovação

1. Envie um e-mail de teste para a conta monitorada com um valor alto (ex: `R$ 10.000,00`);
2. Rode `python -m src.main`;
3. Verifique se a conta do aprovador recebeu o pedido de aprovação;
4. Responda com `APROVAR_` e rode novamente;
5. Confirme que o e-mail foi encaminhado para o financeiro.

---

## 🗄️ Banco de Dados

O banco SQLite é criado automaticamente na primeira execução em `DB_PATH`.

| Tabela | Finalidade |
| :--- | :--- |
| `forwarded_emails` | Histórico de e-mails já processados (evita duplicidade) |
| `pending_approvals` | Aprovações pendentes, aprovadas, reprovadas ou expiradas |
| `blacklist` | Remetentes bloqueados manualmente |
| `whitelist` | Remetentes sempre aprovados |
| `state` | Estado global (última varredura, contadores) |

### Blacklist unificada

A blacklist é carregada do arquivo `data/blacklist.txt` (um e-mail por linha). Linhas iniciadas com `#` são tratadas como comentário. Este arquivo é a fonte primária recomendada para bloqueios dinâmicos, sem necessidade de alterar código.

Exemplo de `data/blacklist.txt`:

```txt
# Remetentes de marketing
marketing@exemplo.com.br
# Notificações automáticas
no-reply@servico.com
```

---

## ⏰ Agendamento (Cron / Task Scheduler)

### Windows (Agendador de Tarefas)

1. Abra o **Agendador de Tarefas** (`taskschd.msc`);
2. Clique em **Criar Tarefa Básica**;
3. Defina o gatilho (ex: diariamente às 08:00);
4. Ação: **Iniciar um programa**;
5. Programa: caminho do `python.exe` do seu ambiente virtual;
6. Argumentos: `-m src.main`;
7. Iniciar em: caminho da pasta do projeto.

### Linux (cron)

Edite o crontab:

```bash
crontab -e
```

Adicione uma linha para rodar a cada hora:

```bash
0 * * * * cd /caminho/do/projeto && /caminho/do/.venv/bin/python -m src.main >> logs/cron.log 2>&1
```

---

## 🔧 Solução de Problemas

| Problema | Causa provável | Solução |
| :--- | :--- | :--- |
| `AUTHENTICATIONFAILED` no IMAP | Senha normal usada no Gmail | Gere uma **Senha de App** |
| `ModuleNotFoundError` | Ambiente virtual não ativado | Ative o `.venv` antes de executar |
| E-mails não encontrados | `START_DATE` muito recente | Verifique a data no `.env` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Problema de certificado | Verifique a porta IMAP/SMTP |
| Banco não criado | Pasta `data/` inexistente | Crie a pasta manualmente |
| Aprovação não processada | Resposta sem `APROVAR_` ou `REPROVAR_` | Use exatamente essas palavras |

### Verificar os logs

Os logs são gravados em `logs/cpfani_YYYYMMDD.log`. Para acompanhar em tempo real:

```powershell
Get-Content logs/cpfani_*.log -Wait -Tail 20
```

---

## 📌 Status do Projeto

- ✅ Leitura de e-mails via IMAP com parse robusto;
- ✅ Motor de filtro com regras de negócio configuráveis;
- ✅ Extração de valores monetários em R$;
- ✅ Fluxo completo de aprovação por e-mail;
- ✅ Blacklist e whitelist persistentes;
- ✅ Banco SQLite com auditoria;
- ✅ Relatório semanal de estatísticas;
- ✅ Diagnóstico de conexão via `--test-connection`.

Pronto para evolução com novos filtros, integração com APIs externas e suporte a múltiplas contas.

---

## 👤 Autor

**Alex** — Desenvolvedor BR
GitHub: [@sunstrix](https://github.com/sunstrix)

---

<div align="center">

⭐ Se este projeto foi útil, considere dar uma estrela no GitHub! ⭐
Feito com ❤️ para automatizar o encaminhamento de e-mails financeiros

</div>