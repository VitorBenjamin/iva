# Análise pré-commit — Estado do repositório antes da próxima etapa

**Data:** 2025-03-12  
**Branch:** master  
**Objetivo:** Consolidar alterações das Waves 1–5 (ocupação, padronização, gráficos, infraestrutura, benchmarks e UI) em commits organizados e fazer push.

---

## Resumo do escopo

| Área | Arquivos | Descrição |
|------|----------|-----------|
| **Core / modelo** | `core/financeiro/modelos.py`, `core/projetos.py`, `core/benchmarks.py`, `core/config.py` | Modelo `Infraestrutura`, benchmarks calibrados (Sonhos de Praia), calendário soberano e períodos especiais |
| **Backend** | `app.py` | Endpoint `GET /api/presets-infraestrutura`, corpo de projeto com `infraestrutura`, curadoria e descontos |
| **Scraper** | `core/scraper/scrapers.py` | Coleta expandida 365 dias, loop de tentativas N+1/N-1, placeholders FALHA |
| **Frontend** | `templates/index.html`, `static/js/main.js`, `templates/dashboard.html`, `templates/simulacao.html` | Seção Infraestrutura (cards + botão Calibrar), título dinâmico desconto, gráficos Chart.js, campo média pessoas, formatação moeda |
| **Análise** | `core/analise/engenharia_reversa.py`, `core/analise/simulacao.py` | Ajustes de análise e simulação |
| **Docs** | `docs/*.md` | Análises de impacto e diagnóstico |

---

## Commits planejados

1. **feat(core): Infraestrutura, benchmarks calibrados e config** — modelo de dados e lógica de presets.
2. **feat(backend): API presets infraestrutura e projeto com infraestrutura** — app.py.
3. **feat(scraper): coleta expandida calendário diário e loop de tentativas** — scrapers.py.
4. **feat(ui): Infraestrutura cards/Calibrar, dashboard e simulador** — templates e main.js.
5. **fix(analise): ajustes engenharia reversa e simulação** — core/analise.
6. **docs: análises de impacto e diagnóstico** — docs/.

---

## Verificações

- [x] Nenhum arquivo de ambiente ou secreto incluído.
- [x] Documentação nova em `docs/` (não sobrescreve nada crítico).
- [x] Modelo `Infraestrutura` opcional (retrocompatível).
- [x] Status no market_bruto permanece compatível (OK/FALHA).
