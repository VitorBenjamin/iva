# Relatorio de Confiabilidade e Estabilidade

## Escopo
- Scraper funcional do core (`core/scraper`): extração por URL parametrizada + parsing de preço/tabela.
- Experimento visual do calendario (`scripts/explorar_calendario_booking.py`): mantido como laboratorio.

## Achados principais
- O core possui fluxo funcional claro: monta URL com `checkin/checkout`, coleta preços, calcula diária e persiste `market_bruto`.
- Existe heuristica de fallback para preço e tipo de tarifa que pode gerar variacao em cenarios de layout diferente.
- O experimento V3 ainda nao apresenta estabilidade para ciclo completo multi-mes.

## Riscos tecnicos
- Alta dependencia de seletor CSS e estrutura dinamica do Booking.
- Desconto fixo para `preco_direto` pode nao refletir realidade comercial por temporada/tarifa.
- Funcoes longas de laboratorio elevam custo de manutencao e chance de regressao.

## Avaliacao geral
- Confiabilidade do core: **moderada para alta** (fluxo principal consolidado, com riscos conhecidos de parsing/seletor).
- Estabilidade do experimento de calendario: **baixa** (intermitencia de abertura e falha de avanço).

## Recomendacoes
1. Congelar experimento V3 em standby (ja documentado).
2. Priorizar testes automatizados no core para validar extracao e consistencia de preço por amostra de datas.
3. Revisar regra de desconto (`preco_direto`) com criterio de negocio configuravel.
4. Refatorar funcoes extensas do script de laboratorio em blocos menores para diagnósticos mais confiaveis.
