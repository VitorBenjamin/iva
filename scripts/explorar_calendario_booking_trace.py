#!/usr/bin/env python3
"""
Script de exploração do Booking com trace Playwright habilitado.
Abre a página do hotel, grava trace (screenshots, snapshots, network) e permite
interação manual ou automatizada por um tempo configurável. Injeta o monitor
de eventos (monitorar_eventos.js) para registrar cliques e scroll. Ao final,
salva trace.zip e event_logs.json para análise posterior. Não altera core/.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

# ============== CONFIGURAÇÃO (editar antes de rodar) ==============
URL_HOTEL = "https://www.booking.com/hotel/br/travel-inn-village-arraial.pt-br.html"
ANO_MES_ALVO = "2026-04"  # YYYY-MM (apenas referência para logs)
# Tempo (segundos) que o script aguarda na página para interação manual ou automatizada
TEMPO_ESPERA_INTERACAO = 60
# Trace e logs (relativos a scripts/)
TRACE_OUTPUT = "trace.zip"
EVENT_LOGS_OUTPUT = "event_logs.json"
# ===================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
TRACE_PATH = SCRIPT_DIR / TRACE_OUTPUT
EVENT_LOGS_PATH = SCRIPT_DIR / EVENT_LOGS_OUTPUT
MONITOR_JS_PATH = SCRIPT_DIR / "monitorar_eventos.js"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (Kernel, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def main() -> None:
    """Abre o navegador com trace, navega para o hotel, aguarda e salva o trace."""
    print("============================================")
    print("EXPLORAÇÃO BOOKING COM TRACE")
    print("============================================")
    print(f"URL: {URL_HOTEL}")
    print(f"Mês alvo (ref.): {ANO_MES_ALVO}")
    print(f"Aguardando {TEMPO_ESPERA_INTERACAO}s para interação...")
    print(f"Trace será salvo em: {TRACE_PATH}")
    print()

    async with async_playwright() as p:
        # Chromium em modo visível para interação e inspeção
        browser = await p.chromium.launch(headless=False)

        # Contexto com locale e user-agent consistentes com o scraper
        context = await browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=USER_AGENT,
        )

        # Inicia gravação do trace (screenshots, snapshots do DOM, network, etc.)
        await context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )

        page = await context.new_page()

        # Injeta o monitor de eventos (cliques, scroll) para coleta em event_logs.json
        if MONITOR_JS_PATH.exists():
            await page.add_init_script(path=str(MONITOR_JS_PATH))
            print("    Monitor de eventos (monitorar_eventos.js) será injetado em cada carga.")
        else:
            print("    Aviso: monitorar_eventos.js não encontrado; event_logs não serão coletados.")

        try:
            print("[1] Navegando para a página do hotel...")
            await page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"    Aviso: {e}. Prosseguindo mesmo assim...")
        await page.wait_for_timeout(2000)

        # Aceitar cookies se aparecer (evita overlay)
        try:
            btn = page.get_by_role("button", name="Aceitar").or_(
                page.get_by_role("button", name="Accept")
            )
            await btn.click(timeout=3000)
            print("    Cookies aceitos (se exibidos).")
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        print(f"[2] Página carregada. Aguardando {TEMPO_ESPERA_INTERACAO}s para interação (manual ou automatizada)...")
        await page.wait_for_timeout(TEMPO_ESPERA_INTERACAO * 1000)

        # Salvar logs de eventos capturados pelo script injetado
        try:
            raw = await page.evaluate("() => JSON.stringify(window.__eventLogs || [])")
            events = json.loads(raw)
            EVENT_LOGS_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    Event logs salvos: {EVENT_LOGS_PATH} ({len(events)} eventos)")
        except Exception as e:
            print(f"    Aviso: não foi possível salvar event_logs: {e}")

        print("[3] Parando trace e salvando...")
        await context.tracing.stop(path=str(TRACE_PATH))
        print(f"    Trace salvo: {TRACE_PATH}")
    await browser.close()
    print("Concluído. Use 'playwright show-trace trace.zip' (na pasta scripts/) para visualizar o trace.")


if __name__ == "__main__":
    asyncio.run(main())
