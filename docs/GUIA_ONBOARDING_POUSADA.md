# Guia de Onboarding de Pousada

Este guia descreve os passos para configurar uma nova pousada (projeto) no sistema IVA.

## 1. Criar a pousada

### Via interface web

1. Acesse a página principal.
2. Clique em **Criar Pousada**.
3. Preencha:
   - **Nome** (obrigatório): ex.: "Pousada do Sol"
   - **URL Booking** (obrigatório): ex.: `https://www.booking.com/hotel/br/sua-pousada`
   - **Cidade** (opcional)
   - **Timezone** (opcional, padrão: `America/Sao_Paulo`)
4. Marque "Executar scrape agora" se quiser rodar a coleta imediata.
5. Clique em **Criar**.

### Via API

```bash
curl -X POST http://localhost:5000/api/pousada \
  -H "Content-Type: application/json" \
  -d '{"nome": "Minha Pousada", "booking_url": "https://www.booking.com/hotel/br/..."}'
```

## 2. Estrutura criada (scaffold)

O sistema cria automaticamente em `data/projects/<id>/`:

| Arquivo/Pasta | Descrição |
|---------------|-----------|
| `projeto.json` | Metadados e configuração principal |
| `scraper_config.json` | Config do scraper (datas, descontos, etc.) |
| `market_bruto.json` | Dados brutos coletados do Booking |
| `market_curado.json` | Dados curados para simulação |
| `cenarios.json` | Cenários salvos |
| `backups/` | Pasta para backups automáticos |
| `README_ONBOARDING.md` | Passos rápidos específicos do projeto |

## 3. Checklist de onboarding

Após criar a pousada, verifique o **Checklist de Onboarding** na interface ou via:

```bash
curl http://localhost:5000/api/pousada/<id>/validate
```

Itens esperados:

- `scraper_config_exists`: config do scraper criada
- `booking_url_valid`: URL Booking em formato válido
- `market_bruto_exists`: arquivo de mercado bruto presente
- `permissions_ok`: permissões de escrita
- `backups_dir_exists`: pasta de backups criada

## 4. Executar o scraper

Para popular `market_bruto.json` com dados do Booking:

```bash
python -m core.scraper.cli --url "https://www.booking.com/hotel/br/..." --id "<id_projeto>" --ano 2026
```

Substitua a URL pela do seu hotel e `<id_projeto>` pelo ID (slug) da pousada.

## 5. Curadoria

1. Selecione a pousada no seletor.
2. Clique em **Abrir Curadoria**.
3. Revise e ajuste os preços manualmente conforme necessário.

## 6. Backups e logs

- **Backups**: Salvos em `data/projects/<id>/backups/`.
- **Audit**: `backups/audit_market_curado.jsonl`
- **Scraper traces**: `scripts/evidence_stability/SCRAPER_CONFIG_TRACE.jsonl`, `LOG_AFTER.jsonl`
- **Eventos do sistema**: `scripts/evidence_stability/SYSTEM_EVENTS.jsonl`

## 7. Regenerar README do projeto

Para gerar ou atualizar o `README_ONBOARDING.md` de um projeto:

```bash
python scripts/generate_project_readme.py <id_projeto>

## 8. Modo STRICT_PERIODOS (Curadoria)

Para ativar o filtro soberano de períodos especiais na Curadoria:

```bash
set STRICT_PERIODOS=true
```

Com a flag ativa, a Curadoria exibe apenas especiais com `meta.periodo_source = "config"` e `meta.periodo_id` válido no `scraper_config.json` atual. Registros fora dessa regra aparecem na seção de **Inconsistências**.
```

## Referências

- [Procedimento do Scraper](PROCEDIMENTO_SCRAPER.md)
- [PRD IVA](PRD_IVA_v1_0.md)
