#!/usr/bin/env python3
"""
Auditoria do calendário inferior (widget de disponibilidade) na seção "Disponibilidade" do Booking.com.

Requisitos:
- Script isolado/standalone
- Nao importa core/ nem app.py
- Nao altera arquivos de producao

Saidas (evidencias):
- scripts/debug_disponibilidade_pagina.png
- scripts/debug_disponibilidade_secao.png
- scripts/debug_disponibilidade_html.txt
- scripts/debug_calendario_inferior_aberto.png
- scripts/debug_widget_calendario_html.txt
- scripts/debug_seletores_celulas.txt
- scripts/debug_amostras_celulas.json
- scripts/output_disponibilidade_auditoria_{ANO_MES_ALVO}.json (resumo tecnico)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ================== CONFIG (edite antes de rodar) ==================
URL_HOTEL = "https://www.booking.com/hotel/br/travel-inn-village-arraial.pt-br.html"
ANO_MES_ALVO = "2026-04"  # YYYY-MM
HEADLESS = False
TIMEOUT_PADRAO_MS = 60000

# Para scroll progressivo ate encontrar a secao
MAX_SCROLLS = 18
SCROLL_STEP_PX = 900
WAIT_AFTER_SCROLL_MS = 600

# Para limitar extracao de amostras e evitar travar
MAX_DATE_CELLS_SAMPLE = 120

# =================================================================

SCRIPT_DIR = Path(__file__).resolve().parent

DEBUG_DIR = SCRIPT_DIR

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SECOES_CANDIDATAS_LOCALIZACAO = [
    'text="Disponibilidade"',
    "text=Disponibilidade",
    'h2:has-text("Disponibilidade")',
    'h3:has-text("Disponibilidade")',
    '[data-testid*="availability"]',
    '[id*="availability"]',
    '[class*="availability"]',
    'text="Availability"',
    "text=Availability",
    'h2:has-text("Availability")',
    'h3:has-text("Availability")',
]

# Candidatos de clique dentro da secao (ordem: textos da barra de datas primeiro)
SELETORES_CLICK_CANDIDATOS = [
    'text="Data de check-in"',
    'text="Data de check-out"',
    '[data-testid="date-display-field-start"]',
    '[data-testid="date-display-field-end"]',
    '[data-testid="searchbox-dates-container"]',
    'text="Alterar pesquisa"',
    'text="Selecionar datas"',
    'text="Ver disponibilidade"',
    'text="Datas"',
    '[data-testid*="date"]',
    '[data-testid*="calendar"]',
    '[class*="date"]',
    '[class*="calendar"]',
    'input[name*="checkin" i]',
    'input[name*="checkout" i]',
    'input',
    'button',
]

# Candidatos de celulas do widget de calendario inferior
SELETORES_CELULAS_CANDIDATOS = [
    '[data-date]',
    'td[data-date]',
    'span[data-date]',
    '[role="gridcell"]',
    '[role="button"]',
    '[role="checkbox"]',
    '[class*="calendar"] [class*="day"]',
    '[class*="calendar"] td',
    '[class*="calendar"] span',
    '[class*="calendar"] [class*="price"]',
    '[class*="price"]',
]

CLASSES_INDISPONIVEL = [
    "disabled",
    "unavailable",
    "blocked",
    "unselectable",
    "no-checkin",
]


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _aceitar_cookies(page, timeout=3000) -> None:
    try:
        btn = page.get_by_role("button", name="Aceitar").or_(
            page.get_by_role("button", name="Accept")
        )
        btn.click(timeout=timeout)
    except Exception:
        pass


def _scroll_ate(texto_ancora: str, page) -> object | None:
    """Rola progressivamente e tenta encontrar um elemento textual. Retorna locator do primeiro match."""
    for _ in range(MAX_SCROLLS):
        try:
            # Lancar uma estrategia simples primeiro para reduzir custo
            # (usamos locators com text selectors na fase de busca completa)
            loc = page.locator(f'text={texto_ancora}').first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            pass
        page.mouse.wheel(0, SCROLL_STEP_PX)
        page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)
    return None


def _localizar_secao_disponibilidade(page):
    """
    Tenta encontrar a secao "Disponibilidade" usando multiplas estrategias.
    Retorna dicionario com:
      - locator
      - estrategia
      - tag_container (tagName do container pai principal encontrado via closest)
      - container_locator_html_snippet
      - bounding_box
    """
    found = None
    tried = []

    # Estrategia: procurar qualquer match visivel e usar o primeiro que tiver bounding box razoavel.
    for sel in SECOES_CANDIDATAS_LOCALIZACAO:
        tried.append(sel)
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            if not loc.is_visible():
                continue

            box = loc.bounding_box()
            if not box:
                continue

            # Se aparecer no topo mas for irrelevante, ainda assim pode servir.
            found = {"locator": loc, "estrategia": sel, "bounding_box": box}
            break
        except Exception:
            continue

    if not found:
        return {"found": False, "tried": tried}

    loc = found["locator"]
    # Container pai razoavel (closest pode retornar null; nesse caso usamos o proprio elemento)
    try:
        container_info = loc.evaluate(
            """el => {
                const c = el.closest('section,article,main,div');
                const container = c || el;
                const r = container.getBoundingClientRect();
                return {
                    tag: container.tagName,
                    html: (container.outerHTML || '').slice(0, 8000),
                    rect: {x: r.x, y: r.y, width: r.width, height: r.height}
                };
            }"""
        )
    except Exception:
        container_info = {"tag": None, "html": "", "rect": None}

    found["tag_container"] = container_info.get("tag")
    # Preferir bounding box do container (para nao ficarmos com apenas a altura do texto/heading)
    rect = container_info.get("rect")
    if rect and "y" in rect and "height" in rect:
        found["bounding_box"] = rect
    return {"found": True, **found, "container_html_snippet": container_info.get("html")}


def _clicar_primeiro_candidato_na_secao(page, secao_locator, secao_box) -> dict:
    """
    Procura candidatos de clique dentro da secao (ou descendentes) e clica no primeiro que estiver
    dentro do range vertical da secao.
    """
    if not secao_box:
        secao_box = {"y": 0, "height": 999999, "x": 0, "width": 999999}
    # Regiao ampliada: titulo "Disponibilidade" + barra de datas logo abaixo (ate ~600px)
    y0 = secao_box["y"]
    y1 = secao_box["y"] + secao_box["height"] + 600
    x0 = max(0, (secao_box.get("x", 0) or 0) - 100)
    x1 = x0 + (secao_box.get("width", 1200) or 1200) + 200

    clicked = False
    clicked_sel = None
    clicked_idx = None
    tried = []

    for sel in SELETORES_CLICK_CANDIDATOS:
        tried.append(sel)
        try:
            # Expandir a busca: alguns widgets/click targets podem ficar em containers vizinhos
            # mesmo estando visivelmente relacionados a esta secao.
            loc = page.locator(sel)
            count = loc.count()
            if count == 0:
                continue

            max_idx = min(count, 40)
            for i in range(max_idx):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                try:
                    b = el.bounding_box()
                except Exception:
                    b = None
                if not b:
                    continue

                cy = b["y"] + b["height"] / 2
                cx = b["x"] + b["width"] / 2
                if cy < y0 - 60 or cy > y1 + 140:
                    continue
                if cx < x0 - 80 or cx > x1 + 80:
                    continue

                try:
                    el.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                try:
                    el.click(timeout=7000)
                except Exception:
                    # tenta force em ultimo caso
                    try:
                        el.click(timeout=7000, force=True)
                    except Exception:
                        continue

                clicked = True
                clicked_sel = sel
                clicked_idx = i
                return {
                    "clicked": True,
                    "clicked_sel": clicked_sel,
                    "clicked_idx": clicked_idx,
                    "tried": tried[:],
                }
        except Exception:
            continue

    # Fallback: clicar no segundo "Data de check-in" (o primeiro costuma ser o da searchbox global)
    try:
        loc = page.locator('text="Data de check-in"')
        n = loc.count()
        for idx in range(min(n, 5)):
            el = loc.nth(idx)
            try:
                b = el.bounding_box()
            except Exception:
                b = None
            if not b or b["y"] < 250:
                continue
            el.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(500)
            el.click(timeout=7000)
            return {
                "clicked": True,
                "clicked_sel": f"text=Data de check-in (idx={idx}) fallback",
                "clicked_idx": idx,
                "tried": tried,
            }
    except Exception:
        pass

    return {"clicked": False, "clicked_sel": clicked_sel, "clicked_idx": clicked_idx, "tried": tried}


def _widget_confirmar(page, secao_box) -> tuple[bool, dict]:
    """
    Confirma widget usando textos esperados e presenca de data-date nas proximidades.
    Retorna (widget_confirmado, evidencias)
    """
    evid = {
        "texto_precos_aprox": False,
        "texto_estadia_1_diaria": False,
        "tem_data_date": False,
        "data_date_count_sample": 0,
    }

    # Textos
    for txt in ["Preços aproximados", "Preços aproximados", "Precos aproximados", "Preços aproximados"]:
        try:
            if page.locator(f'text={txt}').first.count() > 0:
                evid["texto_precos_aprox"] = True
                break
        except Exception:
            pass
    try:
        if page.locator('text="estadia de 1 diária"').first.count() > 0:
            evid["texto_estadia_1_diaria"] = True
        if page.locator('text="estadia de 1 diária"' ).first.count() > 0:
            evid["texto_estadia_1_diaria"] = True
    except Exception:
        pass

    # Presenca de data-date
    try:
        loc = page.locator('[data-date]')
        cnt = loc.count()
        if cnt > 0:
            evid["tem_data_date"] = True
        # amostra dentro de range vertical para nao confundir com calendario superior
        sample = min(cnt, 30)
        y0 = secao_box["y"] - 50 if secao_box else 0
        y1 = (secao_box["y"] + secao_box["height"] + 250) if secao_box else 10**9
        in_range = 0
        for i in range(sample):
            try:
                b = loc.nth(i).bounding_box()
            except Exception:
                b = None
            if b and b["y"] >= y0 and b["y"] <= y1:
                in_range += 1
        evid["data_date_count_sample"] = in_range
    except Exception:
        pass

    # Regra de confirmacao: precisa de texto esperado OR pelo menos indico de data-date no range
    widget_confirmado = evid["texto_precos_aprox"] and (evid["texto_estadia_1_diaria"] or evid["data_date_count_sample"] > 0)
    return widget_confirmado, evid


def _extrair_outer_html_do_widget(page, secao_box):
    """
    A partir de um elemento [data-date] proximo da secao, extrai outerHTML do container mais provavel.
    """
    y0 = secao_box["y"] - 50
    y1 = secao_box["y"] + secao_box["height"] + 250
    loc = page.locator('[data-date]')
    cnt = loc.count()
    chosen = None
    chosen_box = None

    for i in range(min(cnt, 80)):
        try:
            el = loc.nth(i)
            b = el.bounding_box()
            if b and b["y"] >= y0 and b["y"] <= y1:
                chosen = el
                chosen_box = b
                break
        except Exception:
            continue

    if not chosen:
        return {"widget_container_html": None, "widget_bounds": None}

    try:
        info = chosen.evaluate(
            """el => {
                const c = el.closest('[data-testid*="date"], [data-testid*="calendar"], .bui-calendar, [class*="calendar"], [role="grid"]');
                const container = c || el;
                return {
                    html: (container.outerHTML || '').slice(0, 40000),
                    tag: container.tagName || null
                };
            }"""
        )
        return {"widget_container_html": info.get("html"), "widget_bounds": chosen_box, "widget_tag": info.get("tag")}
    except Exception:
        return {"widget_container_html": None, "widget_bounds": chosen_box}


def _extrair_status_celula(el) -> dict:
    """
    Extrai atributos e texto relevantes de uma celula/elemento de dia do widget.
    """
    info = {
        "tipo": "incerta",
        "texto": "",
        "classes": "",
        "atributos": {},
        "html": "",
    }
    try:
        info["texto"] = (el.inner_text() or "").strip()
    except Exception:
        info["texto"] = ""

    try:
        info["classes"] = el.get_attribute("class") or ""
    except Exception:
        info["classes"] = ""

    attrs = {}
    for a in ["data-date", "aria-disabled", "data-disabled", "disabled", "role", "aria-label"]:
        try:
            v = el.get_attribute(a)
        except Exception:
            v = None
        if v is not None:
            attrs[a] = v
    info["atributos"] = attrs

    try:
        info["html"] = (el.evaluate("node => node.outerHTML || ''") or "")[:20000]
    except Exception:
        info["html"] = ""

    # Heuristica para tipo
    txt = info["texto"]
    cls = (info["classes"] or "").lower()
    aria_disabled = (attrs.get("aria-disabled") or "").lower() == "true"
    if aria_disabled or any(c in cls for c in CLASSES_INDISPONIVEL) or "—" in txt:
        info["tipo"] = "com_traco"
        return info

    # Preco visivel: tentamos procurar R$ ou um numero com separador
    if re.search(r"R\$\s*[\d.,]+", txt) or re.search(r"[\d]{1,3}[\d.,]{0,10}", txt):
        info["tipo"] = "com_preco"
        return info

    info["tipo"] = "incerta"
    return info


def main() -> int:
    url = URL_HOTEL
    ano_mes = ANO_MES_ALVO
    start = datetime.utcnow().isoformat()

    print("============================================")
    print("AUDITORIA - CALENDARIO INFERIOR (SECAO DISPONIBILIDADE)")
    print("============================================")
    print(f"URL: {url}")
    print(f"Mes alvo: {ano_mes}")
    print(f"Headless: {HEADLESS}")
    print()

    out_summary = {
        "ano_mes_alvo": ano_mes,
        "url_hotel": url,
        "started_at_utc": start,
        "secao_disponibilidade": None,
        "click_disponibilidade": None,
        "widget_confirmado": None,
        "widget_evidencias": None,
        "widget_bounds": None,
        "debug_files": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", user_agent=USER_AGENT)
        page = context.new_page()

        try:
            # PASSO 1: abrir a pagina
            print("[1] Navegando para o hotel...")
            page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_PADRAO_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO_MS)
            except Exception:
                print("Aviso: timeout em networkidle; prosseguindo...")
            _aceitar_cookies(page)
            page.wait_for_timeout(1500)

            # PASSO 2: rolar e localizar a secao "Disponibilidade"
            print("[2] Buscando a secao 'Disponibilidade' (com scroll)...")
            secao_info = None
            # Tentativa progressiva: rolar e tentar encontrar
            for attempt in range(MAX_SCROLLS):
                secao_info = _localizar_secao_disponibilidade(page)
                if secao_info.get("found"):
                    break
                page.mouse.wheel(0, SCROLL_STEP_PX)
                page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)

            if not secao_info or not secao_info.get("found"):
                print("ERRO: Secao 'Disponibilidade' nao encontrada.")
                _save_text(DEBUG_DIR / "debug_disponibilidade_html.txt", "Secao nao encontrada; seletores tentados:\n" + "\n".join(secao_info.get("tried", []) if secao_info else []))
                page.screenshot(path=str(DEBUG_DIR / "debug_disponibilidade_pagina.png"), full_page=True)
                return 1

            secao_locator = secao_info["locator"]
            secao_box = secao_info.get("bounding_box")
            estrategia = secao_info.get("estrategia")
            tag_container = secao_info.get("tag_container")

            # Garantir visibilidade
            try:
                secao_locator.scroll_into_view_if_needed(timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1200)

            # Screenshots
            page.screenshot(path=str(DEBUG_DIR / "debug_disponibilidade_pagina.png"), full_page=True)
            try:
                secao_locator.screenshot(path=str(DEBUG_DIR / "debug_disponibilidade_secao.png"))
            except Exception:
                # fallback: se screenshot do locator falhar, usa screenshot inteiro
                pass

            # Salvar HTML snippet
            html_snippet = secao_info.get("container_html_snippet") or ""
            _save_text(DEBUG_DIR / "debug_disponibilidade_html.txt", html_snippet)

            print("Secao encontrada:")
            print(f"  - estrategia: {estrategia}")
            print(f"  - tag do container: {tag_container}")
            # Texto visivel (pequeno)
            try:
                texto = (secao_locator.inner_text() or "").strip()
            except Exception:
                texto = ""
            texto = texto.replace("\n", " ")
            if len(texto) > 200:
                texto = texto[:200] + "..."
            print(f"  - texto (amostra): {texto or '-'}")

            out_summary["secao_disponibilidade"] = {
                "estrategia": estrategia,
                "tag_container": tag_container,
                "bounding_box": secao_box,
                "texto_amostra": texto,
                "debug_files": {
                    "pagina": "scripts/debug_disponibilidade_pagina.png",
                    "secao": "scripts/debug_disponibilidade_secao.png",
                    "html": "scripts/debug_disponibilidade_html.txt",
                },
            }

            # PASSO 3: clicar no calendario inferior dentro da secao
            print("[3] Procurando e clicando no controle de datas (somente dentro da secao)...")
            click_info = _clicar_primeiro_candidato_na_secao(page, secao_locator, secao_box)
            out_summary["click_disponibilidade"] = click_info
            if not click_info.get("clicked"):
                print("ERRO: Nao foi possivel clicar em nenhum candidato de datas dentro da secao.")
                page.screenshot(path=str(DEBUG_DIR / "debug_calendario_inferior_aberto.png"), full_page=True)
                _save_text(
                    DEBUG_DIR / "debug_calendario_inferior_click_falhou.txt",
                    "Candidatos tentados:\n" + "\n".join(click_info.get("tried", [])),
                )
                return 1

            print(f"  - clique realizado: seletor={click_info.get('clicked_sel')} idx={click_info.get('clicked_idx')}")
            page.wait_for_timeout(1500)
            try:
                page.screenshot(path=str(DEBUG_DIR / "debug_calendario_inferior_aberto.png"), full_page=True)
            except Exception:
                pass

            # PASSO 4: confirmar que e o widget correto
            print("[4] Confirmando que o widget aberto e o calendario inferior esperado...")
            widget_confirmado, evid = _widget_confirmar(page, secao_box)
            out_summary["widget_confirmado"] = widget_confirmado
            out_summary["widget_evidencias"] = evid

            if widget_confirmado:
                print("Widget confirmado com evidencias de texto e/ou data-date no range.")
            else:
                print("Possivel widget errado aberto (nao achei textos esperados).")
                print("Evidencias:", evid)

            # PASSO 5: extrair HTML bruto do widget para auditoria
            print("[5] Extraindo HTML bruto do widget de calendario inferior...")
            widget_info = _extrair_outer_html_do_widget(page, secao_box)
            widget_html = widget_info.get("widget_container_html")
            out_summary["widget_bounds"] = widget_info.get("widget_bounds")

            if widget_html:
                _save_text(DEBUG_DIR / "debug_widget_calendario_html.txt", widget_html)
            else:
                _save_text(DEBUG_DIR / "debug_widget_calendario_html.txt", "Nenhum container de widget identificado via [data-date].")

            # PASSO 6: testar seletores de celulas do calendario dentro do widget aproximado
            print("[6] Testando seletores reais de celulas (dentro do widget aproximado por bounds)...")
            widget_box = widget_info.get("widget_bounds")
            y0 = widget_box["y"] - 60 if widget_box and "y" in widget_box else (secao_box["y"] - 80 if secao_box else 0)
            y1 = widget_box["y"] + widget_box["height"] + 300 if widget_box and "height" in widget_box else (secao_box["y"] + secao_box["height"] + 350 if secao_box else 10**9)

            selector_report_lines = []
            selector_report_lines.append("Relatorio de seletores de celulas testados\n")
            selector_report_lines.append(f"Bounds widget aproximado: y0={y0} y1={y1}\n\n")

            for sel in SELETORES_CELULAS_CANDIDATOS:
                try:
                    loc = page.locator(sel)
                    total = loc.count()
                    inside = 0
                    samples = []

                    max_iter = min(total, 80)
                    for i in range(max_iter):
                        el = loc.nth(i)
                        try:
                            b = el.bounding_box()
                        except Exception:
                            b = None
                        if not b:
                            continue
                        cy = b["y"] + b["height"] / 2
                        if cy >= y0 and cy <= y1:
                            inside += 1
                            if len(samples) < 3:
                                samples.append(el.evaluate("node => ({html:(node.outerHTML||'').slice(0,1200), text:(node.innerText||'').slice(0,200), cls:(node.className||'')})"))

                    selector_report_lines.append(f"- Seletor: {sel}\n")
                    selector_report_lines.append(f"  total_count={total} | dentro_bounds_est= {inside} (amostra ate {max_iter})\n")
                    for si, s in enumerate(samples):
                        sample_text = (s.get("text", "") or "").replace("\n", " ")[:120]
                        sample_html = (s.get("html", "") or "")[:300]
                        selector_report_lines.append(f"  sample_{si+1} text={sample_text}\n")
                        selector_report_lines.append(f"  sample_{si+1} html_prefix={sample_html}\n")
                    selector_report_lines.append("\n")
                except Exception as e:
                    selector_report_lines.append(f"- Seletor: {sel}\n")
                    selector_report_lines.append(f"  ERRO ao testar: {e}\n\n")

            _save_text(DEBUG_DIR / "debug_seletores_celulas.txt", "".join(selector_report_lines))

            # PASSO 7: coletar amostras reais - com_preco, com_traco, incerta
            print("[7] Coletando amostras de celulas (com preco / com traco / incerta)...")
            candidate_loc = page.locator('[data-date]').first
            # Preferimos usar todos [data-date] dentro bounds (ate o limite)
            data_date_loc = page.locator('[data-date]')
            total_dd = data_date_loc.count()
            max_iter = min(total_dd, MAX_DATE_CELLS_SAMPLE)

            amostras = []
            chosen = {"com_preco": None, "com_traco": None, "incerta": None}

            for i in range(max_iter):
                el = data_date_loc.nth(i)
                try:
                    b = el.bounding_box()
                except Exception:
                    b = None
                if not b:
                    continue
                cy = b["y"] + b["height"] / 2
                if cy < y0 or cy > y1:
                    continue

                info = _extrair_status_celula(el)
                # garantir formato de data
                # (data-date deve existir)
                data_date = info["atributos"].get("data-date")
                if not data_date:
                    continue
                # filtra pelo mes alvo
                if not str(data_date).startswith(ano_mes):
                    continue

                # salvar
                amostras.append(info)
                t = info["tipo"]
                if chosen.get(t) is None:
                    chosen[t] = info
                if all(chosen.values()):
                    break

            # se nada para o mes alvo, mantem amostras de qualquer mes dentro bounds
            if not any(chosen.values()):
                for i in range(max_iter):
                    el = data_date_loc.nth(i)
                    try:
                        b = el.bounding_box()
                    except Exception:
                        b = None
                    if not b:
                        continue
                    cy = b["y"] + b["height"] / 2
                    if cy < y0 or cy > y1:
                        continue
                    info = _extrair_status_celula(el)
                    data_date = info["atributos"].get("data-date")
                    if not data_date:
                        continue
                    amostras.append(info)
                    t = info["tipo"]
                    if chosen.get(t) is None:
                        chosen[t] = info
                    if all(chosen.values()):
                        break

            amostras_list = [chosen["com_preco"], chosen["com_traco"], chosen["incerta"]]
            amostras_final = [a for a in amostras_list if a]
            _save_json(DEBUG_DIR / "debug_amostras_celulas.json", amostras_final)

            # PASSO 8: resumo
            output_summary = {
                "secao_encontrada": True,
                "widget_confirmado": widget_confirmado,
                "evidencias_widget": evid,
                "widget_bounds_aprox": widget_info.get("widget_bounds"),
                "amostras_coletadas": [a.get("tipo") for a in amostras_final],
                "files": {
                    "pagina": "scripts/debug_disponibilidade_pagina.png",
                    "secao": "scripts/debug_disponibilidade_secao.png",
                    "html_secao": "scripts/debug_disponibilidade_html.txt",
                    "screenshot_popup": "scripts/debug_calendario_inferior_aberto.png",
                    "html_widget": "scripts/debug_widget_calendario_html.txt",
                    "seletores_celulas": "scripts/debug_seletores_celulas.txt",
                    "amostras_celulas": "scripts/debug_amostras_celulas.json",
                },
            }

            out_summary["output"] = output_summary
            _save_json(DEBUG_DIR / f"output_disponibilidade_auditoria_{ano_mes}.json", out_summary)

            print()
            print("FIM - AUDITORIA COMPLETA")
            print(f"JSON resumo: scripts/output_disponibilidade_auditoria_{ano_mes}.json")
            return 0

        except Exception:
            print("ERRO inesperado durante a auditoria.")
            # Sem dependencia externa; apenas imprime a mensagem
            exc_type, exc_value, _tb = sys.exc_info()
            print(f"Tipo={exc_type} | Mensagem={exc_value}")
            try:
                page.screenshot(path=str(DEBUG_DIR / "debug_erro_auditoria.png"), full_page=True)
            except Exception:
                pass
            _save_text(DEBUG_DIR / "debug_erro_auditoria_trace.txt", "Falha na auditoria (ver print acima).")
            return 1
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())

