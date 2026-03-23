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
    resolve_periodo_por_checkin,
    definir_calendario_soberano_ano,
    definir_periodos_12meses,
    gerar_calendario_diario_projeto,
    obter_desconto_dinamico,
)
from core.projetos import (
    ArquivoProjetoNaoEncontrado,
    carregar_projeto,
    get_market_bruto_path,
    get_scraper_config_path,
)
from core.scraper.modelos import DadosMercado, DiariaPeriodo, MarketBruto, MarketBrutoRegistro
from core.scraper.parsing import detectar_tipo_tarifa, parsear_valor_preco

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
EVIDENCE_STABILITY_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "evidence_stability"
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


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_goto(
    page,
    url: str,
    timeout_ms: int,
    data_alvo: str,
    log_path: Path,
    on_restart=None,
) -> tuple[bool, str | None, bool]:
    """Goto resiliente com retry/backoff; reinicia sessão em erro de rede grave."""
    backoffs = [2000, 4000, 8000]
    restarted = False
    for tentativa in range(1, 4):
        err_code = None
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
            except Exception:
                pass
            _append_jsonl(log_path, {
                "timestamp": datetime.now().isoformat(),
                "data_alvo": data_alvo,
                "tentativa": tentativa,
                "resultado": "OK",
                "erro_code": None,
                "browser_restarted": restarted,
            })
            return True, None, restarted
        except Exception as e:
            msg = str(e)
            err_code = "ERR_INTERNET_DISCONNECTED" if "ERR_INTERNET_DISCONNECTED" in msg else "GOTO_ERROR"
            _append_jsonl(log_path, {
                "timestamp": datetime.now().isoformat(),
                "data_alvo": data_alvo,
                "tentativa": tentativa,
                "resultado": "FALHA",
                "erro_code": err_code,
                "browser_restarted": restarted,
                "erro_msg": msg[:300],
            })
            if (err_code == "ERR_INTERNET_DISCONNECTED" or tentativa >= 3) and on_restart is not None:
                try:
                    on_restart()
                    restarted = True
                    _append_jsonl(log_path, {
                        "timestamp": datetime.now().isoformat(),
                        "data_alvo": data_alvo,
                        "tentativa": tentativa,
                        "resultado": "RESTART",
                        "erro_code": err_code,
                        "browser_restarted": True,
                    })
                except Exception:
                    pass
            if tentativa < 3:
                page.wait_for_timeout(backoffs[tentativa - 1])
    return False, err_code, restarted


def _add_months(base: date, months: int) -> date:
    y = base.year + ((base.month - 1 + months) // 12)
    m = ((base.month - 1 + months) % 12) + 1
    return date(y, m, 1)


def _parse_data_flex(s: str) -> date | None:
    """Parse data em YYYY-MM-DD ou DD/MM/YYYY. Retorna None se inválido."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    parts = s.split("/")
    if len(parts) == 3:
        try:
            dia, mes, ano = int(parts[0]), int(parts[1]), int(parts[2])
            return date(ano, mes, dia)
        except (ValueError, TypeError):
            pass
    return None


def _periodos_dinamicos_do_config(cfg: dict | None, hoje: date | None = None) -> list[dict]:
    """Prioriza datas_especiais; fallback para próximos X meses sem datas fixas.
    Aceita checkin/inicio e checkout/fim em YYYY-MM-DD ou DD/MM/YYYY (padrão da interface).
    """
    cfg = cfg or {}
    hoje = hoje or date.today()
    noites_cfg = cfg.get("noites") or {}
    noites = max(1, int(noites_cfg.get("preferencial", 3)))
    especiais = cfg.get("datas_especiais") or cfg.get("periodos_especiais") or []
    periodos: list[dict] = []

    for idx, item in enumerate(especiais):
        if not isinstance(item, dict):
            continue
        checkin = (item.get("checkin") or item.get("inicio") or "").strip()
        if not checkin:
            continue
        d_in = _parse_data_flex(checkin)
        if d_in is None:
            continue
        checkout = (item.get("checkout") or item.get("fim") or "").strip()
        if checkout:
            d_out = _parse_data_flex(checkout)
            if d_out is None:
                d_out = d_in + timedelta(days=noites)
        else:
            d_out = d_in + timedelta(days=noites)
        noites_reais = max(1, (d_out - d_in).days)
        periodos.append(
            {
                "codigo": f"cfg_{idx+1:02d}",
                "checkin": d_in.isoformat(),
                "checkout": d_out.isoformat(),
                "noites": noites_reais,
                "nome_periodo": (item.get("nome") or item.get("periodo_nome") or "Data Especial").strip(),
            }
        )

    if periodos:
        return periodos

    parametros = cfg.get("parametros_tecnicos") or {}
    meses_frente = max(1, int(parametros.get("proximos_meses", 6)))
    dia_ref = int(parametros.get("dia_checkin_preferencial", 15))
    for i in range(meses_frente):
        primeiro_dia = _add_months(date(hoje.year, hoje.month, 1), i)
        dia = min(max(dia_ref, 1), 28)
        d_in = date(primeiro_dia.year, primeiro_dia.month, dia)
        d_out = d_in + timedelta(days=noites)
        periodos.append(
            {
                "codigo": f"rolling_{d_in.strftime('%Y%m')}",
                "checkin": d_in.isoformat(),
                "checkout": d_out.isoformat(),
                "noites": noites,
                "nome_periodo": f"Próximos meses {d_in.strftime('%m/%Y')}",
            }
        )
    return periodos


def _log_scraper_config_trace(id_projeto: str, cfg_path: Path, cfg: dict) -> None:
    periodos_especiais = cfg.get("datas_especiais") or cfg.get("periodos_especiais") or []
    logger.info("Scraper config lido de: {} (exists={})", cfg_path, cfg_path.exists())
    logger.info("Períodos especiais carregados ({}): {}", len(periodos_especiais), periodos_especiais)
    _append_jsonl(
        EVIDENCE_STABILITY_DIR / "SCRAPER_CONFIG_TRACE.jsonl",
        {
            "timestamp": datetime.now().isoformat(),
            "id_projeto": id_projeto,
            "scraper_config_path": str(cfg_path),
            "scraper_config_exists": cfg_path.exists(),
            "periodos_especiais_count": len(periodos_especiais),
            "periodos_especiais": periodos_especiais,
        },
    )


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


# ---------- Calendário inferior (seção Disponibilidade) - seletores V3 ----------
SECOES_DISPONIBILIDADE = [
    "div:has(h2:has-text('Disponibilidade'))",
    "div:has(h3:has-text('Disponibilidade'))",
    "section:has(h2:has-text('Disponibilidade'))",
    "section:has(h3:has-text('Disponibilidade'))",
]
CANDIDATOS_BOTAO_DATA = [
    'button:has-text("Data")',
    '[data-testid*="date"]',
    '.bui-calendar__control',
    'a:has-text("Data de check-in")',
    'span:has-text("Data de check-in")',
    '[data-testid="date-display-field-start"]',
    '[data-testid="date-display-field-end"]',
]
SELETOR_CELULAS_DATA = "[data-date]"
BOTOES_PROXIMO_MES = [
    '[data-testid="datepicker-next-month-button"]',
    '[aria-label*="próximo"]',
    '[aria-label*="next"]',
    'button:has-text("Próximo")',
    '[data-bui-ref="calendar-next"]',
]
TIMEOUT_ABERTURA_CALENDARIO = 10000


def _abrir_calendario_inferior(page, timeout: int = TIMEOUT_ABERTURA_CALENDARIO) -> bool:
    """Localiza seção Disponibilidade, scroll/hover/clique no campo de data. Retorna True se [data-date] aparecer."""
    secao_scope = None
    for sel in SECOES_DISPONIBILIDADE:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                secao_scope = loc
                break
        except Exception:
            continue
    if not secao_scope or secao_scope.count() == 0:
        return False
    try:
        secao_scope.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    try:
        secao_scope.hover(timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    for sel in CANDIDATOS_BOTAO_DATA:
        try:
            el = secao_scope.locator(sel).first
            if el.count() == 0 or not el.is_visible():
                continue
            el.hover(timeout=3000)
            page.wait_for_timeout(500)
            el.click(timeout=5000)
            page.wait_for_timeout(1500)
            page.wait_for_selector(SELETOR_CELULAS_DATA, timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _navegar_calendario_para_mes(page, ano_mes: str, max_clicks: int = 12) -> bool:
    """Clica em 'Próximo mês' até o mês visível ser ano_mes. Retorna True se alcançou."""
    for _ in range(max_clicks):
        try:
            loc = page.locator(SELETOR_CELULAS_DATA)
            n = loc.count()
            for i in range(min(n, 50)):
                data_date = loc.nth(i).get_attribute("data-date")
                if data_date and data_date.startswith(ano_mes):
                    return True
            for sel in BOTOES_PROXIMO_MES:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=3000)
                        page.wait_for_timeout(800)
                        break
                except Exception:
                    continue
        except Exception:
            pass
    return False


def _extrair_mapa_mes_visivel(page, ano_mes: str) -> dict[str, str]:
    """Extrai mapa data -> DISPONIVEL|INDISPONIVEL para células do mês ano_mes (YYYY-MM)."""
    resultado: dict[str, str] = {}
    try:
        loc = page.locator(SELETOR_CELULAS_DATA)
        n = loc.count()
        for i in range(n):
            cel = loc.nth(i)
            data_date = cel.get_attribute("data-date")
            if not data_date or not data_date.startswith(ano_mes):
                continue
            aria_disabled = cel.get_attribute("aria-disabled")
            status = "INDISPONIVEL" if aria_disabled == "true" else "DISPONIVEL"
            resultado[data_date] = status
    except Exception:
        pass
    return resultado


class BookingScraper:
    """Scraper do Booking com fase de reconhecimento (calendário inferior) para pular datas indisponíveis."""

    def __init__(self, url_booking: str, id_projeto: str):
        self.url_booking = url_booking
        self.id_projeto = id_projeto
        self.mapa_projeto: dict[str, str] = {}
        self._calendario_aberto = False

    def _mapear_disponibilidade_mes(self, page, ano_mes: str) -> dict[str, str]:
        """Abre o calendário inferior (uma vez), navega até ano_mes e extrai status por data. Retorna {} em falha."""
        if not self._calendario_aberto:
            if not _abrir_calendario_inferior(page, timeout=TIMEOUT_ABERTURA_CALENDARIO):
                logger.warning(
                    "Calendário inferior não abriu em %s s; seguindo no modo tradicional.",
                    TIMEOUT_ABERTURA_CALENDARIO // 1000,
                )
                return {}
            self._calendario_aberto = True
        if not _navegar_calendario_para_mes(page, ano_mes):
            return {}
        return _extrair_mapa_mes_visivel(page, ano_mes)

    def run_expandido(self) -> MarketBruto:
        """Executa coleta expandida (calendário diário): mapeamento prévio + loop com skip de datas indisponíveis."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        headless = os.environ.get("HEADLESS", "false").lower() == "true"

        from core.config import asegurar_scraper_config
        asegurar_scraper_config(self.id_projeto)
        cfg = carregar_config_scraper(self.id_projeto) or {}
        cfg_path = get_scraper_config_path(self.id_projeto)
        _log_scraper_config_trace(self.id_projeto, cfg_path, cfg)
        n_periodos_config = len(cfg.get("periodos_especiais") or cfg.get("datas_especiais") or [])
        habilitar_reconhecimento_calendario = bool((cfg.get("parametros_tecnicos") or {}).get("usar_calendario_widget", False))
        logger.info(
            "Config scraper carregado ([{}] períodos especiais encontrados).",
            n_periodos_config,
        )

        try:
            projeto = carregar_projeto(self.id_projeto)
            ano_referencia = projeto.ano_referencia or date.today().year
        except ArquivoProjetoNaoEncontrado:
            ano_referencia = date.today().year
            logger.warning("Projeto não encontrado; usando ano atual {} como ano_referencia", ano_referencia)

        noites_cfg = cfg.get("noites") or {}
        noites_preferencial = int(noites_cfg.get("preferencial", 2))
        max_tentativas = int(noites_cfg.get("max_tentativas", 4))
        noites_preferencial = max(1, noites_preferencial)
        max_tentativas = max(1, max_tentativas)

        calendario_completo = gerar_calendario_diario_projeto(
            self.id_projeto, ano_referencia, rolling=True
        )
        amostra = definir_calendario_soberano_ano(
            ano_referencia=ano_referencia,
            noites=noites_preferencial,
            id_projeto=self.id_projeto,
            rolling=True,
        )
        lista_normais = amostra["normais"]
        lista_especiais = amostra["especiais"]
        lista_final_coleta = lista_normais + lista_especiais
        total_normais = len(lista_normais)
        total_especiais = len(lista_especiais)
        total_coleta = len(lista_final_coleta)

        logger.info(
            "Plano de Coleta: [{}] normais + [{}] especiais = [{}] check-ins.",
            total_normais,
            total_especiais,
            total_coleta,
        )
        logger.info(
            "Calendário diário: {} dias totais; noites pref={}, max_tent={}",
            len(calendario_completo),
            noites_preferencial,
            max_tentativas,
        )

        coletados: dict[str, MarketBrutoRegistro] = {}
        registros: list[MarketBrutoRegistro] = []
        timeout_ms = int(((cfg.get("parametros_tecnicos") or {}).get("timeout_ms")) or 30000)
        log_after = EVIDENCE_STABILITY_DIR / "LOG_AFTER.jsonl"
        if log_after.exists():
            log_after.unlink()

        with sync_playwright() as p:
            browser = None
            context = None
            page = None

            def _start_session():
                nonlocal browser, context, page
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                    user_agent=USER_AGENT,
                )
                page = context.new_page()

            def _restart_session():
                nonlocal browser, context, page
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    if browser:
                        browser.close()
                except Exception:
                    pass
                _start_session()
                logger.warning("Sessão do navegador reiniciada por resiliência.")

            _start_session()

            # Fase de reconhecimento visual de calendário desabilitada por padrão.
            # Mantemos somente scraping funcional por URL parametrizada/tabela.
            if habilitar_reconhecimento_calendario:
                try:
                    _safe_goto(
                        page=page,
                        url=self.url_booking,
                        timeout_ms=timeout_ms,
                        data_alvo="bootstrap_reconhecimento",
                        log_path=log_after,
                        on_restart=_restart_session,
                    )
                except Exception:
                    page.wait_for_timeout(5000)
                _aceitar_cookies(page)
                page.wait_for_timeout(2000)
                meses_distintos = sorted({p.get("mes_ano") for p in lista_final_coleta})
                for ano_mes in meses_distintos:
                    m = self._mapear_disponibilidade_mes(page, ano_mes)
                    self.mapa_projeto.update(m)
                disp = sum(1 for v in self.mapa_projeto.values() if v == "DISPONIVEL")
                bloc = sum(1 for v in self.mapa_projeto.values() if v == "INDISPONIVEL")
                logger.info(
                    "Mapeamento concluído: %s dias disponíveis, %s bloqueados.",
                    disp,
                    bloc,
                )
            else:
                logger.info("Reconhecimento por widget de calendário: DESATIVADO (modo estável por URL/tabela).")

            for i, periodo in enumerate(lista_final_coleta):
                if i == 0:
                    logger.info(
                        "Iniciando FASE 1: Datas Normais ([{}] itens)...",
                        total_normais,
                    )
                elif i == total_normais:
                    logger.info(
                        "Iniciando FASE 2: Datas Especiais ([{}] itens)...",
                        total_especiais,
                    )

                checkin_str = periodo["checkin"]
                mes_ano = periodo["mes_ano"]
                tipo_dia = periodo["tipo_dia"]
                categoria_dia = periodo.get("categoria_dia", "normal")
                periodo_nome = (periodo.get("periodo_nome") or "").strip()
                periodo_match = resolve_periodo_por_checkin(self.id_projeto, checkin_str)
                if periodo_match:
                    periodo_id_meta = periodo_match.get("periodo_id")
                    periodo_nome_meta = periodo_match.get("nome")
                    periodo_source_meta = "config"
                elif categoria_dia == "especial":
                    periodo_id_meta = None
                    periodo_nome_meta = periodo_nome or None
                    periodo_source_meta = "fallback"
                else:
                    periodo_id_meta = None
                    periodo_nome_meta = None
                    periodo_source_meta = "none"
                if periodo_nome:
                    tipo_label = f"ESPECIAL - {periodo_nome}"
                else:
                    tipo_label = "NORMAL"

                if self.mapa_projeto.get(checkin_str) == "INDISPONIVEL":
                    logger.info(
                        "[SKIP] Data %s marcada como indisponível no calendário inferior.",
                        checkin_str,
                    )
                    checkin_date = date.fromisoformat(checkin_str)
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
                        meta={
                            "periodo_id": periodo_id_meta,
                            "periodo_nome": periodo_nome_meta,
                            "periodo_source": periodo_source_meta,
                        },
                    )
                    continue

                noites_seq = _sequencia_noites_tentativas(noites_preferencial, max_tentativas)
                checkin_date = date.fromisoformat(checkin_str)
                sucesso = False
                for noites_reais in noites_seq:
                    checkout_date = checkin_date + timedelta(days=noites_reais)
                    checkout_str = checkout_date.strftime("%Y-%m-%d")
                    try:
                        logger.info(
                            ">>> [{}/{}] {} ({} noites) [TIPO: {}]",
                            i + 1,
                            total_coleta,
                            checkin_str,
                            noites_reais,
                            tipo_label,
                        )
                        url = _url_com_datas(self.url_booking, checkin_str, checkout_str)
                        ok_goto, err_code, restarted = _safe_goto(
                            page=page,
                            url=url,
                            timeout_ms=timeout_ms,
                            data_alvo=checkin_str,
                            log_path=log_after,
                            on_restart=_restart_session,
                        )
                        if restarted and context:
                            page = context.new_page()
                        if not ok_goto:
                            raise ValueError(f"Falha de navegação: {err_code}")
                        _aceitar_cookies(page)
                        page.wait_for_timeout(2000)
                        quartos = _extrair_quartos_pagina(page)
                        if not quartos:
                            raise ValueError("Nenhum preço")
                        menor = min(quartos, key=lambda x: x["total"])
                        total = menor["total"]
                        preco_booking = round(total / noites_reais, 2)
                        desconto = obter_desconto_dinamico(cfg, mes_ano)
                        preco_direto = round(preco_booking * (1 - desconto), 2)
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
                            meta={
                                "periodo_id": periodo_id_meta,
                                "periodo_nome": periodo_nome_meta,
                                "periodo_source": periodo_source_meta,
                            },
                        )
                        sucesso = True
                        break
                    except Exception as e:
                        logger.warning("Tentativa {} noites para {}: {}", noites_reais, checkin_str, e)
                        continue
                if not sucesso:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path_scr = ARTIFACTS_DIR / f"falha_{self.id_projeto}_{checkin_str}_{ts}.png"
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
                        meta={
                            "periodo_id": periodo_id_meta,
                            "periodo_nome": periodo_nome_meta,
                            "periodo_source": periodo_source_meta,
                        },
                    )

            if context:
                context.close()
            if browser:
                browser.close()

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
                        meta={
                            "periodo_id": None,
                            "periodo_nome": None,
                            "periodo_source": "none",
                        },
                    )
                )

        tem_valido = any(
            (r.preco_booking is not None and r.preco_booking > 0)
            or (r.preco_direto is not None and r.preco_direto > 0)
            for r in registros
        )
        market = MarketBruto(
            id_projeto=self.id_projeto,
            url=self.url_booking,
            ano=ano_referencia,
            criado_em=datetime.utcnow(),
            registros=registros,
        )
        path_bruto = get_market_bruto_path(self.id_projeto)
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


def coletar_dados_mercado(url_booking: str, ano: int, id_projeto: str) -> DadosMercado:
    """Coleta diárias do Booking por período sazonal; retorna DadosMercado com períodos válidos."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "false").lower() == "true"
    cfg_path = get_scraper_config_path(id_projeto)
    cfg = carregar_config_scraper(id_projeto) or {}
    periodos = _periodos_dinamicos_do_config(cfg, hoje=date.today())
    _log_scraper_config_trace(id_projeto, cfg_path, cfg)
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
                cfg = carregar_config_scraper(id_projeto) or {}
                desconto = obter_desconto_dinamico(cfg, checkin[:7])
                diaria_direta = round(diaria_booking * (1 - desconto), 2)
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
    Usa BookingScraper com fase de reconhecimento (calendário inferior) para pular datas indisponíveis."""
    return BookingScraper(url_booking, id_projeto).run_expandido()
