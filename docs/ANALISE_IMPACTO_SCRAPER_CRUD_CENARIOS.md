# Análise de Impacto e Plano de Ação: Robustez do Scraper + CRUD de Cenários

**Data:** 2025-03-12  
**Escopo:** (1) Revisão da lógica do scraper (datas especiais + log semântico), (2) CRUD de cenários (Update + persistência), (3) Auditoria de CRUDs gerais.  
**Restrição:** NÃO IMPLEMENTAR — apenas análise e plano.

---

## 1. REVISÃO DA LÓGICA DO SCRAPER (DATAS ESPECIAIS)

### 1.1 Como `definir_calendario_soberano_ano` gera a amostra hoje

**Local:** `core/config.py`, linhas 289–385.

- A função gera **uma única lista** de períodos (dicts com `checkin`, `checkout`, `mes_ano`, `tipo_dia`, `categoria_dia`, `noites`).
- Regra fixa: **4 datas por mês** (2 sábados + 2 terças: 1ª e 3ª semana, 2ª e 4ª semana), dentro da janela rolling (hoje → hoje+365) ou ano civil.
- Para cada uma dessas 4×N datas, é calculado `categoria_dia = "especial"` se o check-in cair em algum `periodos_especiais` (ou feriado) ou `"normal"` caso contrário.
- **Não há lista separada por tipo:** todos os itens vêm da mesma grade 4/mês. O número total de itens é **fixo** (~46 para 12 meses na janela rolling); o que muda é apenas quantos desses 46 são marcados como `"especial"` e quantos como `"normal"`.

**Conclusão:** A contagem de “especiais” não reflete o peso desejado (1–2 check-ins por período configurado). Ela só indica quantos dos 4/mês caíram dentro de um período especial. Se o usuário adicionar 5 períodos no `scraper_config.json`, o total de itens da amostra **não aumenta**; só pode mudar a classificação de alguns dos 46 itens.

---

### 1.2 Diagnóstico: por que a contagem de especiais “não muda” da forma esperada?

- **Causa raiz:** A amostra é **só a grade 4/mês**. Períodos especiais do config são usados apenas para **classificar** cada data dessa grade, não para **gerar** check-ins adicionais.
- **Efeito:** Adicionar ou remover períodos em `periodos_especiais` altera apenas quantos dos ~46 itens são `categoria_dia="especial"`. Não aparece “1 ou 2 check-ins por período” como bloco dedicado.

---

### 1.3 Proposta: duas listas — `lista_normais` e `lista_especiais`

| Lista | Regra de geração | Fonte |
|-------|-------------------|--------|
| **lista_normais** | Amostragem mensal: 4 datas/mês (2 FDS + 2 dia de semana), **excluindo** qualquer data que caia dentro de um período especial (ou feriado). | Mesma lógica de `definir_calendario_soberano_ano`, mas filtrar `if not eh_especial(checkin)`. |
| **lista_especiais** | 1 ou 2 check-ins **por** período em `_periodos_especiais_de_config` (já com avanço automático): ex.: 1º dia do período e opcionalmente dia intermediário ou último. Dentro da janela rolling. | Nova função ou extensão em `core/config.py` que percorre `periodos_list` e, para cada `(d_ini, d_fim, nome)`, gera 1–2 datas de check-in em `[d_ini, d_fim]` com `noites` do config. |

**Ordem de execução no scraper:** FASE 1 = iterar `lista_normais`; FASE 2 = iterar `lista_especiais`. O resultado final (preencher `calendario_completo` a partir de `coletados`) permanece: cada dia do calendário diário continua tendo no máximo um registro (coletado ou placeholder). Não há mudança no formato de `market_bruto.json`.

---

### 1.4 Onde inserir `carregar_config_scraper()` para o CLI usar o JSON mais recente

- **Hoje:** `carregar_config_scraper(id_projeto)` é chamado **dentro** de `coletar_dados_mercado_expandido` (uma vez, no início) e também indiretamente em `definir_calendario_soberano_ano` → `_periodos_especiais_de_config` → `carregar_config_scraper`. Ou seja, o config é lido no momento da coleta.
- **CLI:** `core/scraper/cli.py` não chama `carregar_config_scraper`. Ele chama `coletar_dados_mercado_expandido(url_booking, id_projeto)`, que já carrega o config. Portanto o CLI **já usa** o JSON mais recente no momento da execução.
- **Reforço desejável:** No início de `coletar_dados_mercado_expandido`, **antes** de gerar calendário e amostras, chamar explicitamente `cfg = carregar_config_scraper(id_projeto) or {}` e usar esse `cfg` (e, se necessário, repassar `id_projeto` para as funções que leem config) para garantir uma única leitura “fresca” no início da coleta. Opcionalmente, o CLI pode chamar `carregar_config_scraper(id_projeto)` logo após `_atualizar_projeto` apenas para validar que o projeto tem config (e logar aviso se não tiver), sem alterar a lógica atual de quem realmente usa o config (scrapers).

**Recomendação:** Manter a leitura dentro de `coletar_dados_mercado_expandido` como fonte da verdade; adicionar no **início** dessa função uma chamada explícita e um log do tipo: `Config scraper carregado para projeto <id> (periodos_especiais: N).`

---

### 1.5 Novo formato de LOG no terminal

- **Antes do loop:**  
  - `Total NORMAIS: X | Total ESPECIAIS: Y`  
  - `FASE 1: NORMAIS` e depois `FASE 2: ESPECIAIS` (com linha separadora opcional).
- **Por item:**  
  - `>>> [i/Total] DATA (NOITES) [TIPO: NORMAL | ESPECIAL - NOME_PERIODO]`  
  - Exemplo normal: `>>> [3/40] 2025-04-12 (2) [TIPO: NORMAL]`  
  - Exemplo especial: `>>> [42/52] 2025-12-28 (2) [TIPO: ESPECIAL - Réveillon]`

Implementação: em `core/scraper/scrapers.py`, construir `lista_normais` e `lista_especiais`; concatenar para um único loop **ou** dois loops com logs de fase; em cada iteração logar com o rótulo acima (para especiais, incluir `nome` do período no log).

---

### 1.6 Plano de ação (scraper + log)

| Passo | Onde | Ação |
|-------|------|------|
| 1 | `core/config.py` | Criar função `gerar_amostra_soberano_ano(id_projeto, ano_referencia, noites, rolling=True)` que retorna `{"normais": list[dict], "especiais": list[dict]}`. Normais: mesma regra 4/mês, excluindo datas em período especial. Especiais: 1–2 check-ins por período em `_periodos_especiais_de_config`, dentro da janela. Cada item com `checkin`, `checkout`, `mes_ano`, `noites`, `categoria_dia`, e para especiais `periodo_nome`. |
| 2 | `core/config.py` | Manter `definir_calendario_soberano_ano` compatível (retornar lista única) **ou** deprecar e passar a usar apenas `gerar_amostra_soberano_ano` no scraper. Se deprecar, substituir chamadas em um único lugar. |
| 3 | `core/scraper/scrapers.py` | Em `coletar_dados_mercado_expandido`: (a) Chamar `carregar_config_scraper(id_projeto)` no início e logar resumo do config. (b) Obter amostra via `gerar_amostra_soberano_ano` (ou equivalente que retorne normais + especiais). (c) Definir `dias_amostra = lista_normais + lista_especiais` (ou iterar em duas fases). (d) Logar totais: "Total NORMAIS: X | Total ESPECIAIS: Y". (e) Na iteração: log "FASE 1: NORMAIS" antes do primeiro bloco e "FASE 2: ESPECIAIS" antes do segundo; para cada item logar `>>> [i/Total] checkin (noites) [TIPO: NORMAL | ESPECIAL - NOME]`. |
| 4 | `app.py` | Se existir uso de `definir_calendario_soberano_ano` ou de amostra em preview/outros endpoints, passar a usar a nova estrutura (normais + especiais) apenas onde for necessário; manter compatibilidade com o que consome o resultado. |

---

### 1.7 Mock de log do terminal (exemplo)

```
Config scraper carregado para projeto 'meu-projeto' (periodos_especiais: 5).
Calendário diário: 365 dias totais; amostra: 52 para coleta (noites pref=2, max_tent=4).
Total NORMAIS: 40 | Total ESPECIAIS: 12
--- FASE 1: NORMAIS ---
>>> [1/52] 2025-03-15 (2) [TIPO: NORMAL]
>>> [2/52] 2025-03-22 (2) [TIPO: NORMAL]
...
>>> [40/52] 2025-12-09 (2) [TIPO: NORMAL]
--- FASE 2: ESPECIAIS ---
>>> [41/52] 2025-12-28 (2) [TIPO: ESPECIAL - Réveillon]
>>> [42/52] 2026-02-14 (2) [TIPO: ESPECIAL - Carnaval]
...
Market bruto salvo: ... (365 registros; ...)
```

---

### 1.8 Riscos e compatibilidade com `market_bruto.json`

- **Estrutura do arquivo:** Continua igual: um registro por dia do `calendario_completo` (gerado por `gerar_calendario_diario_projeto`). Apenas o **conjunto de check-ins que são efetivamente raspados** aumenta (normais + especiais), preenchendo mais chaves em `coletados` e portanto mais dias com `preco_booking`/`preco_direto` preenchidos.
- **Risco:** Se, por bug, uma mesma data de check-in aparecer em normais e especiais, o segundo sobrescreve em `coletados[checkin_str]`. Mitigação: garantir que a geração de normais **exclua** datas que já estão em qualquer período especial.
- **Compatibilidade:** Leitores existentes de `market_bruto.json` (curadoria, análise) já esperam uma lista de registros por dia; não há mudança de schema. **Sem impacto de quebra.**

---

## 2. CRUD DE CENÁRIOS (UPDATE E PERSISTÊNCIA)

### 2.1 Identificar Update vs Create no `POST /api/projeto/<id>/simulacao/cenarios`

- **Hoje:** O endpoint só cria: gera `uuid` novo, ignora qualquer `id` no body.
- **Proposta:** Aceitar no body um campo opcional `id` (string). Se `id` for enviado **e** existir um cenário com esse `id` em `simulacao_cenarios.json`, tratar como **UPDATE**: substituir esse objeto na lista (mesmo `id` e `criado_em`, atualizar `nome`, `metas_mensais`, `investimento_inicial`, `resultado`, e opcionalmente `atualizado_em`). Caso contrário (sem `id` ou `id` não encontrado), tratar como **CREATE** (comportamento atual).
- **Alternativa REST:** Usar `PUT /api/projeto/<id>/simulacao/cenarios/<cid>` para update e manter `POST` apenas para create. A análise considera a opção de um único `POST` com `id` opcional para reduzir mudanças no frontend e manter um único botão “Salvar”.

---

### 2.2 Persistência atômica ao atualizar um cenário

- **Hoje:** `_salvar_cenarios(id_projeto, cenarios)` reescreve o arquivo inteiro com `path.write_text(...)`. Se o processo morrer no meio da escrita, o arquivo pode ficar corrompido.
- **Atômico:** Escrever em arquivo temporário no mesmo diretório (ex.: `simulacao_cenarios.json.tmp`) e depois `os.replace(tmp, path)` (ou `Path.rename`). Em Windows/POSIX, `replace` é atômico em relação a outros processos que abrem o path final.
- **Outros cenários:** A atualização de um cenário é feita em memória: lista = carregar; encontrar índice por `id`; `lista[indice] = novo_cenario`; salvar lista. Não há lock entre leitura e escrita; em ambiente single-worker (Flask dev) o risco é baixo. Para multi-worker, considerar lock por arquivo ou por `id_projeto`.

---

### 2.3 Frontend: estado do “Cenário Ativo”

- **Hoje:** Não existe noção de “cenário ativo”. Ao clicar “Salvar cenário”, sempre abre prompt de nome e envia POST (create). Carregar um cenário apenas preenche inputs e gráficos; não marca qual cenário está “em edição”.
- **Proposta:**  
  - Variável JS global (ex.: `cenarioAtivoId: string | null`). Ao **carregar** um cenário (botão “Carregar”): `cenarioAtivoId = c.id`. Ao criar novo (sem carregar de lista) ou após “Novo cenário”: `cenarioAtivoId = null`.  
  - Botão “Salvar”:  
    - Se `cenarioAtivoId !== null`: enviar POST com `id: cenarioAtivoId` (e mesmo payload de metas, investimento, resultado) → backend atualiza.  
    - Se `cenarioAtivoId === null`: pedir nome (prompt) e enviar POST sem `id` → backend cria.  
  - Após salvar com sucesso (create ou update), atualizar lista; em caso de update, manter `cenarioAtivoId`; em caso de create, opcionalmente definir `cenarioAtivoId` como o novo `id` retornado.  
  - Botão “Novo cenário” (opcional): limpar formulário e `cenarioAtivoId = null`.

---

## 3. AUDITORIA DE CRUDs GERAIS

### 3.1 Projetos

- **Create:** `POST /api/projeto` — cria projeto com `id` (slug) e persiste.
- **Read:** `GET /api/projeto/<id>` (implícito em várias rotas) e listagem de projetos.
- **Update:** `PUT /api/projeto/<id>` — atualiza nome, url_booking, numero_quartos, faturamento_anual, ano_referencia, financeiro (parcial). **Edição completa disponível.**
- **Delete:** Não identificado endpoint de delete na análise rápida; pode ser que não exista.

**Conclusão:** Projetos têm CRUD completo para edição (Create + Read + Update); só falta Delete se for requisito.

---

### 3.2 Scraper Config

- **Read:** `GET /api/projeto/<id_projeto>/scraper/config` (JSON) e página `GET /projeto/<id_projeto>/scraper/config`.
- **Update (parcial):** `POST /projeto/<id_projeto>/scraper/config`:  
  - Se o body contiver **apenas** `descontos`, faz **merge** com config existente (atualiza só descontos).  
  - Se o body contiver mais campos (ex.: `periodos_especiais`), o backend **substitui o arquivo inteiro** por `body` (após validações), ou seja, **save completo** da config.  
- **Conclusão:** Não é “apenas criar”. É um **único endpoint de escrita** que faz update completo quando o formulário envia a config inteira, e update parcial (só descontos) quando recebe só `descontos`. Ou seja, **edição completa é possível** via POST com body completo.

---

## 4. RESUMO DO PLANO DE EXECUÇÃO (QUANDO AUTORIZADO)

1. **Scraper – config:**  
   - No início de `coletar_dados_mercado_expandido`, chamar e logar `carregar_config_scraper(id_projeto)`.

2. **Scraper – duas listas:**  
   - Em `core/config.py`, implementar `gerar_amostra_soberano_ano` → `{normais, especiais}`; normais = 4/mês fora de períodos especiais; especiais = 1–2 check-ins por período configurado.  
   - Em `core/scraper/scrapers.py`, usar essa amostra, iterar em duas fases (normais, depois especiais) e aplicar o novo formato de log.

3. **Cenários – backend:**  
   - Em `POST /api/projeto/<id>/simulacao/cenarios`, se o body tiver `id` e o cenário existir, fazer update in-place na lista e retornar 200 com dados do cenário; senão, create como hoje.  
   - Em `_salvar_cenarios`, escrever em `path + ".tmp"` e depois `os.replace(tmp, path)` para persistência atômica.

4. **Cenários – frontend:**  
   - Manter `cenarioAtivoId`; ao carregar cenário, setar `cenarioAtivoId = c.id`; ao salvar, enviar `id: cenarioAtivoId` se não for null; caso contrário, pedir nome e criar. Opcional: botão “Novo cenário” que zera `cenarioAtivoId` e limpa formulário.

5. **Auditoria:**  
   - Nenhuma alteração obrigatória em Projetos ou Scraper Config; ambos já permitem edição (update). Implementar delete de projeto apenas se for requisito futuro.

---

*Documento gerado para apoio à decisão; implementação somente após autorização.*
