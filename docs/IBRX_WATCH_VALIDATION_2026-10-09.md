# Decisão de validação — IBRX Model Watch

Data da revisão: 09/10/2026  
Escopo: 17 registros importados em `market_event_staging` a partir de
`ibrx_model_watch_events.csv`.

## Resultado do lote

| Decisão | Eventos |
|---|---:|
| Aprovado para teste OOS | 0 |
| Pendente | 16 |
| Rejeitado | 1 |

Nenhum registro deste lote deve ser promovido para `market_events`, receber
`confirmed=true` ou `oos_enabled=true`. Portanto, as features de eventos
continuam inativas e o modelo de produção não é alterado.

`Aprovado para teste OOS` exige simultaneamente: documento primário específico,
momento público verificável, ticker/classe e universo histórico confirmados, e
uma regra de `available_from`, `feature_from` e `feature_to` decidida antes da
avaliação de performance. Ausência de um único requisito resulta em bloqueio.

## Decisões por evento

| `event_id` | Decisão | Evidência / conclusão | Condição para reabrir |
|---|---|---|---|
| `bradesco-initial-BBDC3` | Pendente | O alerta não possui data nem documento que identifique a operação. Proposta, homologação pelo conselho e aprovação regulatória são marcos distintos. | Localizar o comunicado específico e os horários de divulgação e disponibilidade. |
| `bradesco-initial-BBDC4` | Pendente | Mesma operação do registro BBDC3; não contar duas vezes como dois eventos econômicos. | Mesma condição de BBDC3, com mapeamento para as duas classes. |
| `braskem-opa` | Pendente | Não há edital ou fato relevante primário identificado que corresponda ao resumo. | Localizar o documento CVM/RI e a classe abrangida. |
| `santander-opa` | Pendente | O RI contém mais de um documento de OPA; a linha não identifica qual operação originou o alerta. | Vincular um documento, data/hora pública e estágio da OPA. |
| `yduqs-afya` | Pendente | Há reprodução jornalística, mas não o documento primário nem seu horário de arquivamento. | Obter fato relevante/CVM e definir regra de término para negócio pendente. |
| `movida-capital` | Pendente | O RI lista operações diferentes em 2026; o resumo não permite selecionar uma sem inventar precisão. | Identificar o comunicado e o marco econômico exato. |
| `guidance-mineracao-CMIN3` | Pendente | A página de RI da CSN Mineração confirma comunicado de 29/09 sobre redução de volumes e revisão de projeções, mas ainda não há política de feature para revisão de guidance. | Anexar o documento, horário e uma regra de sinal estritamente causal. |
| `guidance-mineracao-CSNA3` | Pendente | A divulgação é da controlada CMIN; o efeito sobre CSNA3 é uma hipótese de exposição indireta, não um fato do ticker. | Justificar economicamente o escopo CSNA3 e testá-lo separadamente de CMIN3. |
| `tenda-SHARE_BUYBACK` | Pendente | A página de RI é índice de documentos, não prova da recompra indicada. | Localizar o fato relevante com data, parâmetros e ticker. |
| `tenda-OWN_SHARE_TRS` | Pendente | Não foi identificado documento específico para a operação de TRS. | Localizar contrato/comunicado e definir duração causal. |
| `axia-operation-4` | Pendente | Há cobertura secundária; ticker/classe PNC, documento primário e datas de disponibilidade não estão confirmados. | Confirmar documento B3/CVM, classe negociável e marcos. |
| `vix-high` | Pendente | A notícia oficial da B3 de 01/10 confirma nível superior a 30, porém há divergência textual entre 32,39 e 32,89 e uma notícia isolada não define duração de regime. | Usar série diária oficial, convenção de disponibilidade e regra pré-definida de início/fim. |
| `bradesco-board-BBDC3` | Pendente | Matéria de imprensa corrobora homologação pelo conselho, ainda condicionada a homologação do Bacen. | Ler o documento primário e modelar os marcos sem antecipar aprovação regulatória. |
| `bradesco-board-BBDC4` | Pendente | Mesmo evento econômico de BBDC3; não duplicar contagem. | Mesma condição de BBDC3 e vínculo controlado entre as duas classes. |
| `election-repricing` | Pendente | Fonte B3 descreve movimento intradiário publicado às 13:39 em 05/10; ela não estava disponível na abertura. O regime não possui duração definida. | Definir regra de regime somente com informações disponíveis após o horário público. |
| `unifique-opa` | Rejeitado | O próprio Watch registrou que não incorporou o evento por falta de confirmação do universo IBRX point-in-time. | Somente criar um novo candidato se a participação no universo histórico e o documento primário forem comprovados. |
| `axia-operation-5` | Pendente | B3 confirma PNC ex-direitos em 09/10 e aponta protocolo CVM, mas o conteúdo do documento e o cadastro de `AXIA7` ainda não foram verificados. Ex-direitos não determina duração de feature. | Ler o documento CVM, validar ticker/classe e aprovar uma feature específica para o marco ex-direitos. |

## Fontes primárias já corroboradas

- B3: [VIX da B3 em outubro de 2026](https://b3.com.br/pt_br/noticias/outubro-inicia-com-recorde-do-indice-da-b3-que-mede-expectativa-de-volatilidade-do-mercado-brasileiro.htm).
- B3: [fato relevante da Axia de 07/10/2026](https://sistemasweb.b3.com.br/PlantaoNoticias/Noticias/Detail?agencia=18&dataNoticia=2026-10-07+10%3A17%3A20&idNoticia=3508197).
- B3: [notícia intradiária de 05/10/2026](https://borainvestir.b3.com.br/noticias/mercado/ibovespa-b3-alcanca-maxima-historica-intradiaria-acima-dos-209-mil-pontos-dolar-cai-abaixo-de-r-5/).
- CSN Mineração RI: [comunicados e fatos relevantes](https://ri.csnmineracao.com.br/comunicados-e-fatos-relevantes/).
- Movida RI: [documentos CVM](https://ri.movida.com.br/informacoes-financeiras/documentos-cvm/).

As fontes corroboram apenas os fatos explicitamente descritos acima. Elas não
suprem os requisitos de causalidade, escopo e regra de vigência exigidos para
uso como feature.

## Próxima execução controlada

1. Preservar o staging como trilha de auditoria; nenhuma promoção automática.
2. Criar uma ficha de validação por candidato, com documento primário e horário
   de divulgação.
3. Para cada ficha completa, fixar por escrito a regra causal antes de rodar o
   comparativo OOS.
4. Apenas candidatos aprovados individualmente entram em um experimento
   base-versus-eventos, com os mesmos splits, custos e universo da estratégia
   atual.
5. Promover somente se houver ganho estável fora da amostra, sem piora material
   de drawdown, turnover ou concentração.
