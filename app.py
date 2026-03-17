# Entry point Flask
import json
import os
import sys
from datetime import date, datetime

from flask import Flask, jsonify, render_template, request
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

logger.remove()
logger.add(sys.stderr, level="INFO")

from core.config import definir_calendario_soberano_ano, definir_periodos_sazonais
from core.financeiro.modelos import DadosFinanceiros, Infraestrutura
from core.projetos import (
    PROJECTS_DIR,
    ArquivoProjetoNaoEncontrado,
    Projeto,
    carregar_projeto,
    gerar_id_projeto,
    get_market_bruto_path,
    get_market_curado_path,
    get_projeto_json_path,
    get_simulacao_cenarios_path,
    get_simulacao_salva_path,
    listar_projetos,
    migrar_estrutura_legada,
    salvar_projeto,
)
from core.analise.engenharia_reversa import (
    gerar_analise_curado,
    gerar_relatorio_engenharia_reversa,
    gerar_relatorio_engenharia_reversa_registros,
)
from core.scraper.modelos import DadosMercado, MarketBruto, MarketCurado, MarketCuradoRegistro
from core.scraper.scrapers import coletar_dados_mercado, coletar_dados_mercado_expandido

app = Flask(__name__)


@app.before_request
def _startup_migracao():
    """Executa migração da estrutura legada uma vez no startup."""
    if not getattr(app, "_migracao_rodou", False):
        try:
            migrar_estrutura_legada()
            app._migracao_rodou = True
        except Exception as e:
            logger.warning("Migração legada (ignorando): {}", e)


def _format_moeda_br(val: float | int | None) -> str:
    """Formata número como moeda pt-BR (R$ 1.234,56)."""
    if val is None:
        return "—"
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    s = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


@app.template_filter("format_moeda")
def format_moeda_filter(val):
    """Filtro Jinja: formata número como R$ 1.234,56 (pt-BR)."""
    return _format_moeda_br(val)


class CriarProjetoBody(BaseModel):
    """Payload para POST /projeto."""

    nome: str = Field(min_length=1)
    url_booking: str = ""
    numero_quartos: int = Field(ge=1)
    faturamento_anual: float = Field(ge=0)
    ano_referencia: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)
    financeiro: DadosFinanceiros | None = None
    infraestrutura: Infraestrutura | None = None


class AtualizarProjetoBody(BaseModel):
    """Payload para PUT /api/projeto/<id> (campos opcionais)."""

    nome: str | None = None
    url_booking: str | None = None
    numero_quartos: int | None = None
    faturamento_anual: float | None = None
    ano_referencia: int | None = None
    financeiro: DadosFinanceiros | None = None
    infraestrutura: Infraestrutura | None = None


@app.get("/")
def index():
    """Serve a página principal (Single Page)."""
    return render_template("index.html")


@app.get("/api/projetos")
def api_listar_projetos():
    """Lista projetos em JSON (padrão R3)."""
    projetos = listar_projetos()
    dados = [p.model_dump(mode="json") for p in projetos]
    return jsonify({"success": True, "message": "Projetos listados.", "data": dados})


@app.get("/api/presets-infraestrutura")
def api_presets_infraestrutura():
    """Retorna presets calibrados para infraestrutura (query: tipo_unidade, matriz_energetica, matriz_hidrica, modelo_lavanderia, numero_quartos)."""
    try:
        from core.benchmarks import obter_presets_infraestrutura
    except ImportError as e:
        logger.warning("benchmarks não disponível: {}", e)
        return jsonify({"success": False, "message": "Presets não disponíveis.", "data": None}), 500
    try:
        tipo_unidade = (request.args.get("tipo_unidade") or "").strip() or None
        matriz_energetica = (request.args.get("matriz_energetica") or "").strip() or None
        matriz_hidrica = (request.args.get("matriz_hidrica") or "").strip() or None
        modelo_lavanderia = (request.args.get("modelo_lavanderia") or "").strip() or None
        try:
            numero_quartos = int(request.args.get("numero_quartos", 10))
        except (TypeError, ValueError):
            numero_quartos = 10
        numero_quartos = max(1, min(1000, numero_quartos))
        data = obter_presets_infraestrutura(
            tipo_unidade=tipo_unidade,
            matriz_energetica=matriz_energetica,
            matriz_hidrica=matriz_hidrica,
            modelo_lavanderia=modelo_lavanderia,
            numero_quartos=numero_quartos,
        )
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.warning("Erro ao obter presets: {}", e)
        return jsonify({"success": False, "message": str(e), "data": None}), 400


@app.post("/projeto")
def criar_projeto():
    """Cria novo projeto; id único com sufixo numérico se slug já existir."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        payload = CriarProjetoBody.model_validate(body)
    except Exception as e:
        logger.warning("Validação POST /projeto falhou: {}", e)
        return jsonify({
            "success": False,
            "message": str(e),
            "data": None,
        }), 400

    id_base = gerar_id_projeto(payload.nome)
    id_projeto = id_base
    n = 1
    while get_projeto_json_path(id_projeto).exists() or (PROJECTS_DIR / f"{id_projeto}.json").exists():
        id_projeto = f"{id_base}-{n}"
        n += 1

    financeiro = payload.financeiro if payload.financeiro is not None else DadosFinanceiros()
    projeto = Projeto(
        id=id_projeto,
        nome=payload.nome,
        url_booking=payload.url_booking,
        numero_quartos=payload.numero_quartos,
        faturamento_anual=payload.faturamento_anual,
        ano_referencia=payload.ano_referencia,
        financeiro=financeiro,
        infraestrutura=payload.infraestrutura,
        dados_mercado=None,
    )
    salvar_projeto(projeto)
    logger.info("Projeto criado via POST: {}", id_projeto)
    return jsonify({
        "success": True,
        "message": "Projeto criado.",
        "data": {"id": projeto.id},
    }), 201


@app.put("/api/projeto/<id>")
def api_atualizar_projeto(id: str):
    """Atualiza projeto existente; aceita campos parciais (incl. financeiro completo)."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({
            "success": False,
            "message": "Projeto não encontrado",
            "data": None,
        }), 404
    try:
        body = request.get_json(force=True, silent=True) or {}
        payload = AtualizarProjetoBody.model_validate(body)
    except Exception as e:
        logger.warning("Validação PUT /api/projeto/<id> falhou: {}", e)
        return jsonify({
            "success": False,
            "message": str(e),
            "data": None,
        }), 400
    if payload.nome is not None:
        projeto.nome = payload.nome
    if payload.url_booking is not None:
        projeto.url_booking = payload.url_booking
    if payload.numero_quartos is not None:
        projeto.numero_quartos = payload.numero_quartos
    if payload.faturamento_anual is not None:
        projeto.faturamento_anual = payload.faturamento_anual
    if payload.ano_referencia is not None:
        projeto.ano_referencia = payload.ano_referencia
    if payload.financeiro is not None:
        projeto.financeiro = payload.financeiro
    if payload.infraestrutura is not None:
        projeto.infraestrutura = payload.infraestrutura
    salvar_projeto(projeto)
    logger.info("Projeto atualizado via PUT: {}", id)
    return jsonify({
        "success": True,
        "message": "Projeto atualizado.",
        "data": {"id": projeto.id},
    }), 200


@app.post("/api/projeto/<id>/coletar-mercado")
def api_coletar_mercado(id: str):
    """Dispara coleta de dados de mercado e salva em market_<id>.json."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({
            "success": False,
            "message": "Projeto não encontrado",
            "data": None,
        }), 404

    url_booking = projeto.url_booking or ""
    if not url_booking.strip():
        return jsonify({
            "success": False,
            "message": "Projeto sem URL do Booking",
            "data": None,
        }), 400

    ano = projeto.ano_referencia or date.today().year
    resultado = coletar_dados_mercado(url_booking, ano, id)
    total = len(definir_periodos_sazonais(ano))
    sucesso = len(resultado.diarias_por_periodo)
    falha = total - sucesso

    path_market = PROJECTS_DIR / f"market_{id}.json"
    path_market.parent.mkdir(parents=True, exist_ok=True)
    with open(path_market, "w", encoding="utf-8") as f:
        json.dump(resultado.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    resumo = []
    for cod, per in resultado.diarias_por_periodo.items():
        valor_br = f"R$ {per.diaria_booking:.2f}".replace(".", ",")
        resumo.append(f"{per.nome_periodo}: {valor_br} ({per.nome_quarto})")

    logger.info("Market salvo: {} ({} períodos)", path_market, sucesso)
    payload = resultado.model_dump(mode="json")
    payload["resumo"] = resumo
    return jsonify({
        "success": True,
        "message": f"Coleta de mercado concluída ({sucesso} períodos com sucesso, {falha} com falha).",
        "data": payload,
    })


@app.post("/api/projeto/<id>/coletar-mercado-expandido")
def api_coletar_mercado_expandido(id: str):
    """Coleta expandida 12 meses × 4 datas/mês; salva em market_bruto_<id>.json."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    url_booking = (projeto.url_booking or "").strip()
    if not url_booking:
        return jsonify({"success": False, "message": "Projeto sem URL do Booking", "data": None}), 400
    resultado = coletar_dados_mercado_expandido(url_booking, id)
    return jsonify({
        "success": True,
        "message": f"Coleta expandida concluída ({len(resultado.registros)} registros).",
        "data": resultado.model_dump(mode="json"),
    })


def _carregar_registros_com_valor_efetivo(id_projeto: str) -> list[dict] | None:
    """Carrega bruto + curado (se existir), retorna lista com valor_efetivo = preco_curado ou preco_direto."""
    path_bruto = get_market_bruto_path(id_projeto)
    if not path_bruto.exists() or not path_bruto.is_file():
        path_bruto = PROJECTS_DIR / f"market_bruto_{id_projeto}.json"
    if not path_bruto.exists() or not path_bruto.is_file():
        return None
    try:
        raw_bruto = path_bruto.read_text(encoding="utf-8")
        logger.info("Leitura market bruto: {}", path_bruto)
        bruto = MarketBruto.model_validate(json.loads(raw_bruto))
    except (json.JSONDecodeError, ValidationError, ValueError):
        return None
    curado_por_checkin: dict[str, float | None] = {}
    path_curado = get_market_curado_path(id_projeto)
    if not path_curado.exists():
        path_curado = PROJECTS_DIR / f"market_curado_{id_projeto}.json"
    if path_curado.exists() and path_curado.is_file():
        try:
            raw_c = path_curado.read_text(encoding="utf-8")
            logger.info("Leitura market curado: {}", path_curado)
            if raw_c.strip():
                curado = MarketCurado.model_validate(json.loads(raw_c))
                for r in curado.registros:
                    curado_por_checkin[r.checkin] = r.preco_curado
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass
    registros = []
    for r in bruto.registros:
        valor_efetivo = curado_por_checkin.get(r.checkin)
        if valor_efetivo is None:
            valor_efetivo = r.preco_direto
        categoria = getattr(r, "categoria_dia", "normal") or "normal"
        registros.append({
            "valor_efetivo": valor_efetivo,
            "checkin": r.checkin,
            "mes_ano": r.mes_ano,
            "tipo_dia": r.tipo_dia,
            "categoria_dia": categoria,
        })
    return registros


def _carregar_registros_dashboard(id_projeto: str) -> list | dict:
    """Carrega market_bruto e mescla com market_curado.
    Exibe todas as datas TENTADAS pelo scraper (amostra normais + especiais), com ou sem preço.
    Registros com preco_booking null (falha) aparecem para ajuste manual. Datas especiais agregadas em uma linha por período."""
    path_bruto = get_market_bruto_path(id_projeto)
    if not path_bruto.exists():
        path_bruto = PROJECTS_DIR / f"market_bruto_{id_projeto}.json"
    logger.info("Tentando carregar dashboard para ID: {} no caminho: {}", id_projeto, path_bruto)
    if not path_bruto.exists() or not path_bruto.is_file():
        logger.warning("Arquivo não encontrado: {}", path_bruto)
        return []
    try:
        raw = path_bruto.read_text(encoding="utf-8")
        if not raw.strip():
            logger.warning("Arquivo vazio: {}", path_bruto)
            return []
        bruto = MarketBruto.model_validate(json.loads(raw))
    except FileNotFoundError:
        logger.warning("Arquivo não encontrado ao ler: {}", path_bruto)
        return []
    except json.JSONDecodeError as e:
        logger.error("JSON inválido em {}: {}", path_bruto, e)
        return []
    except (ValidationError, ValueError) as e:
        logger.error("Schema inesperado em {}: {}", path_bruto, e)
        return []
    curado_por_checkin: dict[str, dict] = {}
    path_curado = get_market_curado_path(id_projeto)
    if not path_curado.exists():
        path_curado = PROJECTS_DIR / f"market_curado_{id_projeto}.json"
    if path_curado.exists() and path_curado.is_file():
        try:
            raw_c = path_curado.read_text(encoding="utf-8")
            if raw_c.strip():
                curado = MarketCurado.model_validate(json.loads(raw_c))
                for r in curado.registros:
                    curado_por_checkin[r.checkin] = {
                        "preco_curado": r.preco_curado,
                        "status": r.status,
                    }
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("Market curado inválido, ignorando: {} - {}", path_curado, e)

    from datetime import date
    from core.config import obter_config_scraper_com_defaults, _periodos_especiais_de_config
    scraper_cfg = obter_config_scraper_com_defaults(id_projeto)
    descontos_cfg = scraper_cfg.get("descontos") or {}
    desconto_global = descontos_cfg.get("global")
    if desconto_global is None:
        desconto_global = 0.20
    descontos_por_mes = descontos_cfg.get("por_mes") or {}
    periodos_especiais = _periodos_especiais_de_config(id_projeto)

    MESES_PT = {
        "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
        "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
        "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
    }

    def _moeda_br(val: float) -> str:
        if val is None:
            return "—"
        s = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"

    def _data_br(iso_date: str) -> str:
        if not iso_date or len(iso_date) < 10:
            return iso_date or "—"
        parts = iso_date[:10].split("-")
        return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else iso_date

    def _periodo_para_checkin(checkin_str: str) -> str | None:
        try:
            d = date.fromisoformat(checkin_str[:10])
        except (ValueError, TypeError):
            return None
        for ini, fim, nome in periodos_especiais:
            if ini <= d <= fim:
                return nome
        return None

    ano_ref = getattr(bruto, "ano", None) or date.today().year
    noites_cfg = scraper_cfg.get("noites") or {}
    noites_pref = int(noites_cfg.get("preferencial", 2))
    amostra = definir_calendario_soberano_ano(
        ano_referencia=ano_ref,
        noites=max(1, noites_pref),
        id_projeto=id_projeto,
        rolling=True,
    )
    checkins_amostra = {p["checkin"] for p in amostra["normais"] + amostra["especiais"]}
    coletados = [r for r in bruto.registros if r.checkin in checkins_amostra]

    registros_normais: list[dict] = []
    registros_especiais_raw: list[dict] = []
    for r in coletados:
        tem_curado = r.checkin in curado_por_checkin
        preco_curado = curado_por_checkin[r.checkin].get("preco_curado") if tem_curado else None
        status = "Editado (Manual)" if tem_curado else ("Original (Booking)" if r.preco_booking is not None else "Faltando")
        partes = (r.mes_ano.split("-") + ["", ""])[:2]
        ano, mes = partes[0], partes[1]
        mes_ano_label = f"{MESES_PT.get(mes, mes)}/{ano}" if mes and ano else r.mes_ano
        categoria = getattr(r, "categoria_dia", "normal") or "normal"
        mes_key = mes if mes else ""
        desconto = descontos_por_mes.get(mes_key) if mes_key in descontos_por_mes else desconto_global
        if r.preco_booking is not None and desconto is not None:
            preco_direto_exibicao = round(float(r.preco_booking) * (1 - float(desconto)), 2)
        else:
            preco_direto_exibicao = r.preco_direto
        preco_falha = r.preco_booking is None or (r.preco_booking == 0)
        row = {
            "checkin": r.checkin,
            "checkout": r.checkout,
            "checkin_br": _data_br(r.checkin),
            "checkout_br": _data_br(r.checkout),
            "mes_ano": r.mes_ano,
            "mes_ano_label": mes_ano_label,
            "tipo_dia": r.tipo_dia,
            "categoria_dia": categoria,
            "preco_booking": r.preco_booking,
            "preco_direto": preco_direto_exibicao,
            "preco_curado": preco_curado,
            "status": status,
            "nome_quarto": r.nome_quarto or "",
            "tipo_tarifa": r.tipo_tarifa or "",
            "noites": r.noites,
            "preco_falha": preco_falha,
            "preco_booking_fmt": _moeda_br(r.preco_booking),
            "preco_direto_fmt": _moeda_br(preco_direto_exibicao) if preco_direto_exibicao is not None else None,
            "preco_curado_fmt": _moeda_br(preco_curado) if preco_curado is not None else None,
            "periodo_nome": _periodo_para_checkin(r.checkin) if categoria == "especial" else None,
        }
        if categoria == "especial":
            registros_especiais_raw.append(row)
        else:
            registros_normais.append(row)

    periodos_agrupados: dict[str, list[dict]] = {}
    for row in registros_especiais_raw:
        pn = row.get("periodo_nome") or "Outro (especial)"
        periodos_agrupados.setdefault(pn, []).append(row)

    registros_especiais: list[dict] = []
    for periodo_nome, grupo in sorted(periodos_agrupados.items(), key=lambda x: (x[1][0]["checkin"] if x[1] else "")):
        checkins = [r["checkin"] for r in grupo]
        checkin_ini = min(g["checkin"] for g in grupo)
        checkout_fim = max(g["checkout"] for g in grupo)
        precos_direto = [g["preco_direto"] for g in grupo if g["preco_direto"] is not None]
        precos_curado = [g["preco_curado"] for g in grupo if g["preco_curado"] is not None]
        adr_medio = sum(precos_direto) / len(precos_direto) if precos_direto else 0.0
        preco_curado_periodo = sum(precos_curado) / len(precos_curado) if precos_curado else None
        status = "Editado (Manual)" if all(g["status"] == "Editado (Manual)" for g in grupo) else ("Original (Booking)" if any(g.get("preco_booking") for g in grupo) else "Faltando")
        preco_falha_agregado = not any(g.get("preco_booking") for g in grupo)
        registros_especiais.append({
            "periodo_nome": periodo_nome,
            "checkin": checkin_ini,
            "checkout": checkout_fim,
            "checkin_br": _data_br(checkin_ini),
            "checkout_br": _data_br(checkout_fim),
            "checkins": checkins,
            "mes_ano_label": grupo[0]["mes_ano_label"] if grupo else "",
            "preco_direto": adr_medio if precos_direto else None,
            "preco_curado": preco_curado_periodo,
            "preco_direto_fmt": _moeda_br(adr_medio) if precos_direto else None,
            "preco_curado_fmt": _moeda_br(preco_curado_periodo) if preco_curado_periodo is not None else None,
            "preco_booking_fmt": _moeda_br(grupo[0]["preco_booking"]) if grupo and grupo[0].get("preco_booking") else None,
            "preco_falha": preco_falha_agregado,
            "status": status,
            "nome_quarto": grupo[0].get("nome_quarto", "") if grupo else "",
            "tipo_tarifa": grupo[0].get("tipo_tarifa", "") if grupo else "",
            "noites": grupo[0].get("noites", 0) if grupo else 0,
        })

    from itertools import groupby
    registros_normais_ordenados = sorted(registros_normais, key=lambda x: x["checkin"])
    grupos_normais = []
    grupos_especiais = []
    for mes_ano, it in groupby(registros_normais_ordenados, key=lambda x: x["mes_ano"]):
        lista = list(it)
        grupos_normais.append({"mes_ano_label": lista[0]["mes_ano_label"], "mes_ano": mes_ano, "registros": lista})
    if registros_especiais:
        grupos_especiais.append({"mes_ano_label": "Datas Especiais", "mes_ano": "especial", "registros": registros_especiais})

    meses_mes_ano = {r.mes_ano for r in coletados}
    meses_com_normais = {g["mes_ano"] for g in grupos_normais}
    meses_mes_ano = {r.mes_ano for r in coletados}
    meses_com_normais = {g["mes_ano"] for g in grupos_normais}
    meses_sem_normais = sorted(meses_mes_ano - meses_com_normais)
    meses_sem_normais_labels = []
    for mes_ano in meses_sem_normais:
        partes = (mes_ano.split("-") + ["", ""])[:2]
        ano, mes = partes[0], partes[1]
        label = f"{MESES_PT.get(mes, mes)}/{ano}" if mes and ano else mes_ano
        meses_sem_normais_labels.append(label)

    logger.info(
        "Dashboard carregou {} registros (normais: {}, especiais: {}) para o projeto {}",
        len(registros_normais) + len(registros_especiais),
        len(registros_normais),
        len(registros_especiais),
        id_projeto,
    )
    return {
        "registros_normais": registros_normais,
        "registros_especiais": registros_especiais,
        "grupos_normais": grupos_normais,
        "grupos_especiais": grupos_especiais,
        "meses_sem_normais": meses_sem_normais_labels,
    }


@app.get("/projeto/<id>/curadoria")
def curadoria_mercado(id: str):
    """Renderiza página de Curadoria de Mercado (bruto + curado mesclados)."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    dados = _carregar_registros_dashboard(id)
    if isinstance(dados, list):
        dados = {"registros": dados, "grupos_mes": [], "grupos_normais": [], "grupos_especiais": [], "meses_sem_normais": []}
    from core.config import obter_config_scraper_com_defaults
    descontos_config = obter_config_scraper_com_defaults(id).get("descontos") or {"global": 0.20, "por_mes": {}}
    dg = descontos_config.get("global")
    desconto_exibicao = f"{float(dg or 0.20) * 100:.1f}".replace(".", ",")
    return render_template(
        "dashboard.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="curadoria",
        grupos_mes=dados.get("grupos_mes", []),
        grupos_normais=dados.get("grupos_normais", []),
        grupos_especiais=dados.get("grupos_especiais", []),
        meses_sem_normais=dados.get("meses_sem_normais", []),
        registros=dados.get("registros", []),
        descontos_config=descontos_config,
        desconto_exibicao=desconto_exibicao,
    )


@app.post("/api/projeto/<id>/curadoria")
def api_salvar_curadoria(id: str):
    """Recebe ajustes (preco_curado, status) e grava market_curado_<id>.json; R3."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        logger.warning("Curadoria: projeto não encontrado: {}", id)
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    path_bruto = get_market_bruto_path(id)
    if not path_bruto.exists():
        path_bruto = PROJECTS_DIR / f"market_bruto_{id}.json"
    if not path_bruto.exists() or not path_bruto.is_file():
        return jsonify({
            "success": False,
            "message": "Dados brutos não encontrados. Execute a coleta expandida primeiro.",
            "data": None,
        }), 400
    try:
        logger.info("Leitura market bruto (curadoria): {}", path_bruto)
        bruto = MarketBruto.model_validate(json.loads(path_bruto.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        logger.warning("Curadoria: bruto inválido {}: {}", id, e)
        return jsonify({"success": False, "message": "Dados brutos inválidos.", "data": None}), 400
    body = request.get_json(force=True, silent=True) or {}
    registros_payload = body.get("registros") if isinstance(body, dict) else []
    if not isinstance(registros_payload, list):
        return jsonify({"success": False, "message": "Payload deve conter lista 'registros'.", "data": None}), 400
    bruto_por_checkin = {r.checkin: r for r in bruto.registros}
    curado_registros = []
    for item in registros_payload:
        if not isinstance(item, dict):
            continue
        checkin = item.get("checkin")
        if not checkin or checkin not in bruto_por_checkin:
            continue
        base = bruto_por_checkin[checkin]
        preco_curado = item.get("preco_curado")
        if preco_curado is not None and not isinstance(preco_curado, (int, float)):
            continue
        # Persistir APENAS registros com preco_curado numérico válido (linhas realmente editadas)
        if preco_curado is None:
            continue
        try:
            valor = float(preco_curado)
        except (TypeError, ValueError):
            continue
        status = item.get("status")
        if status is not None and not isinstance(status, str):
            status = "Editado (Manual)"
        curado_registros.append(MarketCuradoRegistro(
            checkin=base.checkin,
            checkout=base.checkout,
            mes_ano=base.mes_ano,
            tipo_dia=base.tipo_dia,
            preco_booking=base.preco_booking,
            preco_direto=base.preco_direto,
            preco_curado=valor,
            status=(status or "Editado (Manual)")[:80],
            nome_quarto=base.nome_quarto,
            tipo_tarifa=base.tipo_tarifa,
            noites=base.noites,
        ))
    market_curado = MarketCurado(
        id_projeto=id,
        url=bruto.url,
        ano=bruto.ano,
        criado_em=datetime.utcnow(),
        registros=curado_registros,
    )
    path_curado = get_market_curado_path(id)
    path_curado.parent.mkdir(parents=True, exist_ok=True)
    with open(path_curado, "w", encoding="utf-8") as f:
        json.dump(market_curado.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    logger.info("Market curado salvo: {} ({} registros)", path_curado, len(curado_registros))
    data_response = {"registros_salvos": len(curado_registros)}
    regs_efetivo = _carregar_registros_com_valor_efetivo(id)
    if regs_efetivo:
        analise = gerar_analise_curado(projeto, regs_efetivo)
        data_response["analise"] = analise.model_dump(mode="json")
    return jsonify({
        "success": True,
        "message": "Ajustes salvos.",
        "data": data_response,
    })


@app.post("/api/projeto/<id>/analise")
def api_analise_engenharia_reversa(id: str):
    """Gera análise: carrega curado se existir, senão bruto; senão market legado (sazonal)."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        logger.warning("Análise: projeto não encontrado: {}", id)
        return jsonify({
            "success": False,
            "message": "Projeto não encontrado",
            "data": None,
        }), 404

    registros = _carregar_registros_com_valor_efetivo(id)
    if registros:
        analise = gerar_analise_curado(projeto, registros)
        return jsonify({
            "success": True,
            "message": "Análise de engenharia reversa concluída (preços curados/direto).",
            "data": {"analise": analise.model_dump(mode="json")},
        })

    path_market = PROJECTS_DIR / f"market_{id}.json"
    if not path_market.exists() or not path_market.is_file():
        logger.warning("Análise: dados de mercado não encontrados para {}", id)
        return jsonify({
            "success": False,
            "message": "Dados de mercado não encontrados. Execute a coleta (ou coleta expandida) primeiro.",
            "data": None,
        }), 400

    try:
        raw = path_market.read_text(encoding="utf-8")
        if not raw.strip():
            raise ValueError("Arquivo vazio")
        dados_dict = json.loads(raw)
        dados_mercado = DadosMercado.model_validate(dados_dict)
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        logger.warning("Análise: market inválido ou vazio para {}: {}", id, e)
        return jsonify({
            "success": False,
            "message": "Dados de mercado não encontrados. Execute a coleta primeiro.",
            "data": None,
        }), 400

    resultado = gerar_relatorio_engenharia_reversa(projeto, dados_mercado)
    return jsonify({
        "success": True,
        "message": "Análise de engenharia reversa concluída.",
        "data": resultado.model_dump(mode="json"),
    })


@app.get("/projeto/<id_projeto>/viabilidade")
def estudo_viabilidade(id_projeto: str):
    """Renderiza a página de Estudo de Viabilidade (engenharia reversa) com análise curada."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    registros = _carregar_registros_com_valor_efetivo(id_projeto)
    if not registros:
        return render_template(
            "relatorio.html",
            projeto=projeto.model_dump(mode="json"),
            nav_active="relatorio",
            analise=None,
            sem_dados=True,
        )
    analise = gerar_analise_curado(projeto, registros)
    return render_template(
        "relatorio.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="relatorio",
        analise=analise.model_dump(mode="json"),
        sem_dados=False,
    )


@app.get("/projeto/<id_projeto>/viabilidade/resumo")
def estudo_viabilidade_resumo(id_projeto: str):
    """Renderiza apenas o resumo executivo do Estudo de Viabilidade (sem abas visuais)."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    registros = _carregar_registros_com_valor_efetivo(id_projeto)
    if not registros:
        return render_template(
            "relatorio.html",
            projeto=projeto.model_dump(mode="json"),
            nav_active="relatorio",
            analise=None,
            sem_dados=True,
        )
    analise = gerar_analise_curado(projeto, registros)
    return render_template(
        "relatorio.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="relatorio",
        analise=analise.model_dump(mode="json"),
        sem_dados=False,
    )


@app.get("/projeto/<id_projeto>/scraper/config")
def scraper_config_get(id_projeto: str):
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    from core.config import obter_config_scraper_com_defaults

    config = obter_config_scraper_com_defaults(id_projeto)
    return render_template(
        "scraper_config.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="config",
        config=config,
    )


@app.get("/api/projeto/<id_projeto>/scraper/config")
def api_scraper_config_get(id_projeto: str):
    """Retorna a config do scraper em JSON (para merge de descontos no dashboard)."""
    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    from core.config import obter_config_scraper_com_defaults
    config = obter_config_scraper_com_defaults(id_projeto)
    return jsonify({"success": True, "data": config})


@app.post("/projeto/<id_projeto>/scraper/config")
def scraper_config_post(id_projeto: str):
    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    from core.config import obter_config_scraper_com_defaults, salvar_config_scraper

    body = request.get_json(force=True, silent=True) or {}
    # Atualização apenas de descontos (merge com config existente)
    if set(body.keys()) <= {"descontos"} and "descontos" in body:
        descontos = body.get("descontos") or {}
        global_desc = descontos.get("global")
        if global_desc is not None:
            try:
                val = float(global_desc)
                if val < 0 or val > 1:
                    return jsonify({"success": False, "message": "Desconto global deve estar entre 0 e 1."}), 400
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "Desconto global inválido."}), 400
        por_mes = descontos.get("por_mes") or {}
        for mes, v in list(por_mes.items()):
            try:
                val = float(v)
                if val < 0 or val > 1:
                    return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
                por_mes[mes] = val
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
        cfg = obter_config_scraper_com_defaults(id_projeto)
        cfg["descontos"] = {"global": descontos.get("global", cfg.get("descontos", {}).get("global", 0.20)), "por_mes": por_mes}
        salvar_config_scraper(id_projeto, cfg)
        return jsonify({"success": True, "message": "Descontos salvos."})

    # Validar datas dos períodos especiais
    from datetime import datetime as dt

    periodos = body.get("periodos_especiais", [])
    for p in periodos:
        try:
            inicio = dt.strptime(p["inicio"], "%d/%m/%Y")
            fim = dt.strptime(p["fim"], "%d/%m/%Y")
            if inicio > fim:
                return jsonify({"success": False, "message": f"Data início maior que fim em: {p.get('nome', '')}"}), 400
        except (KeyError, ValueError) as e:
            return jsonify({"success": False, "message": f"Data inválida: {e}"}), 400
    # Validar descontos (se existirem)
    descontos = body.get("descontos") or {}
    global_desc = descontos.get("global")
    if global_desc is not None:
        try:
            val = float(global_desc)
            if val < 0 or val > 1:
                return jsonify({"success": False, "message": "Desconto global deve estar entre 0 e 1."}), 400
            descontos["global"] = val
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Desconto global inválido."}), 400
    por_mes = descontos.get("por_mes") or {}
    for mes, v in list(por_mes.items()):
        try:
            val = float(v)
            if val < 0 or val > 1:
                return jsonify({"success": False, "message": f"Desconto inválido para mês {mes} (deve estar entre 0 e 1)."}), 400
            por_mes[mes] = val
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
    descontos["por_mes"] = por_mes
    body["descontos"] = descontos

    salvar_config_scraper(id_projeto, body)
    return jsonify({"success": True, "message": "Configurações salvas."})


@app.get("/api/projeto/<id_projeto>/scraper/preview")
def scraper_preview(id_projeto: str):
    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    from core.config import definir_periodos_12meses

    periodos = definir_periodos_12meses(noites=2, id_projeto=id_projeto)
    normais: list[dict] = []
    especiais: list[dict] = []
    for p in periodos:
        # p pode ser dict ou objeto simples; normalizamos via getattr/get
        item = {
            "checkin": getattr(p, "checkin", None) or (p.get("checkin", "") if isinstance(p, dict) else ""),
            "checkout": getattr(p, "checkout", None) or (p.get("checkout", "") if isinstance(p, dict) else ""),
            "mes_ano": getattr(p, "mes_ano", None) or (p.get("mes_ano", "") if isinstance(p, dict) else ""),
            "tipo_dia": getattr(p, "tipo_dia", None) or (p.get("tipo_dia", "") if isinstance(p, dict) else ""),
            "categoria_dia": getattr(p, "categoria_dia", None) or (p.get("categoria_dia", "normal") if isinstance(p, dict) else "normal"),
            "nome_evento": getattr(p, "nome_evento", None) or (p.get("nome_evento", "") if isinstance(p, dict) else ""),
        }
        if item["categoria_dia"] == "especial":
            especiais.append(item)
        else:
            normais.append(item)
    return jsonify({"success": True, "normais": normais, "especiais": especiais})


# --- Simulação Futura (Projeção) ---

def _carregar_dados_simulacao_salva(id_projeto: str) -> dict | None:
    """Carrega simulacao_salva.json se existir. Retorna None em caso de erro ou ausência."""
    path = get_simulacao_salva_path(id_projeto)
    if not path.exists() or not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


@app.get("/projeto/<id>/simulacao")
def simulacao_page(id: str):
    """Renderiza página de simulação de metas de ocupação e ADR."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    from core.analise.adr_por_mes import obter_adr_por_mes
    from core.analise.engenharia_reversa import _custo_fixo_mensal_total, _custo_variavel_por_noite

    adr_por_mes = obter_adr_por_mes(id)
    custo_fixo_mensal = _custo_fixo_mensal_total(projeto)
    custo_var_por_noite = _custo_variavel_por_noite(projeto)
    custos_base = {
        "custo_fixo_mensal": custo_fixo_mensal,
        "custo_var_por_noite": custo_var_por_noite,
    }
    dados_salvos = _carregar_dados_simulacao_salva(id)
    return render_template(
        "simulacao.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="simulacao",
        adr_por_mes=adr_por_mes,
        custos_base=custos_base,
        numero_quartos=projeto.numero_quartos or 1,
        dados_salvos=dados_salvos,
    )


@app.get("/api/projeto/<id>/simulacao/dados-base")
def api_simulacao_dados_base(id: str):
    """Retorna ADR por mês, custos fixos, custo_var_por_noite, numero_quartos."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    from core.analise.adr_por_mes import obter_adr_por_mes
    from core.analise.engenharia_reversa import _custo_fixo_mensal_total, _custo_variavel_por_noite

    adr_por_mes = obter_adr_por_mes(id)
    custo_fixo_mensal = _custo_fixo_mensal_total(projeto)
    custo_var_por_noite = _custo_variavel_por_noite(projeto)
    fin = projeto.financeiro
    financeiro = None
    media_pessoas_por_diaria = 2.0
    if fin:
        media_pessoas_por_diaria = float(getattr(fin, "media_pessoas_por_diaria", 2.0) or 2.0)
        financeiro = {
            "custos_fixos": fin.custos_fixos.model_dump() if hasattr(fin.custos_fixos, "model_dump") else {},
            "folha_pagamento_mensal": fin.folha_pagamento_mensal,
            "custos_variaveis": fin.custos_variaveis.model_dump() if hasattr(fin.custos_variaveis, "model_dump") else {},
            "media_pessoas_por_diaria": media_pessoas_por_diaria,
            "aliquota_impostos": fin.aliquota_impostos,
            "outros_impostos_taxas_percentual": fin.outros_impostos_taxas_percentual,
        }
    return jsonify({
        "success": True,
        "data": {
            "adr_por_mes": adr_por_mes,
            "custo_fixo_mensal": custo_fixo_mensal,
            "custo_var_por_noite": custo_var_por_noite,
            "media_pessoas_por_diaria": media_pessoas_por_diaria,
            "numero_quartos": projeto.numero_quartos or 1,
            "ano_referencia": projeto.ano_referencia or 2025,
            "financeiro": financeiro,
        },
    })


@app.post("/api/projeto/<id>/simulacao/salvar")
def api_simulacao_salvar(id: str):
    """Salva metas_mensais e investimento_inicial em simulacao_salva.json."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    body = request.get_json(force=True, silent=True) or {}
    metas_mensais = body.get("metas_mensais") or {}
    investimento_inicial = float(body.get("investimento_inicial") or 0)
    path = get_simulacao_salva_path(id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metas_mensais": metas_mensais,
        "investimento_inicial": investimento_inicial,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return jsonify({"success": False, "message": str(e)}), 500
    return jsonify({"success": True, "message": "Cenário salvo com sucesso."})


@app.post("/api/projeto/<id>/simulacao/calcular")
def api_simulacao_calcular(id: str):
    """Calcula projeção com metas mensais e investimento inicial."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    from core.analise.simulacao import calcular_projecao

    body = request.get_json(force=True, silent=True) or {}
    metas_mensais = body.get("metas_mensais") or {}
    investimento_inicial = float(body.get("investimento_inicial") or 0)
    resultado = calcular_projecao(id, metas_mensais, investimento_inicial)
    if "erro" in resultado:
        return jsonify({
            "success": False,
            "message": resultado.get("erro", "Erro na simulação"),
            "data": None,
        }), 404
    return jsonify({"success": True, "data": resultado})


@app.post("/api/projeto/<id>/simulacao/curva-sensibilidade")
def api_simulacao_curva_sensibilidade(id: str):
    """Retorna pontos (ocupacao_pct, lucro_anual, lucro_medio_mensal) para gráfico de sensibilidade."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    from core.analise.simulacao import calcular_curva_sensibilidade

    body = request.get_json(force=True, silent=True) or {}
    investimento_inicial = float(body.get("investimento_inicial") or 0)
    metas_mensais = body.get("metas_mensais") or {}
    passo = float(body.get("passo_ocupacao") or 0.1)
    passo = max(0.05, min(0.25, passo))
    pontos = calcular_curva_sensibilidade(id, investimento_inicial, metas_mensais, passo_ocupacao=passo)
    return jsonify({"success": True, "data": {"pontos": pontos}})


def _carregar_cenarios(id_projeto: str) -> list[dict]:
    """Carrega lista de cenários de simulacao_cenarios.json. Retorna lista vazia se não existir."""
    path = get_simulacao_cenarios_path(id_projeto)
    if not path.exists() or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("cenarios") if isinstance(data.get("cenarios"), list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _salvar_cenarios(id_projeto: str, cenarios: list[dict]) -> None:
    """Persiste lista de cenários em simulacao_cenarios.json com escrita atômica."""
    path = get_simulacao_cenarios_path(id_projeto)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    content = json.dumps({"cenarios": cenarios}, ensure_ascii=False, indent=2)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _migrar_simulacao_salva_para_cenarios(id_projeto: str) -> list[dict]:
    """Se simulacao_cenarios.json não existir mas simulacao_salva.json existir, cria cenário inicial."""
    path_cenarios = get_simulacao_cenarios_path(id_projeto)
    if path_cenarios.exists():
        return _carregar_cenarios(id_projeto)
    path_salva = get_simulacao_salva_path(id_projeto)
    if not path_salva.exists() or not path_salva.is_file():
        return []
    try:
        dados = json.loads(path_salva.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    metas = dados.get("metas_mensais") or {}
    invest = float(dados.get("investimento_inicial") or 0)
    from core.analise.simulacao import calcular_projecao
    resultado = calcular_projecao(id_projeto, metas, invest)
    if "erro" in resultado:
        resultado = {"meses": [], "resumo": {}}
    import uuid
    from datetime import datetime
    cenario = {
        "id": str(uuid.uuid4())[:8],
        "nome": "Cenário atual",
        "criado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metas_mensais": metas,
        "investimento_inicial": invest,
        "resultado": resultado,
    }
    cenarios = [cenario]
    _salvar_cenarios(id_projeto, cenarios)
    return cenarios


@app.get("/api/projeto/<id>/simulacao/cenarios")
def api_simulacao_listar_cenarios(id: str):
    """Lista cenários salvos. Migra simulacao_salva.json para cenário único se necessário."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    lista = []
    for c in cenarios:
        resumo = (c.get("resultado") or {}).get("resumo") or {}
        lista.append({
            "id": c.get("id"),
            "nome": c.get("nome") or "Sem nome",
            "criado_em": c.get("criado_em"),
            "lucro_anual": resumo.get("lucro_anual"),
            "payback_meses": resumo.get("payback_meses"),
            "payback_status": resumo.get("payback_status"),
        })
    return jsonify({"success": True, "data": {"cenarios": lista}})


@app.post("/api/projeto/<id>/simulacao/cenarios")
def api_simulacao_criar_ou_atualizar_cenario(id: str):
    """Cria ou atualiza cenário. Se body.id for enviado e existir na lista: UPDATE. Senão: CREATE."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    body = request.get_json(force=True, silent=True) or {}
    cid = (body.get("id") or "").strip() or None
    from datetime import datetime
    import uuid
    metas_mensais = body.get("metas_mensais") or {}
    investimento_inicial = float(body.get("investimento_inicial") or 0)
    resultado = body.get("resultado")
    if not resultado or not isinstance(resultado, dict):
        from core.analise.simulacao import calcular_projecao
        resultado = calcular_projecao(id, metas_mensais, investimento_inicial)
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    idx = next((i for i, c in enumerate(cenarios) if c.get("id") == cid), None)
    if cid and idx is not None:
        cenario = cenarios[idx]
        cenario["nome"] = (body.get("nome") or "").strip() or cenario.get("nome") or "Sem nome"
        cenario["metas_mensais"] = metas_mensais
        cenario["investimento_inicial"] = investimento_inicial
        cenario["resultado"] = resultado
        _salvar_cenarios(id, cenarios)
        return jsonify({
            "success": True,
            "message": "Cenário atualizado.",
            "data": {"id": cenario["id"], "nome": cenario["nome"], "criado_em": cenario.get("criado_em")},
        })
    nome = (body.get("nome") or "").strip() or None
    if not nome:
        nome = "Sem nome " + datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    cenario = {
        "id": str(uuid.uuid4())[:8],
        "nome": nome,
        "criado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metas_mensais": metas_mensais,
        "investimento_inicial": investimento_inicial,
        "resultado": resultado,
    }
    cenarios.append(cenario)
    _salvar_cenarios(id, cenarios)
    return jsonify({
        "success": True,
        "message": "Cenário salvo.",
        "data": {"id": cenario["id"], "nome": cenario["nome"], "criado_em": cenario["criado_em"]},
    })


@app.get("/api/projeto/<id>/simulacao/cenarios/<cid>")
def api_simulacao_obter_cenario(id: str, cid: str):
    """Retorna um cenário salvo por id."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    for c in cenarios:
        if c.get("id") == cid:
            return jsonify({"success": True, "data": c})
    return jsonify({"success": False, "message": "Cenário não encontrado", "data": None}), 404


@app.delete("/api/projeto/<id>/simulacao/cenarios/<cid>")
def api_simulacao_deletar_cenario(id: str, cid: str):
    """Remove um cenário da lista."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    novo = [c for c in cenarios if c.get("id") != cid]
    if len(novo) == len(cenarios):
        return jsonify({"success": False, "message": "Cenário não encontrado"}), 404
    _salvar_cenarios(id, novo)
    return jsonify({"success": True, "message": "Cenário excluído."})
