# PRD – Projeto IVA v1.0 (Product Requirements Document)

## 1. Introdução

### 1.1. Nome e Versão

- **Sistema:** IVA – Inteligência de Viabilidade de Arrendamento  
- **Versão:** 1.0 (MVP com uma instância de usuário, sem login)

### 1.2. Objetivo do Documento

Definir os **requisitos de produto**, **escopo** e **prioridades** do IVA, alinhados ao SDD para implementação consistente.

---

## 2. Arquitetura Global (Visão Resumida)

### 2.1. Visão em Camadas

#### Camada de Interface (Frontend Web)

- HTML único (Single Page) servido pelo Flask
- CSS: Bootstrap 5 via CDN
- JS: Fetch API, Cleave.js (máscara), lógica básica de UI

#### Camada de Aplicação (Backend Web)

- Flask: rotas HTTP, controle de fluxo, serialização JSON
- Orquestra chamadas para módulos de domínio (scraper, financeiro, cenários, relatório)

#### Camada de Domínio (Core IVA)

Implementada no pacote `core/`. Submódulos:

- `core.projetos`
- `core.scraper`
- `core.financeiro`
- `core.cenarios`
- `core.relatorio`
- `core.orquestrador`
- `core.config`

#### Camada de Persistência

Arquivos JSON em disco:

- `data/projects/<id>.json` — projeto completo
- `data/projects/market_<id>.json` — dados de mercado (scraping)
- `data/projects/reports/<id>.html` — relatório estático gerado (opcional)

---

## 3. Tecnologias e Dependências

### 3.1. Linguagens e Runtime

- Python 3.11+ (ideal) ou 3.8+ (mínimo)
- HTML5, CSS3, JavaScript (navegador)

### 3.2. Bibliotecas Backend

- **Flask** – servidor web
- **Pydantic** – validação e modelagem de dados
- **Loguru** – logs estruturados
- **Playwright** – scraping dinâmico (Booking.com)
- **Jinja2** – templates HTML (via Flask)

### 3.3. Bibliotecas Frontend

- **Bootstrap 5** (CDN) – layout, toasts, botões
- **Cleave.js** (CDN) – máscara monetária e numérica
- **Chart.js** (CDN) – gráficos no relatório

---

## 4. Estrutura de Diretórios

### 4.1. Pacote de domínio (core)

```text
core/
├── __init__.py
├── config.py
├── orquestrador.py
├── projetos.py
│
├── scraper/
│   ├── __init__.py
│   ├── scrapers.py
│   ├── parsing.py
│   └── viabilidade.py
│
├── financeiro/
│   ├── __init__.py
│   ├── modelos.py
│   ├── calculos.py
│   └── custos.py
│
├── cenarios/
│   ├── __init__.py
│   ├── modelos.py
│   └── gerador.py
│
└── relatorio/
    ├── __init__.py
    └── gerador_html.py
```

### 4.2. Raiz do projeto

```text
iva/
├── app.py
├── requirements.txt
├── docs/
│   ├── PRD_IVA_v1_0.md
│   └── SDD_IVA_v1_0.md
├── data/
│   └── projects/
├── artifacts/
└── core/
```

---

## 5. Modelagem de Domínio

### 5.1. Entidade Projeto

Representa uma pousada / análise de viabilidade.

**Modelo Pydantic Projeto (conceitual):**

- `id`: str – identificador único (slug)
- `nome`: str
- `url_booking`: str
- `numero_quartos`: int
- `faturamento_anual`: float
- `ano_referencia`: int
- `financeiro`: DadosFinanceiros (modelo aninhado)
- `dados_mercado`: Optional[DadosMercado] – pode estar vazio antes da coleta

### 5.2. Dados Financeiros

**Modelo Pydantic DadosFinanceiros:**

- `custos_fixos`: CustosFixosMensais
- `funcionarios`: List[Funcionario]
- `custos_variaveis`: CustosVariaveisPorNoite
- `aliquota_impostos`: float (padrão 0.06)
- `percentual_contingencia`: float (padrão 0.05)

**Submodelos:**

**CustosFixosMensais**

- `luz`, `agua`, `internet`, `iptu`, `contabilidade`, `seguros`, `outros`: float

**Funcionario**

- `nome`: str
- `salario`: float
- `encargos_percentual`: float (ex.: 0.7 para 70%)
- `quantidade`: int

**CustosVariaveisPorNoite**

- `cafe_manha`, `amenities`, `lavanderia`, `outros`: float

### 5.3. Dados de Mercado (Scraping)

**Modelo Pydantic DadosMercado:**

- `id_projeto`: str
- `url`: str
- `ano`: int
- `criado_em`: datetime
- `diarias_por_periodo`: Dict[str, DiariaPeriodo]

**DiariaPeriodo:**

- `nome_periodo`: str
- `datas`: str (ex.: "2026-02-10 a 2026-02-15")
- `noites`: int
- `diaria_booking`: float
- `diaria_direta`: float (Regra: booking / 1.20)
- `tipo_tarifa`: str (ex.: "Reembolsável")
- `nome_quarto`: str

### 5.4. Resultado de Análise

**Modelo Pydantic ResultadoAnalise:**

- `diaria_media`: float
- `noites_vendidas`: float
- `taxa_ocupacao`: float (0–1)
- `rdm`: float
- `viavel`: bool
- `cenarios`: Dict[str, ResultadoCenario]

**ResultadoCenario:**

- `nome`: str (ex.: "Conservador", "Moderado", "Otimista")
- `taxa_ocupacao_alvo`: float
- `adr_utilizada`: float
- `receita_anual_estimada`: float
- `custos_totais`: float
- `lucro_liquido`: float
- `ponto_equilibrio_ocupacao`: float
- `valor_arrendamento_sugerido_mensal`: float

---

## 6. Módulos e Responsabilidades

### 6.1. core.projetos

Responsável por CRUD de projetos em JSON.

**Funções (conceituais):**

- `listar_projetos()` → List[Projeto]
- `carregar_projeto(id: str)` → Projeto
- `salvar_projeto(projeto: Projeto)` → None
- `criar_projeto_draft(dados_iniciais: dict)` → Projeto
- `gerar_id_projeto(nome: str)` → str (slugify do nome)

**Regras:**

- Ignorar arquivos `market_*.json` e subpastas como `reports/`
- Validar dados via Pydantic antes de salvar

### 6.2. core.scraper.scrapers

Responsável pela automação Playwright.

**Função principal:**

- `coletar_dados_mercado(url_booking: str, ano: int)` → DadosMercado

**Comportamento interno:**

- Configurar navegador: `locale = "pt-BR"`, `timezone_id = "America/Sao_Paulo"`
- Gerar períodos de datas (usa `core.config.definir_periodos_sazonais`)
- Para cada período: abrir Booking.com, aceitar cookies, selecionar 2 adultos/1 quarto, extrair menor diária
- Calcular `diaria_direta = diaria_booking / 1.20`
- Em caso de falha: log + screenshot em `artifacts/`
- Saída: dados no modelo DadosMercado (não HTML cru)

### 6.3. core.scraper.parsing

Funções utilitárias de parsing de texto.

- `parsear_valor_preco(texto: str)` → float (remove R$, espaços, pontos de milhar; troca vírgula por ponto)
- `detectar_tipo_tarifa(texto: str)` → str (ex.: "cancelamento grátis" → "Reembolsável")

### 6.4. core.scraper.viabilidade

Motor de engenharia reversa a partir de faturamento + dados de mercado.

**Função principal:**

- `calcular_viabilidade(faturamento_anual, numero_quartos, dados_mercado)` → ResultadoAnaliseBasica

**ResultadoAnaliseBasica:** `diaria_media`, `noites_vendidas`, `taxa_ocupacao`, `rdm`

**Regras:**

- Diária média: média simples das `diaria_direta` dos períodos bem-sucedidos
- Noites vendidas: faturamento_anual / diaria_media
- Taxa de ocupação: noites_vendidas / (quartos × 365)
- RDM: noites_vendidas / 365

### 6.5. core.financeiro.modelos e core.financeiro.calculos

- **modelos.py:** Define os Pydantic models de 5.2
- **calculos.py:** `calcular_custos_fixos_mensais`, `calcular_custos_funcionarios_mensais`, `calcular_custos_variaveis_anuais`, `calcular_impostos_e_contingencia`

### 6.6. core.cenarios.modelos e core.cenarios.gerador

- **modelos.py:** Define Cenario e ResultadoCenario (ver 5.4)
- **gerador.py:** `gerar_cenarios_basicos(analise_basica, financeiro)` → Dict com perfis Conservador, Moderado, Otimista

### 6.7. core.relatorio.gerador_html

- **Função:** `gerar_relatorio_html(projeto, analise, dados_mercado, caminho_saida)` → None
- **Requisitos:** Layout Bootstrap, tabela períodos×diárias, gráfico Chart.js, resumo de viabilidade

### 6.8. core.orquestrador

Integração central dos módulos.

- `apenas_coletar_dados_mercado(projeto)` → DadosMercado (salva em `market_<id>.json`)
- `executar_analise_com_dados_mercado(projeto, dados_mercado)` → ResultadoAnalise (inclui geração do relatório HTML)

---

## 7. Backend Web – app.py

### 7.1. Rotas Principais

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Lista projetos; redireciona ou mostra criação |
| GET | `/projeto/<id>` | Renderiza página principal com dados do projeto |
| POST | `/projeto` | Cria novo projeto |
| PUT | `/projeto/<id>` | Atualiza projeto (validação Pydantic) |
| POST | `/projeto/<id>/coletar-mercado` | Dispara coleta de mercado |
| POST | `/projeto/<id>/simular` | Executa análise e gera relatório |
| GET | `/projeto/<id>/relatorio` | Serve HTML gerado |

### 7.2. Padrão de Resposta JSON

```json
{
  "success": true,
  "message": "Descrição curta",
  "data": {}
}
```

Erros: `success: false` e `message` descritiva.

---

## 8. Frontend (Página Principal)

### 8.1. Seções

- **Cabeçalho:** Nome do sistema + seleção de projeto
- **Dados Básicos:** Nome, URL Booking, nº quartos, faturamento, ano
- **Botão "Coletar Dados de Mercado":** Normal / processando (spinner) / feedback toast
- **Configuração Financeira:** Campos `.moeda` com Cleave.js, validação básica
- **Funcionários:** Lista dinâmica, botão "Adicionar funcionário"
- **Botão "Atualizar Cálculos":** Mesmo padrão de estado/feedback
- **Link "Abrir Relatório":** Habilitado após simulação bem-sucedida

### 8.2. Máscara Monetária (Cleave.js)

- `numeral: true`
- `numeralThousandsGroupStyle: 'thousand'`
- `prefix: 'R$ '`
- Enviar `rawValue` ao backend (sem formatação)

---

## 9. Logs e Monitoramento

- **Backend:** Logar requisições importantes; erros de scraping com stack trace
- **Frontend:** Falhas de fetch → toast amigável (nunca `alert()`)

---

## 10. Roadmap de Implementação

1. Implementar `core.projetos` + rotas básicas (criar/lista de projetos)
2. Implementar UI básica com Bootstrap 5 e Cleave.js
3. Implementar `core.scraper.scrapers` com Playwright (teste isolado)
4. Integrar rota `/projeto/<id>/coletar-mercado`
5. Implementar `viabilidade` + módulos `financeiro` + `cenarios`
6. Implementar `relatorio.gerador_html`
7. Integrar rota `/projeto/<id>/simular` + link para relatório na interface

---

*Fim do PRD – Projeto IVA v1.0*
