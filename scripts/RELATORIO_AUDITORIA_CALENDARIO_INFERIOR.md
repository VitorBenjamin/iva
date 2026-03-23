# Relatório — Auditoria do calendário inferior (seção Disponibilidade) Booking.com

**Data:** 2025-03  
**Script:** `scripts/auditar_calendario_booking_disponibilidade.py`  
**Objetivo:** Localizar e inspecionar o calendário **inferior** da seção "Disponibilidade" (preços por dia / "—") sem alterar o scraper principal.

---

## 1) Análise de impacto (antes da execução)

### Arquivo(s) alterados/criados
- **Criado:** `scripts/auditar_calendario_booking_disponibilidade.py` (script isolado).
- **Criado:** `scripts/RELATORIO_AUDITORIA_CALENDARIO_INFERIOR.md` (este relatório).
- **Não alterados:** `core/`, `app.py`, `templates/`, `static/`, e o script `explorar_calendario_booking.py` (este último continua focado no calendário superior da searchbox).

### Funções impactadas (apenas no script de auditoria)
- **Abertura de página:** `main()` — goto, networkidle (com fallback em timeout), aceitar cookies.
- **Localização da seção:** `_localizar_secao_disponibilidade()` — múltiplos seletores text/attr; `_scroll_ate()` (não usada no fluxo final; a localização é feita em loop com scroll em `main()`).
- **Clique no calendário:** `_clicar_primeiro_candidato_na_secao()` — busca candidatos na região (bounds da seção + margem), fallback por `text="Data de check-in"` com filtro por `y > 250`.
- **Confirmação do widget:** `_widget_confirmar()` — textos "Preços aproximados", "estadia de 1 diária", contagem de `[data-date]` no range.
- **Extração DOM:** `_extrair_outer_html_do_widget()`, `_extrair_status_celula()`; dump de seletores em `debug_seletores_celulas.txt`, amostras em `debug_amostras_celulas.json`.

### Riscos
- **Timeout por lazy-load:** Mitigado — tentativa de `networkidle` com timeout; em falha, o script segue.
- **Seção "Disponibilidade" não visível sem scroll:** Mitigado — scroll progressivo até encontrar âncora textual "Disponibilidade".
- **Elementos renderizados só após interação:** Risco — se o campo de datas da seção for carregado sob demanda, o primeiro scroll pode não ser suficiente; o script tenta múltiplos scrolls antes de localizar.
- **A/B test / layout variável:** Risco — seletores e textos podem variar por região/experimento; múltiplos candidatos e fallback reduzem, mas não eliminam, o risco.
- **Captura do widget errado:** Risco — o script confirma o widget por texto ("Preços aproximados", etc.) e por posição vertical dos `[data-date]`; se o Booking abrir o mesmo widget da searchbox ao clicar no campo inferior, a confirmação pode falhar ou identificar o widget errado.

---

## 2) Objetivo técnico da auditoria — evidências reais

### A) Como localizar a seção "Disponibilidade"?
- **Estratégia que funcionou:** `text="Disponibilidade"` (primeiro elemento visível após scroll).
- O script faz scroll progressivo e, a cada passo, tenta os candidatos: `text="Disponibilidade"`, `h2:has-text("Disponibilidade")`, `h3:has-text(...)`, `[data-testid*="availability"]`, `[id*="availability"]`, `[class*="availability"]`, e equivalentes em "Availability". O primeiro com `bounding_box()` válido é usado.

### B) Seletor do bloco/container da seção
- **Tag do container:** `DIV` (obtido via `el.closest('section,article,main,div')` a partir do elemento que contém o texto "Disponibilidade").
- O container não tem um `data-testid` ou `id` único identificado no HTML salvo; o script usa o **bounding box** desse DIV (x, y, width, height) para delimitar a região de busca de cliques.

### C) Elemento que abre o calendário inferior
- **Esperado:** Campo "Data de check-in" ou "Data de check-out" **dentro** da seção (barra horizontal com dois campos de data e botão "Pesquisar").
- **Problema observado:** Na execução automática, nenhum candidato de clique (inputs, botões, `[data-testid*="date"]`, etc.) **dentro da região delimitada** (bounds do container + 600px abaixo + margens laterais) foi clicável com sucesso. O fallback que tenta clicar no segundo (ou posterior) elemento com texto "Data de check-in" (y > 250) também não disparou o calendário inferior nas execuções realizadas — possíveis causas: sobreposição por outro elemento, necessidade de hover, ou o locator pegando um elemento não clicável (ex.: label em vez do input).

### D) Seletor real das células do calendário inferior
- **Não foi possível inspecionar in loco** porque o calendário inferior não foi aberto pelo script. No calendário **superior** (searchbox), o script `explorar_calendario_booking.py` já identificou: `[data-date]` em elementos `<span>` com `role="checkbox"` e `aria-disabled` para dias indisponíveis.
- **Hipótese:** O calendário inferior pode reutilizar a mesma estrutura (`[data-date]`, grid) e diferenciar-se pela **posição na página** (abaixo da seção Disponibilidade) e por textos como "Preços aproximados" / "estadia de 1 diária". Para confirmar, é necessário abrir esse widget (manual ou ajuste fino do clique).

### E) Distinguir dia com preço / "—" / sem informação
- **Com base no script de exploração superior e no código de auditoria:**
  - **Dia com preço:** texto com "R$" e números; ou atributos sem `aria-disabled` e sem classes de bloqueio.
  - **Dia com "—":** `aria-disabled="true"` ou classes contendo "disabled", "unavailable", "blocked", etc., ou texto contendo "—".
  - **Dia sem informação / incerto:** apenas número do dia (1–31), sem preço nem "—"; o script de exploração trata como "disponível" por padrão (heurística conservadora).

### F) Navegação entre meses no widget inferior
- **Não verificado** (widget não aberto). No widget superior, candidatos de "próximo mês" incluem: `[data-testid="datepicker-next-month-button"]`, `[aria-label*="próximo"]`, `[data-bui-ref="calendar-next"]`. O mesmo pode valer para o inferior; requer inspeção do DOM após abertura.

---

## 3) Estratégia do script (2 fases)

- **FASE 1 — Localizar e diagnosticar a seção "Disponibilidade":**  
  Scroll, localização por texto/atributos, `scroll_into_view_if_needed`, screenshots (`debug_disponibilidade_pagina.png`, `debug_disponibilidade_secao.png`), salvamento de ~8.000 caracteres do HTML do container em `debug_disponibilidade_html.txt`, impressão no terminal da estratégia, tag do container e amostra de texto.

- **FASE 2 — Abrir e inspecionar o calendário inferior:**  
  Busca de candidatos de clique (inputs, botões, textos "Data de check-in", etc.) **na região** (bounds do container + 600px abaixo + margens). Clique no primeiro candidato válido; fallback: clique no n-ésimo "Data de check-in" com y > 250. Confirmação do widget por textos e `[data-date]` no range. Extração do HTML do widget, teste de seletores de células, amostras (com_preco / com_traco / incerta) em `debug_amostras_celulas.json`.

---

## 4) Resultado da execução (resumo)

- **FASE 1:** Sucesso. Seção "Disponibilidade" encontrada com `text="Disponibilidade"`, container DIV, screenshots e HTML salvos.
- **FASE 2:** O clique no calendário inferior **não foi obtido** nas execuções: nenhum candidato na região respondeu ao clique, e o fallback "Data de check-in" (y > 250) também não abriu o widget. Assim, os arquivos que dependem da abertura do popup (`debug_calendario_inferior_aberto.png`, `debug_widget_calendario_html.txt`, `debug_seletores_celulas.txt`, `debug_amostras_celulas.json`) não foram preenchidos com dados do **calendário inferior**; em caso de falha, o script salva `debug_calendario_inferior_click_falhou.txt` com a lista de seletores tentados.

---

## 5) Próximos passos recomendados

1. **Abrir o calendário inferior manualmente** na mesma URL, inspecionar no DevTools o elemento clicável (Data de check-in da seção) e o container do popup (tag, `data-testid`, classes). Registrar o seletor exato e, se necessário, usar `page.locator("...").nth(N)` com N adequado para evitar o campo da searchbox.
2. **Testar hover antes do clique:** Alguns sites exibem o campo clicável só após hover na seção; adicionar `page.hover(secao_locator)` antes de procurar candidatos.
3. **Ajustar bounds:** Garantir que o retângulo usado (container + 600px) inclua de fato a barra "Data de check-in" / "Data de check-out" da seção (por exemplo, inspecionando `debug_disponibilidade_pagina.png` e medindo o y do campo).
4. **Seletor mais específico:** Se o Booking usar um `data-testid` ou `id` diferente para o bloco de datas da seção (em relação ao da searchbox), usar esse seletor primeiro na lista de candidatos.

---

## 6) Arquivos de evidência gerados

| Arquivo | Conteúdo |
|--------|----------|
| `scripts/debug_disponibilidade_pagina.png` | Screenshot full-page após localizar a seção. |
| `scripts/debug_disponibilidade_secao.png` | Screenshot do elemento/container da seção. |
| `scripts/debug_disponibilidade_html.txt` | ~8.000 primeiros caracteres do HTML do container. |
| `scripts/debug_calendario_inferior_aberto.png` | Só preenchido se o clique abrir o widget. |
| `scripts/debug_calendario_inferior_click_falhou.txt` | Lista de seletores tentados quando o clique falha. |
| `scripts/debug_widget_calendario_html.txt` | HTML do widget (após abertura). |
| `scripts/debug_seletores_celulas.txt` | Relatório de seletores de células testados. |
| `scripts/debug_amostras_celulas.json` | Amostras com_preco / com_traco / incerta. |
| `scripts/output_disponibilidade_auditoria_{ANO_MES}.json` | Resumo técnico (secao, click, widget_confirmado, etc.). |

Com a falha do clique, apenas os três primeiros e o `debug_calendario_inferior_click_falhou.txt` contêm dados úteis para esta execução; os demais dependem da abertura do calendário inferior.
