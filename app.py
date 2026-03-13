# Entry point Flask
import json
import sys
from datetime import date, datetime

from flask import Flask, jsonify, render_template, request
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

logger.remove()
logger.add(sys.stderr, level="INFO")

from core.config import definir_periodos_sazonais
from core.financeiro.modelos import DadosFinanceiros
from core.projetos import (
    PROJECTS_DIR,
    ArquivoProjetoNaoEncontrado,
    Projeto,
    carregar_projeto,
    gerar_id_projeto,
    listar_projetos,
    salvar_projeto,
)
from core.analise.engenharia_reversa import (
    gerar_relatorio_engenharia_reversa,
    gerar_relatorio_engenharia_reversa_registros,
)
from core.scraper.modelos import DadosMercado, MarketBruto, MarketCurado, MarketCuradoRegistro
from core.scraper.scrapers import coletar_dados_mercado, coletar_dados_mercado_expandido

app = Flask(__name__)


class CriarProjetoBody(BaseModel):
    """Payload para POST /projeto."""

    nome: str = Field(min_length=1)
    url_booking: str = ""
    numero_quartos: int = Field(ge=1)
    faturamento_anual: float = Field(ge=0)
    ano_referencia: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)


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
    while (PROJECTS_DIR / f"{id_projeto}.json").exists():
        id_projeto = f"{id_base}-{n}"
        n += 1

    projeto = Projeto(
        id=id_projeto,
        nome=payload.nome,
        url_booking=payload.url_booking,
        numero_quartos=payload.numero_quartos,
        faturamento_anual=payload.faturamento_anual,
        ano_referencia=payload.ano_referencia,
        financeiro=DadosFinanceiros(),
        dados_mercado=None,
    )
    salvar_projeto(projeto)
    logger.info("Projeto criado via POST: {}", id_projeto)
    return jsonify({
        "success": True,
        "message": "Projeto criado.",
        "data": {"id": projeto.id},
    }), 201


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
        registros.append({"valor_efetivo": valor_efetivo, "checkin": r.checkin})
    return registros


def _carregar_registros_dashboard(id_projeto: str) -> list | dict:
    """Carrega market_bruto e mescla com market_curado por check-in; retorna dict com registros e grupos_mes ou lista vazia."""
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
        """Converte yyyy-mm-dd para dd/mm/yyyy."""
        if not iso_date or len(iso_date) < 10:
            return iso_date or "—"
        parts = iso_date[:10].split("-")
        if len(parts) != 3:
            return iso_date
        return f"{parts[2]}/{parts[1]}/{parts[0]}"

    registros = []
    for r in bruto.registros:
        tem_curado = r.checkin in curado_por_checkin
        preco_curado = curado_por_checkin[r.checkin].get("preco_curado") if tem_curado else None
        status = "Editado (Manual)" if tem_curado else "Original (Booking)"
        partes = (r.mes_ano.split("-") + ["", ""])[:2]
        ano, mes = partes[0], partes[1]  # mes_ano vem como "yyyy-mm" (ex: 2026-03)
        mes_ano_label = f"{MESES_PT.get(mes, mes)}/{ano}" if mes and ano else r.mes_ano
        row = {
            "checkin": r.checkin,
            "checkout": r.checkout,
            "checkin_br": _data_br(r.checkin),
            "checkout_br": _data_br(r.checkout),
            "mes_ano": r.mes_ano,
            "mes_ano_label": mes_ano_label,
            "tipo_dia": r.tipo_dia,
            "preco_booking": r.preco_booking,
            "preco_direto": r.preco_direto,
            "preco_curado": preco_curado,
            "status": status,
            "nome_quarto": r.nome_quarto or "",
            "tipo_tarifa": r.tipo_tarifa or "",
            "noites": r.noites,
            "preco_booking_fmt": _moeda_br(r.preco_booking),
            "preco_direto_fmt": _moeda_br(r.preco_direto),
            "preco_curado_fmt": _moeda_br(preco_curado) if preco_curado is not None else None,
        }
        registros.append(row)
    # Agrupar por mês para exibição (mantém ordem por mes_ano e checkin)
    from itertools import groupby
    registros_ordenados = sorted(registros, key=lambda x: (x["mes_ano"], x["checkin"]))
    grupos_mes = []
    for mes_ano, it in groupby(registros_ordenados, key=lambda x: x["mes_ano"]):
        lista = list(it)
        grupos_mes.append({"mes_ano_label": lista[0]["mes_ano_label"], "mes_ano": mes_ano, "registros": lista})
    logger.info("Dashboard carregou {} registros para o projeto {}", len(registros), id_projeto)
    return {"registros": registros, "grupos_mes": grupos_mes}


@app.get("/projeto/<id>/dashboard")
def dashboard(id: str):
    """Renderiza dashboard de curadoria (bruto + curado mesclados)."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    dados = _carregar_registros_dashboard(id)
    if isinstance(dados, list):
        dados = {"registros": dados, "grupos_mes": []}
    return render_template(
        "dashboard.html",
        projeto=projeto.model_dump(mode="json"),
        grupos_mes=dados.get("grupos_mes", []),
        registros=dados.get("registros", []),
    )


@app.post("/api/projeto/<id>/curadoria")
def api_salvar_curadoria(id: str):
    """Recebe ajustes (preco_curado, status) e grava market_curado_<id>.json; R3."""
    try:
        projeto = carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        logger.warning("Curadoria: projeto não encontrado: {}", id)
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
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
    path_curado = PROJECTS_DIR / f"market_curado_{id}.json"
    path_curado.parent.mkdir(parents=True, exist_ok=True)
    with open(path_curado, "w", encoding="utf-8") as f:
        json.dump(market_curado.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    logger.info("Market curado salvo: {} ({} registros)", path_curado, len(curado_registros))
    data_response = {"registros_salvos": len(curado_registros)}
    regs_efetivo = _carregar_registros_com_valor_efetivo(id)
    if regs_efetivo:
        resultado_analise = gerar_relatorio_engenharia_reversa_registros(projeto, regs_efetivo)
        data_response["analise"] = resultado_analise.model_dump(mode="json")
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
        resultado = gerar_relatorio_engenharia_reversa_registros(projeto, registros)
        return jsonify({
            "success": True,
            "message": "Análise de engenharia reversa concluída (dados curado/bruto).",
            "data": resultado.model_dump(mode="json"),
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
