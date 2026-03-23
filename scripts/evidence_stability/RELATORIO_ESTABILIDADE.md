# Wave 3 - Relatorio de Estabilidade

## Escopo
- Implementacao de resiliência no scraper em `core/scraper/scrapers.py`:
  - `safe_goto` com retries (3), backoff exponencial (2s/4s/8s) e timeout dinamico (default 30s, configuravel).
  - Restart de sessão de navegador em falha grave/repetida.
  - Telemetria estruturada em JSONL.

## Antes (Ato I)
- Arquivos:
  - `LOG_BEFORE.jsonl`
  - `METRICS_BEFORE.json`
- Resultado:
  - total_periodos: 6
  - sucesso: 3
  - falhas: 3
  - taxa_sucesso: 50%

## Depois (Ato IV)
- Arquivos:
  - `LOG_AFTER.jsonl`
  - `METRICS_AFTER.json`
- Resultado:
  - total_eventos: 2
  - sucessos: 1
  - falhas: 1
  - taxa_sucesso: 50%
  - browser_restarts: 1

## Evidencia de resiliencia
- O `LOG_AFTER.jsonl` registra explicitamente:
  - 3 tentativas de falha na URL ruim (`resultado=FALHA`)
  - evento de reinicio (`resultado=RESTART`, `browser_restarted=true`)
  - prosseguimento com sucesso na URL seguinte (`resultado=OK`)

## Observacoes de idempotencia
- Persistencia continua via `get_market_bruto_path(id_projeto)` (sem hardcode de path de saida de dados).
- Em caso de interrupcao, nova execucao recompõe registros e regrava `market_bruto.json` do projeto.

## Proximos passos recomendados
1. Encapsular restart para reaproveitar fila pendente automaticamente no loop expandido completo.
2. Classificar `erro_code` em categorias mais finas (`timeout`, `dns`, `internet_disconnected`).
3. Adicionar teste automatizado de caos (falha de rede simulada) na pipeline.
