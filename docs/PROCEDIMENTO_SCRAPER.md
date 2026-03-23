# Procedimento para Rodar o Scraper e Atualizar Dados

Este documento descreve como atualizar os dados de mercado (`market_bruto.json` e `market_curado.json`) de um projeto IVA.

## Pré-requisitos

- Python 3.10+
- Playwright instalado: `python -m playwright install`
- Projeto cadastrado em `data/projects/<id_projeto>/` com `projeto.json` e `scraper_config.json`

## Passo a Passo

### 1. Entrar na pasta do projeto IVA

```bash
cd /caminho/absoluto/do/iva
```

### 2. Executar o scraper

```bash
python -m core.scraper.cli --url "https://www.booking.com/hotel/br/..." --id "id-projeto" --ano 2026
```

**Parâmetros:**
- `--url`: URL do hotel no Booking.com (obrigatório)
- `--id`: ID/slug do projeto (obrigatório)
- `--ano`: Ano de referência (opcional; padrão: ano atual)

### 3. Resultado da execução

O scraper:
- Lê `scraper_config.json` do projeto (períodos especiais, descontos, etc.)
- Sobrescreve `market_bruto.json` com os novos dados coletados
- Ao concluir com sucesso, os dados antigos são substituídos

### 4. Após a atualização

- Abra a **Curadoria** do projeto na interface web para revisar e ajustar preços manualmente
- A Curadoria usa os descontos configurados em `scraper_config.json` (seção `descontos`) para calcular o Preço Direto
- Ao salvar ajustes na Curadoria, o `market_curado.json` é gravado com backup automático em `data/projects/<id>/backups/`

## Descontos no scraper_config.json

O sistema aceita descontos em dois formatos:
- **Decimal:** `0.15` (15%)
- **Percentual:** `15` (15%)

Exemplo:
```json
{
  "descontos": {
    "global": 0.15,
    "por_mes": {
      "07": 0.20
    }
  }
}
```

## Backups de market_curado.json

Toda gravação do `market_curado.json` (ao clicar em "Salvar Ajustes" na Curadoria):
1. Faz backup do arquivo atual em `data/projects/<id>/backups/market_curado_YYYYMMDD_HHMMSS.json`
2. Grava o novo conteúdo de forma atômica
3. Registra o evento em `data/projects/<id>/backups/audit_market_curado.jsonl`

## Atualizar dados sem perder ajustes manuais

⚠️ **Atenção:** O scraper sobrescreve o `market_bruto.json`. O `market_curado.json` é independente e contém apenas os ajustes manuais (preço_curado) por check-in. Ao rodar o scraper novamente, o `market_bruto` é atualizado, mas o `market_curado` permanece. A Curadoria faz o merge: para cada check-in, usa `preco_curado` se existir, senão usa `preco_direto` (calculado do bruto com desconto).

Se o scraper adicionar novas datas que não existiam antes, essas datas aparecerão na Curadoria com preço calculado automaticamente. Datas removidas do bruto não aparecem mais.
