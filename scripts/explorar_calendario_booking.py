#!/usr/bin/env python3
"""
Script de exploração do calendário do Booking.com — standalone.
Abre a página do hotel, interage com o calendário e imprime mapa de disponibilidade.
Não importa nada de core/ ou app.py. Ferramenta de diagnóstico.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ============== CONFIGURAÇÃO (editar antes de rodar) ==============
URL_HOTEL = "https://www.booking.com/hotel/br/travel-inn-village-arraial.pt-br.html"
ANO_MES_ALVO = "2026-04"  # YYYY-MM
HEADLESS = False
TIMEOUT_PADRAO = 15000  # ms
# V3 = Calendário INFERIOR (seção Disponibilidade). False = calendário superior (searchbox).
MODO_V3 = True
# Demonstração ampliada: abrir widget e extrair datas em múltiplos meses (somente scripts/).
DEMO_V3_EXTENDED = True
# Ciclo completo: selecionar RANGE (check-in + check-out) por mês e extrair datas.
DEMO_V3_FULL_CYCLE = True
N_MONTHS_TO_TEST = 2
EVIDENCE_DIR_V3_EXTENDED = "evidence_v3_demo_extended"
# ===================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (Kernel, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Candidatos de seletores (ordem de tentativa)
SELETORES_CAMPO_DATA = [
    '[data-testid="searchbox-dates-container"]',
    '[data-testid="date-display-field-start"]',
    '.sb-date-field__start',
    'input[name="checkin"]',
    '[class*="checkin"]',
    '[class*="date"]',
]

SELETORES_CONTAINER_CALENDARIO = [
    '[data-testid="datepicker-tabs"]',
    '.bui-calendar',
    '[class*="calendar"]',
    '[class*="datepicker"]',
]

SELETORES_BOTAO_PROXIMO = [
    '[data-testid="datepicker-next-month-button"]',
    '[aria-label*="próximo"]',
    '[aria-label*="next"]',
    'button[class*="next"]',
    '[data-bui-ref="calendar-next"]',
]

SELETORES_CELULAS_DIA = [
    'td[data-date]',
    '[data-date]',
    '[data-testid="calendar-day"]',
    'span[data-date]',
    '[class*="calendar__item"]',
    'td[class*="day"]',
]

CLASSES_INDISPONIVEL = [
    "disabled", "unavailable", "blocked", "unselectable", "no-checkin",
]
MAX_CLIQUES_PROXIMO = 12
WAIT_APOS_CLIQUE_MS = 800
WAIT_AFTER_SCROLL_MS = 1500
WAIT_FOR_WIDGET_MS = 5000
WAIT_AFTER_CLICK_MS = 1200
MAX_NEXT_TRIES = 3
HEADER_CHANGE_TIMEOUT_MS = 2000
HEADER_SHORT_WAIT_MS = 800


def _aceitar_cookies(page, timeout=3000):
    """Tenta aceitar o banner de cookies."""
    try:
        btn = page.get_by_role("button", name="Aceitar").or_(
            page.get_by_role("button", name="Accept")
        )
        btn.click(timeout=timeout)
    except Exception:
        pass


def _screenshot(page, nome: str) -> Path:
    """Salva screenshot em scripts/ e retorna o path."""
    path = SCRIPT_DIR / nome
    try:
        page.screenshot(path=str(path))
        return path
    except Exception as e:
        print(f"Aviso: não foi possível salvar screenshot: {e}", file=sys.stderr)
        return path


def _extrair_mes_ano_do_calendario(page, container_sel: str) -> str | None:
    """Tenta ler o mês/ano exibido no header do calendário (ex: 'abril 2026')."""
    for sel in [
        f"{container_sel} [class*='calendar-header']",
        f"{container_sel} [class*='month']",
        f"{container_sel} [data-testid*='month']",
        f"{container_sel} h3",
        f"{container_sel} .bui-calendar__month",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                txt = loc.inner_text(timeout=2000).strip()
                if txt and re.search(r"\d{4}", txt):
                    return txt
        except Exception:
            continue
    return None


def _mes_visivel_para_yyyymm(texto_mes: str) -> str | None:
    """Converte 'abril 2026' -> '2026-04'. Mapeamento PT-BR."""
    if not texto_mes:
        return None
    meses_pt = {
        "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
        "abril": "04", "maio": "05", "junho": "06", "julho": "07",
        "agosto": "08", "setembro": "09", "outubro": "10",
        "novembro": "11", "dezembro": "12",
    }
    texto = texto_mes.lower().strip()
    match = re.search(r"(\d{4})", texto)
    ano = match.group(1) if match else None
    if not ano:
        return None
    for nome, mes in meses_pt.items():
        if nome in texto:
            return f"{ano}-{mes}"
    return None


def _analisar_celula(el, mes_ano: str) -> dict:
    """Analisa um elemento de célula e retorna dict data, disponivel, preco_visivel, motivo_indisponivel, html_raw."""
    resultado = {
        "data": None,
        "disponivel": None,  # True, False ou None (incerto)
        "preco_visivel": None,
        "motivo_indisponivel": None,
        "html_raw": None,
    }
    try:
        html = el.evaluate("node => node.outerHTML || ''")
        resultado["html_raw"] = (html or "")[:200]

        # Data: atributo data-date
        data_date = el.get_attribute("data-date")
        if data_date and re.match(r"\d{4}-\d{2}-\d{2}", data_date):
            resultado["data"] = data_date[:10]
        else:
            # Tentar texto do dia + mes_ano
            txt = el.inner_text()
            dia_match = re.search(r"\b(\d{1,2})\b", txt)
            if dia_match and mes_ano:
                ano, mes = mes_ano.split("-")
                dia = int(dia_match.group(1))
                resultado["data"] = f"{ano}-{mes}-{dia:02d}"

        # Atributos de indisponibilidade
        aria_disabled = el.get_attribute("aria-disabled")
        if aria_disabled == "true":
            resultado["disponivel"] = False
            resultado["motivo_indisponivel"] = "aria-disabled"
        if el.get_attribute("disabled"):
            resultado["disponivel"] = False
            resultado["motivo_indisponivel"] = resultado["motivo_indisponivel"] or "disabled"
        if el.get_attribute("data-disabled"):
            resultado["disponivel"] = False
            resultado["motivo_indisponivel"] = resultado["motivo_indisponivel"] or "data-disabled"

        # Classes
        cls = (el.get_attribute("class") or "").lower()
        for c in CLASSES_INDISPONIVEL:
            if c in cls:
                resultado["disponivel"] = False
                resultado["motivo_indisponivel"] = resultado["motivo_indisponivel"] or f"classe_{c}"
                break

        # Texto: "—" ou "-" -> indisponível; número R$ -> disponível
        txt = (el.inner_text() or "").strip()
        if "—" in txt or (len(txt) < 5 and re.match(r"^\-+$", txt)):
            resultado["disponivel"] = False
            resultado["motivo_indisponivel"] = resultado["motivo_indisponivel"] or "texto_traco"
        if re.search(r"R\$\s*[\d.,]+", txt) or re.search(r"[\d.,]+\s*R\$", txt):
            resultado["disponivel"] = True
            preco_match = re.search(r"R?\$?\s*([\d.,]+)", txt)
            if preco_match:
                resultado["preco_visivel"] = preco_match.group(1).strip()

        # Se só tem número do dia e ainda não definiu,
        # assumimos que é um dia selecionável (disponível).
        if resultado["disponivel"] is None and re.match(r"^\d{1,2}$", txt.strip()):
            resultado["disponivel"] = True
    except Exception as e:
        resultado["motivo_indisponivel"] = f"erro: {e}"
    return resultado


def _dna_celula(loc) -> dict:
    """Extrai 'DNA' de uma célula: outerHTML, classes, aria-label, aria-disabled, texto interno."""
    out = {"outerHTML": "", "classes": "", "aria_label": None, "aria_disabled": None, "texto": "", "tem_traco_interno": None}
    try:
        out["outerHTML"] = (loc.evaluate("el => el.outerHTML || ''") or "")[:4000]
    except Exception:
        pass
    try:
        out["classes"] = loc.get_attribute("class") or ""
    except Exception:
        pass
    try:
        out["aria_label"] = loc.get_attribute("aria-label")
    except Exception:
        pass
    try:
        out["aria_disabled"] = loc.get_attribute("aria-disabled")
    except Exception:
        pass
    try:
        out["texto"] = (loc.inner_text() or "").strip()[:500]
    except Exception:
        pass
    try:
        traco = loc.locator("span:has-text('—'), div:has-text('—')").first
        out["tem_traco_interno"] = traco.count() > 0
    except Exception:
        out["tem_traco_interno"] = None
    return out


def _neutralizar_painel_melhor_de(page) -> int:
    """Neutraliza overlays flutuantes do Booking (principalmente "O melhor de")."""
    try:
        count = page.evaluate(
            """() => {
                const xpath = "//*[contains(., 'O melhor de')]";
                const iter = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_ITERATOR_TYPE, null);
                let node;
                const nodes = [];
                while ((node = iter.iterateNext()) !== null) nodes.push(node);
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 720;

                function isTooBig(rect) {
                    if (!rect) return true;
                    const area = rect.width * rect.height;
                    const viewportArea = vw * vh;
                    // Evita neutralizar containers que ocupam quase toda a tela (ex: <html>/<body>)
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

                // Para cada ocorrência, escolhe um ancestral "real" moderado (div/section/aside/article)
                let changed = 0;
                for (let k = 0; k < Math.min(nodes.length, 4); k++) {
                    let target = nodes[k];
                    if (!target || !target.parentElement) continue;
                    // Sobe no DOM, mas com guardas para não chegar em <html>/<body> e não neutralizar super-containers
                    let picked = null;
                    let cur = target.nodeType === 1 ? target : target.parentElement;
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
                        picked.style.opacity = '0';
                        changed++;
                    }
                }
                // Neutralização agressiva adicional para overlays flutuantes comuns.
                const extra = document.querySelectorAll('[class*="floating"], [class*="overlay"], [class*="popover"], [data-testid*="overlay"], [aria-modal="true"]');
                extra.forEach(el => {
                    if (!el || !el.getBoundingClientRect) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 120 || rect.height < 40) return;
                    const style = window.getComputedStyle(el);
                    const maybeFloating = style.position === 'fixed' || style.position === 'sticky' || style.zIndex !== 'auto';
                    if (!maybeFloating) return;
                    el.style.pointerEvents = 'none';
                    el.style.opacity = '0';
                    changed++;
                });
                return changed;
            }"""
        )
        return count or 0
    except Exception:
        return 0


def _element_from_point(page, x: float, y: float) -> dict:
    """Retorna tagName, id, className e outerHTML (até 600 chars) do elemento sob (x, y)."""
    try:
        return page.evaluate(
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
            [x, y],
        )
    except Exception:
        return {}


def _desobstruir_pointer_para_elemento(page, el, log_prefix: str = "[V3]") -> int:
    """Desabilita pointer-events em elementos fixed/sticky que cubram o centro do el, para permitir hover/clique. Retorna quantidade de nós alterados."""
    try:
        box = el.bounding_box()
        if not box:
            return 0
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        count = page.evaluate(
            """([x, y]) => {
                const fixedSticky = document.querySelectorAll('[style*="position: fixed"], [style*="position:fixed"], [style*="position: sticky"], [style*="position:sticky"]');
                const byClass = document.querySelectorAll('[class*="fixed"], [class*="sticky"], [id*="cookie"], [class*="cookie"], [data-testid*="cookie"], [class*="header"]');
                const candidates = new Set([...fixedSticky, ...byClass]);
                let n = 0;
                candidates.forEach(el => {
                    if (el.offsetParent === null) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 2 && rect.height < 2) return;
                    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
                        const style = window.getComputedStyle(el);
                        if (style.position === 'fixed' || style.position === 'sticky' || el.id?.toLowerCase().includes('cookie') || el.className?.toString().toLowerCase().includes('cookie')) {
                            el.style.setProperty('pointer-events', 'none');
                            n++;
                        }
                    }
                });
                return n;
            }""",
            [cx, cy],
        )
        if count and count > 0:
            print(f"    {log_prefix} Desobstruído: {count} elemento(s) com pointer-events: none no caminho do botão.")
        return count or 0
    except Exception:
        return 0


def _click_com_verificacao_overlap(page, el, log_prefix: str = "[V3]") -> bool:
    """Obtém bbox do el, verifica elementFromPoint no centro. Se outro elemento no ponto (ex. painel), loga HTML e usa force=True. Retorna True se clique foi disparado."""
    try:
        box = el.bounding_box()
        if not box:
            el.click(timeout=5000)
            return True
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        under = _element_from_point(page, cx, cy)
        under_html = (under.get("outerHTML") or "").lower()
        under_tag = (under.get("tagName") or "")
        under_tag_lower = (under_tag or "").lower()

        # Se o hit-test está caindo em SVG/PATH, clique no pai (button/a) para garantir o acionamento do CTA.
        # Isso evita que o navegador dispare o handler de um elemento interno e não o botão/link esperado.
        if under_tag_lower in ("svg", "path"):
            clicked_parent = False
            try:
                clicked_parent = page.evaluate(
                    """([cx, cy]) => {
                        const under = document.elementFromPoint(cx, cy);
                        if (!under || !under.closest) return false;
                        const parent = under.closest('button, a');
                        if (!parent) return false;
                        parent.click();
                        return true;
                    }""",
                    [cx, cy],
                )
            except Exception:
                clicked_parent = False
            if clicked_parent:
                print(f"    {log_prefix} Hit em {under_tag_lower}; clicando pai button/a.")
                return True

        # V1: caso o hit-test não seja svg/path, clique normalmente no elemento.
        # Mantemos logs/diagnóstico, mas não usamos force no caminho normal.
        is_overlap = "melhor" in under_html or "collapse" in under_html or "accordion" in under_html
        if is_overlap:
            html_amostra = (under.get("outerHTML") or "")[:300]
            print(f"    {log_prefix} (diagnóstico) possivel sobreposição: [{html_amostra}]")
        else:
            print(f"    {log_prefix} Caminho livre para o clique (elemento sob o ponto: {under_tag}).")
        el.click(timeout=5000)
        return True
    except Exception:
        try:
            el.click(timeout=5000, force=True)
            return True
        except Exception:
            return False


def run_v3_calendario_inferior(page) -> int:
    """
    V3: Interação restrita à seção Disponibilidade; extração do padrão '—' e do preço.
    Não fecha o browser (quem chama fecha).
    """
    print("[V3] Modo Calendário INFERIOR (seção Disponibilidade)")
    print()

    # ----- 1) Localização restrita (mira laser) -----
    print("[V3.1] Localizando seção 'Disponibilidade' e definindo escopo...")
    secao_scope = None
    for sel in [
        "div:has(h2:has-text('Disponibilidade'))",
        "div:has(h3:has-text('Disponibilidade'))",
        "section:has(h2:has-text('Disponibilidade'))",
        "section:has(h3:has-text('Disponibilidade'))",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                secao_scope = loc
                print(f"    Escopo obtido com: {sel}")
                break
        except Exception:
            continue

    if not secao_scope or secao_scope.count() == 0:
        print("    ERRO: Seção 'Disponibilidade' não encontrada.")
        _screenshot(page, "debug_v3_secao_nao_encontrada.png")
        return 1

    # ----- 1b) Neutralização do painel "O melhor de" (evitar loop abrir/fechar) -----
    print("[V3.1b] Neutralizando painel colapsável 'O melhor de' (pointer-events none + opacity 0)...")
    n_neutralizados = _neutralizar_painel_melhor_de(page)
    if n_neutralizados > 0:
        print(f"    Painel neutralizado: {n_neutralizados} elemento(s).")
    else:
        print("    Nenhum painel 'O melhor de' encontrado (ou já neutro).")
    page.wait_for_timeout(400)

    # ----- Evidências por tentativa (scripts/evidence/ ou scripts/evidence_v3_demo_extended/) -----
    evidence_dir = SCRIPT_DIR / (EVIDENCE_DIR_V3_EXTENDED if DEMO_V3_EXTENDED else "evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if DEMO_V3_EXTENDED:
        # limpar diretório (somente scripts/) para uma execução "limpa"
        try:
            for p in evidence_dir.rglob("*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
        except Exception:
            pass
    attempts_log: list[dict] = []
    attempts_log_path = evidence_dir / "attempts_log.json"

    def _dump_attempts_log() -> None:
        try:
            attempts_log_path.write_text(
                json.dumps(attempts_log, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"Aviso: falha ao salvar attempts_log.json: {e}", file=sys.stderr)

    # ----- 2) Âncora + área de busca (1000px abaixo) + gatilhos priorizados -----
    print("[V3.2] Âncora #availability_target / h2 'Disponibilidade' e busca de gatilhos na área (até 1000px abaixo)...")
    ancora = page.locator("#availability_target").or_(page.locator("h2:has-text('Disponibilidade'), h3:has-text('Disponibilidade')")).first
    anchor_box = None
    y0_search, y1_search = 0, 10000
    try:
        if ancora.count() > 0:
            anchor_box = ancora.bounding_box()
            if anchor_box:
                y0_search = anchor_box["y"]
                y1_search = anchor_box["y"] + 2500
                ancora.scroll_into_view_if_needed(timeout=5000)
                print(f"    Âncora encontrada: y0={y0_search:.0f}, área de busca até y={y1_search:.0f}")
    except Exception:
        pass
    if not anchor_box:
        try:
            anchor_box = secao_scope.bounding_box()
            if anchor_box:
                y0_search = anchor_box["y"]
                y1_search = anchor_box["y"] + 2500
        except Exception:
            pass
    page.wait_for_timeout(600)
    # Em algumas cargas o Booking injeta o bloco de disponibilidade de forma tardia.
    # Para não perder o gatilho comprovado (dentro de #hp_availability_style_changes),
    # aguardamos brevemente esse container aparecer.
    try:
        page.wait_for_selector("#hp_availability_style_changes", timeout=5000)
    except Exception:
        pass
    # Espera ativa por gatilho de datas exclusivamente no container de disponibilidade.
    try:
        page.wait_for_selector(
            "#hp_availability_style_changes [data-testid='searchbox-dates-container'], "
            "#hp_availability_style_changes [data-testid*='date']",
            timeout=15000,
        )
    except Exception:
        pass

    # Gatilhos em ordem de prioridade (acionador comprovado: searchbox-dates-container dentro do container de disponibilidade)
    seletores_gatilhos = [
        '#hp_availability_style_changes button[data-testid="searchbox-dates-container"]',
        '#hp_availability_style_changes [data-testid*="date"]',
    ]
    # Coletar todos os candidatos na página que caem na área de busca, priorizando pela distância à âncora
    candidatos_na_area = []
    has_av_container = False
    try:
        has_av_container = page.locator("#hp_availability_style_changes").count() > 0
    except Exception:
        has_av_container = False
    for sel in seletores_gatilhos:
        try:
            # Seletor comprovado no probe deve ser buscado dentro do container de disponibilidade,
            # para não pegar nodes de outros date pickers da página.
            if not has_av_container:
                continue
            loc = page.locator(sel)
            n = loc.count()
            max_i = 15
            if 'data-testid*="date"' in sel:
                max_i = 40
            for i in range(min(n, max_i)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                try:
                    b = el.bounding_box()
                except Exception:
                    continue
                if not b:
                    continue
                cy = b["y"] + b["height"] / 2
                # Para seletores comprovados/ancorados no container de disponibilidade, não restringimos por cy;
                # a janela vertical pode excluir o nó correto dependendo do layout/scroll.
                is_ancorado_av = sel == '[data-testid*="date"]' or sel.startswith('#hp_availability_style_changes ')
                if not is_ancorado_av:
                    if cy < y0_search - 50 or cy > y1_search + 50:
                        continue
                texto = (el.inner_text() or "").strip()[:60]
                anchor_cy = (anchor_box["y"] + anchor_box.get("height", 0) / 2) if anchor_box else 0
                el_cy = b["y"] + b["height"] / 2
                dist = abs(anchor_cy - el_cy) if anchor_box else b["y"]
                # Priorizar gatilhos que abrem o widget (tentar primeiro)
                if "searchbox-dates-container" in sel or sel == '[data-testid*="date"]':
                    dist = -1000 - i
                candidatos_na_area.append((dist, sel, i, el, texto))
        except Exception:
            continue
    # Ordenar por proximidade à âncora (mais perto primeiro)
    candidatos_na_area.sort(key=lambda x: x[0])
    # Desduplicar por (sel, i) mantendo ordem
    vistos = set()
    candidatos_unicos = []
    for _, sel, idx, el, texto in candidatos_na_area:
        key = (sel, idx)
        if key in vistos:
            continue
        vistos.add(key)
        candidatos_unicos.append((sel, idx, el, texto))

    elemento_clicado = None
    attempt_counter = 0
    for sel, idx, el, texto in candidatos_unicos:
        try:
            # Proibição explícita de clicar em "Aplicar alterações" (evita redirecionar para a busca geral)
            texto_lower = (texto or "").lower()
            if "aplicar" in texto_lower:
                print(f"    [V3] Pulando candidato por conter 'Aplicar': sel={sel} idx={idx} texto={texto!r}")
                continue
            attempt_counter += 1
            attempt_id = f"{attempt_counter:03d}"
            print(f"    Tentando gatilho [tentativa {attempt_id}]: {sel} (idx={idx}) texto={texto!r}...")

            # Arquivos de evidência (por tentativa)
            before_scroll_path = evidence_dir / f"attempt_{attempt_id}_before_scroll.png"
            after_scroll_path = evidence_dir / f"attempt_{attempt_id}_after_scroll.png"
            element_path = evidence_dir / f"attempt_{attempt_id}_element.png"
            after_click_path = evidence_dir / f"attempt_{attempt_id}_after_click.png"
            fail_html_path = evidence_dir / f"attempt_{attempt_id}_fail.html"

            # 1) screenshot antes do scroll
            try:
                page.screenshot(path=str(before_scroll_path))
            except Exception:
                pass

            # 2) scroll cirúrgico e espera para estabilidade
            el.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)

            # 3) screenshot após o scroll
            try:
                page.screenshot(path=str(after_scroll_path))
            except Exception:
                pass

            # 4) definir coordenadas e detectar se o hit-test cai em svg/path
            el_box = None
            cx = cy = None
            hit_info = {}
            try:
                el_box = el.bounding_box()
            except Exception:
                el_box = None
            if el_box:
                cx = el_box["x"] + el_box["width"] / 2
                cy = el_box["y"] + el_box["height"] / 2
                hit_info = _element_from_point(page, cx, cy) or {}

            hit_tag = (hit_info.get("tagName") or "").lower()
            hit_is_svg_path = hit_tag in ("svg", "path")

            # 5) escolher o elemento que será clicado (pai button/a se hit for svg/path)
            clicked_parent_used = False
            click_target = el
            try:
                if hit_is_svg_path and cx is not None and cy is not None:
                    # Marca o elemento final (button/a) para permitir screenshot
                    marker_ok = page.evaluate(
                        """([cx, cy]) => {
                            const hit = document.elementFromPoint(cx, cy);
                            if (!hit || !hit.closest) return false;
                            const parent = hit.closest('button, a');
                            if (!parent) return false;
                            parent.setAttribute('data-evidence-click', 'true');
                            return true;
                        }""",
                        [cx, cy],
                    )
                    if marker_ok:
                        clicked_parent_used = True
                        click_target = page.locator('[data-evidence-click="true"]').first
                        page.wait_for_timeout(50)
                    # cleanup do marker (após capturar screenshot, mais abaixo)
            except Exception:
                clicked_parent_used = False
                click_target = el

            # 6) screenshot do elemento que será clicado
            try:
                if click_target and click_target.count() > 0:
                    click_target.screenshot(path=str(element_path))
                else:
                    el.screenshot(path=str(element_path))
            except Exception:
                try:
                    el.screenshot(path=str(element_path))
                except Exception:
                    pass

            # cleanup marker
            try:
                page.evaluate(
                    """() => {
                        document.querySelectorAll('[data-evidence-click="true"]')
                          .forEach(n => n.removeAttribute('data-evidence-click'));
                    }"""
                )
            except Exception:
                pass

            # 7) desobstruir overlays e tentar hover
            _desobstruir_pointer_para_elemento(page, click_target, "[V3]")
            page.wait_for_timeout(300)

            hover_ok = False
            try:
                click_target.hover(timeout=3000)
                hover_ok = True
                page.wait_for_timeout(500)
            except Exception:
                print("    [V3] Hover bloqueado (timeout/interceptação); usando clique com verificação.")
            if hover_ok:
                _click_com_verificacao_overlap(page, click_target, "[V3]")
            else:
                # V1: sem fallback force=True aqui; chamamos a mesma estratégia de verificação.
                _click_com_verificacao_overlap(page, click_target, "[V3]")

            # 8) aguardar o widget (sem scroll) e capturar após o clique
            opened_widget = False
            try:
                page.wait_for_selector("[data-date]", timeout=WAIT_FOR_WIDGET_MS)
                opened_widget = True
            except Exception:
                opened_widget = False
            try:
                page.screenshot(path=str(after_click_path))
            except Exception:
                pass

            # 9) falha -> HTML completo
            if not opened_widget:
                try:
                    html = page.content()
                    fail_html_path.write_text(html, encoding="utf-8")
                    # manter "fail.html" como ponteiro do último erro
                    (evidence_dir / "fail.html").write_text(html, encoding="utf-8")
                except Exception:
                    pass

                attempts_log.append(
                    {
                        "attempt_id": attempt_id,
                        "ts": datetime.now().isoformat(),
                        "selector": sel,
                        "idx": idx,
                        "texto": texto,
                        "coords": {"cx": cx, "cy": cy},
                        "hit_info": hit_info,
                        "hit_is_svg_path": hit_is_svg_path,
                        "clicked_parent_used": clicked_parent_used,
                        "opened_widget": False,
                        "paths": {
                            "before_scroll": str(before_scroll_path),
                            "after_scroll": str(after_scroll_path),
                            "element": str(element_path),
                            "after_click": str(after_click_path),
                            "fail_html": str(fail_html_path),
                        },
                    }
                )
                print(f"    [EVID] tentativa {attempt_id}: FAIL (sem [data-date]) — segue para próximo.")
                _dump_attempts_log()
                continue

            attempts_log.append(
                {
                    "attempt_id": attempt_id,
                    "ts": datetime.now().isoformat(),
                    "selector": sel,
                    "idx": idx,
                    "texto": texto,
                    "coords": {"cx": cx, "cy": cy},
                    "hit_info": hit_info,
                    "hit_is_svg_path": hit_is_svg_path,
                    "clicked_parent_used": clicked_parent_used,
                    "opened_widget": True,
                    "paths": {
                        "before_scroll": str(before_scroll_path),
                        "after_scroll": str(after_scroll_path),
                        "element": str(element_path),
                        "after_click": str(after_click_path),
                        "fail_html": str(fail_html_path),
                    },
                }
            )
            _dump_attempts_log()

            elemento_clicado = sel
            print(f"    Clique executado em: {sel} — widget aberto.")
            break
        except Exception as e:
            print(f"    Falha ao interagir com {sel}: {e}")
            # Se falhar antes de abrir/validar, ainda assim registramos evidência básica
            attempt_id = attempt_id if "attempt_id" in locals() else "000"
            try:
                attempts_log.append(
                    {
                        "attempt_id": attempt_id,
                        "ts": datetime.now().isoformat(),
                        "selector": sel,
                        "idx": idx,
                        "texto": texto,
                        "opened_widget": False,
                        "error": str(e),
                    }
                )
                _dump_attempts_log()
            except Exception:
                pass
            continue

    if not elemento_clicado:
        print("    ERRO: Nenhum gatilho abriu o calendário na área de busca.")
        _screenshot(page, "debug_v3_clique_falhou.png")
        _dump_attempts_log()
        return 1

            # Estabilidade pós-clique: após aparecer [data-date], não fazer scroll e aguardar curto.
    page.wait_for_timeout(300)

    _screenshot(page, "debug_v3_aberto.png")
    print("    Screenshot salvo: scripts/debug_v3_aberto.png")

    # ====================== DEMO AMPLIADA: selecionar/extrair datas por mês ======================
    if DEMO_V3_EXTENDED:
        print()
        print(f"[V3.DEMO] Iniciando demo ampliada: {N_MONTHS_TO_TEST} mês(es) — evidências em {evidence_dir} ...")
        if DEMO_V3_FULL_CYCLE:
            print("[V3.DEMO] Modo Ciclo Completo: seleção de RANGE (check-in + check-out) por mês.")

        dates_extracted: list[dict] = []
        dates_path = evidence_dir / ("dates_extracted_full.json" if DEMO_V3_FULL_CYCLE else "dates_extracted.json")

        url_inicial = page.url

        # Escopo do widget do datepicker (para evitar clicar em elementos fora do calendário inferior)
        widget_scope = None
        try:
            marked = page.evaluate(
                """() => {
                    const first = document.querySelector('[data-date]');
                    if (!first || !first.closest) return false;
                    const host = first.closest('[data-testid*=\"datepicker\"], [data-testid*=\"calendar\"], [class*=\"datepicker\"], [class*=\"calendar\"], [role=\"dialog\"]');
                    if (!host) return false;
                    host.setAttribute('data-evidence-widget-scope', '1');
                    return true;
                }"""
            )
            if marked:
                widget_scope = page.locator('[data-evidence-widget-scope="1"]').first
        except Exception:
            widget_scope = None

        def _is_navegacao_inesperada() -> bool:
            try:
                return page.url != url_inicial
            except Exception:
                return False

        def _reabrir_widget_v3() -> bool:
            try:
                _neutralizar_painel_melhor_de(page)
            except Exception:
                pass
            for sel_open in [
                '#hp_availability_style_changes button[data-testid="searchbox-dates-container"]',
                '#hp_availability_style_changes [data-testid*="date"]',
            ]:
                try:
                    loc = page.locator(sel_open)
                    if loc.count() <= 0:
                        continue
                    target = loc.first
                    if not target.is_visible():
                        continue
                    target.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)
                    _click_com_verificacao_overlap(page, target, "[V3.DEMO.REOPEN]")
                    page.wait_for_selector("[data-date]", timeout=WAIT_FOR_WIDGET_MS)
                    return True
                except Exception:
                    continue
            return False

        def _salvar_estado_falha(prefix: str) -> None:
            try:
                page.screenshot(path=str(evidence_dir / f"{prefix}_full.png"))
            except Exception:
                pass
            try:
                (evidence_dir / f"{prefix}.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass

        def _celula_disponivel(cel) -> bool:
            try:
                aria_disabled = cel.get_attribute("aria-disabled")
                if aria_disabled == "true":
                    return False
                cls = (cel.get_attribute("class") or "").lower()
                if any(x in cls for x in ("disabled", "unavailable", "blocked", "unselectable")):
                    return False
                txt = (cel.inner_text() or "").strip()
                if "—" in txt:
                    return False
                return True
            except Exception:
                return False

        def _mes_visivel_yyyymm() -> str | None:
            # Datepickers frequentemente exibem dias “de borda” do mês anterior/próximo.
            # Para inferir o mês atual com robustez, pegamos o mês DOMINANTE (mais frequente)
            # entre as células visíveis com data-date.
            try:
                loc = page.locator("[data-date]")
                n_loc = loc.count()
                counts: dict[str, int] = {}
                for i in range(min(n_loc, 140)):
                    try:
                        cel = loc.nth(i)
                        if not cel.is_visible():
                            continue
                        dd = cel.get_attribute("data-date")
                        if not dd or not re.match(r"\d{4}-\d{2}-\d{2}", dd):
                            continue
                        mm = dd[:7]
                        counts[mm] = counts.get(mm, 0) + 1
                    except Exception:
                        continue
                if not counts:
                    return None
                return max(counts.items(), key=lambda kv: kv[1])[0]
            except Exception:
                return None

        def _meses_visiveis() -> list[str]:
            try:
                loc = page.locator("[data-date]")
                n_loc = loc.count()
                months: set[str] = set()
                for i in range(min(n_loc, 220)):
                    try:
                        cel = loc.nth(i)
                        if not cel.is_visible():
                            continue
                        dd = cel.get_attribute("data-date")
                        if not dd or not re.match(r"\d{4}-\d{2}-\d{2}", dd):
                            continue
                        months.add(dd[:7])
                    except Exception:
                        continue
                return sorted(months)
            except Exception:
                return []

        def _header_calendario_texto() -> str | None:
            try:
                base = widget_scope if (widget_scope and widget_scope.count() > 0) else page
                for sel_h in [
                    '[data-testid*="month"]',
                    '[class*="calendar-month-header"]',
                    '[class*="month"]',
                    "h3",
                    "h4",
                ]:
                    loc = base.locator(sel_h)
                    n = loc.count()
                    for i in range(min(n, 4)):
                        txt = (loc.nth(i).inner_text() or "").strip()
                        if txt and re.search(r"\d{4}", txt):
                            return txt
                return None
            except Exception:
                return None

        def _header_next_coords() -> dict | None:
            """Retorna coordenadas do botão next dentro do header que contém mês/ano."""
            try:
                payload = page.evaluate(
                    """() => {
                        const roots = Array.from(document.querySelectorAll(
                            '[data-testid*="datepicker"], [data-testid*="calendar"], [class*="datepicker"], [class*="calendar"], [role="dialog"]'
                        ));
                        const all = roots.length ? roots : [document.body];
                        const hasMonth = (t) => /\\b(20\\d{2})\\b/.test(t || '');
                        for (const root of all) {
                            const headers = Array.from(root.querySelectorAll(
                                '[class*="month"], [class*="header"], [data-testid*="month"], h3, h4'
                            ));
                            for (const h of headers) {
                                const txt = (h.textContent || '').trim();
                                if (!hasMonth(txt)) continue;
                                const cands = Array.from(h.querySelectorAll('button, a'));
                                let target = null;
                                if (cands.length) {
                                    target = cands[cands.length - 1];
                                } else {
                                    let cur = h.parentElement;
                                    for (let i = 0; i < 3 && cur && !target; i++) {
                                        const near = Array.from(cur.querySelectorAll('button, a'));
                                        if (near.length) target = near[near.length - 1];
                                        cur = cur.parentElement;
                                    }
                                }
                                if (!target) continue;
                                const ttxt = (target.textContent || '').toLowerCase();
                                if (ttxt.includes('aplicar')) continue;
                                const r = target.getBoundingClientRect();
                                if (!r || r.width < 4 || r.height < 4) continue;
                                return {
                                    ok: true,
                                    cx: r.left + r.width / 2,
                                    cy: r.top + r.height / 2,
                                    header: txt.slice(0, 120),
                                };
                            }
                        }
                        return { ok: false };
                    }"""
                ) or {}
                if not payload.get("ok"):
                    return None
                return payload
            except Exception:
                return None

        def _header_next_by_sibling() -> dict | None:
            """Mapeia o botão next pelo sibling mais à direita do header com ano visível."""
            try:
                data = page.evaluate(
                    """() => {
                        const isYear = (s) => /\\b20\\d{2}\\b/.test(s || '');
                        const headers = Array.from(document.querySelectorAll(
                            '[data-testid*="month"], [class*="month"], [class*="header"], h3, h4, div, span'
                        )).filter((n) => {
                            const txt = (n.textContent || '').trim();
                            if (!txt || txt.length > 80) return false;
                            return isYear(txt);
                        });
                        for (const h of headers) {
                            const parent = h.parentElement;
                            if (!parent) continue;
                            const sibs = Array.from(parent.children);
                            const cands = [];
                            for (const s of sibs) {
                                const btns = Array.from(s.querySelectorAll('button, div[role="button"], a'));
                                for (const b of btns) {
                                    const t = (b.innerText || '').toLowerCase();
                                    if (t.includes('aplicar')) continue;
                                    const r = b.getBoundingClientRect();
                                    if (!r || r.width < 4 || r.height < 4) continue;
                                    cands.push({
                                        x: r.left + r.width / 2,
                                        y: r.top + r.height / 2,
                                        left: r.left,
                                        tag: (b.tagName || '').toLowerCase(),
                                        cls: (b.className || '').toString().slice(0, 140),
                                        hdr: (h.textContent || '').trim().slice(0, 80),
                                    });
                                }
                            }
                            if (!cands.length) continue;
                            cands.sort((a, b) => a.left - b.left);
                            const rightMost = cands[cands.length - 1];
                            return { ok: true, ...rightMost };
                        }
                        return { ok: false };
                    }"""
                ) or {}
                if not data.get("ok"):
                    return None
                return data
            except Exception:
                return None

        def _neutralizar_overlay_no_ponto(cx: float, cy: float) -> dict:
            try:
                return page.evaluate(
                    """([cx, cy]) => {
                        const top = document.elementFromPoint(cx, cy);
                        if (!top) return { changed: false };
                        const container = top.closest('[class*="overlay"], [class*="popover"], [class*="floating"], [aria-modal="true"], [role="dialog"]');
                        const node = container || top;
                        const txt = ((node.innerText || '') + ' ' + (node.className || '')).toLowerCase();
                        const looksOverlay = txt.includes('o melhor de') || txt.includes('overlay') || txt.includes('popover') || txt.includes('modal');
                        if (!looksOverlay) return { changed: false };
                        const prev = {
                            pe: node.style.pointerEvents || '',
                            op: node.style.opacity || '',
                        };
                        node.style.pointerEvents = 'none';
                        node.style.opacity = '0.4';
                        node.setAttribute('data-v3-blocked', '1');
                        return {
                            changed: true,
                            className: (node.className || '').toString().slice(0, 200),
                            innerText: (node.innerText || '').slice(0, 200),
                            prevPointer: prev.pe,
                            prevOpacity: prev.op,
                        };
                    }""",
                    [cx, cy],
                ) or {"changed": False}
            except Exception:
                return {"changed": False}

        def _restaurar_overlays_temporarios() -> None:
            try:
                page.evaluate(
                    """() => {
                        document.querySelectorAll('[data-v3-blocked="1"]').forEach((n) => {
                            n.style.pointerEvents = '';
                            n.style.opacity = '';
                            n.removeAttribute('data-v3-blocked');
                        });
                    }"""
                )
            except Exception:
                pass

        def _clicar_next_por_coordenada(candidate) -> dict:
            try:
                box = candidate.bounding_box()
                if not box:
                    return {"clicked": False, "reason": "sem bounding_box"}
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                top_info = _element_from_point(page, cx, cy) or {}
                top_tag = (top_info.get("tagName") or "").lower()
                top_html = (top_info.get("outerHTML") or "")
                if "aplicar" in top_html.lower():
                    return {"clicked": False, "reason": "top element contém Aplicar", "cx": cx, "cy": cy}

                overlay_info = _neutralizar_overlay_no_ponto(cx, cy)
                if overlay_info.get("changed"):
                    print(
                        "    [V3] overlay temporariamente neutralizado:",
                        (overlay_info.get("className") or overlay_info.get("innerText") or "")[:120],
                    )

                clicked = False
                if top_tag in ("svg", "path") or top_tag not in ("button", "a"):
                    try:
                        clicked = page.evaluate(
                            """([cx, cy]) => {
                                const top = document.elementFromPoint(cx, cy);
                                if (!top || !top.closest) return false;
                                const target = top.closest('button,a');
                                if (!target) return false;
                                const txt = (target.innerText || '').toLowerCase();
                                if (txt.includes('aplicar')) return false;
                                target.click();
                                return true;
                            }""",
                            [cx, cy],
                        )
                    except Exception:
                        clicked = False

                if not clicked:
                    try:
                        page.mouse.click(cx, cy)
                        clicked = True
                    except Exception:
                        clicked = False

                return {
                    "clicked": bool(clicked),
                    "cx": cx,
                    "cy": cy,
                    "top_tag": top_tag,
                    "top_html": top_html[:280],
                    "overlay_changed": bool(overlay_info.get("changed")),
                }
            except Exception as e:
                return {"clicked": False, "reason": str(e)}

        def _selecionar_primeira_data_disponivel(month_index: int, mes_ref: str | None) -> dict | None:
            # Captura de evidência antes
            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_before_select.png"))
            except Exception:
                pass

            loc = page.locator("[data-date]")
            n_loc = 0
            try:
                n_loc = loc.count()
            except Exception:
                n_loc = 0
            escolhida = None
            for i in range(min(n_loc, 200)):
                try:
                    cel = loc.nth(i)
                    if not cel.is_visible():
                        continue
                    if mes_ref:
                        dd = cel.get_attribute("data-date")
                        if not dd or not dd.startswith(mes_ref):
                            continue
                    if not _celula_disponivel(cel):
                        continue
                    escolhida = cel
                    break
                except Exception:
                    continue

            if not escolhida:
                _salvar_estado_falha(f"cand_{month_index:02d}_no_cell")
                return None

            # Clique com V1 (hit-test-aware)
            try:
                _click_com_verificacao_overlap(page, escolhida, "[V3.DEMO]")
            except Exception:
                try:
                    escolhida.click(timeout=5000, force=True)
                except Exception:
                    _salvar_estado_falha(f"cand_{month_index:02d}_click_fail")
                    return None

            page.wait_for_timeout(WAIT_AFTER_CLICK_MS)
            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_after_select.png"))
            except Exception:
                pass
            try:
                page.wait_for_timeout(1000)
                range_global = evidence_dir / "range_azul_confirmado.png"
                range_month = evidence_dir / f"cand_{month_index:02d}_range_azul_confirmado.png"
                page.screenshot(path=str(range_global), full_page=True)
                page.screenshot(path=str(range_month), full_page=True)
                if not range_global.exists():
                    page.screenshot(path=str(range_global), full_page=True)
                if not range_month.exists():
                    page.screenshot(path=str(range_month), full_page=True)
            except Exception:
                pass

            data_date = None
            visible_text = None
            try:
                data_date = escolhida.get_attribute("data-date")
            except Exception:
                data_date = None
            try:
                visible_text = (escolhida.inner_text() or "").strip()
            except Exception:
                visible_text = None

            return {
                "month_index": month_index,
                "attempt_ts": datetime.now().isoformat(),
                "selector_used": elemento_clicado,
                "month_ref": mes_ref,
                "data_date": data_date,
                "visible_text": (visible_text or "")[:200],
                "screenshot_paths": {
                    "before_select": str(evidence_dir / f"cand_{month_index:02d}_before_select.png"),
                    "after_select": str(evidence_dir / f"cand_{month_index:02d}_after_select.png"),
                },
                "notes": "Selecionada primeira célula visível com data-date e sem aria-disabled/classe disabled.",
            }

        def _selecionar_range_mes(month_index: int, mes_ref: str | None) -> dict | None:
            """Seleciona intervalo: check-in = primeira célula disponível do mês; check-out = +3 dias ou próxima disponível no mês."""
            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_before_select.png"))
            except Exception:
                pass

            loc = page.locator("[data-date]")
            n_loc = 0
            try:
                n_loc = loc.count()
            except Exception:
                n_loc = 0
            celulas_disponiveis: list = []
            for i in range(min(n_loc, 200)):
                try:
                    cel = loc.nth(i)
                    if not cel.is_visible():
                        continue
                    if mes_ref:
                        dd = cel.get_attribute("data-date")
                        if not dd or not dd.startswith(mes_ref):
                            continue
                    if not _celula_disponivel(cel):
                        continue
                    celulas_disponiveis.append(cel)
                except Exception:
                    continue

            if not celulas_disponiveis:
                _salvar_estado_falha(f"cand_{month_index:02d}_no_cell")
                return None

            checkin_el = celulas_disponiveis[0]
            # Check-out: +3 dias se existir no mesmo mês, senão próxima disponível
            checkout_idx = min(3, len(celulas_disponiveis) - 1) if len(celulas_disponiveis) > 1 else 0
            if checkout_idx == 0 and len(celulas_disponiveis) > 1:
                checkout_idx = 1
            checkout_el = celulas_disponiveis[checkout_idx]

            # Extrair data-date antes dos cliques (DOM pode mudar após seleção)
            checkin_date = None
            checkout_date = None
            try:
                checkin_date = checkin_el.get_attribute("data-date")
                checkout_date = checkout_el.get_attribute("data-date")
            except Exception:
                pass

            try:
                _click_com_verificacao_overlap(page, checkin_el, "[V3.DEMO]")
            except Exception:
                try:
                    checkin_el.click(timeout=5000, force=True)
                except Exception:
                    _salvar_estado_falha(f"cand_{month_index:02d}_checkin_click_fail")
                    return None
            page.wait_for_timeout(WAIT_AFTER_CLICK_MS)
            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_checkin_ok.png"))
            except Exception:
                pass

            try:
                _click_com_verificacao_overlap(page, checkout_el, "[V3.DEMO]")
            except Exception:
                try:
                    checkout_el.click(timeout=5000, force=True)
                except Exception:
                    _salvar_estado_falha(f"cand_{month_index:02d}_checkout_click_fail")
                    return None
            page.wait_for_timeout(WAIT_AFTER_CLICK_MS)
            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_checkout_ok.png"))
            except Exception:
                pass
            # Garantir screenshot de confirmação visual do range (ou fallback full page).
            try:
                page.wait_for_timeout(1000)
                range_global = evidence_dir / "range_azul_confirmado.png"
                range_month = evidence_dir / f"cand_{month_index:02d}_range_azul_confirmado.png"
                page.screenshot(path=str(range_global))
                page.screenshot(path=str(range_month))
                if not range_global.exists():
                    page.screenshot(
                        path=str(evidence_dir / f"range_azul_confirmado_fullpage_{month_index:02d}.png"),
                        full_page=True,
                    )
                if not range_month.exists():
                    page.screenshot(path=str(range_month), full_page=True)
            except Exception:
                try:
                    page.screenshot(
                        path=str(evidence_dir / f"range_azul_confirmado_fullpage_{month_index:02d}.png"),
                        full_page=True,
                    )
                except Exception:
                    pass

            try:
                page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_after_select.png"))
            except Exception:
                pass

            # Fallback: ler dos campos de exibição se data-date não foi obtido antes do clique
            if not checkin_date or not checkout_date:
                try:
                    start_el = page.locator("[data-testid='date-display-field-start']").first
                    end_el = page.locator("[data-testid='date-display-field-end']").first
                    if start_el.count() > 0:
                        checkin_date = (start_el.get_attribute("data-date") or (start_el.inner_text() or "").strip() or checkin_date)
                    if end_el.count() > 0:
                        checkout_date = (end_el.get_attribute("data-date") or (end_el.inner_text() or "").strip() or checkout_date)
                except Exception:
                    pass
                # Aceitar apenas formato YYYY-MM-DD
                if checkin_date and not re.match(r"\d{4}-\d{2}-\d{2}", checkin_date or ""):
                    checkin_date = None
                if checkout_date and not re.match(r"\d{4}-\d{2}-\d{2}", checkout_date or ""):
                    checkout_date = None

            range_formed = False
            try:
                inrange_count = page.locator(
                    "[data-date][aria-selected='true'], [data-date][class*='selected'], [data-date][class*='inrange']"
                ).count()
                range_formed = inrange_count >= 2 and bool(checkin_date and checkout_date)
            except Exception:
                range_formed = bool(checkin_date and checkout_date)

            return {
                "month_index": month_index,
                "month_ref": mes_ref,
                "checkin_date": checkin_date,
                "checkout_date": checkout_date,
                "selector_used": elemento_clicado,
                "screenshot_paths": {
                    "before_select": str(evidence_dir / f"cand_{month_index:02d}_before_select.png"),
                    "after_select": str(evidence_dir / f"cand_{month_index:02d}_after_select.png"),
                    "checkin_ok": str(evidence_dir / f"cand_{month_index:02d}_checkin_ok.png"),
                    "checkout_ok": str(evidence_dir / f"cand_{month_index:02d}_checkout_ok.png"),
                    "range_confirmed": str(evidence_dir / "range_azul_confirmado.png"),
                },
                "range_formed": range_formed,
                "notes": "Range: check-in primeira célula disponível; check-out +3 dias ou próxima no mês.",
            }

        def _clicar_proximo_mes(month_index: int, mes_atual: str | None) -> bool:
            coords_path = evidence_dir / f"attempt_{month_index:02d}_coords.json"
            coords_log: list[dict] = []
            for tent in range(MAX_NEXT_TRIES):
                # Painel pode surgir após seleção; neutralizar novamente antes de tentar avançar mês.
                try:
                    _neutralizar_painel_melhor_de(page)
                except Exception:
                    pass
                header_before = _header_calendario_texto() or ""
                pre_click_url = page.url

                print("    [V3.DEMO] Clique relativo no upper-right do widget...")
                rel_clicked = False
                cx = cy = None
                widget_rect = None
                try:
                    # clique por região: x=95% da largura, y=5% da altura do widget
                    box = None
                    if widget_scope and widget_scope.count() > 0:
                        box = widget_scope.bounding_box()
                    if not box:
                        box = page.locator("[data-date]").first.bounding_box()
                    if box:
                        cx = int(box["x"] + (box["width"] * 0.95))
                        cy = int(box["y"] + (box["height"] * 0.05))
                        widget_rect = {
                            "x": float(box["x"]),
                            "y": float(box["y"]),
                            "width": float(box["width"]),
                            "height": float(box["height"]),
                        }
                        print(
                            f"    [V3] widget_rect={widget_rect} click_point={{'cx': {cx}, 'cy': {cy}}}"
                        )
                        _neutralizar_overlay_no_ponto(cx, cy)
                        page.mouse.click(cx, cy)
                        rel_clicked = True
                except Exception:
                    rel_clicked = False
                if not rel_clicked:
                    try:
                        page.locator("[data-date]").first.click(timeout=3000)
                    except Exception:
                        pass
                    page.keyboard.press("ArrowRight")

                page.wait_for_timeout(WAIT_AFTER_CLICK_MS)
                try:
                    page.screenshot(path=str(evidence_dir / f"cand_{month_index:02d}_month_after_next_t{tent+1}.png"))
                except Exception:
                    pass

                post_click_url = page.url
                if post_click_url != pre_click_url:
                    _salvar_estado_falha(f"cand_{month_index:02d}_unexpected_nav_t{tent+1}")
                    try:
                        page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=TIMEOUT_PADRAO)
                        _aceitar_cookies(page)
                        page.wait_for_timeout(1200)
                        _reabrir_widget_v3()
                    except Exception:
                        pass
                    _restaurar_overlays_temporarios()
                    continue

                # Validar avanço por texto do cabeçalho do calendário.
                header_after = _header_calendario_texto() or ""
                siblings_short = []
                try:
                    siblings_short = page.evaluate(
                        """() => {
                            const out = [];
                            const hs = Array.from(document.querySelectorAll('[class*="month"], [class*="header"], [data-testid*="month"], h3, h4'));
                            for (const h of hs) {
                                const txt = (h.textContent || '').trim();
                                if (!/\\b20\\d{2}\\b/.test(txt)) continue;
                                const p = h.parentElement;
                                if (!p) continue;
                                for (const s of Array.from(p.children).slice(0, 8)) {
                                    out.push({
                                        text: ((s.textContent || '').trim()).slice(0, 80),
                                        className: ((s.className || '').toString()).slice(0, 120),
                                    });
                                }
                                break;
                            }
                            return out;
                        }"""
                    ) or []
                except Exception:
                    siblings_short = []
                coords_log.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "month_index": month_index,
                        "attempt_index": tent + 1,
                        "widget_rect": widget_rect,
                        "click_point": {"cx": cx, "cy": cy},
                        "header_text_before": header_before,
                        "header_text_after": header_after,
                        "siblings_short": siblings_short,
                    }
                )
                print(
                    f"    [V3] tentativa {month_index}.{tent+1} — cx={cx} cy={cy} "
                    f"header_before='{header_before}' header_after='{header_after}'"
                )
                try:
                    coords_path.write_text(json.dumps(coords_log, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
                if header_before and header_after and header_before != header_after:
                    _restaurar_overlays_temporarios()
                    return True

                # Espera curta para mudança do header (até 2s)
                elapsed = 0
                while elapsed < HEADER_CHANGE_TIMEOUT_MS:
                    page.wait_for_timeout(250)
                    elapsed += 250
                    header_after = _header_calendario_texto() or ""
                    if header_before and header_after and header_before != header_after:
                        _restaurar_overlays_temporarios()
                        return True

                # fallback alternativo por tecla quando header não muda
                try:
                    page.keyboard.press("ArrowRight")
                    page.wait_for_timeout(500)
                    header_after = _header_calendario_texto() or ""
                    if header_before and header_after and header_before != header_after:
                        _restaurar_overlays_temporarios()
                        return True
                except Exception:
                    pass

                # fallback: mês dominante
                mes_novo = _mes_visivel_yyyymm()
                if mes_atual and mes_novo and mes_novo != mes_atual:
                    _restaurar_overlays_temporarios()
                    return True

                # Dump completo de botões quando falha em avançar
                try:
                    dom_dump = page.evaluate(
                        """() => {
                            const root = document.querySelector('[data-evidence-widget-scope="1"]') || document.body;
                            const nodes = Array.from(root.querySelectorAll('button, [role="button"]'));
                            return nodes.map((n) => {
                                const r = n.getBoundingClientRect();
                                return {
                                    tag: (n.tagName || '').toLowerCase(),
                                    role: n.getAttribute('role'),
                                    text: ((n.innerText || n.textContent || '').trim()).slice(0, 180),
                                    className: (n.className || '').toString().slice(0, 180),
                                    rect: { x: r.left, y: r.top, w: r.width, h: r.height },
                                };
                            });
                        }"""
                    )
                    (evidence_dir / "dom_dump.json").write_text(
                        json.dumps(dom_dump, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass
                # Pausa de inspeção visual após falha da tentativa
                page.wait_for_timeout(5000)
                _restaurar_overlays_temporarios()
            try:
                coords_path.write_text(json.dumps(coords_log, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            return False

        for month_index in range(N_MONTHS_TO_TEST):
            # Garantir widget aberto
            try:
                page.wait_for_selector("[data-date]", timeout=WAIT_FOR_WIDGET_MS)
            except Exception:
                ok_reopen = _reabrir_widget_v3()
                if not ok_reopen:
                    _salvar_estado_falha(f"cand_{month_index:02d}_widget_closed")
                    break

            if _is_navegacao_inesperada():
                _salvar_estado_falha(f"cand_{month_index:02d}_unexpected_nav")
                try:
                    page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=TIMEOUT_PADRAO)
                    _aceitar_cookies(page)
                    page.wait_for_timeout(1500)
                except Exception:
                    break
                # Reabrir widget usando a rotina inteira (simplificação)
                return run_v3_calendario_inferior(page)

            mes_ref = _mes_visivel_yyyymm()
            if DEMO_V3_FULL_CYCLE:
                entry = _selecionar_range_mes(month_index, mes_ref)
            else:
                entry = _selecionar_primeira_data_disponivel(month_index, mes_ref)
            if entry:
                dates_extracted.append(entry)
                try:
                    dates_path.write_text(json.dumps(dates_extracted, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
                if DEMO_V3_FULL_CYCLE:
                    print(f"    [V3.DEMO] mês {month_index}: check-in={entry.get('checkin_date')} check-out={entry.get('checkout_date')}")
                else:
                    print(f"    [V3.DEMO] mês {month_index}: data extraída = {entry.get('data_date')}")
            else:
                print(f"    [V3.DEMO] mês {month_index}: falha ao selecionar {'range' if DEMO_V3_FULL_CYCLE else 'data'}.")

            if month_index < (N_MONTHS_TO_TEST - 1):
                ok_next = _clicar_proximo_mes(month_index, mes_ref)
                if not ok_next:
                    print(f"    [V3.DEMO] mês {month_index}: falha ao avançar para o próximo mês.")
                    if dates_extracted and len(dates_extracted) >= (month_index + 1):
                        dates_extracted[month_index]["month_advance"] = "fail"
                        dates_extracted[month_index]["notes"] = (
                            (dates_extracted[month_index].get("notes") or "")
                            + " | avanço de mês: falha após tentativas."
                        )
                        try:
                            dates_path.write_text(
                                json.dumps(dates_extracted, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                    _salvar_estado_falha(f"cand_{month_index:02d}_next_not_found")
                    break
                else:
                    if dates_extracted and len(dates_extracted) >= (month_index + 1):
                        dates_extracted[month_index]["month_advance"] = "success"
                        dates_extracted[month_index]["notes"] = (
                            (dates_extracted[month_index].get("notes") or "")
                            + " | avanço de mês: sucesso."
                        )
                        try:
                            dates_path.write_text(
                                json.dumps(dates_extracted, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass

        # zip das evidências
        try:
            import os
            import zipfile

            zip_name = "evidence_v3_demo_extended_full.zip" if DEMO_V3_FULL_CYCLE else "evidence_v3_demo_extended.zip"
            zip_path = SCRIPT_DIR / zip_name
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for root_dir, _dirs, files in os.walk(evidence_dir):
                    for f in files:
                        fp = Path(root_dir) / f
                        arc = fp.relative_to(SCRIPT_DIR)
                        z.write(fp, arcname=str(arc))
            print(f"[V3.DEMO] ZIP gerado: {zip_path}")
        except Exception as e:
            print(f"[V3.DEMO] Aviso: falha ao gerar ZIP: {e}", file=sys.stderr)

    # ----- 3) Captura do padrão "—" e de preço -----
    print("[V3.3] Capturando 'DNA' de célula indisponível (—) e de célula com preço...")
    loc_celulas = page.locator("[data-date]")
    n = loc_celulas.count()
    dna_indisponivel = None
    dna_preco = None

    for i in range(min(n, 80)):
        try:
            cel = loc_celulas.nth(i)
            texto = (cel.inner_text() or "").strip()
            aria_disabled = cel.get_attribute("aria-disabled")
            if aria_disabled == "true" or "—" in texto:
                if dna_indisponivel is None:
                    dna_indisponivel = _dna_celula(cel)
                    dna_indisponivel["data_date"] = cel.get_attribute("data-date")
                if dna_preco is not None:
                    break
            elif re.search(r"R\$\s*[\d.,]+", texto) or (re.search(r"[\d.,]+", texto) and "—" not in texto and aria_disabled != "true"):
                if dna_preco is None:
                    dna_preco = _dna_celula(cel)
                    dna_preco["data_date"] = cel.get_attribute("data-date")
                if dna_indisponivel is not None:
                    break
        except Exception:
            continue

    print()
    print("========== DNA CÉLULA INDISPONÍVEL (—) ==========")
    if dna_indisponivel:
        print("  data-date:", dna_indisponivel.get("data_date"))
        print("  classes:", dna_indisponivel.get("classes"))
        print("  aria-label:", dna_indisponivel.get("aria_label"))
        print("  aria-disabled:", dna_indisponivel.get("aria_disabled"))
        print("  texto:", (dna_indisponivel.get("texto") or "")[:200])
        print("  tem_traco_interno (span/div com '—'):", dna_indisponivel.get("tem_traco_interno"))
        print("  outerHTML (início):")
        print((dna_indisponivel.get("outerHTML") or "")[:1200])
    else:
        print("  (nenhuma célula com '—' ou aria-disabled encontrada)")
    print()
    print("========== DNA CÉLULA COM PREÇO ==========")
    if dna_preco:
        print("  data-date:", dna_preco.get("data_date"))
        print("  classes:", dna_preco.get("classes"))
        print("  aria-label:", dna_preco.get("aria_label"))
        print("  aria-disabled:", dna_preco.get("aria_disabled"))
        print("  texto:", (dna_preco.get("texto") or "")[:200])
        print("  outerHTML (início):")
        print((dna_preco.get("outerHTML") or "")[:1200])
    else:
        print("  (nenhuma célula com preço encontrada)")
    print()

    # ----- 4) Diagnóstico de navegação (Próximo Mês) -----
    print("[V3.4] Procurando botão 'Próximo Mês' dentro do widget...")
    botoes_proximo = [
        '[data-testid="datepicker-next-month-button"]',
        '[aria-label*="próximo"]',
        '[aria-label*="next"]',
        'button:has-text("Próximo")',
        '[data-bui-ref="calendar-next"]',
    ]
    primeiro_mes_antes = None
    try:
        primeiro_mes_antes = _extrair_mes_ano_do_calendario(page, "body")
    except Exception:
        pass

    for sel in botoes_proximo:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                page.wait_for_timeout(800)
                primeiro_mes_depois = _extrair_mes_ano_do_calendario(page, "body")
                print(f"    Clique em '{sel}' executado.")
                print(f"    Mês antes: {primeiro_mes_antes} | Mês depois: {primeiro_mes_depois}")
                break
        except Exception:
            continue
    else:
        print("    Nenhum botão 'Próximo Mês' clicado.")

    print()
    print("[V3] Concluído. Confirmação: clique dentro da seção =", "OK" if elemento_clicado else "FALHOU")
    _dump_attempts_log()
    return 0


def main() -> int:
    seletor_campo_ok = None
    seletor_container_ok = None
    seletor_celulas_ok = None
    seletor_proximo_ok = None
    seletores_campo_falharam = []
    seletores_container_falharam = []
    seletores_celulas_falharam = []
    seletores_proximo_falharam = []

    print("============================================")
    print("EXPLORAÇÃO DO CALENDÁRIO BOOKING")
    print("============================================")
    print(f"URL: {URL_HOTEL}")
    print(f"Mês alvo: {ANO_MES_ALVO}")
    print(f"Headless: {HEADLESS}")
    print("Navegador aberto. Iniciando extração visual...")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            # ----- PASSO 1: Abrir página do hotel -----
            print("[1] Navegando para a página do hotel...")
            page.goto(URL_HOTEL, wait_until="domcontentloaded", timeout=TIMEOUT_PADRAO)
            try:
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
            except Exception:
                # O Booking pode manter requisições longas em background; não bloquear o diagnóstico.
                print("Aviso: timeout em networkidle. Prosseguindo mesmo assim...")
            _aceitar_cookies(page)
            page.wait_for_timeout(1500)

            if MODO_V3:
                resultado = run_v3_calendario_inferior(page)
                browser.close()
                return resultado

            # ----- PASSO 2: Abrir calendário -----
            print("[2] Procurando campo de datas e abrindo calendário...")
            for sel in SELETORES_CAMPO_DATA:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.click(timeout=5000)
                        seletor_campo_ok = sel
                        break
                except Exception:
                    seletores_campo_falharam.append(sel)
            else:
                seletores_campo_falharam = SELETORES_CAMPO_DATA[:]

            if not seletor_campo_ok:
                print("ERRO: Não foi possível clicar em nenhum campo de data.")
                print("Seletores tentados:", seletores_campo_falharam)
                _screenshot(page, "debug_calendario.png")
                browser.close()
                return 1

            page.wait_for_timeout(1000)

            # Localizar container do calendário
            for sel in SELETORES_CONTAINER_CALENDARIO:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.wait_for_state("visible", timeout=5000)
                        seletor_container_ok = sel
                        break
                except Exception:
                    seletores_container_falharam.append(sel)
            else:
                seletores_container_falharam = SELETORES_CONTAINER_CALENDARIO[:]

            # Garantir que o calendário realmente abriu: esperar por qualquer elemento com data-date.
            # O Booking pode renderizar o widget sem casar com os seletores de container acima.
            try:
                page.wait_for_selector("[data-date]", timeout=5000)
            except Exception:
                print("ERRO: Calendário não encontrado (nenhum elemento com data-date).")
                if not seletor_container_ok:
                    print("Seletores container tentados:", seletores_container_falharam)
                _screenshot(page, "debug_calendario.png")
                browser.close()
                return 1

            container_for_mes = seletor_container_ok or "body"
            if not seletor_container_ok:
                print(
                    "    Aviso: container do calendário não identificado pelos seletores; "
                    "continuando com fallback para leitura do mês/ano."
                )
            print(f"    Calendário aberto. Container: {seletor_container_ok or '- (não identificado)'}")

            # ----- PASSO 3: Navegar até o mês alvo -----
            print(f"[3] Navegando até o mês {ANO_MES_ALVO}...")
            for _ in range(MAX_CLIQUES_PROXIMO):
                texto_mes = _extrair_mes_ano_do_calendario(page, container_for_mes)
                mes_atual = _mes_visivel_para_yyyymm(texto_mes or "")
                if mes_atual == ANO_MES_ALVO:
                    print(f"    Mês alvo alcançado: {texto_mes}")
                    break
                if mes_atual and mes_atual > ANO_MES_ALVO:
                    print(f"    Mês atual ({mes_atual}) já é posterior ao alvo. Usando mês visível.")
                    break
                # Clicar próximo
                clicou = False
                for sel in SELETORES_BOTAO_PROXIMO:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0:
                            loc.click(timeout=3000)
                            seletor_proximo_ok = sel
                            clicou = True
                            break
                    except Exception:
                        if sel not in seletores_proximo_falharam:
                            seletores_proximo_falharam.append(sel)
                if not clicou:
                    seletores_proximo_falharam = list(SELETORES_BOTAO_PROXIMO)
                    print("    Aviso: botão próximo não encontrado. Usando mês atual.")
                    break
                page.wait_for_timeout(WAIT_APOS_CLIQUE_MS)

            if seletor_proximo_ok:
                seletores_proximo_falharam = [s for s in SELETORES_BOTAO_PROXIMO if s != seletor_proximo_ok]

            mes_visivel = _mes_visivel_para_yyyymm(
                _extrair_mes_ano_do_calendario(page, container_for_mes) or ""
            ) or ANO_MES_ALVO

            # ----- PASSO 4: Extrair células -----
            print("[4] Extraindo células de dia...")
            dias_resultado = []
            for sel in SELETORES_CELULAS_DIA:
                try:
                    loc = page.locator(sel)
                    n = loc.count()
                    if n == 0:
                        seletores_celulas_falharam.append(sel)
                        continue
                    seletor_celulas_ok = sel
                    for i in range(n):
                        el = loc.nth(i)
                        info = _analisar_celula(el, mes_visivel)
                        if info["data"] or info["html_raw"]:
                            if info["disponivel"] is None and not info["motivo_indisponivel"]:
                                info["motivo_indisponivel"] = "incerto"
                            dias_resultado.append(info)
                    if dias_resultado:
                        break
                except Exception as e:
                    seletores_celulas_falharam.append(f"{sel} ({e})")
                    continue

            if not dias_resultado:
                print("ERRO: Nenhuma célula de dia encontrada. Seletores tentados:", seletores_celulas_falharam)
                _screenshot(page, "debug_celulas.png")
                browser.close()
                return 1

            # Deduplicar por data e filtrar pelo mês visível
            vistas = set()
            dias_unicos = []
            for d in dias_resultado:
                k = d.get("data") or d.get("html_raw", "")
                if k and k not in vistas:
                    vistas.add(k)
                    dias_unicos.append(d)

            # Preferir o mês alvo (ANO_MES_ALVO) via atributo data-date.
            # Se não houver nenhum dia daquele mês (ex: calendário mostrou apenas meses próximos),
            # cair para o mês visível.
            mes_efetivo = ANO_MES_ALVO
            dias_mes_alvo = [
                d
                for d in dias_unicos
                if d.get("data") and d["data"].startswith(ANO_MES_ALVO)
            ]
            if dias_mes_alvo:
                dias_resultado = sorted(dias_mes_alvo, key=lambda x: x["data"] or "")
            else:
                dias_mes_visivel = [
                    d
                    for d in dias_unicos
                    if d.get("data") and mes_visivel and d["data"].startswith(mes_visivel)
                ]
                if dias_mes_visivel:
                    dias_resultado = sorted(dias_mes_visivel, key=lambda x: x["data"] or "")
                    mes_efetivo = mes_visivel
                    print(f"Aviso: mês alvo {ANO_MES_ALVO} não alcançado; usando mês visível {mes_visivel}.")
                else:
                    dias_resultado = [d for d in dias_unicos if d.get("data")] or dias_unicos
                    mes_efetivo = mes_visivel or ANO_MES_ALVO

        except Exception as e:
            print(f"ERRO inesperado: {e}")
            import traceback
            traceback.print_exc()
            _screenshot(page, "debug_erro.png")
            browser.close()
            return 1

        browser.close()

    # ----- PASSO 5: Resumo e contagens -----
    total = len(dias_resultado)
    disponiveis = sum(1 for d in dias_resultado if d.get("disponivel") is True)
    indisponiveis = sum(1 for d in dias_resultado if d.get("disponivel") is False)
    incertos = sum(1 for d in dias_resultado if d.get("disponivel") is None)
    com_preco = sum(1 for d in dias_resultado if d.get("preco_visivel"))

    # ----- Imprimir tabela -----
    print()
    print("============================================")
    print(f"MAPA DE DISPONIBILIDADE - {mes_efetivo}")
    print("============================================")
    print(f"{'Data':<12} | {'Status':<14} | {'Preço Visível':<14} | Motivo")
    print("-" * 12 + "|" + "-" * 16 + "|" + "-" * 16 + "|-------")
    for d in dias_resultado:
        data = d.get("data") or "?"
        if d.get("disponivel") is True:
            status = "[OK] Disponível"
        elif d.get("disponivel") is False:
            status = "[NAO] Indisponível"
        else:
            status = "[INCERTO]"
        preco = d.get("preco_visivel") or "-"
        if preco != "-":
            preco = f"R$ {preco}"
        motivo = d.get("motivo_indisponivel") or "-"
        print(f"{data:<12} | {status:<14} | {preco:<14} | {motivo}")

    print()
    print("RESUMO:")
    print(f"  - Total de dias encontrados: {total}")
    print(f"  - Disponíveis: {disponiveis}")
    print(f"  - Indisponíveis: {indisponiveis}")
    print(f"  - Incertos: {incertos}")
    print(f"  - Dias com preço visível: {com_preco}")
    print()
    print("SELETORES QUE FUNCIONARAM:")
    print(f"  - Campo de data: {seletor_campo_ok or '-'}")
    print(f"  - Container do calendário: {seletor_container_ok or '-'}")
    print(f"  - Células de dia: {seletor_celulas_ok or '-'}")
    print(f"  - Botão próximo mês: {seletor_proximo_ok or '-'}")
    print()
    falharam = []
    if seletores_campo_falharam:
        falharam.append("campo_data: " + ", ".join(seletores_campo_falharam[:3]))
    if seletores_container_falharam:
        falharam.append("container: " + ", ".join(seletores_container_falharam[:3]))
    if seletores_celulas_falharam:
        falharam.append("celulas: " + ", ".join(str(s)[:50] for s in seletores_celulas_falharam[:3]))
    if seletores_proximo_falharam:
        falharam.append("proximo: " + ", ".join(seletores_proximo_falharam[:3]))
    print("SELETORES QUE FALHARAM (amostra):")
    for f in falharam:
        print(f"  - {f}")
    print()
    print("HTML BRUTO DE AMOSTRA (até 3 células):")
    for i, d in enumerate(dias_resultado[:3]):
        label = "disponível" if d.get("disponivel") else ("indisponível" if d.get("disponivel") is False else "incerto")
        print(f"  [{label}] {d.get('data', '?')}:")
        print(f"    {(d.get('html_raw') or '')[:180]}...")
        print()

    # ----- PASSO 6: Salvar JSON -----
    out_path = SCRIPT_DIR / f"output_calendario_{ANO_MES_ALVO}.json"
    payload = {
        "ano_mes": mes_efetivo,
        "url_hotel": URL_HOTEL,
        "seletor_container": seletor_container_ok,
        "seletor_celulas": seletor_celulas_ok,
        "seletor_campo_data": seletor_campo_ok,
        "seletor_botao_proximo": seletor_proximo_ok,
        "dias": dias_resultado,
        "resumo": {
            "total": total,
            "disponiveis": disponiveis,
            "indisponiveis": indisponiveis,
            "incertos": incertos,
            "com_preco_visivel": com_preco,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"JSON salvo em: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())


# Como rodar:
#   python scripts/explorar_calendario_booking.py
# Editar URL_HOTEL e ANO_MES_ALVO no topo do arquivo antes de rodar.
