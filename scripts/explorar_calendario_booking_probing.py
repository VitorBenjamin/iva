#!/usr/bin/env python3
"""
Probe automático para descobrir qual acionador abre o calendário inferior ([data-date])
na seção/área de "Disponibilidade" do Booking.com.

Regras:
- Não altera core/.
- Apenas scripts/ e evidências em scripts/evidence_probing/.

Estratégia:
- Carrega a URL uma vez para localizar âncora "Disponibilidade" (#availability_target / h2/h3).
- Define uma área de busca indo 1000px para baixo.
- Coleta candidatos na área (ordem de prioridade definida no enunciado).
- Para cada candidato:
  - Recarrega a página (estado limpo)
  - Neutraliza painel "O melhor de" com função segura (sem bloquear html/body)
  - Testa até MAX_VARIATIONS_PER_SELECTOR variações de interação (V1..V6, mas respeita o max)
  - Em cada variação: screenshots antes/após, screenshot do elemento, after_action,
    espera por [data-date] (WAIT_FOR_WIDGET_MS) e registra sucesso/fracasso.
  - Se sucesso: salva evidências e retorna imediatamente.
"""

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ============== CONFIGURAÇÃO (editar se necessário) ==============
URL_HOTEL = "https://www.booking.com/hotel/br/travel-inn-village-arraial.pt-br.html"
MODO_V3 = True
HEADLESS = False
MAX_VARIATIONS_PER_SELECTOR = 3
WAIT_AFTER_SCROLL_MS = 1500
WAIT_FOR_WIDGET_MS = 5000

EVIDENCE_DIR = Path("scripts/evidence_probing/")

# Seletores/ordem de candidatos (priority)
SELETORES_PRIORIDADE = [
    'button:has-text("Veja a disponibilidade")',
    'a:has-text("Veja a disponibilidade")',
    'button:has-text("Ver disponibilidade")',
    'a:has-text("Ver disponibilidade")',
    'button:has-text("disponibilidade")',
    'a:has-text("disponibilidade")',
    '[data-testid*="date"]',
    'span:has-text("Data de check-in")',
    'span:has-text("Data de check-out")',
]

# Clique/inputs genéricos e fallback "clickable"
CLICKABLE_FALLBACK_QUERY = "button, a, [role='button'], [onclick], [data-test*='date']"

# Métodos de interação
VARIACOES = ["V1", "V2", "V3", "V4", "V5", "V6"]


SCRIPT_DIR = Path(__file__).resolve().parent


# ============== Helpers de neutralização segura ==============
async def neutralizar_painel_melhor_de(page) -> int:
    """
    Neutraliza 'O melhor de' com pointer-events none e opacity 0.5.
    Importante: evita aplicar em <html>/<body> e evita contêineres gigantes
    para não bloquear interação global.
    """
    try:
        changed = await page.evaluate(
            """() => {
                const xpath = "//*[contains(., 'O melhor de')]";
                const iter = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_ITERATOR_TYPE, null);
                const nodes = [];
                let node;
                while ((node = iter.iterateNext()) !== null) nodes.push(node);
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 720;
                const viewportArea = vw * vh;

                function isTooBig(rect) {
                    if (!rect) return true;
                    const area = rect.width * rect.height;
                    return area >= viewportArea * 0.85;
                }

                function eligibleCandidate(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const tag = (el.tagName || "").toUpperCase();
                    if (tag === 'HTML' || tag === 'BODY') return false;
                    const rect = el.getBoundingClientRect();
                    if (isTooBig(rect)) return false;
                    return rect.width > 150 && rect.height > 30;
                }

                let changed = 0;
                const maxNodes = Math.min(nodes.length, 4);
                for (let k = 0; k < maxNodes; k++) {
                    let target = nodes[k];
                    if (!target || !target.parentElement) continue;

                    // sobe até achar um ancestral com tag boa e tamanho moderado
                    let picked = null;
                    let cur = target;
                    for (let steps = 0; steps < 12 && cur && cur !== document.body; steps++) {
                        const tag = (cur.tagName || '').toUpperCase();
                        const okTag = tag === 'DIV' || tag === 'SECTION' || tag === 'ASIDE' || tag === 'ARTICLE' || tag === 'MAIN';
                        if (okTag && eligibleCandidate(cur)) {
                            picked = cur;
                            break;
                        }
                        cur = cur.parentElement;
                    }
                    if (picked) {
                        picked.style.pointerEvents = 'none';
                        picked.style.opacity = '0.5';
                        changed++;
                    }
                }
                return changed;
            }"""
        )
        return int(changed or 0)
    except Exception:
        return 0


async def aceitar_cookies(page, timeout_ms: int = 3000) -> None:
    try:
        btn = page.get_by_role("button", name="Aceitar").or_(page.get_by_role("button", name="Accept"))
        await btn.click(timeout=timeout_ms)
    except Exception:
        pass


async def anchor_box_and_center(page) -> tuple[float, float, float, float]:
    """
    Retorna (x_center, y_center, y_top_search, y_bottom_search) para a âncora "Disponibilidade".
    """
    anc = page.locator("#availability_target").or_(page.locator("h2:has-text('Disponibilidade'), h3:has-text('Disponibilidade')")).first
    await anc.wait_for(state="attached", timeout=8000)
    box = await anc.bounding_box()
    if not box:
        raise RuntimeError("Âncora 'Disponibilidade' encontrada mas sem bounding_box.")
    x_center = box["x"] + box["width"] / 2
    y_center = box["y"] + box["height"] / 2
    y0_search = box["y"]
    y1_search = box["y"] + 1000
    return x_center, y_center, y0_search, y1_search


async def element_hit_info(page, cx: float, cy: float) -> dict[str, Any]:
    try:
        return await page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                if (!el) return { tagName: '', id: '', className: '', outerHTML: '' };
                return {
                    tagName: el.tagName || '',
                    id: el.id || '',
                    className: (typeof el.className === 'string' ? el.className : '') || '',
                    outerHTML: (el.outerHTML || '').slice(0, 600)
                };
            }""",
            [cx, cy],
        )
    except Exception:
        return {}


async def element_contains_aplicar(page, el) -> bool:
    try:
        return bool(
            await page.evaluate(
                """(node) => {
                    const closest = node && node.closest ? node.closest('button, a, [role="button"]') : null;
                    const txt = closest ? (closest.innerText || '') : (node.innerText || '');
                    return (txt || '').toLowerCase().includes('aplicar');
                }""",
                el,
            )
        )
    except Exception:
        return False


async def screenshot_safe(page, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path))
    except Exception:
        pass


async def dispatch_pointer_events(page, el, cx: float, cy: float) -> None:
    """
    Dispara pointer/mouse/click via dispatch manual.
    """
    await page.evaluate(
        """(node, cx, cy) => {
            if (!node) return;
            const opts = { bubbles: true, cancelable: true, clientX: cx, clientY: cy };
            let pd = new PointerEvent('pointerdown', opts);
            let pu = new PointerEvent('pointerup', opts);
            let md = new MouseEvent('mousedown', opts);
            let mu = new MouseEvent('mouseup', opts);
            let cl = new MouseEvent('click', opts);
            node.dispatchEvent(pd);
            node.dispatchEvent(pu);
            node.dispatchEvent(md);
            node.dispatchEvent(mu);
            node.dispatchEvent(cl);
        }""",
        el,
        cx,
        cy,
    )


async def attempt_method_action(page, el, method: str, cx: float, cy: float, selector_testado: str) -> bool:
    """
    Retorna True se a ação disparou sem lançar exceção.
    """
    if method == "V1":
        # click no pai button/a mais próximo se hit-test cair em svg/path
        try:
            hit = await element_hit_info(page, cx, cy)
            hit_tag = (hit.get("tagName") or "").lower()
            if hit_tag in ("svg", "path"):
                clicked = await page.evaluate(
                    """([x, y]) => {
                        const hit = document.elementFromPoint(x, y);
                        if (!hit || !hit.closest) return false;
                        const parent = hit.closest('button, a');
                        if (!parent) return false;
                        parent.click();
                        return true;
                    }""",
                    [cx, cy],
                )
                return bool(clicked)
        except Exception:
            pass
        # fallback: click normal
        await el.click(timeout=5000)
        return True

    if method == "V2":
        await el.click(timeout=5000)
        return True

    if method == "V3":
        await page.mouse.click(cx, cy, timeout=5000)
        return True

    if method == "V4":
        await el.click(timeout=5000, force=True)
        return True

    if method == "V5":
        await dispatch_pointer_events(page, el, cx, cy)
        return True

    if method == "V6":
        try:
            await el.focus(timeout=3000)
        except Exception:
            pass
        await page.keyboard.press("Enter")
        return True

    return False


async def wait_widget_open(page) -> bool:
    try:
        await page.wait_for_selector("[data-date]", timeout=WAIT_FOR_WIDGET_MS)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False


async def collect_candidates(page, anchor_center_y: float, y0_search: float, y1_search: float) -> list[dict[str, Any]]:
    """
    Coleta candidatos na área usando os critérios e ordem solicitados.
    Deduplica por (selector, index).
    """
    candidates: list[tuple[float, str, int, Any, str]] = []

    def _in_area(b) -> bool:
        if not b:
            return False
        cy = b["y"] + b["height"] / 2
        return (cy >= y0_search - 50) and (cy <= y1_search + 50)

    # a) b) c) d) e) listas prioritárias
    for sel in SELETORES_PRIORIDADE:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 15)):
                el = loc.nth(i)
                if not await el.is_visible():
                    continue
                b = await el.bounding_box()
                if not _in_area(b):
                    continue
                dist = abs((b["y"] + b["height"] / 2) - anchor_center_y)
                txt = ""
                try:
                    txt = (await el.inner_text() or "").strip()[:60]
                except Exception:
                    txt = ""
                candidates.append((dist, sel, i, el, txt))
        except Exception:
            continue

    # f) role="button" dentro da área
    try:
        loc = page.locator('[role="button"]')
        n = await loc.count()
        for i in range(min(n, 20)):
            el = loc.nth(i)
            if not await el.is_visible():
                continue
            b = await el.bounding_box()
            if not _in_area(b):
                continue
            dist = abs((b["y"] + b["height"] / 2) - anchor_center_y)
            candidates.append((dist, '[role="button"]', i, el, ""))
    except Exception:
        pass

    # g) qualquer elemento "clickable" via querySelectorAll
    try:
        loc = page.locator(CLICKABLE_FALLBACK_QUERY)
        n = await loc.count()
        for i in range(min(n, 30)):
            el = loc.nth(i)
            if not await el.is_visible():
                continue
            b = await el.bounding_box()
            if not _in_area(b):
                continue
            dist = abs((b["y"] + b["height"] / 2) - anchor_center_y)
            candidates.append((dist, CLICKABLE_FALLBACK_QUERY, i, el, ""))
    except Exception:
        pass

    # sort and dedup
    candidates.sort(key=lambda x: x[0])
    vistos: set[tuple[str, int]] = set()
    out: list[dict[str, Any]] = []
    for dist, sel, idx, el, txt in candidates:
        key = (sel, idx)
        if key in vistos:
            continue
        vistos.add(key)
        out.append(
            {
                "selector": sel,
                "index": idx,
                "dist": dist,
                "visible_text": txt,
            }
        )
    return out


async def main() -> int:
    evidence_dir = EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if MODO_V3 is not True:
        print("Este probe foi desenhado para MODO_V3=True. Prosseguindo mesmo assim.")

    attempts_summary: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()

        # lista circular (últimos 200 console)
        console_lines: list[str] = []

        def push_console(line: str):
            console_lines.append(line)
            if len(console_lines) > 200:
                del console_lines[: len(console_lines) - 200]

        page.on(
            "console",
            lambda msg: push_console(
                f"{datetime.now().isoformat()} [{msg.type}] {msg.text}"
            ),
        )

        # --- Carrega 1x para coletar âncora e candidatos ---
        console_lines.clear()
        await page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await aceitar_cookies(page)

        x_center, y_center, y0_search, y1_search = await anchor_box_and_center(page)
        candidates = await collect_candidates(page, y_center, y0_search, y1_search)
        print(f"[PROBE] Candidatos coletados: {len(candidates)} | y_area=[{y0_search:.0f}..{y1_search:.0f}]")

        # --- Loop por candidato ---
        for cand_idx, cand in enumerate(candidates, start=1):
            selector_testado = cand["selector"]
            el_index = cand["index"]

            # reset console buffer
            console_lines.clear()

            # evidências por candidato
            before_scroll = evidence_dir / f"cand_{cand_idx:03d}_before_scroll.png"
            after_scroll = evidence_dir / f"cand_{cand_idx:03d}_after_scroll.png"

            # status por candidato para registrar
            cand_opened = False
            cand_attempts: list[dict[str, Any]] = []

            try:
                # Recarrega estado limpo
                await page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await aceitar_cookies(page)
                await neutralizar_painel_melhor_de(page)

                # re-localiza anchor para manter mesma área
                _, y_center2, y0_search2, y1_search2 = await anchor_box_and_center(page)

                el = page.locator(selector_testado).nth(el_index)
                # se não existir/visível, falha e segue
                if (await el.count()) == 0:
                    print(f"[PROBE] cand {cand_idx:03d}: elemento não encontrado (selector={selector_testado}, idx={el_index}).")
                    continue
                if not await el.is_visible():
                    print(f"[PROBE] cand {cand_idx:03d}: elemento invisível (selector={selector_testado}, idx={el_index}).")
                    continue

                # Se o elemento ou ancestral contém "Aplicar", skip
                if await element_contains_aplicar(page, el):
                    print(f"[PROBE] cand {cand_idx:03d}: skip por conter 'Aplicar'. selector={selector_testado} idx={el_index}")
                    continue

                # Antes do scroll
                await el.scroll_into_view_if_needed(timeout=5000)
                await screenshot_safe(page, before_scroll)

                await page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)
                await screenshot_safe(page, after_scroll)

                # bounding/coords
                el_box = await el.bounding_box()
                if not el_box:
                    raise RuntimeError("bounding_box do elemento retornou None.")
                cx = el_box["x"] + el_box["width"] / 2
                cy = el_box["y"] + el_box["height"] / 2

                # variações a testar (respeitar MAX)
                methods_to_try = VARIACOES[:MAX_VARIATIONS_PER_SELECTOR]
                for var_idx, method in enumerate(methods_to_try, start=1):
                    attempt_id = f"{cand_idx:03d}.{var_idx:02d}"

                    element_shot = evidence_dir / f"attempt_{attempt_id}_element.png"
                    after_action_shot = evidence_dir / f"attempt_{attempt_id}_after_action.png"
                    fail_html_path = evidence_dir / f"attempt_{attempt_id}_fail.html"

                    try:
                        await screenshot_safe(page, element_shot)  # screenshot do elemento alvo

                        action_ok = await attempt_method_action(page, el, method, cx, cy, selector_testado)
                        # validar abertura sem scroll adicional
                        opened_widget = await wait_widget_open(page)
                        await screenshot_safe(page, after_action_shot)

                        if opened_widget:
                            cand_opened = True
                            console_excerpt = console_lines[-200:]
                            attempts_summary.append(
                                {
                                    "selector_testado": selector_testado,
                                    "metodo": method,
                                    "tentativa_idx": attempt_id,
                                    "opened_widget": True,
                                    "screenshots": {
                                        "before_scroll": str(before_scroll),
                                        "after_scroll": str(after_scroll),
                                        "element": str(element_shot),
                                        "after_action": str(after_action_shot),
                                    },
                                    "fail_html": None,
                                    "console_logs_excerpt": console_excerpt,
                                    "timestamp": datetime.now().isoformat(),
                                    "notes": f"Variação {method} disparou action_ok={action_ok}",
                                }
                            )
                            print(f"[PROBE] SUCCESS cand {cand_idx:03d} metodo {method} (attempt_id={attempt_id}).")
                            # sucesso imediato: retornar
                            attempts_results_path = evidence_dir / "probe_results.json"
                            attempts_results_path.write_text(
                                json.dumps(
                                    {
                                        "summary": {
                                            "success": True,
                                            "candidato": cand_idx,
                                            "selector": selector_testado,
                                            "metodo": method,
                                        },
                                        "tentativas": attempts_summary,
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                                encoding="utf-8",
                            )
                            return 0

                        # se não abriu, tenta capturar HTML falho
                        console_excerpt = console_lines[-200:]
                        if not opened_widget:
                            try:
                                html = await page.content()
                                fail_html_path.write_text(html, encoding="utf-8")
                            except Exception:
                                pass
                            attempts_summary.append(
                                {
                                    "selector_testado": selector_testado,
                                    "metodo": method,
                                    "tentativa_idx": attempt_id,
                                    "opened_widget": False,
                                    "screenshots": {
                                        "before_scroll": str(before_scroll),
                                        "after_scroll": str(after_scroll),
                                        "element": str(element_shot),
                                        "after_action": str(after_action_shot),
                                    },
                                    "fail_html": str(fail_html_path) if fail_html_path.exists() else None,
                                    "console_logs_excerpt": console_excerpt,
                                    "timestamp": datetime.now().isoformat(),
                                    "notes": f"opened_widget False; action_ok={action_ok}",
                                }
                            )
                            print(f"[PROBE] cand {cand_idx:03d} metodo {method}: opened_widget=False")

                    except Exception as e:
                        console_excerpt = console_lines[-200:]
                        try:
                            html = await page.content()
                            fail_html_path.write_text(html, encoding="utf-8")
                        except Exception:
                            pass
                        attempts_summary.append(
                            {
                                "selector_testado": selector_testado,
                                "metodo": method,
                                "tentativa_idx": attempt_id,
                                "opened_widget": False,
                                "screenshots": {
                                    "before_scroll": str(before_scroll),
                                    "after_scroll": str(after_scroll),
                                    "element": str(element_shot),
                                    "after_action": str(after_action_shot),
                                },
                                "fail_html": str(fail_html_path) if fail_html_path.exists() else None,
                                "console_logs_excerpt": console_excerpt,
                                "timestamp": datetime.now().isoformat(),
                                "notes": f"Erro: {e}",
                            }
                        )
                        print(f"[PROBE] cand {cand_idx:03d} metodo {method}: ERRO {e}")

            except Exception as e:
                print(f"[PROBE] cand {cand_idx:03d}: falhou preparação: {e}")
                # não mata o loop
                continue

        # Se chegou aqui, esgotou candidatos sem sucesso
        attempts_results_path = evidence_dir / "probe_results.json"
        attempts_results_path.write_text(
            json.dumps(
                {
                    "summary": {"success": False, "message": "Esgotou candidatos sem abrir [data-date]."},
                    "tentativas": attempts_summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("[PROBE] Fim: sem sucesso.")
        return 1
    # end async playwright


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

