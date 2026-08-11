# QuantB3 — Cockpit Quantitativo B3

**Versão:** 1.0 (Operação Simulada)
**Modelo:** `LightGBM_Fwd10_Sticky_LiqP10_Realistic` (v2.1)
**Stack:** Python 3.11 · Supabase · GitHub Actions · Streamlit Cloud

> ⚠️ **OPERAÇÃO SIMULADA — SEM CAPITAL REAL**
> Este sistema realiza paper trading para validação do modelo durante ~2 meses.

---

## Visão Geral

O QuantB3 é um cockpit quantitativo para acompanhamento de sinais semanais de compra/venda no universo IBRX (B3), baseado em modelo LightGBM com:

- **Sinal:** Retorno forward de 10 pregões (LightGBM regressor)
- **Carteira:** Top 8 ações com peso igual (R$ 250/posição)
- **Sticky turnover:** Mantém posições no top N+4 para reduzir rotatividade
- **Filtro de liquidez:** Volume médio 21d ≥ Percentil 10 do universo
- **Gestão de risco:** Stop -5% / Take 1:2,5
- **Ciclo:** Segunda (sinal) → Terça (execução simulada) → Quarta (reconciliação)

---

## Arquitetura

```
GitHub Actions (cron)
    │
    ├── Segunda 18:30 BRT → monday.py   → sinais + e-mail + Telegram
    ├── Terça   18:30 BRT → tuesday.py  → execução simulada + notas
    ├── Quarta  12:00 BRT → wednesday.py → reconciliação + equity
    └── Diário  19:00 BRT → daily_prices.py → atualiza OHLCV
                                │
                         Supabase (PostgreSQL)
                                │
                    Streamlit Cloud (dashboard)
```

## Memoriais Descritivos

O memorial operacional, do modelo LightGBM, da engenharia de software e do
simulador OHLCV está consolidado em
[docs/MEMORIAIS_DESCRITIVOS.md](docs/MEMORIAIS_DESCRITIVOS.md). Consulte-o
antes de alterar parâmetros, workflows ou rotinas de carga.

---

## Pré-requisitos

- Conta no [GitHub](https://github.com) (gratuita)
- Conta no [Supabase](https://supabase.com) (gratuita)
- Conta no [Streamlit Community Cloud](https://streamlit.io/cloud) (gratuita)
- Bot do Telegram criado via [@BotFather](https://t.me/BotFather)
- Conta no [Brevo](https://brevo.com) ou [Resend](https://resend.com) para e-mail (gratuito)

---

## Guia de Deploy Passo a Passo

### Passo 1 — Configurar o Supabase

1. Acesse [supabase.com](https://supabase.com) e crie um novo projeto
2. Anote a **Connection String** em: *Project Settings → Database → Connection string → URI*
3. No **SQL Editor**, execute o conteúdo de `sql/schema.sql`
4. Verifique se as tabelas foram criadas: `prices`, `signals`, `orders`, `positions`, `equity`, `notifications`, `runs`

> **Atenção:** O projeto Supabase pausa após 7 dias sem atividade no free tier. O job `daily_prices` (que roda todo dia útil) evita isso automaticamente.

### Passo 2 — Criar o repositório no GitHub

```bash
# Clone ou crie um novo repositório
git init quantb3
cd quantb3

# Copie todos os arquivos deste projeto
# Configure o .gitignore (já incluído)

git add .
git commit -m "QuantB3 v1.0 — setup inicial"
git remote add origin https://github.com/SEU_USUARIO/quantb3.git
git push -u origin main
```

> **Importante:** Use repositório **público** para aproveitar os minutos ilimitados do GitHub Actions. Os secrets ficam protegidos nas configurações do repositório.

### Passo 3 — Configurar GitHub Secrets

Em *Settings → Secrets and variables → Actions → New repository secret*, adicione:

| Nome | Valor |
|------|-------|
| `DATABASE_URL` | Connection string do Supabase |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | ID do seu chat com o bot |
| `EMAIL_PROVIDER` | `brevo`, `resend` ou `smtp` |
| `EMAIL_API_KEY` | API key do provedor de e-mail |
| `EMAIL_FROM` | E-mail remetente |
| `EMAIL_TO` | Seu e-mail |
| `EMAIL_SMTP_HOST` | Host SMTP (Yahoo: `smtp.mail.yahoo.com`) |
| `EMAIL_SMTP_PORT` | Porta SMTP SSL (Yahoo: `465`) |
| `EMAIL_SMTP_PASSWORD` | Senha de aplicativo SMTP |

### Passo 4 — Carga inicial dos dados históricos

```bash
# Instale as dependências localmente
pip install -r requirements.txt

# Configure o .env local
cp .env.example .env
# Edite .env com DATABASE_URL e demais variáveis

# Execute a carga inicial do CSV histórico
python scripts/load_initial_data.py cotacoes_ibrx_ohlcv_completo.csv
```

> Isso carrega ~4 anos de dados OHLCV para o Supabase (≈ 50-100 MB).

### Passo 5 — Configurar o Telegram Bot

1. Abra o Telegram e inicie uma conversa com [@BotFather](https://t.me/BotFather)
2. Digite `/newbot` e siga as instruções
3. Anote o **token** gerado
4. Para obter seu **chat_id**: inicie uma conversa com o bot e acesse:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. O `chat_id` aparece em `result[0].message.from.id`

### Passo 6 — Configurar e-mail (Brevo)

1. Crie conta em [brevo.com](https://brevo.com) (gratuito: 300 e-mails/dia)
2. Acesse *SMTP & API → API Keys → Create a new API key*
3. Verifique o e-mail remetente em *Senders & IPs → Senders*
4. Configure `EMAIL_PROVIDER=brevo`, `EMAIL_API_KEY`, `EMAIL_FROM`, `EMAIL_TO`

**Alternativa — Resend:**
1. Crie conta em [resend.com](https://resend.com) (gratuito: 3.000 e-mails/mês)
2. Configure `EMAIL_PROVIDER=resend` e os demais campos

**Alternativa — Yahoo Mail (senha de aplicativo):**
1. Crie uma senha de aplicativo na segurança da sua conta Yahoo.
2. Configure `EMAIL_PROVIDER=smtp`, `EMAIL_FROM` com seu Yahoo e
   `EMAIL_SMTP_PASSWORD` com a senha gerada.

### Passo 7 — Deploy no Streamlit Cloud

1. Acesse [share.streamlit.io](https://share.streamlit.io) e conecte com GitHub
2. Clique em **New app**
3. Configure:
   - **Repository:** `SEU_USUARIO/quantb3`
   - **Branch:** `main`
   - **Main file path:** `dashboard/app.py`
4. Em **Advanced settings → Secrets**, adicione o conteúdo de `dashboard/.streamlit/secrets.toml.example` preenchido com seus valores reais
5. Clique em **Deploy**

### Passo 8 — Configurar senha do dashboard

```bash
# Gere o hash da sua senha
python scripts/generate_password_hash.py

# Copie o hash gerado e adicione:
# - No GitHub Secrets como DASHBOARD_PASSWORD_HASH
# - No Streamlit Secrets como DASHBOARD_PASSWORD_HASH = "hash_aqui"
```

### Passo 9 — Testar os jobs manualmente

No GitHub, acesse *Actions* e execute manualmente cada workflow:

1. **daily_prices** — Atualiza preços (teste primeiro)
2. **monday_signals** — Gera sinais (pode demorar 5-10 min pelo treinamento LGBM)
3. **tuesday_execution** — Executa ordens simuladas
4. **wednesday_reconcile** — Reconcilia carteira

---

## Estrutura do Projeto

```
quantb3/
├── README.md                          # Este arquivo
├── requirements.txt                   # Dependências Python
├── .env.example                       # Template de variáveis de ambiente
├── .gitignore
├── .github/workflows/
│   ├── daily_prices.yml               # Job diário de preços
│   ├── monday_signals.yml             # Job de sinais (segunda)
│   ├── tuesday_execution.yml          # Job de execução (terça)
│   └── wednesday_reconcile.yml        # Job de reconciliação (quarta)
├── config/
│   └── settings.py                    # Parâmetros centrais do modelo
├── sql/
│   └── schema.sql                     # Schema do banco de dados
├── src/
│   ├── db/
│   │   ├── connection.py              # Conexão Supabase/PostgreSQL
│   │   └── repositories.py           # CRUD para todas as tabelas
│   ├── data/
│   │   └── collector.py              # Coleta OHLCV via yfinance
│   ├── features/
│   │   └── engineering.py            # 18 features do modelo LGBM
│   ├── model/
│   │   ├── train_predict.py          # Treinamento walk-forward LGBM
│   │   └── ranking.py               # Ranking + sticky + ordens
│   ├── execution/
│   │   └── simulator.py             # Preço triangular + slippage
│   ├── reporting/
│   │   └── signal_report.py         # Relatórios de sinais e notas
│   ├── notify/
│   │   ├── telegram_sender.py       # Notificações Telegram
│   │   └── email_sender.py          # Notificações e-mail
│   └── jobs/
│       ├── monday.py                # Job segunda-feira
│       ├── tuesday.py               # Job terça-feira
│       ├── wednesday.py             # Job quarta-feira
│       └── daily_prices.py          # Job diário de preços
├── dashboard/
│   ├── app.py                       # Dashboard Streamlit
│   └── .streamlit/
│       ├── config.toml              # Configuração visual
│       └── secrets.toml.example     # Template de secrets
├── scripts/
│   ├── load_initial_data.py         # Carga inicial do CSV histórico
│   └── generate_password_hash.py    # Gerador de hash de senha
├── quantb3_model.py                 # Modelo original (referência)
├── quantb3_ohlcv_simulator_v2.py    # Simulador OHLCV (referência)
└── quantb3_exemplo_backtest.py      # Exemplo de backtest
```

---

## Parâmetros do Modelo (Congelados — v2.1)

| Parâmetro | Valor |
|-----------|-------|
| Capital | R$ 2.000,00 |
| Posições | 8 |
| Target LGBM | Retorno forward 10d |
| Treino mínimo | 378 dias |
| Liquidez | Volume médio 21d ≥ P10 |
| Sticky buffer | 4 |
| Stop Loss | -5% |
| Take Profit | 1:2,5 |
| Slippage entrada | 0,05% |
| Slippage stop | 0,10% |
| Slippage take | 0,05% |
| Emolumentos B3 | 0,03% |

---

## Ciclo Operacional

| Dia | Horário (BRT) | Ação |
|-----|---------------|------|
| Segunda | ~18:30 | Gera sinais LGBM → relatório → e-mail + Telegram |
| Terça | ~18:30 | Executa ordens simuladas → notas → e-mail + Telegram |
| Quarta | ~12:00 | Reconcilia carteira → atualiza equity → notifica |
| Diário | ~19:00 | Atualiza preços OHLCV (mantém Supabase ativo) |

---

## Desenvolvimento Local

```bash
# Clonar repositório
git clone https://github.com/SEU_USUARIO/quantb3.git
cd quantb3

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente
cp .env.example .env
# Edite .env com seus valores

# Aplicar schema no Supabase (via SQL Editor)
# Conteúdo: sql/schema.sql

# Carga inicial de dados
python scripts/load_initial_data.py cotacoes_ibrx_ohlcv_completo.csv

# Testar job de segunda manualmente
python -m src.jobs.monday

# Rodar dashboard localmente
streamlit run dashboard/app.py
```

---

## Resolução de Problemas

**Job falha com erro de conexão ao banco:**
- Verifique se `DATABASE_URL` está correto no GitHub Secrets
- Confirme se o projeto Supabase não está pausado (acesse o painel)
- Teste localmente: `python -c "from src.db.connection import test_connection; print(test_connection())"`

**Sem sinais gerados:**
- Verifique se há dados suficientes no banco (mínimo 378 dias = ~1,5 anos)
- Execute `daily_prices` manualmente para garantir dados atualizados
- Verifique os logs em *GitHub Actions → monday_signals → último run*

**Dashboard não carrega:**
- Verifique se `DATABASE_URL` está nos Streamlit Secrets
- Confirme se o app está ativo no Streamlit Cloud (pode adormecer após 12h sem acesso)
- Acesse o app para "acordá-lo" e aguarde ~30 segundos

**Telegram não recebe mensagens:**
- Verifique `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`
- Certifique-se de ter iniciado uma conversa com o bot antes
- Teste: `curl "https://api.telegram.org/bot<TOKEN>/getMe"`

---

## Segurança

- Nenhum secret deve ser commitado no repositório
- Use sempre GitHub Secrets para variáveis sensíveis nos workflows
- Use Streamlit Secrets para variáveis no dashboard
- O arquivo `.env` é apenas para desenvolvimento local e está no `.gitignore`
- A senha do dashboard é armazenada apenas como hash SHA-256

---

## Referências

- [Memoriais Descritivos consolidados](docs/MEMORIAIS_DESCRITIVOS.md)
- [Documentação Supabase](https://supabase.com/docs)
- [Documentação Streamlit](https://docs.streamlit.io)
- [GitHub Actions — Scheduled Workflows](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)
