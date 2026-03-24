# IVA — Memory

## Decisoes arquiteturais vigentes
- Backend Flask + Pydantic + Loguru.
- Source of truth de caminhos: `core/projetos.py`.
- Estrutura oficial por projeto em `data/projects/<id>/`.
- Contrato API padrao: `{"success","message","data"}`.

## Decisoes financeiras
- Decimal para normalizacao sensivel (RH granular, quantizacao monetaria).
- Float para motor analitico e serializacao JSON.
- ADR oficial vem de `core/analise/adr_por_mes.py`.
- Simulacao:
  - EBITDA = Receita Bruta - Custos Fixos - Custos Variaveis
  - Lucro Liquido = EBITDA - Impostos
- Comissao de venda:
  - campo `financeiro.comissao_venda_pct`
  - custo variavel sobre receita bruta.
- Break-even operacional: EBITDA >= 0.
- Payback: apenas com lucro medio mensal positivo.

## Compatibilidade e legado
- Ainda ha fallback para estrutura legada:
  - `data/projects/<id>.json` (projeto legado)
  - nomes antigos de market/cenarios em algumas trilhas
  - `simulacao_salva.json` e `simulacao_cenarios.json` como apoio de migracao.
- Novas features devem usar apenas estrutura oficial.
- Remocao de legado exige migracao explicita + teste de regressao.

## UI e UX
- Base visual: Bootstrap 5 + Chart.js.
- Simulador deve operar em modo "cockpit":
  - atualizacao via AJAX
  - sem recarregar pagina
  - feedback por toast/spinner.

## Auditoria e rastreabilidade
- Eventos em `scripts/evidence_stability/SYSTEM_EVENTS.jsonl`.
- Mudancas estruturais:
  - analise de impacto
  - backup `.bak`
  - registro de evento.

## Dividas tecnicas mapeadas
- Duplicacao de mascara/parse de moeda em pontos de frontend.
- Parte da logica do simulador permanece inline em `templates/simulacao.html`.
