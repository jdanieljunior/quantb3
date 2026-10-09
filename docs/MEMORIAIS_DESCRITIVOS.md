# Memoriais Descritivos — QuantB3

**Versão documental:** 1.5
**Atualizado em:** 09/10/2026
**Escopo:** operação simulada (paper trading), sem capital real.

Este documento consolida os memoriais operacional, do modelo, de engenharia e do simulador. Deve ser atualizado quando houver mudanças em modelo, coleta, workflows ou regras de execução.

## 1. Memorial Descritivo Operacional

O QuantB3 acompanha o universo IBRX da B3 e gera uma carteira semanal simulada. A operação é coordenada por GitHub Actions, com persistência no Supabase e visualização no Streamlit Cloud.

| Etapa | Workflow | Agenda (UTC) | Resultado |
|---|---|---:|---|
| Preços e marcação diária | `daily_prices` | Seg–Sex, 22:30 | OHLCV, posições, caixa e patrimônio no fechamento B3 |
| Geração de sinais | `GeracaoSinais` (`monday_signals.yml`) | Seg–Sex, 21:30 | Primeiro pregão B3 da semana: sinais, ordens pendentes e notificações |
| Execução simulada | `NegociacaoOrdens` (`tuesday_execution.yml`) | Seg–Sex, 21:45 | Pregão seguinte ao lote de sinais: preenchimento simulado das ordens |
| Reconciliação | `ReconciliacaoCarteira` (`wednesday_reconcile.yml`) | Seg–Sex, 22:00 | Pregão seguinte à negociação: equity e resumo operacional |

Os workflows aceitam disparo manual. Antes da execução de uma ordem, uma nova execução de geração substitui atomicamente os sinais e as ordens `PENDING` da mesma data. Após existir ordem `FILLED`, a geração para aquela data é bloqueada, preservando o vínculo entre sinais e execução.

### Orquestração por pregão B3

O ciclo não depende mais do nome do dia da semana. O módulo `src/jobs/trading_calendar.py` identifica finais de semana, feriados nacionais e feriados recorrentes da B3. Em dia sem pregão, o workflow automático é encerrado com status `skipped`, sem atualizar sinais, ordens, posições ou patrimônio. A geração semanal envia um único aviso de adiamento ao Telegram; os demais jobs apenas registram o `skipped`, evitando notificações redundantes. Uma data manual sem pregão é recusada explicitamente.

A **GeracaoSinais** roda somente no primeiro pregão da semana: normalmente segunda-feira; se segunda for feriado, terça-feira; e assim por diante. A **NegociacaoOrdens** consulta exclusivamente o lote de sinais do pregão B3 imediatamente anterior. A **ReconciliacaoCarteira** consulta exclusivamente as ordens `FILLED` do pregão imediatamente anterior. Sem lote predecessor, ambos os jobs terminam como `skipped` e não alteram a carteira.

Cada workflow possui grupo de concorrência próprio, evitando duas execuções simultâneas da mesma etapa. A tabela `runs` registra os identificadores operacionais `signal_generation`, `order_negotiation` e `portfolio_reconciliation`, além dos status `success`, `error` ou `skipped`.

### Marcação diária a mercado

Após as etapas operacionais, o workflow `daily_prices` executa às 19:30 BRT e chama `src/jobs/daily_mark_to_market.py`. Ele reconstrói caixa e quantidades exclusivamente pelas ordens `FILLED` até a data de fechamento, valoriza cada posição pelo `close` do mesmo dia e substitui o snapshot em `positions`. Em seguida, grava em `equity` os campos `equity`, `cash`, `pos_value` e `n_positions`.

Se uma posição não possuir preço de fechamento no dia, a marcação falha sem sobrescrever o snapshot anterior. Em feriado ou antes da disponibilidade do fechamento, o job fica `skipped`, preservando o último snapshot válido. Assim, as telas de carteira e performance, o bot do Telegram e o Power BI passam a usar uma curva diária consistente sem criar operações simuladas adicionais.

### Notificações

Os relatórios operacionais são enviados para Telegram e e-mail. O e-mail pode usar Brevo, Resend ou SMTP. As credenciais ficam exclusivamente nos GitHub Secrets e nunca devem ser incluídas no repositório.

Além das notificações ativas dos jobs, o bot do Telegram oferece consultas sob demanda sobre a simulação. Essa interface é somente de leitura: não cria, altera ou executa ordens.

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
                    └─ Telegram Bot API (notificações)

Telegram → Supabase Edge Function `telegram-bot` → Supabase/PostgreSQL
                                                    └─ respostas e gráfico SVG
```

As principais tabelas são `prices`, `signals`, `orders`, `positions`, `equity`, `notifications` e `runs`. A tabela `prices` usa upsert por `(date, ticker)`; por isso, a rebaixada de 100 dias corrige dados sem criar duplicidade.

### Integridade de carteira e reconciliação

O livro de ordens com status `FILLED` é a fonte de verdade para caixa e posições. O módulo `src/execution/ledger.py` percorre as ordens em ordem de execução e:

1. debita compra pelo valor financeiro mais custos;
2. credita venda, stop ou take pelo valor líquido de custos;
3. recompõe quantidade, preço médio, stop e take de cada posição;
4. interrompe a reconciliação se identificar preço inválido, venda sem posição suficiente ou caixa negativo.

Os snapshots em `positions` e `equity` são projeções do razão, não insumos para uma nova execução. A reconciliação e a marcação diária substituem integralmente as posições da data, eliminando ativos encerrados que poderiam permanecer em snapshots anteriores. O patrimônio obedece sempre à identidade `equity = cash + pos_value`.

Na tela de carteira, **P&L Não Realizado** mede apenas a variação de mercado das posições abertas. O retorno total da página de performance inclui também os custos operacionais e é calculado contra o capital inicial da simulação. CAGR não é exibido para séries inferiores a 30 dias.

Cada job registra execução na tabela `runs` e produz logs no GitHub Actions. O timeout por ticker limita bloqueios individuais do yfinance; o coletor continua com os demais ativos quando uma consulta falha.

Segredos são mantidos em GitHub Secrets e Streamlit Secrets. Integrações externas de análise, como Power BI e Excel, usam uma role PostgreSQL dedicada, com `LOGIN`, `CONNECT`, `USAGE` no schema `public` e somente `SELECT` nas tabelas atuais e futuras. Essa role não recebe permissões de inserção, alteração, exclusão, DDL ou privilégios administrativos. Para redes IPv4, a conexão deve usar o **Session Pooler** do Supabase na porta 5432, com TLS.

### Bot consultivo do Telegram

O bot é hospedado como a Edge Function `supabase/functions/telegram-bot/index.ts`. O Telegram entrega mensagens por webhook para a função; ela consulta as tabelas `signals`, `orders`, `positions` e `equity` e responde ao mesmo chat. Os comandos disponíveis são:

| Comando | Resposta |
|---|---|
| `/sinais` | Sinais da data mais recente |
| `/posicoes` | Posições reconciliadas mais recentes |
| `/carteira` | Patrimônio, caixa, valor em posições e quantidade de ativos |
| `/performance` | Retorno acumulado e máximo drawdown da curva de equity |
| `/grafico` | Curva de patrimônio em arquivo SVG |
| `/ajuda` ou `/start` | Lista de comandos |

O endpoint não usa JWT porque o Telegram não o fornece. Em compensação, exige simultaneamente um segredo aleatório no parâmetro do webhook (`TELEGRAM_WEBHOOK_SECRET`) e igualdade exata entre o chat que enviou a mensagem e `TELEGRAM_ALLOWED_CHAT_ID`. O token do bot fica apenas em `TELEGRAM_BOT_TOKEN`, nos Edge Function Secrets do Supabase. Esses três valores não pertencem ao GitHub, ao Streamlit nem ao repositório.

### Histórico por ativo no dashboard

A página **Histórico por Ativo** restringe o seletor aos tickers que já possuem ordem `FILLED` ou que constam na carteira atual. Para o ativo escolhido, ela mostra o fechamento diário da tabela `prices` e sobrepõe as negociações executadas na data exata: compra com bolinha amarela, venda lucrativa com triângulo verde ascendente e venda com prejuízo com triângulo vermelho descendente.

O cursor de cada venda apresenta quantidade, preço, custo, resultado financeiro e percentual realizado. O percentual é calculado contra o preço médio da posição imediatamente antes daquela venda, incluindo os custos registrados no razão.

A aplicação é destinada exclusivamente a simulação.

### IBRX Model Watch e eventos de mercado

O IBRX Model Watch é uma camada de dados estruturados para enriquecer o modelo, e não um gerador de ordens. A tabela `market_events` registra ticker opcional, tipo e classe do evento, datas de divulgação e efetivação, período de vigência, fonte, referência, status e confirmação. As migrações são `sql/012_market_events.sql` e `sql/013_market_event_staging_point_in_time.sql`.

| Classe | Tipos inicialmente suportados | Feature | Regra temporal |
|---|---|---|---|
| Pontual | `CORPORATE_ACTION`, `IBRX_COMPOSITION`, `B3_REGULATORY` | flags de 5, 5 e 10 dias | inicia na maior data entre divulgação e vigência; nunca antes da divulgação |
| Regime | `HIGH_VOLATILITY_REGIME`, `RISK_OFF_REGIME` | flags de regime | ativa até `valid_to`, ou até o último dado disponível se não houver término |

O CSV bruto do Watch é importado em `market_event_staging`, preservando `event_id`, fontes, evidências, notas e o payload original. A área de staging jamais é lida pelo modelo. O importador `scripts/import_market_event_staging.py` exige UTF-8 com BOM e converte booleanos textuais somente por comparação explícita; portanto, a string `"false"` não se torna verdadeira acidentalmente.

O dashboard **Eventos** aceita apenas a ingestão estruturada e sempre grava como `PENDING_VALIDATION`. Para um registro tornar-se `CONFIRMED`, sua fonte deve ser revisada em fonte confiável (por exemplo, B3, CVM ou RI da companhia), com responsável e nota de confirmação. Além disso, a promoção exige `available_from` e, para regimes, `feature_to` explícito. Registros pendentes, rejeitados ou sem essa disponibilidade causal são ignorados pela engenharia de features.

As features do Watch permanecem desligadas por padrão (`ENABLE_MARKET_EVENT_FEATURES=false`). Isto mantém as 18 features e todos os parâmetros da estratégia v2.1 inalterados. A habilitação requer uma base histórica confirmada e o relatório `compare_base_vs_events_oos`, que executa os dois modelos em walk-forward e o mesmo motor de backtest no período temporal fora da amostra. Sem eventos históricos confirmados, não há evidência para promover o enriquecimento à produção.

## 4. Memorial do Simulador OHLCV

As ordens criadas na geração de sinais são simuladas no pregão B3 seguinte. A execução usa a série OHLCV e aplica custos operacionais definidos em `config/settings.py`:

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
3. Verifique se já existem ordens `FILLED` para a mesma data de sinal; nesse caso, não reexecute `GeracaoSinais`.
4. Confirme que Telegram e e-mail estão configurados.
5. Em execução manual, informe sempre uma data de pregão B3. Feriados são recusados para não criar um ciclo inconsistente.
6. Após `NegociacaoOrdens`, aguarde ou execute `ReconciliacaoCarteira` somente no pregão B3 seguinte e confirme a igualdade entre patrimônio, caixa e posições.
