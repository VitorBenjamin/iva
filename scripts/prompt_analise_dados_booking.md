# Prompt para análise dos dados coletados (Booking — calendário inferior)

Use este prompt ao analisar os artefatos gerados pelo fluxo de diagnóstico do calendário Booking (`trace.zip` e `event_logs.json`). Copie o bloco abaixo e cole no Cursor junto com o contexto dos arquivos quando disponíveis.

---

## Bloco para cópia

```
## Objetivo da análise

Analise os artefatos de diagnóstico do problema de interação com o calendário inferior na página do Booking:

1. **trace.zip** — Trace do Playwright (gravação da sessão: screenshots, snapshots do DOM, network).  
   - Como usar: na pasta `scripts/`, execute `playwright show-trace trace.zip` (ou abra pelo Playwright Trace Viewer).  
   - Identifique no trace: o momento em que a navegação para a página do hotel termina; os eventos de clique/hover (se houver automação); qualquer falha de timeout ou erro de "element not visible" / "intercepted"; mudanças no DOM após scroll ou clique.

2. **event_logs.json** — Log de eventos de mouse e scroll capturados pelo script injetado `monitorar_eventos.js`.  
   - Cada entrada contém: `type` (click, mousedown, mouseup, pointerdown, pointerup, scroll), `ts` (timestamp), coordenadas (`clientX`, `clientY`, `pageX`, `pageY` quando aplicável) e `target` (tagName, id, className, dataTestId, innerText, rect).  
   - Use para: mapear em qual elemento cada clique foi disparado; ver a sequência de eventos antes de uma falha; identificar se cliques estão caindo em overlays (elementos com id/class de cookie, header, modal) em vez do botão "Veja a disponibilidade".

## Tarefas solicitadas

1. **Diagnosticar o ponto exato de falha**  
   - Com base no trace e nos event_logs: em que etapa a interação falha? (hover no botão, clique, abertura do widget, navegação entre meses?)  
   - O trace mostra algum erro de Playwright (timeout, element intercepted)? Em que ação (hover vs click)?  
   - Nos event_logs, o último evento antes da falha é em qual elemento (tag, id, class, innerText)?

2. **Mapear elementos que bloqueiam ou causam loops**  
   - Liste os elementos (tag, id, class, data-testid) que aparecem como alvo de cliques nos event_logs e que NÃO são o botão desejado ("Veja a disponibilidade" ou campo de data).  
   - Indique se algum desses elementos é fixo/sticky (header, cookie bar, overlay) e como isso explica o timeout no hover ou o clique no elemento errado.  
   - Se houver padrão de eventos repetidos (ex.: vários click em um mesmo elemento de toggle), descreva o possível loop.

3. **Plano de ação detalhado para o scraper principal**  
   - Ordene as correções por prioridade (ex.: 1) desobstruir overlays antes do hover; 2) fallback para click(force=True) em timeout de hover; 3) seletores mais específicos para o botão).  
   - Para cada item: descreva a alteração sugerida no código (arquivo e função), sem alterar arquivos de produção (`core/`) nesta análise; apenas proponha.  
   - Inclua tratamento de erro recomendado (timeouts, retry, logs).

4. **Trechos de código e plano de testes**  
   - Forneça trechos de código (Python/Playwright) que implementem as correções prioritárias, prontos para colar no script de exploração (`scripts/explorar_calendario_booking.py`).  
   - Proponha um plano de testes: (a) teste manual com trace + event_logs em um hotel onde o problema ocorre; (b) critérios de sucesso (calendário abre em até X segundos, sem loop); (c) teste de regressão em modo não-V3.

## Formato da resposta esperada

- **Resumo executivo** (2–3 linhas).  
- **Diagnóstico** (pontos 1 e 2 acima) com evidências (referências a trechos do trace ou a entradas do event_logs).  
- **Plano de ação** (ponto 3) numerado e com indicação de arquivo/função.  
- **Código** (ponto 4): trechos completos e comentados.  
- **Plano de testes**: passos e critérios de aceitação.
```

---

## Como gerar os artefatos

1. **Trace e event_logs em uma execução**  
   Na pasta do repositório:
   ```bash
   cd scripts
   python explorar_calendario_booking_trace.py
   ```
   Configure `URL_HOTEL` e `TEMPO_ESPERA_INTERACAO` no topo do script. Ao final, estarão em `scripts/`:
   - `trace.zip`
   - `event_logs.json`

2. **Apenas trace (sem injeção de JS)**  
   Comente ou remova a chamada a `add_init_script` no script de trace se não quiser o monitor de eventos.

3. **Visualizar o trace**  
   ```bash
   cd scripts
   playwright show-trace trace.zip
   ```

4. **Incluir no contexto do Cursor**  
   Ao pedir a análise, anexe ou referencie:
   - `scripts/trace.zip` (se o Cursor suportar; caso contrário, descreva o que viu no Trace Viewer).
   - `scripts/event_logs.json` (conteúdo ou amostra das primeiras/últimas entradas).
