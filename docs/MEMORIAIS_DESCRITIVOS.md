# Memoriais Descritivos — QuantB3

**Versão documental:** 1.1  
**Atualizado em:** 10/08/2026  
**Escopo:** operação simulada (paper trading), sem capital real.

Este documento consolida os memoriais operacional, do modelo, de engenharia e do simulador. Deve ser atualizado quando houver mudanças em modelo, coleta, workflows ou regras de execução.

## 1. Memorial Descritivo Operacional

O QuantB3 acompanha o universo IBRX da B3 e gera uma carteira semanal simulada. A operação é coordenada por GitHub Actions, com persistência no Supabase e visualização no Streamlit Cloud.

| Etapa | Workflow | Agenda (UTC) | Resultado |
|---|---|---:|---|
| Atualização de preços | `daily_prices` | Seg–Sex, 22:00 | OHLCV no Supabase |
| Geração de sinais | `monday_signals` | Segunda, 21:30 | Sinais, ordens pendentes e notificações |
| Execução simulada | `tuesday_execution` | Terça, 21:30 | Preenchimento simulado das ordens |
| Reconciliação | `wednesday_reconcile` | Quarta, 15:00 | Equity e resumo operacional |

Os workflows aceitam disparo manual. O job de segunda-feira pode criar registros em `signals` e ordens `PENDING`; portanto, não deve ser repetido indiscriminadamente.

### Notificações

Os relatórios operacionais são enviados para Telegram e e-mail. O e-mail pode usar Brevo, Resend ou SMTP. As credenciais ficam exclusivamente nos GitHub Secrets e nunca devem ser incluídas no repositório.

### Recuperação da base de preços

A coleta é feita por ticker, com timeout e tentativas individuais. Para cada ativo já existente, os últimos 100 dias são rebaixados, corrigindo lacunas recentes da fonte. Ativos sem histórico recebem carga desde 01/01/2022.

Para evitar que a carga inicial exceda o tempo do GitHub Actions, o valor padrão é quatro novos tickers por execução. O campo manual `initial_tickers_per_run` pode ampliar esse número quando necessário. O workflow diário tem limite de 60 minutos.

Ativos temporariamente indisponíveis no Yahoo Finance permanecem em uma blacklist configurável e são ignorados até nova validação.

## 2. Memorial do Modelo LightGBM

O modelo é um `LightGBMRegressor` que estima o retorno futuro de 10 pregões para ranquear os ativos elegíveis.

| Item | Configuração |
|---|---|
| Target | retorno forward de 10 pregões (`fwd_10`) |
| Treino mínimo | 378 dias |
| Carteira alvo | até 8 posições com pesos iguais |
| Liquidez | volume médio de 21 dias acima do percentil 10 |
| Sticky turnover | mantém ativos do top N+4 para reduzir giro |
| Stop loss | -5% |
| Take profit | relação risco-retorno 1:2,5 |

São calculadas 18 features de momentum, volatilidade, volume, posição de preço, excesso contra o benchmark e indicadores técnicos.

O painel de treino contém somente datas com `fwd_10` disponível. Para a data mais recente, as features são calculadas separadamente, sem exigir um retorno que ainda não existe. Essa separação permite produzir ranking no pregão atual sem vazamento de dados futuros.

## 3. Memorial de Engenharia de Software

```text
GitHub Actions → jobs Python → Supabase/PostgreSQL → Streamlit Cloud
                    ├─ yfinance (OHLCV)
                    ├─ LightGBM (ranking)
                    ├─ SMTP/API (e-mail)
                    └─ Telegram Bot API
```

As principais tabelas são `prices`, `signals`, `orders`, `positions`, `equity`, `notifications` e `runs`. A tabela `prices` usa upsert por `(date, ticker)`; por isso, a rebaixada de 100 dias corrige dados sem criar duplicidade.

Cada job registra execução na tabela `runs` e produz logs no GitHub Actions. O timeout por ticker limita bloqueios individuais do yfinance; o coletor continua com os demais ativos quando uma consulta falha.

Segredos são mantidos em GitHub Secrets e Streamlit Secrets. O acesso Excel, quando habilitado, usa credencial PostgreSQL dedicada e somente leitura. A aplicação é destinada exclusivamente a simulação.

## 4. Memorial do Simulador OHLCV

As ordens criadas na segunda-feira são simuladas na terça-feira. A execução usa a série OHLCV e aplica custos operacionais definidos em `config/settings.py`:

| Parâmetro | Valor |
|---|---:|
| Slippage de entrada | 0,05% |
| Slippage de stop | 0,10% |
| Slippage de take | 0,05% |
| Emolumentos | 0,03% |

O simulador não envia ordens a corretoras e não movimenta recursos. Os resultados são gravados no Supabase para acompanhamento no cockpit e nas rotinas de reconciliação.

## 5. Checklist para Executar Sinais

1. Confirme que `daily_prices` terminou com sucesso.
2. Confirme a cobertura histórica e a ausência de lacunas recentes.
3. Verifique se já existem ordens pendentes para a mesma data de sinal.
4. Confirme que Telegram e e-mail estão configurados.
5. Dispare `monday_signals` somente uma vez para aquela data, salvo reprocessamento consciente.
