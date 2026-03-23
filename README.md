# IVA - Inteligência de Viabilidade de Arrendamento

## Onboarding de Pousada

Para criar uma nova pousada e configurar o scaffold completo, veja [Guia de Onboarding de Pousada](docs/GUIA_ONBOARDING_POUSADA.md).

## Estrutura de dados (oficial)

- `data/projects/<id_projeto>/projeto.json`
- `data/projects/<id_projeto>/scraper_config.json`
- `data/projects/<id_projeto>/market_bruto.json`
- `data/projects/<id_projeto>/market_curado.json`
- `data/projects/<id_projeto>/cenarios.json`

## Paths centralizados

Use sempre os helpers de `core/projetos.py`:

- `get_projeto_json_path(id_projeto)`
- `get_scraper_config_path(id_projeto)`
- `get_market_bruto_path(id_projeto)`
- `get_market_curado_path(id_projeto)`
- `get_cenarios_path(id_projeto)`

Evite caminhos hardcoded para manter compatibilidade com migrações e estrutura legada.

## Feature-flag STRICT_PERIODOS

- `STRICT_PERIODOS` controla o filtro soberano de datas especiais na Curadoria.
- Valor padrão: `false` (comportamento legado).
- Quando `true`, a Curadoria exibe especiais apenas com `meta.periodo_source == "config"` e `meta.periodo_id` presente no `scraper_config` atual.
- Override opcional por projeto em `projeto.json`:
  - `strict_periodos: true|false`, ou
  - `curadoria.strict_periodos: true|false`

## Feature-flags de desconto unificado

- `BACKEND_DESCONTO_UNIFICADO` (default: `true`): backend calcula `preco_direto` da Curadoria via fonte única (`projeto.curadoria` > `market_curado.meta` > `scraper_config`).
- `FRONTEND_DESCONTO_UNIFICADO` (default: `false`): habilita o fluxo novo de preview/aplicação no frontend (rollout controlado).

## Curadoria: Preço Direto por data vs média

- `Preço Direto (por data)`: valor calculado a partir do `preco_booking` da própria data (prioritário na UI quando disponível).
- `Preço Direto (Média do período)`: fallback para casos agregados em que não existe base por data.
- A UI exibe o indicador de origem para evitar confusão entre valor unitário e valor agregado.

## Testes e CI

### Execução local

- Comando padrão:
  - `./scripts/run_tests.sh`
- Com browser habilitado:
  - `SKIP_BROWSER_TESTS=0 ./scripts/run_tests.sh`

### Playwright local

Se houver testes que dependem de browser, instale os navegadores antes:

- `python -m playwright install`

### GitHub Actions

O workflow em `.github/workflows/ci.yml`:

- roda em `push` e `pull_request` nas branches principais;
- executa matriz Python `3.10` e `3.11`;
- define `SKIP_BROWSER_TESTS=1` por padrão no CI;
- executa `python -m unittest discover -v`;
- publica log de testes como artifact.

Há também um job manual (`workflow_dispatch`) para testes com Playwright, com `SKIP_BROWSER_TESTS=0`.
