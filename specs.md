# IVA — Specs de Implementacao

## 1. Escopo minimo por feature
- Objetivo funcional claro.
- Entradas/saidas (API/UI) explicitadas.
- Regra de negocio formalizada (formula quando financeira).
- Criterios de aceite com casos de borda.

## 2. Regras para backend
- Reaproveitar funcoes oficiais antes de criar novas.
- Nao duplicar formula financeira em multiplos pontos.
- Toda persistencia deve usar helpers de path em `core/projetos.py`.
- Validar payload com Pydantic antes de persistir.

## 3. Regras para calculos financeiros
- Ordem obrigatoria:
  1) Receita Bruta
  2) Custos Variaveis (inclui comissao sobre receita)
  3) EBITDA
  4) Impostos
  5) Lucro Liquido
- ADR deve seguir hierarquia oficial vigente.
- Break-even deve respeitar definicao operacional (EBITDA >= 0).
- Payback deve retornar indefinido quando lucro medio mensal <= 0.

## 4. Regras para API
- Resposta padrao:
  - `success: bool`
  - `message: str`
  - `data: object|null`
- Mudanca breaking em endpoint exige:
  - compatibilidade temporaria ou versao
  - migracao documentada.

## 5. Regras para frontend (UX cockpit)
- Simulador e telas analiticas devem atualizar via AJAX (sem reload).
- Mensagens de usuario via Toast Bootstrap, nao `alert()`.
- Inputs monetarios/percentuais devem usar utilitarios compartilhados.
- Graficos devem refletir o mesmo estado da tabela (fonte unica de dados da resposta da API).

## 6. Qualidade e seguranca de mudanca
- Antes de alteracao estrutural:
  1) gerar analise de impacto
  2) criar backup `.bak`
  3) registrar evento em `SYSTEM_EVENTS.jsonl`
- Alteracoes de calculo exigem teste de regressao financeiro.

## 7. Checklist de entrega
- [ ] Regras de negocio atualizadas na documentacao
- [ ] Contrato API validado
- [ ] Testes locais passando
- [ ] Compatibilidade legada avaliada
- [ ] Evento de auditoria registrado
