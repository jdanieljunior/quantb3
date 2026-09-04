# Memoriais Descritivos — QuantB3

**Versão documental:** 1.3  
**Atualizado em:** 03/09/2026  
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

Os workflows aceitam disparo manual. Antes da execução de uma ordem, uma nova execução de segunda-feira substitui atomicamente os sinais e as ordens `PENDING` da mesma data. Após existir ordem `FILLED`, a geração para aquela data é bloqueada, preservando o vínculo entre sinais e execução.

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

Os snapshots em `positions` e `equity` são projeções do razão, não insumos para uma nova execução. A reconciliação substitui integralmente as posições da data, eliminando ativos encerrados que poderiam permanecer em snapshots anteriores. O patrimônio obedece sempre à identidade `equity = cash + pos_value`.

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
3. Verifique se já existem ordens `FILLED` para a mesma data de sinal; nesse caso, não reexecute `monday_signals`.
4. Confirme que Telegram e e-mail estão configurados.
5. Dispare `monday_signals` somente uma vez para aquela data. Antes da terça-feira, reprocessamentos substituem somente o plano pendente; depois da execução, são bloqueados.
6. Após `tuesday_execution`, execute `wednesday_reconcile` e confirme a igualdade entre patrimônio, caixa e posições.
