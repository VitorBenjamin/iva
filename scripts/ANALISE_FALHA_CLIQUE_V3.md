# Análise da falha de clique V3 — Calendário inferior (seção Disponibilidade)

**Data:** 2025-03  
**Contexto:** O script de exploração V3 localizou a seção "Disponibilidade" e neutralizou o painel colapsável com sucesso, mas **não encontrou elemento clicável dentro do `secao_scope`** para abrir o calendário. O screenshot `debug_v3_clique_falhou.png` mostra a seção visível e o widget fechado.

---

## 1. Inspeção do screenshot e gatilho visual

### 1.1 O que o screenshot mostra

- **Seção em destaque:** Na captura, a área visível em foco é a seção **"O que os viajantes estão perguntando"** (perguntas frequentes).
- **Gatilho identificado:** No canto superior direito, alinhado ao cabeçalho dessa área, há um **botão azul com o texto "Veja a disponibilidade"**. Esse é o principal CTA (call-to-action) para abrir o widget de disponibilidade/calendário nesta página.
- **Ausência de campos de data na vista:** Não aparecem na imagem os campos clássicos "Data de check-in" / "Data de check-out" dentro do frame. O texto "disponibilidade" aparece **dentro do botão azul**, e não como título de bloco visível no recorte.
- **Painel "O melhor de":** Não está visível no frame, indicando que a neutralização (Ato 1) provavelmente funcionou ou que o scroll deixou esse bloco fora da vista.

### 1.2 Conclusão visual

O **gatilho correto para abrir o calendário inferior** nesta URL/hotel é o **botão "Veja a disponibilidade"** (botão azul), e não necessariamente um campo "Data de check-in" ou "Data" dentro do mesmo bloco do título "Disponibilidade". O script atual procura apenas **dentro** do `secao_scope` por elementos de data; nesse escopo não existe esse botão.

---

## 2. Por que o seletor atual falhou

### 2.1 Escopo usado no V3

- **Definição:** `secao_scope = page.locator("div:has(h2:has-text('Disponibilidade'))").first`
- Ou equivalente: `div` (ou `section`) que **contém** um `h2` com o texto "Disponibilidade".

### 2.2 Conteúdo real desse container (evidência HTML)

O arquivo **`debug_disponibilidade_html.txt`** mostra o HTML do container que contém o `h2` "Disponibilidade":

```html
<div class="hp-section-header hp-section-header--with-badge ">
  <h2 id="availability_target" name="availability_target" ... class="hp-dates-summary__header">
    Disponibilidade
  </h2>
  <div id="rate_guarantee">
    ... <button data-testid="price-match-trigger" ...>Cobrimos o menor preço!</button> ...
  </div>
</div>
```

Ou seja, dentro desse `div` existem apenas:

- O **h2** "Disponibilidade" (e o id `availability_target`).
- O bloco **"Cobrimos o menor preço!"** (botão de price match).

**Não há:**

- Campos "Data de check-in" / "Data de check-out".
- Botão "Data".
- Botão **"Veja a disponibilidade"**.
- Elementos com `data-testid="date-display-field-start"` ou similares.

### 2.3 Diagnóstico de escopo

- O **`secao_scope`** está correto para achar o **título** "Disponibilidade", mas é **restritivo demais** para achar o gatilho do calendário.
- A barra de datas e o botão **"Veja a disponibilidade"** não são **filhos** desse `div.hp-section-header`; estão em **outro bloco do DOM** (irmão ou bloco seguinte no layout), ainda que visualmente façam parte da “seção de disponibilidade” para o usuário.
- Por isso, **todos** os candidatos atuais (por exemplo `secao_scope.locator('button:has-text("Data")')`, `secao_scope.locator('[data-testid*="date"]')`, etc.) retornam **zero** elementos: eles são procurados **apenas dentro** de um div que não contém nenhum deles.

**Resumo:** O seletor atual falha porque o **elemento que abre o calendário (botão "Veja a disponibilidade") está fora do container definido por `div:has(h2:has-text('Disponibilidade'))`** — ou seja, é um problema de **escopo (container restritivo)**, e não de visibilidade ou ordem de seletores.

---

## 3. Cinco novos seletores candidatos (para este hotel / página)

Com base no screenshot (botão "Veja a disponibilidade") e na estrutura típica do Booking (ids, textos, roles), estes são **5 candidatos específicos** para usar **na página inteira** ou num **escopo alargado** (ver seção 5):

| # | Seletor | Justificativa |
|---|--------|----------------|
| 1 | `button:has-text("Veja a disponibilidade")` | Texto exato do botão azul visível no screenshot. |
| 2 | `a:has-text("Veja a disponibilidade")` | O CTA pode ser um link estilizado como botão. |
| 3 | `[id="availability_target"] ~ * button:has-text("disponibilidade")` | Botão que contenha "disponibilidade" em nó irmão posterior ao `#availability_target`. |
| 4 | `text="Veja a disponibilidade"` | Forma alternativa de match por texto (Playwright). |
| 5 | `[id="availability_target"] >> xpath=following-sibling::*//button[contains(., 'disponibilidade')]` ou, em termos de locator, buscar após o h2 um botão com "disponibilidade" (ex.: `page.locator('#availability_target').locator('..').locator('..').get_by_role('button', name=/disponibilidade/i)`) | Garante busca na **região** seguinte ao título "Disponibilidade", mesmo que em outro bloco. |

Recomendação prática: tentar primeiro **1** e **2** (e, se necessário, **4**) na **página inteira**; se o layout variar, usar **3** ou **5** para amarrar à região do `#availability_target`.

---

## 4. Plano “Clique Robusto” (varredura de gatilhos + debug)

### 4.1 Objetivo

- Não depender de um único container restrito.
- Listar **todos os elementos clicáveis** na região da seção (por exemplo, após o `#availability_target` ou dentro de um bloco “Disponibilidade” mais amplo) e tentar os mais prováveis em ordem.
- Gerar **dump de debug** dos elementos encontrados **antes** de tentar o clique, para diagnóstico mesmo quando falhar.

### 4.2 Escopo alargado (duas opções)

- **Opção A — Por âncora:**  
  - Âncora: `#availability_target` (h2 "Disponibilidade").  
  - Escopo de busca: o **próximo container pai** que englobe o h2 e os irmãos seguintes (ex.: `page.locator('#availability_target').locator('xpath=ancestor::*[position()<=5]')` e escolher o que tiver altura/área razoável), **ou** usar um container conhecido (ex. `[data-block-id="availability"]` se existir).  
  - Dentro desse escopo alargado, buscar botões/links com "disponibilidade", "Data", "check-in", etc.

- **Opção B — Por região da página:**  
  - Obter `bounding_box` do `#availability_target`.  
  - Definir uma faixa vertical (ex.: `y0 = bbox.y`, `y1 = bbox.y + 800`).  
  - Na página inteira, listar todos os `button`, `a`, `[role="button"]` cujo centro esteja nessa faixa e que contenham texto relevante ("Veja a disponibilidade", "Data", "check-in", "disponibilidade", "Alterar pesquisa").

### 4.3 Lógica de tentativa sequencial (varredura de gatilhos)

1. **Fase 1 — Candidatos prioritários (página inteira):**  
   Tentar, em ordem:  
   - `button:has-text("Veja a disponibilidade")`  
   - `a:has-text("Veja a disponibilidade")`  
   - `text="Veja a disponibilidade"`  
   - `get_by_role('button', name=/veja a disponibilidade/i)`  
   Para cada um: verificar `count() > 0` e `is_visible()`; se sim, registrar no dump e tentar hover + clique (com verificação de sobreposição, como no Ato 1).

2. **Fase 2 — Candidatos no escopo alargado:**  
   - Definir escopo como “container que contém `#availability_target` e seus irmãos” (ou faixa vertical como em 4.2 B).  
   - Listar nesse escopo: `button`, `a`, `[role="button"]`, `[data-testid*="date"]`, `[data-testid*="calendar"]`.  
   - Filtrar por: texto contendo "disponibilidade", "Data", "check-in", "Alterar pesquisa", "Ver disponibilidade", "Selecionar datas".  
   - Ordenar por relevância (ex.: "Veja a disponibilidade" e "Data" primeiro).  
   - Para cada elemento: dump (tag, texto, data-testid, classes) e tentativa de clique.

3. **Fase 3 — Fallback por região (bounding box):**  
   - Usar a caixa do `#availability_target` + margem (ex.: +600px para baixo, ±100px lateral).  
   - `page.locator('button, a[href], [role="button"]')` e filtrar por `bounding_box()` dentro da faixa; fazer dump e tentar clicar na ordem: primeiro os que têm "disponibilidade" ou "Data" no texto.

### 4.4 Dump de debug antes do clique

Para **cada** candidato considerado (e, opcionalmente, para todos os clicáveis da região), registrar em log ou em arquivo (ex.: `scripts/debug_v3_gatilhos_candidatos.txt`):

- `tagName`, `id`, `data-testid`, `className` (ou `class`), `innerText` (primeiros 80 caracteres).
- `outerHTML` (primeiros 400–600 caracteres).
- `bounding_box` (x, y, width, height).

Formato sugerido (uma linha por candidato, depois bloco com HTML):

```
[CANDIDATO 1] tag=BUTTON text="Veja a disponibilidade" data-testid=... class=... bbox={...}
[CANDIDATO 2] ...
---
HTML CANDIDATO 1: <button ...>...</button>
---
```

Isso permite, após execução, ver exatamente o que foi encontrado e por que um clique foi ou não tentado, sem alterar produção.

### 4.5 Critério de sucesso

- Após um clique, esperar aparecer o widget (ex.: `[data-date]` ou texto "Preços aproximados") em até 5–10 s.  
- Se aparecer: considerar sucesso e seguir com a extração do DNA (como já no V3).  
- Se nenhum candidato abrir o widget: salvar o dump completo e o screenshot (ex.: `debug_v3_clique_falhou.png`) e encerrar com erro claro: "Nenhum gatilho abriu o calendário; ver debug_v3_gatilhos_candidatos.txt".

---

## 5. Resumo e próximos passos

| Item | Conclusão |
|------|-----------|
| **Por que falhou** | O `secao_scope` (div que contém só o h2 "Disponibilidade") **não contém** o botão "Veja a disponibilidade" nem os campos de data; o gatilho está em **elemento irmão/outro bloco**. |
| **Gatilho visual** | Botão azul **"Veja a disponibilidade"** no topo direito da área de perguntas. |
| **5 novos candidatos** | `button:has-text("Veja a disponibilidade")`, `a:has-text("Veja a disponibilidade")`, `text="Veja a disponibilidade"`, botão com "disponibilidade" em irmão de `#availability_target`, e busca por região (faixa vertical após o h2). |
| **Plano Clique Robusto** | (1) Candidatos prioritários na página inteira; (2) escopo alargado (após `#availability_target` ou por bbox); (3) fallback por região; (4) dump de todos os candidatos antes de clicar; (5) critério de sucesso por presença do widget. |

**Próximo passo recomendado (quando for autorizada a alteração do script):** Implementar no `explorar_calendario_booking.py` a varredura de gatilhos com os novos candidatos e o dump de debug, mantendo a neutralização do painel e o scroll cirúrgico já em uso.
