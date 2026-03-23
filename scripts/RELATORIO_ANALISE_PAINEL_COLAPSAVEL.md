# Relatório técnico — Análise do painel colapsável e loop ao abrir o calendário inferior (Booking)

**Data:** 2025-03  
**Escopo:** Comportamento de loop (abrir/fechar) de painel colapsável ao tentar abrir o calendário da seção "Disponibilidade" via script V3 / auditoria.  
**Restrição:** Análise e propostas apenas; nenhuma alteração em produção sem autorização.

---

## Resumo executivo

O script V3 (e o fluxo de auditoria) abre o calendário inferior ao fazer scroll até a seção "Disponibilidade", hover na seção e clique no campo de data. Durante essa sequência, um painel colapsável (ex.: "O melhor de [destino]") passa a abrir e fechar em loop, prendendo o script. O diagnóstico aponta para **scroll ou hover** trazendo o painel colapsável ao viewport ou sob o ponteiro, com **eventos de toggle** sendo disparados de forma cíclica; correções prioritárias são: **restringir o alvo do hover/clique ao campo de data**, **verificar sobreposição (elementFromPoint)** antes do clique e **mitigação opcional** (desabilitar pointer-events no painel colapsável) com fallback claro.

---

## 1. Análise de impacto

### 1.1 Arquivos afetados

| Arquivo | Tipo de alteração | Observação |
|--------|--------------------|------------|
| `scripts/explorar_calendario_booking.py` | Diagnóstico + mitigação | Função `run_v3_calendario_inferior`: adicionar verificação de sobreposição, clique por coordenadas do elemento, opção de desabilitar painel colapsável, logs e retry. |
| `scripts/auditar_calendario_booking_disponibilidade.py` | Opcional | `_clicar_primeiro_candidato_na_secao`: mesma lógica de elementFromPoint e clique no centro do elemento; logs de attempt e overlap. |
| `core/scraper/scrapers.py` | Opcional (fallback duro) | `_abrir_calendario_inferior`: max_attempts, timeout, log de falha e fallback já existente (continuar modo tradicional). Não alterar lógica de `scrap_data`/extração. |

### 1.2 Funções a alterar

- **explorar_calendario_booking.py**
  - `run_v3_calendario_inferior`: antes do clique, obter bounding box do elemento de data; chamar `elementFromPoint(cx, cy)`; se o elemento sob o ponto não for o alvo (ou descendente), registrar log e tentar clique via `element.click()` com force ou via JS `element.dispatchEvent(new MouseEvent('click', ...))` no centro; opcionalmente desabilitar painel "O melhor de" antes da interação; adicionar retry (ex.: 2 tentativas) com pequeno backoff e screenshot por tentativa.
- **auditar_calendario_booking_disponibilidade.py**
  - `_clicar_primeiro_candidato_na_secao`: idem: elementFromPoint no centro do candidato; se houver sobreposição, log e tentar force=True ou clique por JS.
- **core/scraper/scrapers.py**
  - `_abrir_calendario_inferior`: garantir timeout 10s; em falha, apenas log warning e retorno False (já implementado); opcional: max_attempts=2 com nova tentativa após 2s e screenshot em artifacts em caso de falha.

### 1.3 Riscos

| Risco | Mitigação |
|-------|-----------|
| **NoneType** ao acessar bounding_box ou elementFromPoint | try/except; fallback para clique normal ou force. |
| **FileNotFoundError** ao salvar screenshot/log | Usar `SCRIPT_DIR`/paths centralizados; criar diretório com `mkdir(parents=True, exist_ok=True)`. |
| **Timeouts** (calendário não abre) | Timeout 10s; após falha, script de exploração termina com código 1; scraper segue no modo tradicional (mapa vazio). |
| **Overlays** (painel cobre o campo) | elementFromPoint detecta; mitigação: desabilitar pointer-events no painel ou clicar por JS no elemento. |
| **Desabilitar painel colapsável** altera layout/UX do site | Usar apenas em scripts de diagnóstico; no scraper produtivo, não aplicar por padrão; documentar risco de detecção se usado em produção. |

---

## 2. Diagnóstico com evidências

### 2.1 Fluxo atual (quando o loop ocorre)

1. Localizar seção: `div:has(h2:has-text('Disponibilidade'))` → `secao_scope`
2. `secao_scope.scroll_into_view_if_needed()` → **possível gatilho**: scroll traz outro bloco (ex. "O melhor de") ao viewport
3. `page.wait_for_timeout(800)`
4. `secao_scope.hover()` → **possível gatilho**: seção grande; o centro do elemento pode cair sobre header do painel colapsável ou o painel pode estar sobreposto após scroll
5. `page.wait_for_timeout(500)`
6. Dentro de `secao_scope`, localizar campo de data (ex. `button:has-text("Data")`, `[data-testid*="date"]`) → `el`
7. `el.hover()` + wait 500 ms + `el.click()` → **possível gatilho**: hit-test do clique pode acertar o painel colapsável se ele estiver por cima

**Quando o loop inicia:** O relato indica que o calendário chegou a abrir (screenshot `debug_v3_aberto.png`), mas durante scroll/interação o painel passou a abrir/fechar. Isso sugere que o loop pode começar **após o primeiro hover na seção** ou **após o primeiro clique** (abertura do calendário), quando um segundo elemento (o painel) recebe foco ou eventos e passa a togglear.

### 2.2 Evidências disponíveis

- **scripts/debug_disponibilidade_html.txt:** Contém o início do container da seção: `h2#availability_target` "Disponibilidade" e o bloco "Cobrimos o menor preço!". Não contém "O melhor de" nesse snippet; o painel colapsável tende a ser **irmão** ou **bloco próximo** no DOM, não necessariamente dentro do mesmo div que contém o h2.
- **scripts/debug_disponibilidade_pagina.png / debug_v3_aberto.png:** Screenshots referenciados pelo usuário; indicam que a seção foi encontrada e que em algum momento o calendário abriu, mas a interação com a página provocou o comportamento de abrir/fechar do painel.
- **RELATORIO_AUDITORIA_CALENDARIO_INFERIOR.md:** Confirma que o clique no calendário inferior já falhou em execuções anteriores (nenhum candidato na região abriu o widget); na execução com V3 o calendário abriu, porém com o efeito colateral do painel em loop.

### 2.3 Pontos de falha (respostas às tarefas A e B)

**A. Quando o loop inicia?**  
- Mais provável: **após scroll** e/ou **após hover na seção** (seção grande ou painel entrando no viewport e reagindo a Intersection Observer / scroll).  
- Alternativa: **após o clique** que abre o calendário, quando o layout muda e o painel colapsável passa a receber eventos (focus/hover) e dispara toggle.

**B. Qual elemento DOM recebe eventos que provocam o colapso?**  
- Elemento esperado: um header ou botão do bloco "O melhor de [destino]" (texto parcial: "O melhor de", "melhor de", ou classe/atributo de accordion/collapse).  
- Não há outerHTML exato no repositório; recomenda-se em execução local: antes do clique, avaliar `document.elementFromPoint(cx, cy)` no centro do campo de data e imprimir `tagName`, `id`, `className`, `outerHTML.slice(0,500)` para comparar com o elemento que deveria receber o clique.

**B (cont.). Painel dentro ou sobreposto à seção Disponibilidade?**  
- Provável que seja **sobreposto** ou **vizinho no DOM**: o container capturado em `debug_disponibilidade_html.txt` não inclui "O melhor de"; portanto o painel pode ser irmão ou estar em outra parte da página e, após scroll, sobrepor visualmente a área de datas.

### 2.4 Seletores do painel colapsável (prováveis)

- Texto: `[aria-label*="melhor"]`, `text="O melhor de"`, `button:has-text("O melhor de")`, `div:has(> *:has-text("O melhor de"))`
- Classes típicas de accordion: `[class*="collapse"]`, `[class*="accordion"]`, `[class*="expand"]`, `[data-expanded]`
- Recomendação: em script de diagnóstico, usar `page.locator('text="O melhor de"').first` ou `page.locator('[class*="collapse"]:has-text("melhor")').first` e, se encontrado, obter bounding box e comparar com o bounding box do campo de data para ver sobreposição.

---

## 3. Diagnóstico raiz — hipóteses priorizadas

| # | Hipótese | Prob. | Evidência requerida |
|---|----------|-------|---------------------|
| **H1** | **Scroll ou hover ativa o painel colapsável** (Intersection Observer ou listener de hover no header "O melhor de"); o painel abre, desloca o layout; o próximo hover/scroll o fecha; ciclo se repete. | **Alta** | Log de `elementFromPoint` no centro da seção após scroll e após hover; captura do outerHTML do elemento sob o ponteiro; ver se é o header do painel. |
| **H2** | **Clique acerta outro elemento** (hit-test): o centro do campo de data está coberto pelo painel colapsável; o clique dispara o toggle do painel em vez do campo de data. | **Alta** | `elementFromPoint(cx, cy)` no instante do clique, com (cx, cy) = centro do botão de data; comparar com o elemento que recebeu o click. |
| **H3** | **Focus ou reflow** após abertura do calendário move o DOM e dispara listener do painel (ex.: focusout no campo de data faz o painel reavaliar estado e togglear). | **Média** | Reproduzir com DevTools: inspecionar listeners no painel; após abrir calendário, ver se focus/click em outro nó dispara toggle. |

---

## 4. Correções propostas (priorizadas)

### 4.1 (Prioridade 1) Clique restrito e verificação de sobreposição

- **Objetivo:** Garantir que o clique seja disparado no elemento de data e não no painel.
- **Método:**  
  1. Obter `bounding_box()` do elemento de data.  
  2. Calcular centro `(cx, cy)`.  
  3. Avaliar no page: `elementFromPoint(cx, cy)` (via `page.evaluate`).  
  4. Verificar se o elemento sob o ponto é o alvo ou descendente do alvo (por exemplo com `target.closest(selector)` ou comparando com o handle do Playwright).  
  5. Se houver sobreposição: logar `[OVERLAP] elementFromPoint não é o alvo: tag=... id=... class=...`; tentar `el.click(force=True)` ou clique via JS no elemento (`el.dispatchEvent(new MouseEvent('click', { bubbles: true }))`).

### 4.2 (Prioridade 2) Hover apenas no campo de data (não na seção inteira)

- **Objetivo:** Evitar que o hover na seção atinja o header do painel colapsável.
- **Método:** Não fazer `secao_scope.hover()`; fazer scroll até a seção, pequena pausa, e em seguida **apenas** `el.hover()` no primeiro candidato de data encontrado dentro de `secao_scope`. Reduz a superfície de disparo de listeners do painel.

### 4.3 (Prioridade 3) Desabilitar temporariamente o painel colapsável (mitigação)

- **Objetivo:** Evitar que o painel capture eventos durante a abertura do calendário.
- **Método:** Antes de hover/clique, localizar o painel (ex.: `page.locator('text="O melhor de"').first` ou seletor mais específico) e executar `el.evaluate("node => { node.style.pointerEvents = 'none'; }")` (ou `display: none` se aceitável). **Riscos:** altera layout/UX; em produção pode ser detectado; usar apenas em scripts de exploração/auditoria ou sob flag opcional. **Quando usar:** quando elementFromPoint + force/JS não forem suficientes e o ambiente for apenas diagnóstico.

### 4.4 (Prioridade 4) Retry com backoff e instrumentação

- **Objetivo:** Aumentar robustez e gerar evidências em caso de falha.
- **Método:** Máximo 2–3 tentativas para abrir o calendário; entre tentativas, wait 2s; a cada tentativa: log `attempt_count`, salvar screenshot (ex.: `debug_v3_attempt_N.png`), e opcionalmente salvar `elementFromPoint` (tag, id, class, outerHTML truncado) em `debug_v3_overlap_N.txt`. No scraper: max_attempts=2, em falha log + screenshot em artifacts e seguir no modo tradicional.

### 4.5 (Prioridade 5) Scroll mínimo necessário

- **Objetivo:** Reduzir chance de trazer o painel colapsável ao viewport.
- **Método:** Em vez de `scroll_into_view_if_needed()` no container inteiro, usar scroll até o **título** "Disponibilidade" (ex.: `page.locator('h2:has-text("Disponibilidade")').first.scroll_into_view_if_needed()`) e depois localizar o campo de data dentro do mesmo container; assim o scroll pode ser menor e menos propenso a expor o bloco "O melhor de".

---

## 5. Plano de implementação (Atos)

| Ato | Descrição |
|-----|------------|
| **1** | Em `scripts/explorar_calendario_booking.py`: implementar helper `_element_from_point(page, x, y)` que retorna dict com tagName, id, className, outerHTML (truncado); implementar `_click_with_overlap_check(page, el, log_prefix)` que obtém bbox, centro, chama elementFromPoint, verifica se o nó sob o ponto é o alvo ou descendente, e em caso negativo tenta `el.click(force=True)` ou clique por JS. |
| **2** | Em `run_v3_calendario_inferior`: (a) remover ou tornar opcional `secao_scope.hover()`; (b) fazer scroll apenas até o h2 "Disponibilidade"; (c) localizar campo de data dentro de `secao_scope`; (d) hover apenas no campo; (e) antes do clique, chamar `_click_with_overlap_check`; (f) em falha de abertura do calendário (timeout [data-date]), retry até 2 vezes com wait 2s e screenshot por tentativa. |
| **3** | (Opcional) Em `run_v3_calendario_inferior`: adicionar flag `DESABILITAR_PAINEL_COLAPSAVEL = True` (apenas scripts); se True, antes do passo de clique, localizar painel "O melhor de" e aplicar `pointer-events: none`; documentar risco. |
| **4** | Em `scripts/auditar_calendario_booking_disponibilidade.py`: em `_clicar_primeiro_candidato_na_secao`, antes de cada `el.click()`, obter centro do elemento, executar elementFromPoint, logar se houver sobreposição e tentar `force=True` ou clique por JS. |
| **5** | Em `core/scraper/scrapers.py`: em `_abrir_calendario_inferior`, garantir timeout 10s; opcional: loop max_attempts=2 com screenshot em artifacts em falha; manter retorno False e fluxo tradicional sem quebrar. |

---

## 6. Plano de testes

### 6.1 Testes manuais (comandos exatos)

```bash
# 1) Script de exploração V3 (calendário inferior) — sem headless para observar o painel
cd c:\Users\vitor_3fyrepz\OneDrive\Área de Trabalho\iva
set HEADLESS=false
python scripts/explorar_calendario_booking.py

# 2) Auditoria do calendário inferior (mesmo hotel)
python scripts/auditar_calendario_booking_disponibilidade.py

# 3) Verificar evidências geradas
dir scripts\debug_v3_*.png scripts\debug_disponibilidade_*.png scripts\debug_*overlap*.txt
```

**Critérios de aceitação (manuais):**  
- Calendário inferior abre em ≤ 10 s sem loop visível de abrir/fechar do painel.  
- Se não abrir: log de [OVERLAP] ou timeout e screenshot em `scripts/`; script termina com código definido (ex.: 1) sem travar.

### 6.2 Testes automatizados sugeridos

- **Unitário (helper de sobreposição):** Função que recebe `(bbox, elementFromPoint_result)` e retorna se há sobreposição (elemento sob o ponto diferente do alvo). Input: bbox = `{x, y, width, height}`, elementFromPoint_result = `{tagName, id}`; output: boolean. Pode ser implementado em `tests/` com pytest, sem Playwright.
- **E2E (opcional):** Rodar `explorar_calendario_booking.py` em 3 URLs: (1) hotel com painel "O melhor de" conhecido, (2) hotel sem esse bloco, (3) mesmo hotel com mitigação de pointer-events. Critério: em (1) e (2) o script termina em ≤ 30 s com código 0 ou 1; em caso 1, não deve ficar preso em loop (timeout global 60 s).

### 6.3 Comandos shell para validação

```bash
# Timeout global 60s para detectar loop
python -c "
import subprocess
import sys
r = subprocess.run([sys.executable, 'scripts/explorar_calendario_booking.py'], timeout=60, capture_output=True, text=True)
print('stdout:', r.stdout[-500:] if r.stdout else '')
print('stderr:', r.stderr[-500:] if r.stderr else '')
print('returncode:', r.returncode)
sys.exit(0 if r.returncode in (0, 1) else r.returncode)
"
```

---

## 7. Patches sugeridos (trechos para aplicar manualmente)

### 7.1 scripts/explorar_calendario_booking.py

**Constantes no topo (após MODO_V3):**

```python
# V3: mitigação painel colapsável
V3_MAX_ATTEMPTS = 2
V3_DESABILITAR_PAINEL_COLAPSAVEL = False  # True apenas para diagnóstico
```

**Novo helper (antes de `run_v3_calendario_inferior`):**

```python
def _element_from_point(page, x: float, y: float) -> dict:
    """Retorna tagName, id, className, outerHTML (até 600 chars) do elemento sob (x,y)."""
    try:
        return page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                if (!el) return { tagName: null, id: '', className: '', outerHTML: '' };
                return {
                    tagName: el.tagName || '',
                    id: el.id || '',
                    className: (el.className && typeof el.className === 'string') ? el.className : '',
                    outerHTML: (el.outerHTML || '').slice(0, 600)
                };
            }""",
            [x, y],
        )
    except Exception:
        return {}


def _click_with_overlap_check(page, el, log_prefix: str = "[V3]") -> bool:
    """Obtém bbox do el, verifica elementFromPoint no centro; se outro elemento no ponto (ex. painel), loga e usa force=True. Retorna True se clique foi disparado."""
    try:
        box = el.bounding_box()
        if not box:
            el.click(timeout=5000)
            return True
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        under = _element_from_point(page, cx, cy)
        under_tag = (under.get("tagName") or "").lower()
        under_class = (under.get("className") or "").lower()
        under_html = (under.get("outerHTML") or "").lower()
        # Overlap provável: elemento sob o ponto parece ser painel colapsável ("O melhor de", accordion)
        is_likely_overlap = "melhor" in under_class or "melhor" in under_html or "collapse" in under_class or "accordion" in under_class
        if is_likely_overlap:
            print(f"  {log_prefix} [OVERLAP] elementFromPoint: tag={under_tag} id={under.get('id')} class={under_class[:80]}")
        try:
            el.click(timeout=5000, force=is_likely_overlap)
        except Exception:
            el.click(timeout=5000, force=True)
        return True
    except Exception:
        try:
            el.click(timeout=5000, force=True)
            return True
        except Exception:
            return False
```

**Alteração em `run_v3_calendario_inferior` (trecho 2 — interação):**

Substituir o bloco que faz scroll + hover na seção + clique no candidato por:

```python
    # ----- 2) Interação humana simulada -----
    print("[V3.2] Scroll até a seção e clique no elemento de data (com verificação de sobreposição)...")
    try:
        # Scroll apenas até o título para reduzir chance de expor painel colapsável
        page.locator("h2:has-text('Disponibilidade'), h3:has-text('Disponibilidade')").first.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        secao_scope.scroll_into_view_if_needed(timeout=8000)
    page.wait_for_timeout(800)
    # Não fazer hover na seção inteira; hover apenas no campo de data após localizá-lo

    candidatos_data = [
        'button:has-text("Data")',
        '[data-testid*="date"]',
        '.bui-calendar__control',
        'a:has-text("Data de check-in")',
        'span:has-text("Data de check-in")',
        '[data-testid="date-display-field-start"]',
        '[data-testid="date-display-field-end"]',
    ]
    elemento_clicado = None
    for attempt in range(V3_MAX_ATTEMPTS):
        for sel in candidatos_data:
            try:
                el = secao_scope.locator(sel).first
                if el.count() == 0 or not el.is_visible():
                    continue
                el.hover(timeout=3000)
                page.wait_for_timeout(500)
                if _click_with_overlap_check(page, el, "[V3]"):
                    elemento_clicado = sel
                    print(f"    Clique executado em: {sel} (tentativa {attempt + 1})")
                    break
            except Exception:
                continue
        if elemento_clicado:
            break
        if V3_DESABILITAR_PAINEL_COLAPSAVEL:
            try:
                painel = page.locator('text="O melhor de"').first
                if painel.count() > 0:
                    painel.evaluate("node => { node.style.pointerEvents = 'none'; }")
                    print("    [V3] Painel 'O melhor de' com pointer-events desabilitado.")
            except Exception:
                pass
        page.wait_for_timeout(2000)
        _screenshot(page, f"debug_v3_attempt_{attempt + 1}.png")
    if not elemento_clicado:
        ...
```

(Manter o restante da função igual, incluindo o `if not elemento_clicado` que gera ERRO e screenshot.)

**Instrumentação opcional:** Antes do clique, salvar `under` em `SCRIPT_DIR / f"debug_v3_overlap_{attempt + 1}.txt"` (tagName, id, className, outerHTML) para análise posterior.

**Nota:** A chamada a `el.element_handle()` no `_click_with_overlap_check` pode exigir ajuste conforme a API do Playwright (ex.: passar o locator e usar evaluate com o elemento resolvido). Alternativa mais simples: não checar is_target e sempre usar `el.click(force=True)` após log de OVERLAP quando elementFromPoint for diferente do esperado (comparando tag/class do under com o do locator).

### 7.2 scripts/auditar_calendario_booking_disponibilidade.py (opcional)

Em `_clicar_primeiro_candidato_na_secao`, antes de cada `el.click(timeout=7000)` (e antes do fallback com force), obter o centro do elemento e chamar `elementFromPoint`; se o elemento sob o ponto não for o esperado (ex. tag diferente ou classe contendo "collapse"/"melhor"), logar e usar `el.click(timeout=7000, force=True)`:

```python
# Dentro do loop de candidatos, antes de el.click():
try:
    b = el.bounding_box()
    if b:
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        under = page.evaluate("""([x,y]) => { const e = document.elementFromPoint(x,y); return e ? { tag: e.tagName, id: e.id, class: (e.className||'').slice(0,100) } : {}; }""", [cx, cy])
        if under.get("class") and ("melhor" in under.get("class","") or "collapse" in under.get("class","")):
            print("  [OVERLAP] elementFromPoint indica painel colapsável; usando force=True")
            el.click(timeout=7000, force=True)
        else:
            el.click(timeout=7000)
    else:
        el.click(timeout=7000)
except Exception:
    el.click(timeout=7000, force=True)
```

### 7.3 core/scraper/scrapers.py (opcional)

- Manter `_abrir_calendario_inferior` como está; em caso de falha já existe warning e retorno False.
- Opcional: adicionar um loop `for attempt in range(2)` antes do `for sel in CANDIDATOS_BOTAO_DATA`, com `page.wait_for_timeout(2000)` entre tentativas e, na segunda tentativa, tentar apenas `el.click(force=True)`.

---

## 8. Seletores finais recomendados para _abrir_calendario_inferior

- **Seção:** `div:has(h2:has-text('Disponibilidade'))` (ou `section:has(h2:has-text('Disponibilidade'))`).
- **Scroll:** Preferir `page.locator("h2:has-text('Disponibilidade')").first.scroll_into_view_if_needed()` para minimizar scroll.
- **Campo de data (ordem):** `button:has-text("Data")`, `[data-testid*="date"]`, `.bui-calendar__control`, `[data-testid="date-display-field-start"]`, `[data-testid="date-display-field-end"]`, `a:has-text("Data de check-in")`, `span:has-text("Data de check-in")`.
- **Células:** `[data-date]` (ou `span[data-date]`).
- **Indisponível:** `aria-disabled="true"`.
- **Painel colapsável (mitigação):** `text="O melhor de"` ou `[aria-label*="melhor"]` para aplicar `pointer-events: none` apenas em scripts de diagnóstico.

---

## 9. Estimativa de esforço

| Fase | Horas (estimativa) |
|------|--------------------|
| (a) Análise completa + patches (relatório + diffs) | 1,5–2 |
| (b) Implementação (aplicar patches em scripts/ e opcional em scrapers) | 1–1,5 |
| (c) Testes manuais e ajustes (3 hotéis, evidências) | 1–2 |
| **Total** | **3,5–5,5 h** |

---

## 10. Entregáveis finais (checklist)

- [x] **scripts/RELATORIO_ANALISE_PAINEL_COLAPSAVEL.md** — diagnóstico, evidências, plano (este arquivo).
- [x] **Patches sugeridos** — trechos em §7 para aplicar manualmente em `explorar_calendario_booking.py` e opcional em `scrapers.py`.
- [x] **Plano de testes** — §6 com comandos exatos e critérios de aceitação.
- [x] **Lista de seletores recomendados** — §8 para `_abrir_calendario_inferior` e painel colapsável.

---

*Relatório gerado para análise técnica; nenhuma alteração em produção foi aplicada.*
