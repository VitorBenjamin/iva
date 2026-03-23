# Relatorio de Saneamento e Estabilidade do Scraper Funcional

## Escopo aplicado
- Correcao de feriados/eventos especiais no calendario soberano.
- Substituicao de desconto fixo por desconto dinamico de configuracao.
- Desativacao por padrao da fase de reconhecimento visual de calendario no core scraper.

## Validacao executada
- Comando: execucao direta de `coletar_dados_mercado(...)` para `village-arraial`.
- Resultado: 6 periodos coletados com sucesso e 0 falhas.
- Amostra de saida:
  - `alta_janeiro`: diaria_booking 680.40 / diaria_direta 544.32
  - `alta_julho`: diaria_booking 241.00 / diaria_direta 192.80
  - `reveillon`: diaria_booking 1304.20 / diaria_direta 1043.36

## Mudancas tecnicas
- `core/config.py`
  - Nova funcao `obter_desconto_dinamico(cfg, mes_ano)`.
  - Feriados nacionais agora coexistem com periodos especiais de config (nao sao descartados quando ha config).
- `core/scraper/scrapers.py`
  - `preco_direto` calculado com desconto dinamico (global/por_mes).
  - Fase de widget/calendario inferior desativada por padrao, com flag opcional `parametros_tecnicos.usar_calendario_widget`.

## Confiabilidade apos saneamento
- Fluxo funcional (URL + tabela): estavel nesta rodada de teste.
- Riscos residuais: mudancas de layout da pagina do Booking e qualidade da configuracao de periodos especiais.
