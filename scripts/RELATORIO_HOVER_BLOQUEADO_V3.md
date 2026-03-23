# Relatório técnico — Falha de hover no botão "Veja a disponibilidade" (V3)

**Data:** 2025-03  
**Contexto:** O Playwright localiza o botão "Veja a disponibilidade" e tenta `hover()` antes do clique, mas ocorre **timeout** porque o elemento está visível porém **bloqueado para interação** (interceptação de pointer events).

---

## 1. Diagnóstico

### 1.1 Causa provável do timeout no hover

O método `element.hover()` do Playwright dispara eventos de mouse (mouseenter, mouseover, mousemove) **no elemento alvo**. Para isso, o Playwright verifica se o elemento está **actionable** (visível, estável, recebe eventos). Se outro nó do DOM estiver **por cima** do elemento (em termos de stacking context e hit-test) e tiver `pointer-events: auto` (padrão), o **nó que cobre** recebe os eventos e o Playwright considera que o alvo está **interceptado** → timeout após 3000 ms (valor atual).

Ou seja: **não é que o botão não exista ou não esteja visível; é que um overlay, banner fixo ou outro elemento está capturando os pointer events no retângulo do botão.**

### 1.2 Tipos de elementos que costumam bloquear

| Tipo | Exemplo no Booking | Seletor / característica |
|------|---------------------|---------------------------|
| Barra de cookies | Banner "Aceitar" / "Cookie preferences" | `[data-testid="cookie-banner"]`, `#cookiebanner`, `[class*="cookie"]` |
| Header fixo / sticky | Barra superior com busca, login | `header[class*="fixed"]`, `[class*="sticky"]`, `#header` |
| Overlay de modal | Lightbox, "Ver preços" | `[class*="overlay"]`, `[role="dialog"]`, `.modal` |
| Painel colapsável | "O melhor de" (já neutralizado) | `text="O melhor de"` |
| Divs de tracking/analytics | Camadas invisíveis ou semitransparentes | `position: fixed` com grande área |
| Badge / tooltip fixo | "Cobrimos o menor preço!" próximo ao bloco | Dentro do mesmo bloco da seção Disponibilidade |

O **elementFromPoint(cx, cy)** no centro do botão (já usado em `_click_com_verificacao_overlap`) indica **quem** está de fato recebendo o hit-test; se não for o botão, esse é o interceptador.

### 1.3 Por que o hover falha e o click(force=True) pode funcionar

- **hover()** não aceita `force=True` no Playwright; ele sempre exige que o elemento esteja actionable. Se houver interceptação → timeout.
- **click(force=True)** ignora a verificação de actionable e dispara o clique nas **coordenadas** do elemento (ou no centro), mesmo que outro nó esteja por cima. Por isso é um **fallback válido** quando o bloqueio é apenas visual/pointer-events.

---

## 2. Estratégia de mitigação

### 2.1 Desabilitar temporariamente elementos que interceptam (JS)

Antes do hover/clique, executar no page um script que:

1. **Identifique** o elemento alvo (ex.: botão "Veja a disponibilidade") e obtenha seu `getBoundingClientRect()`.
2. **No centro (cx, cy)** do retângulo, use `document.elementFromPoint(cx, cy)`.
3. Se o nó retornado **não for** o botão nem descendente dele:
   - Aplique no nó (ou no ancestral que cobre a área, ex.: primeiro com `position: fixed` ou `sticky`) **`style.pointerEvents = 'none'`** (e opcionalmente `visibility: 'hidden'` ou `opacity: 0` só para teste).
4. Repita para **todos** os nós entre o topo do stacking context e o documento (por exemplo, subindo com `elementFromPoint` e desabilitando camadas fixas até o alvo ficar "livre").

Alternativa mais simples e segura: **listar elementos com `position: fixed` ou `position: sticky`** que intersectem o bounding box do botão e definir `pointerEvents = 'none'` neles durante a interação. Isso remove a maioria dos headers, cookies e overlays sem alterar layout de conteúdo principal.

### 2.2 Fluxo recomendado no script

1. **Neutralização já existente:** Manter a neutralização do painel "O melhor de" (Ato 1).
2. **Nova etapa — “Desobstruir” antes do hover:**  
   Chamar uma função `_desobstruir_pointer_para_elemento(page, el)` que:  
   - Obtém o `bounding_box` do `el` (via JS ou locator).  
   - No page, executa JS que: usa `elementFromPoint` no centro; se não for o alvo, sobe na árvore e aplica `pointer-events: none` em nós com `position: fixed/sticky` que contenham esse ponto; retorna o número de nós alterados.  
   - Opcional: também desabilitar elementos com classes/ids típicos de cookie banner e header fixo.
3. **Tentativa de hover:**  
   - `el.hover(timeout=3000)`.  
   - **Em caso de timeout:** não falhar o fluxo; logar "Hover bloqueado; desobstruindo e usando clique forçado." e ir para o passo 4.
4. **Clique:**  
   - Se hover ok: usar `_click_com_verificacao_overlap` (que já pode usar `force=True` se detectar sobreposição).  
   - Se hover falhou ou se o clique normal falhar: chamar `el.click(timeout=5000, force=True)` diretamente.
5. **Validação:** Manter a espera por `[data-date]` (até 5 s) para confirmar abertura do widget.

### 2.3 Uso de click(force=True) como fallback

- **Recomendado:** Usar `force=True` **apenas** quando:  
  (a) o hover der timeout, ou  
  (b) o clique normal (sem force) falhar por interceptação.  
- Assim evitamos abusar de force em páginas onde o hit-test está correto e reduzimos risco de clicar no elemento errado.

---

## 3. Plano de implementação (patches)

### 3.1 Nova função: desobstruir pointer-events

Adicionar em `explorar_calendario_booking.py` uma função que recebe `page` e o **bounding_box** (ou o locator do botão) e executa um `page.evaluate` que:

- No centro do bbox, chama `elementFromPoint`.
- Enquanto o elemento sob o ponto não for o alvo (ou filho do alvo), sobe no DOM e aplica `pointer-events: none` em nós com `position: fixed` ou `position: sticky`, ou em nós com id/class de cookie/header (lista fixa).
- Retorna quantos nós foram alterados (para log).

Para não precisar passar o “alvo” para dentro do evaluate (o que exige handle), pode-se passar apenas `{ x, y }` do centro e, no JS, desabilitar **todos** os elementos `fixed`/`sticky` que contenham esse ponto (por exemplo, iterando os fixed/sticky e checando `getBoundingClientRect().contains(x, y)`).

### 3.2 Ajuste no loop de gatilhos

No loop que tenta cada candidato (`for sel, idx, el, texto in candidatos_unicos`):

1. **Antes** de `el.hover(...)`:
   - Chamar `_desobstruir_pointer_para_elemento(page, el)` (ou passar bbox de `el.bounding_box()`).
2. **Tentativa de hover:**
   - Envolver `el.hover(timeout=3000)` em try/except.
   - Em caso de exceção (timeout ou “element is not visible”): log "Hover bloqueado; usando clique forçado." e **não** relançar; seguir para o clique.
3. **Clique:**
   - Se houve hover com sucesso: `_click_com_verificacao_overlap(page, el, "[V3]")` como hoje.
   - Se hover falhou: chamar diretamente `el.click(timeout=5000, force=True)`.
4. Manter o restante (espera por `[data-date]`, próximo candidato em caso de falha).

### 3.3 Fallback adicional no _click_com_verificacao_overlap

Dentro de `_click_com_verificacao_overlap`, se o `el.click(timeout=5000)` (sem force) lançar exceção, já existe fallback com `el.click(timeout=5000, force=True)`. Garantir que esse fallback está presente e que a exceção de hover não interrompe o fluxo antes de chegar ao clique.

---

## 4. Sugestão de testes para validar

### 4.1 Teste manual

1. Rodar `python scripts/explorar_calendario_booking.py` com `MODO_V3 = True` e `HEADLESS = False`.
2. **Critério de sucesso:** O script deve:
   - Logar "Âncora encontrada" e "Tentando gatilho: ... Veja a disponibilidade ...".
   - Ou logar "Hover bloqueado; usando clique forçado." e em seguida "Clique executado em: ... — widget aberto." (sem travar).
   - Gerar `debug_v3_aberto.png` com o calendário aberto.
3. **Se ainda falhar:** Verificar no DevTools quais elementos têm `position: fixed` sobre o botão e adicionar seletores na lista de desobstrução.

### 4.2 Teste de regressão

- Com a neutralização do painel "O melhor de" ativa, garantir que o calendário superior (modo não-V3) não é afetado.
- Garantir que, quando não há overlay (ex.: em outro hotel ou após fechar cookies), o fluxo com hover continua funcionando (não forçar sempre `force=True` desnecessariamente).

---

## 5. Resumo

| Item | Conclusão |
|------|-----------|
| **Causa do timeout** | Elemento (overlay, header fixo, cookie bar) interceptando pointer events no retângulo do botão; hover exige elemento actionable. |
| **Desobstruir** | Via JS: elementFromPoint no centro do botão; desabilitar `pointer-events` em nós fixed/sticky (e opcionalmente cookie/header) que cubram o ponto. |
| **click(force=True)** | Usar como fallback quando hover falhar ou quando clique normal falhar; evita depender do hit-test. |
| **Melhoria de fluxo** | (1) Desobstruir antes do hover; (2) em timeout de hover, não falhar e usar clique forçado; (3) manter validação por `[data-date]`. |

---

## 6. Patches aplicados no script de exploração

- **Função `_desobstruir_pointer_para_elemento(page, el, log_prefix)`:** Obtém o bounding box do elemento, calcula o centro (cx, cy) e executa em `page.evaluate` um script que: (1) seleciona nós com `position: fixed/sticky` (via style ou class) e nós com "cookie" ou "header" em id/class; (2) filtra os que contêm o ponto (cx, cy) no retângulo; (3) aplica `style.pointer-events = 'none'` neles; (4) retorna o número de nós alterados. Log: "Desobstruído: N elemento(s) com pointer-events: none no caminho do botão."
- **Loop de gatilhos:** Antes de cada `hover`, chama-se `_desobstruir_pointer_para_elemento(page, el)`. O `el.hover(timeout=3000)` foi envolvido em try/except: em caso de exceção, loga "Hover bloqueado (timeout/interceptação); usando clique forçado." e define `hover_ok = False`. Se `hover_ok` for True, usa `_click_com_verificacao_overlap`; senão, chama `el.click(timeout=5000, force=True)` diretamente. A validação por `[data-date]` e o fallback para o próximo candidato foram mantidos.
