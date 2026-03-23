# Experimento Calendario V3 - Standby

## Status
- Estado atual: `standby`
- Motivo: fluxo visual do widget inferior ainda instavel para abertura consistente e avanço de mes.

## Evidencias relevantes
- `attempts_log.json`
- `dates_extracted_full.json`
- `dom_dump.json`
- `cand_00_month_after_next_t1.png`
- `cand_00_month_after_next_t2.png`
- `cand_00_month_after_next_t3.png`
- `cand_00_next_not_found_full.png`

## Sintese tecnica
- Abertura do widget: intermitente.
- Selecao de range: parcialmente funcional (check-in/check-out extraidos em execucoes pontuais).
- Confirmacao de range visual: inconsistente (`range_formed=false` nas ultimas evidencias).
- Avanco de mes: falha recorrente, sem mudanca robusta de header.

## Condicoes para retomada
- Reestabelecer abertura deterministica do widget com retries controlados.
- Consolidar estrategia unica de clique no "proximo mes" com validacao por header e dump por tentativa.
- Criar teste automatizado repetivel (>= 5 execucoes) com taxa de sucesso minima aceitavel.
