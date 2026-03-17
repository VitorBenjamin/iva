# Diagnóstico e Análise de Impacto — Custos variáveis por “pessoas por diária”

**Data:** 2025-03-12  
**Objetivo:** Análise prévia a qualquer alteração no cálculo de custos variáveis (modelo “pessoas por diária”).  
**Restrição:** Nenhuma implementação; apenas achados, evidências e propostas.

---

## 1) Modelo atual (projeto.json / Pydantic)

### Onde ficam os custos variáveis

- **Caminho no código:** `projeto.financeiro.custos_variaveis`
- **Persistência:** `data/projects/<id>/projeto.json` → chave `financeiro.custos_variaveis`
- **Modelo Pydantic:** `core/financeiro/modelos.py`

**Classe:**

```python
class CustosVariaveisPorNoite(BaseModel):
    """Custos variáveis por noite vendida."""

    cafe_manha: float = Field(default=0.0, ge=0)
    amenities: float = Field(default=0.0, ge=0)
    lavanderia: float = Field(default=0.0, ge=0)
    outros: float = Field(default=0.0, ge=0)
```

**Campos disponíveis:** Apenas quatro floats: `cafe_manha`, `amenities`, `lavanderia`, `outros`. Não há campo `nome`, `unidade`, `por_pessoa` nem indicação explícita de unidade no schema.

**Interpretação hoje no código:** Os valores são tratados como **R$/noite por pessoa** (evidência na função de cálculo abaixo). O docstring do modelo diz “por noite vendida”, mas a única função que usa esses campos interpreta a soma como “por pessoa” e multiplica por `ocupacao_media_pessoas`.

**Resposta (a/b/c):**  
**b) R$/noite por pessoa** — é assim que a função `_custo_variavel_por_noite` os usa (soma × pessoas). O schema não declara isso; a intenção está apenas na implementação.

---

## 2) Auditoria da função de cálculo

### Função e onde é chamada

- **Função:** `_custo_variavel_por_noite(projeto, ocupacao_media_pessoas=2.0)`  
- **Arquivo:** `core/analise/engenharia_reversa.py` (linhas 104–112)
- **Chamadas:**
  - `core/analise/simulacao.py`: `calcular_projecao` (com `ocupacao_media_pessoas=2.0`)
  - `core/analise/engenharia_reversa.py`: cálculo de custos variáveis anuais na análise (com `2.0`)
- **API:** `app.py` em `/api/projeto/<id>/simulacao/dados-base` chama `_custo_variavel_por_noite(projeto)` **sem** segundo argumento → usa default 2.0.

### Fórmula exata

```python
def _custo_variavel_por_noite(projeto: Projeto, ocupacao_media_pessoas: float = 2.0) -> float:
    """Retorna o custo variável estimado por noite (por quarto), considerando pessoas."""
    ...
    cv = fin.custos_variaveis
    por_pessoa = float(cv.cafe_manha) + float(cv.amenities) + float(cv.lavanderia) + float(cv.outros)
    total = por_pessoa * ocupacao_media_pessoas
    return max(total, 0.0)
```

- **Fórmula:** `(cafe_manha + amenities + lavanderia + outros) * ocupacao_media_pessoas`
- **Multiplicador fixo:** Sim. O default é `2.0` (usado no simulador e na engenharia reversa; a API de dados-base não passa o parâmetro).
- **O que o 2 representa:** O docstring diz “por noite (por quarto), considerando pessoas”. O nome do parâmetro é `ocupacao_media_pessoas`. Conclusão: **2 = “média de 2 pessoas por diária”** (premissa fixa hoje).

---

## 3) Consistência com a memória de cálculo (simulacao.py)

No `core/analise/simulacao.py`:

- **`ocupacao_media_pessoas = 2.0`** — mesmo valor usado em `_custo_variavel_por_noite`.
- **`itens_cv_unitarios`:** cada item é `(nome, val * ocupacao_media_pessoas)`, em que `val` é o valor bruto do modelo (cafe_manha, amenities, etc.).
- **`valor_unitario`** no detalhe = `valor_unit` = valor por pessoa × 2 → **R$/noite por quarto (2 pessoas)**.
- **`subtotal_mensal`** = `valor_unitario * noites_vendidas` → alinhado ao custo variável total do mês (`noites_vendidas * custo_var_noite`), pois `custo_var_noite` é a soma desses `valor_unitario`.

**Conclusão:** A memória de cálculo está **alinhada** com `_custo_variavel_por_noite`: ambos tratam os campos do modelo como “por pessoa” e multiplicam por 2. Não há duplicação de multiplicador; o risco é **conceitual**: o schema e a UI não deixam claro que os valores no projeto são “por pessoa” e que o sistema aplica “× 2” por diária.

---

## 4) Proposta de mudança (apenas conceito)

### Alternativa A — Modelo 2 simples

- Incluir no projeto (ex.: `projeto.financeiro` ou no próprio `CustosVariaveisPorNoite`) um campo **`media_pessoas_por_diaria`** (float, ex.: 2.13).
- **Uso:** Em `_custo_variavel_por_noite` e na memória de cálculo, substituir o `2.0` fixo por esse campo (com default 2.0 para compatibilidade).
- **Vantagem:** Um único parâmetro, fácil de explicar e de preencher (média histórica ou meta).
- **Onde definir:** Pode ser em `DadosFinanceiros` (afeta só custos variáveis) ou no nível do `Projeto` (se for usado em outros módulos no futuro).

### Alternativa B — Modelo 3 estendido (futuro)

- Campos do tipo **adultos** e **crianças** por diária (ex.: `media_adultos_por_diaria`, `media_criancas_por_diaria`), com possibilidade de custos por tipo (ex.: café só adulto, criança com fator 0,5).
- **Schema atual:** `CustosVariaveisPorNoite` não tem estrutura por tipo de hóspede; teria que ser estendido (novos campos ou subobjeto) e a fórmula redefinida.
- **Uso:** Só faz sentido se houver regra de negócio diferenciada (ex.: preço criança para café/lavanderia). Caso contrário, A atende.

---

## 5) Análise de impacto (implementação futura)

### Arquivos a alterar

| Arquivo | Alteração |
|---------|-----------|
| `core/financeiro/modelos.py` | Incluir `media_pessoas_por_diaria` (ou equivalente) em `DadosFinanceiros` ou em `CustosVariaveisPorNoite`; documentar unidade dos campos (R$/pessoa/noite). |
| `core/analise/engenharia_reversa.py` | `_custo_variavel_por_noite`: obter multiplicador do projeto (default 2.0) em vez de fixo. |
| `core/analise/simulacao.py` | Obter `media_pessoas_por_diaria` do projeto; usar em `itens_cv_unitarios` e garantir que `detalhe_custos_variaveis` e totais continuem consistentes. |
| `app.py` | Se a API expuser “custo variável por noite” ou parâmetros de simulação, incluir/retornar `media_pessoas_por_diaria` quando existir. |
| `templates/simulacao.html` | Na “Memória de cálculo”, opcionalmente exibir “Média de X pessoas por diária” e garantir que o rótulo “Custo unitário (R$/noite)” continue claro (por quarto, já considerando pessoas). |
| Telas/forms de cadastro do projeto (ex.: `static/js/main.js`, templates de projeto) | Campo de entrada para `media_pessoas_por_diaria` (default 2) e salvamento em `financeiro`. |

### Funções afetadas

- `_custo_variavel_por_noite` (engenharia_reversa): passar a usar parâmetro vindo do projeto.
- `calcular_projecao` (simulacao): leitura de `media_pessoas_por_diaria` e repasse para o detalhe e para o total.
- Qualquer outro uso de “2.0” ou “ocupacao_media_pessoas” hardcoded em custos variáveis (hoje só esses dois módulos).

### Riscos

1. **Duplicar o multiplicador:** Se em um lugar usar “× 2” e em outro “× media_pessoas_por_diaria”, os totais divergem. Mitigação: uma única fonte (projeto ou default 2.0) em todas as funções.
2. **Backend vs UI:** Front exibir “R$/noite” sem deixar claro que é “por quarto (já com X pessoas)”. Mitigação: rótulo explícito e, se possível, exibir “X pessoas/diária” na memória de cálculo.
3. **Cenários salvos:** `simulacao_cenarios.json` guarda `resultado` (meses com `custos_variaveis`, `detalhe_custos_variaveis`). Cenários antigos foram calculados com 2.0; ao mudar o projeto para 2.13, ao **recalcular** o cenário os números mudam; ao **apenas carregar** o cenário salvo, continuam os números antigos. Comportamento esperado; não é necessário migrar JSON de cenários.
4. **Projetos existentes sem o novo campo:** Default 2.0 no código e no Pydantic (`Field(default=2.0)`) mantém comportamento atual.

### Backward compatibility / migração

- **Novo campo:** `media_pessoas_por_diaria: float = 2.0` (ou nome escolhido) com default no modelo.
- **Leitura:** Sempre usar `getattr(..., "media_pessoas_por_diaria", 2.0)` ou `projeto.financeiro.media_pessoas_por_diaria` com default no schema, para projetos antigos sem a chave no JSON.
- **Persistência:** Ao salvar projeto (PUT ou form), gravar o novo campo; projetos antigos passam a tê-lo como 2.0 ao serem recarregados (default do Pydantic).

---

## Entregável resumido

| Item | Conteúdo |
|------|----------|
| **Como é hoje** | Custos variáveis no projeto são quatro floats (café, amenities, lavanderia, outros). O schema diz “por noite vendida”; o código trata como **R$/noite por pessoa** e aplica **× 2** (média de 2 pessoas por diária) para obter R$/noite por quarto. Simulador e memória de cálculo usam a mesma regra. |
| **Risco principal** | Interpretação “por pessoa” não está documentada no modelo nem na UI; trocar depois para “pessoas por diária” configurável pode confundir se o default ou o rótulo não forem claros. Risco de duplicar multiplicador se a mudança for feita em apenas um dos pontos (eng. reversa vs simulador). |
| **Recomendação** | Adotar **Alternativa A**: campo único `media_pessoas_por_diaria` (default 2.0), uma única fonte de verdade no projeto, e documentar no schema/UI que os quatro itens são “R$/noite por pessoa”. Só considerar B se surgir regra de negócio por tipo de hóspede. |
| **O que mudar depois** | (1) Schema + default em `core/financeiro/modelos.py`; (2) `_custo_variavel_por_noite` e `calcular_projecao` usando o valor do projeto; (3) API/front que expõem ou editam dados financeiros; (4) rótulos na memória de cálculo (ex.: “Custo unitário (R$/noite por quarto, 2,13 pess.)”). |
