"""
scrapers - Automação Playwright para extração de dados.
Responsabilidade: execução do scraping e captura de evidências em artifacts/.
"""
import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

from loguru import logger
from playwright.sync_api import sync_playwright

from core.config import (
    carregar_config_scraper,
    definir_calendario_soberano_ano,
    definir_periodos_sazonais,
    definir_periodos_12meses,
    gerar_calendario_diario_projeto,
)
from core.projetos import ArquivoProjetoNaoEncontrado, carregar_projeto, get_market_bruto_path
from core.scraper.modelos import DadosMercado, DiariaPeriodo, MarketBruto, MarketBrutoRegistro
from core.scraper.parsing import detectar_tipo_tarifa, parsear_valor_preco

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SELETORES_PRECO = [
    '[data-testid="price-and-discounted-price"]',
    ".prco-val",
    ".bui-price-display__value",
    "[class*='price']",
    "[class*='Price']",
]


def _url_com_datas(url_base: str, checkin: str, checkout: str) -> str:
    """Adiciona check-in, check-out e ocupação à URL do Booking."""
    params = {
        "checkin": checkin,
        "checkout": checkout,
        "group_adults": 2,
        "group_children": 0,
        "no_rooms": 1,
    }
    parsed = urlparse(url_base)
    query = parsed.query
    new_query = urlencode(params) if not query else query + "&" + urlencode(params)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))


def _extrair_preco_unico(page) -> float:
    """Fallback: primeiro valor em R$ encontrado na página."""
    for seletor in SELETORES_PRECO:
        try:
            loc = page.locator(seletor)
            if loc.count() == 0:
                continue
            texto = loc.first.inner_text(timeout=3000)
            return parsear_valor_preco(texto)
        except Exception:
            continue
    return 0.0


def _texto_container(el) -> str:
    """Obtém texto do container (linha/tr/card) do elemento para nome e tarifa."""
    try:
        return el.evaluate(
            """node => {
            let p = node;
            for (let i = 0; i < 8 && p; i++) {
                if (p.tagName === 'TR' || (p.getAttribute && p.getAttribute('data-testid')))
                    return (p.innerText || '').trim();
                p = p.parentElement;
            }
            return (node.innerText || '').trim();
        }"""
        )
    except Exception:
        return ""


def _eh_texto_capacidade(texto: str) -> bool:
    """Verifica se o texto é de capacidade (ex: 'Acomoda somente 1 hóspede') e não nome do quarto."""
    if not texto or not texto.strip():
        return True
    t = texto.strip().lower()
    return "acomoda" in t or "hóspede" in t or "hospede" in t or "pessoa" in t or "pessoas" in t


def _nome_quarto_no_bloco(el) -> str:
    """Nome real do quarto: prioriza .hprt-roomtype-name, depois [data-testid=room-name], h3, etc."""
    try:
        nome = el.evaluate(
            """node => {
            let p = node;
            for (let i = 0; i < 10 && p; i++) {
                let name = p.querySelector('.hprt-roomtype-name');
                if (name && name.innerText) return name.innerText.trim();
                name = p.querySelector('[data-testid="room-name"]');
                if (name && name.innerText) return name.innerText.trim();
                let h3 = p.querySelector('h3');
                if (h3 && h3.innerText) return h3.innerText.trim();
                let t = p.querySelector('span[class*="title"], [class*="room-name"], [class*="RoomName"]');
                if (t && t.innerText) return t.innerText.trim();
                p = p.parentElement;
            }
            return '';
        }"""
        )
        return nome or ""
    except Exception:
        return ""


def _extrair_quartos_pagina(page) -> list[dict]:
    """Varre todos os preços visíveis e retorna lista de {nome, tarifa, total} para auditoria."""
    quartos: list[dict] = []
    for seletor in SELETORES_PRECO:
        try:
            loc = page.locator(seletor)
            n = loc.count()
            if n == 0:
                continue
            for i in range(n):
                try:
                    el = loc.nth(i)
                    texto_preco = el.inner_text(timeout=2000)
                    total = parsear_valor_preco(texto_preco)
                    if total <= 0:
                        continue
                    nome = _nome_quarto_no_bloco(el)
                    if not nome:
                        ctx = _texto_container(el)
                        linhas = [ln.strip() for ln in (ctx or "").split("\n") if ln.strip() and "máx" not in ln.lower() and "pessoas" not in ln.lower()]
                        nome = (linhas[0][:80] if linhas else "") or ""
                    else:
                        nome = nome[:80]
                    if _eh_texto_capacidade(nome):
                        logger.warning("Nome do quarto inválido (texto de capacidade ou vazio), usando Indefinido: %r", nome or "(vazio)")
                        nome = "Indefinido"
                    if not nome:
                        nome = "Indefinido"
                    ctx = _texto_container(el)
                    tarifa = detectar_tipo_tarifa(ctx)
                    if not tarifa or not tarifa.strip():
                        logger.warning("Tipo de tarifa não identificado, usando Indefinido")
                        tarifa = "Indefinido"
                    quartos.append({"nome": nome, "tarifa": tarifa, "total": total})
                except Exception:
                    continue
            if quartos:
                return quartos
        except Exception:
            continue
    total_unico = _extrair_preco_unico(page)
    if total_unico > 0:
        quartos.append({"nome": "Indefinido", "tarifa": "Indefinido", "total": total_unico})
    return quartos


def _aceitar_cookies(page) -> None:
    """Clica em botão de aceitar cookies se aparecer (timeout curto)."""
    try:
        btn = page.get_by_role("button", name="Aceitar").or_(page.get_by_role("button", name="Accept"))
        btn.click(timeout=3000)
    except Exception:
        pass


def coletar_dados_mercado(url_booking: str, ano: int, id_projeto: str) -> DadosMercado:
    """Coleta diárias do Booking por período sazonal; retorna DadosMercado com períodos válidos."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "false").lower() == "true"
    periodos = definir_periodos_sazonais(ano)
    diarias: dict[str, DiariaPeriodo] = {}
    sucesso = 0
    falha = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        for periodo in periodos:
            codigo = periodo["codigo"]
            checkin = periodo["checkin"]
            checkout = periodo["checkout"]
            noites = periodo["noites"]
            nome_periodo = periodo["nome_periodo"]
            datas_str = f"{checkin} a {checkout}"

            try:
                logger.info(">>> Coletando {} ({} a {})", nome_periodo, checkin, checkout)
                url = _url_com_datas(url_booking, checkin, checkout)
                logger.info("Navegando para {}", datas_str)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                _aceitar_cookies(page)
                page.wait_for_timeout(2000)

                quartos = _extrair_quartos_pagina(page)
                logger.info("Encontrados {} quartos", len(quartos))
                if not quartos:
                    raise ValueError("Nenhum preço encontrado")

                for q in quartos:
                    logger.info(
                        "Analisando quarto: {} | Tarifa: {} | Total: R$ {:.2f}",
                        q["nome"],
                        q["tarifa"],
                        q["total"],
                    )

                menor = min(quartos, key=lambda x: x["total"])
                diaria_booking = round(menor["total"] / noites, 2)
                diaria_direta = round(diaria_booking / 1.20, 2)
                logger.info(
                    "Calculando diária média... Menor preço total: R$ {:.2f} / {} noites = R$ {:.2f}/noite (diária direta R$ {:.2f})",
                    menor["total"],
                    noites,
                    diaria_booking,
                    diaria_direta,
                )

                diarias[codigo] = DiariaPeriodo(
                    nome_periodo=nome_periodo,
                    datas=datas_str,
                    noites=noites,
                    diaria_booking=diaria_booking,
                    diaria_direta=diaria_direta,
                    tipo_tarifa=menor["tarifa"],
                    nome_quarto=menor["nome"],
                )
                sucesso += 1
                logger.info("Período {} coletado: {} - R$ {:.2f}/noite", codigo, menor["nome"], diaria_booking)
            except Exception as e:
                falha += 1
                logger.warning("Falha no período {}: {}", codigo, e)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path_screenshot = ARTIFACTS_DIR / f"falha_{id_projeto}_{codigo}_{ts}.png"
                try:
                    page.screenshot(path=str(path_screenshot))
                    logger.info("Screenshot salvo: {}", path_screenshot)
                except Exception as ex:
                    logger.error("Erro ao salvar screenshot: {}", ex)

        logger.info("Coleta finalizada: {} sucesso, {} falha", sucesso, falha)
        context.close()
        browser.close()

    return DadosMercado(
        id_projeto=id_projeto,
        url=url_booking,
        ano=ano,
        criado_em=datetime.utcnow(),
        diarias_por_periodo=diarias,
    )


def _sequencia_noites_tentativas(preferencial: int, max_tentativas: int) -> list[int]:
    """Retorna [N, N+1, N-1, N+2, ...] até max_tentativas valores, todos >= 1."""
    out: list[int] = []
    if preferencial >= 1:
        out.append(preferencial)
    n = preferencial
    for delta in [1, -1, 2, -2, 3, -3]:
        if len(out) >= max_tentativas:
            break
        k = n + delta
        if k >= 1 and k not in out:
            out.append(k)
    return out[:max_tentativas]


def coletar_dados_mercado_expandido(url_booking: str, id_projeto: str) -> MarketBruto:
    """Calendário diário 365 dias: gera market_bruto com um registro por dia do ano.
    Amostra 48 dias/mês (4/mês) para coleta; demais dias recebem placeholder preco_booking=null, status='FALHA'.
    Salva sempre para que a Curadoria tenha os 365 slots."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "false").lower() == "true"
    try:
        projeto = carregar_projeto(id_projeto)
        ano_referencia = projeto.ano_referencia or date.today().year
    except ArquivoProjetoNaoEncontrado:
        ano_referencia = date.today().year
        logger.warning("Projeto não encontrado; usando ano atual {} como ano_referencia", ano_referencia)
    cfg = carregar_config_scraper(id_projeto) or {}
    noites_cfg = cfg.get("noites") or {}
    noites_preferencial = int(noites_cfg.get("preferencial", 2))
    max_tentativas = int(noites_cfg.get("max_tentativas", 4))
    noites_preferencial = max(1, noites_preferencial)
    max_tentativas = max(1, max_tentativas)

    calendario_completo = gerar_calendario_diario_projeto(
        id_projeto, ano_referencia, rolling=True
    )
    dias_amostra = definir_calendario_soberano_ano(
        ano_referencia=ano_referencia,
        noites=noites_preferencial,
        id_projeto=id_projeto,
        rolling=True,
    )
    coletados: dict[str, MarketBrutoRegistro] = {}
    registros: list[MarketBrutoRegistro] = []
    logger.info(
        "Calendário diário: {} dias totais; amostra de {} para coleta (noites pref={}, max_tent={})",
        len(calendario_completo),
        len(dias_amostra),
        noites_preferencial,
        max_tentativas,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        for i, periodo in enumerate(dias_amostra):
            checkin_str = periodo["checkin"]
            mes_ano = periodo["mes_ano"]
            tipo_dia = periodo["tipo_dia"]
            categoria_dia = periodo.get("categoria_dia", "normal")
            noites_seq = _sequencia_noites_tentativas(noites_preferencial, max_tentativas)
            checkin_date = date.fromisoformat(checkin_str)
            sucesso = False
            for noites_reais in noites_seq:
                checkout_date = checkin_date + timedelta(days=noites_reais)
                checkout_str = checkout_date.strftime("%Y-%m-%d")
                try:
                    logger.info(">>> [{}/{}] {} ({} noites) {}", i + 1, len(dias_amostra), checkin_str, noites_reais, tipo_dia)
                    url = _url_com_datas(url_booking, checkin_str, checkout_str)
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    _aceitar_cookies(page)
                    page.wait_for_timeout(2000)
                    quartos = _extrair_quartos_pagina(page)
                    if not quartos:
                        raise ValueError("Nenhum preço")
                    menor = min(quartos, key=lambda x: x["total"])
                    total = menor["total"]
                    preco_booking = round(total / noites_reais, 2)
                    preco_direto = round(preco_booking / 1.20, 2)
                    nome_quarto = (menor.get("nome") or "").strip() or "Indefinido"
                    coletados[checkin_str] = MarketBrutoRegistro(
                        checkin=checkin_str,
                        checkout=checkout_str,
                        mes_ano=mes_ano,
                        tipo_dia=tipo_dia,
                        preco_booking=preco_booking,
                        preco_direto=preco_direto,
                        nome_quarto=nome_quarto,
                        tipo_tarifa=menor.get("tarifa", "Padrão") or "Padrão",
                        noites=noites_reais,
                        status="OK",
                        categoria_dia=categoria_dia,
                    )
                    sucesso = True
                    break
                except Exception as e:
                    logger.warning("Tentativa {} noites para {}: {}", noites_reais, checkin_str, e)
                    continue
            if not sucesso:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path_scr = ARTIFACTS_DIR / f"falha_{id_projeto}_{checkin_str}_{ts}.png"
                try:
                    page.screenshot(path=str(path_scr))
                except Exception:
                    pass
                checkout_fallback = (checkin_date + timedelta(days=1)).strftime("%Y-%m-%d")
                coletados[checkin_str] = MarketBrutoRegistro(
                    checkin=checkin_str,
                    checkout=checkout_fallback,
                    mes_ano=mes_ano,
                    tipo_dia=tipo_dia,
                    preco_booking=None,
                    preco_direto=None,
                    nome_quarto="",
                    tipo_tarifa="Padrão",
                    noites=1,
                    status="FALHA",
                    categoria_dia=categoria_dia,
                )

        context.close()
        browser.close()

    # Montar registros: 365 dias, usando coletados quando existir, senão placeholder
    for dia in calendario_completo:
        checkin_str = dia["checkin"]
        if checkin_str in coletados:
            registros.append(coletados[checkin_str])
        else:
            checkin_date = date.fromisoformat(checkin_str)
            checkout_str = (checkin_date + timedelta(days=1)).strftime("%Y-%m-%d")
            registros.append(
                MarketBrutoRegistro(
                    checkin=checkin_str,
                    checkout=checkout_str,
                    mes_ano=dia["mes_ano"],
                    tipo_dia=dia["tipo_dia"],
                    preco_booking=None,
                    preco_direto=None,
                    nome_quarto="",
                    tipo_tarifa="Padrão",
                    noites=1,
                    status="FALHA",
                    categoria_dia=dia["categoria_dia"],
                )
            )

    tem_valido = any(
        (r.preco_booking is not None and r.preco_booking > 0)
        or (r.preco_direto is not None and r.preco_direto > 0)
        for r in registros
    )
    market = MarketBruto(
        id_projeto=id_projeto,
        url=url_booking,
        ano=ano_referencia,
        criado_em=datetime.utcnow(),
        registros=registros,
    )
    path_bruto = get_market_bruto_path(id_projeto)
    # Calendário soberano: salvar sempre que o calendário foi gerado (permite curadoria manual)
    calendario_gerado = len(registros) > 0
    if calendario_gerado:
        path_bruto.parent.mkdir(parents=True, exist_ok=True)
        with open(path_bruto, "w", encoding="utf-8") as f:
            json.dump(market.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        logger.info(
            "Market bruto salvo: {} ({} registros; possui válidos: {}; ano_referencia: {})",
            path_bruto,
            len(registros),
            tem_valido,
            ano_referencia,
        )
    else:
        logger.warning(
            "Calendário soberano não gerou registros; mantendo arquivo anterior: {}",
            path_bruto,
        )
    return market
