# Entry point Flask
import json
import os
import sys
import unicodedata
from datetime import date, datetime
from typing import Any, List
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

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
    backup_scraper_config_before_action,
    carregar_projeto,
    create_project_scaffold,
    excluir_projeto_seguro,
    gerar_id_projeto,
    get_backups_dir,
    get_market_bruto_path,
    get_market_curado_path,
    get_projeto_json_path,
    get_scraper_config_path,
    get_cenarios_path,
    get_simulacao_cenarios_path,
    get_simulacao_salva_path,
    listar_projetos,
    migrar_estrutura_legada,
    read_project_json,
    salvar_projeto,
)
from core.analise.engenharia_reversa import (
    gerar_analise_curado,
    gerar_relatorio_engenharia_reversa,
    gerar_relatorio_engenharia_reversa_registros,
)
from core.backup import salvar_market_curado_com_backup
from core.analise.desconto import obter_desconto_para_curadoria
from core.analise.simulacao import (
    comparar_cenarios_projeto,
    gerar_contexto_completo_viabilidade,
    sugerir_arrendamento,
)
from core.scraper.modelos import DadosMercado, MarketBruto, MarketCurado, MarketCuradoRegistro
from core.scraper.scrapers import (
    EVIDENCE_STABILITY_DIR,
    coletar_dados_mercado,
    coletar_dados_mercado_expandido,
)

app = Flask(__name__)
IO_LOG_JSONL = app.root_path + "/scripts/evidence_stability/IO_ERRORS.jsonl"


class CenarioPayload(BaseModel):
    nome: str = Field(min_length=1)
    ocupacao_alvo: float = Field(ge=0, le=1)
    adr_projetado: float = Field(ge=0)
    lucro_estimado: float


def _simulacao_investimento_from_body(body: dict | None) -> dict[str, Any]:
    """Extrai overrides de investimento (compatível com investimento_inicial legado)."""
    body = body or {}
    inv_r = body.get("investimento_reforma")
    if inv_r is None and body.get("investimento_inicial") is not None:
        inv_r = body.get("investimento_inicial")
    arr_tot = body.get("arrendamento_total")
    prazo = body.get("prazo_contrato_meses")
    prazo_i = None if prazo is None else int(prazo)
    if prazo_i is not None:
        prazo_i = max(1, min(600, prazo_i))
    return {
        "investimento_reforma": None if inv_r is None else float(inv_r),
        "arrendamento_total": None if arr_tot is None else float(arr_tot),
        "prazo_contrato_meses": prazo_i,
    }


def _persistir_overrides_simulacao_no_projeto(id_projeto: str, body: dict | None) -> None:
    """Grava no projeto os parâmetros de contrato/reforma enviados pelo simulador (fonte única)."""
    ov = _simulacao_investimento_from_body(body)
    if all(ov[k] is None for k in ("arrendamento_total", "prazo_contrato_meses", "investimento_reforma")):
        return
    p = carregar_projeto(id_projeto)
    arr_f = float(ov["arrendamento_total"]) if ov["arrendamento_total"] is not None else float(p.arrendamento_total)
    pr_i = int(ov["prazo_contrato_meses"]) if ov["prazo_contrato_meses"] is not None else int(p.prazo_contrato_meses or 12)
    pr_i = max(1, min(600, pr_i))
    ref_f = float(ov["investimento_reforma"]) if ov["investimento_reforma"] is not None else float(p.investimento_reforma)
    if (
        round(float(p.arrendamento_total), 2) == round(arr_f, 2)
        and int(p.prazo_contrato_meses or 12) == pr_i
        and round(float(p.investimento_reforma), 2) == round(ref_f, 2)
    ):
        return
    p.arrendamento_total = arr_f
    p.prazo_contrato_meses = pr_i
    p.investimento_reforma = ref_f
    salvar_projeto(p)


def _simulacao_investimento_para_persistencia(id_projeto: str, body: dict | None) -> dict[str, Any]:
    """Valores concretos para salvar cenário (preenche com projeto quando omitidos no body)."""
    from core.projetos import carregar_projeto

    ov = _simulacao_investimento_from_body(body)
    p = carregar_projeto(id_projeto)
    ref = ov["investimento_reforma"]
    if ref is None:
        ref = float(p.investimento_reforma)
    arr = ov["arrendamento_total"]
    if arr is None:
        arr = float(p.arrendamento_total)
    prazo = ov["prazo_contrato_meses"]
    if prazo is None:
        prazo = int(p.prazo_contrato_meses or 12)
    return {
        "investimento_reforma": ref,
        "arrendamento_total": arr,
        "prazo_contrato_meses": prazo,
        "investimento_inicial": ref,
    }


def _log_io_error(evento: str, id_projeto: str, erro: str) -> None:
    try:
        from pathlib import Path
        path = Path(IO_LOG_JSONL)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "evento": evento,
            "id_projeto": id_projeto,
            "erro": str(erro)[:400],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _log_system_event(action: str, id_projeto: str, extra: dict | None = None) -> None:
    """Registra eventos de auditoria no SYSTEM_EVENTS.jsonl."""
    try:
        path = EVIDENCE_STABILITY_DIR / "SYSTEM_EVENTS.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "id_projeto": id_projeto,
            "time": datetime.now().isoformat(),
            "user": "cursor-job",
        }
        if extra:
            payload.update(extra)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


_correcao_curadoria_crud_event_logged = False


def _emit_correcao_curadoria_crud_event(id_projeto: str) -> None:
    """Registra uma vez por processo o evento de auditoria da correção Curadoria + CRUD."""
    global _correcao_curadoria_crud_event_logged
    if _correcao_curadoria_crud_event_logged:
        return
    _correcao_curadoria_crud_event_logged = True
    _log_system_event(
        "correcao_curadoria_crud_projetos_applied",
        id_projeto or "system",
        {"evento": "correcao_curadoria_crud_projetos_applied"},
    )


def _strict_periodos_ativo(id_projeto: str) -> bool:
    """Retorna estado de STRICT_PERIODOS (env) com override opcional por projeto."""
    env_val = os.environ.get("STRICT_PERIODOS", "false").strip().lower()
    strict_env = env_val in {"1", "true", "yes", "on"}
    path_projeto = get_projeto_json_path(id_projeto)
    if not path_projeto.exists():
        return strict_env
    try:
        raw = json.loads(path_projeto.read_text(encoding="utf-8"))
        if isinstance(raw.get("strict_periodos"), bool):
            return bool(raw.get("strict_periodos"))
        curadoria = raw.get("curadoria") or {}
        if isinstance(curadoria, dict) and isinstance(curadoria.get("strict_periodos"), bool):
            return bool(curadoria.get("strict_periodos"))
    except Exception:
        return strict_env
    return strict_env


def _backend_desconto_unificado_ativo() -> bool:
    """Flag backend para cálculo unificado de desconto (default true)."""
    env_val = os.environ.get("BACKEND_DESCONTO_UNIFICADO", "true").strip().lower()
    return env_val in {"1", "true", "yes", "on"}


def _frontend_desconto_unificado_ativo(id_projeto: str) -> bool:
    """Flag frontend para desconto unificado (default false), com override por projeto."""
    env_val = os.environ.get("FRONTEND_DESCONTO_UNIFICADO", "false").strip().lower()
    frontend_env = env_val in {"1", "true", "yes", "on"}
    path_projeto = get_projeto_json_path(id_projeto)
    if not path_projeto.exists():
        return frontend_env
    try:
        raw = json.loads(path_projeto.read_text(encoding="utf-8"))
        curadoria = raw.get("curadoria") or {}
        if isinstance(curadoria, dict) and isinstance(curadoria.get("frontend_desconto_unificado"), bool):
            return bool(curadoria.get("frontend_desconto_unificado"))
    except Exception:
        return frontend_env
    return frontend_env


def safe_decimal_from(v) -> Decimal | None:
    """Converte valor para Decimal de forma segura."""
    if v is None:
        return None
    try:
        return Decimal(str(v).replace(",", "."))
    except Exception:
        return None


def format_decimal_for_display(v: Decimal | None) -> float | None:
    """Converte Decimal em float para payload/template."""
    if v is None:
        return None
    return float(v)


def _quantize_decimal(v, places: int = 4) -> float:
    """Normaliza números para persistência estável em JSON."""
    quant = Decimal("1." + ("0" * places))
    return float(Decimal(str(v)).quantize(quant, rounding=ROUND_HALF_UP))


def _normalize_percent(v) -> float:
    n = float(v)
    # UX padrão do frontend: entrada 1 representa 1%
    if n >= 1:
        n = n / 100.0
    return _quantize_decimal(n, 4)


def _normalizar_financeiro_para_persistencia(financeiro: DadosFinanceiros) -> DadosFinanceiros:
    """Arredonda monetários (2) e percentuais (4) mantendo contrato atual."""
    payload = financeiro.model_dump(mode="python")
    cf = dict(payload.get("custos_fixos") or {})
    cf["aluguel"] = 0.0
    cv = payload.get("custos_variaveis") or {}

    def _incidencia_cv_para_str(x) -> str:
        if x is None:
            return "hospede_noite"
        if hasattr(x, "value"):
            return str(x.value)
        s = str(x).strip()
        if s.startswith("IncidenciaCustoVariavel."):
            return "hospede_noite"
        return s or "hospede_noite"

    def _normalizar_item_cv_payload(v) -> dict:
        if v is None:
            return {"valor": 0.0, "incidencia": "hospede_noite"}
        if isinstance(v, dict):
            valor = v.get("valor", 0)
            inc = _incidencia_cv_para_str(v.get("incidencia"))
            return {"valor": _quantize_decimal(valor, 2), "incidencia": inc}
        return {"valor": _quantize_decimal(v, 2), "incidencia": "hospede_noite"}

    keys_cv = ("cafe_manha", "amenities", "lavanderia", "outros")
    payload["custos_fixos"] = {k: _quantize_decimal(v, 2) for k, v in cf.items()}
    payload["custos_variaveis"] = {k: _normalizar_item_cv_payload(cv.get(k)) for k in keys_cv}
    payload["permanencia_media"] = _quantize_decimal(payload.get("permanencia_media", 2.0), 2)
    payload["folha_pagamento_mensal"] = _quantize_decimal(payload.get("folha_pagamento_mensal", 0), 2)
    payload["encargos_pct_padrao"] = _normalize_percent(payload.get("encargos_pct_padrao", 0))
    payload["beneficio_vale_transporte"] = _quantize_decimal(payload.get("beneficio_vale_transporte", 0), 2)
    payload["beneficio_vale_alimentacao"] = _quantize_decimal(payload.get("beneficio_vale_alimentacao", 0), 2)
    payload["media_pessoas_por_diaria"] = _quantize_decimal(payload.get("media_pessoas_por_diaria", 2), 2)
    payload["aliquota_impostos"] = _normalize_percent(payload.get("aliquota_impostos", 0))
    payload["percentual_contingencia"] = _normalize_percent(payload.get("percentual_contingencia", 0))
    payload["outros_impostos_taxas_percentual"] = _normalize_percent(payload.get("outros_impostos_taxas_percentual", 0))

    funcionarios = payload.get("funcionarios") or []
    if not funcionarios:
        # Mantém valor legado sem materializar funcionário sintético na persistência.
        # Isso evita recalcular/multiplicar folha a cada salvamento.
        payload["funcionarios"] = []
        return DadosFinanceiros.model_validate(payload)
    norm_funcs = []
    for f in funcionarios:
        raw_encargos = f.get("encargos_pct", f.get("encargos_percentual"))
        usar_padrao = f.get("usar_encargos_padrao")
        if usar_padrao is None:
            usar_padrao = raw_encargos in (None, "")
        encargos_norm = None
        if not bool(usar_padrao):
            encargos_norm = _normalize_percent(raw_encargos or 0)
        norm_funcs.append({
            "id": str(f.get("id") or ""),
            "cargo": str(f.get("cargo") or f.get("nome") or "Equipe"),
            "quantidade": int(f.get("quantidade", 1)),
            "salario_base": _quantize_decimal(f.get("salario_base", f.get("salario", 0)), 2),
            "encargos_pct": encargos_norm,
            "usar_encargos_padrao": bool(usar_padrao),
            "beneficios": _quantize_decimal(f.get("beneficios", 0), 2),
        })
    payload["funcionarios"] = norm_funcs
    # Compatibilidade de ciclo: mantém campo legado espelhado do cálculo atual.
    try:
        folha_total_calc = Decimal("0")
        for f in norm_funcs:
            salario = Decimal(str(f.get("salario_base", 0)))
            qtd = Decimal(int(f.get("quantidade", 1)))
            encargos_padrao = Decimal(str(payload.get("encargos_pct_padrao", 0)))
            if bool(f.get("usar_encargos_padrao", True)):
                encargos = encargos_padrao
            else:
                encargos = Decimal(str(f.get("encargos_pct") or 0))
            beneficios = Decimal(str(f.get("beneficios", 0)))
            beneficio_global = Decimal(
                str(payload.get("beneficio_vale_transporte", 0) + payload.get("beneficio_vale_alimentacao", 0))
            ) * qtd
            folha_total_calc += (salario * qtd) * (Decimal("1") + encargos) + beneficios + beneficio_global
        payload["folha_pagamento_mensal"] = _quantize_decimal(folha_total_calc, 2)
    except Exception:
        payload["folha_pagamento_mensal"] = _quantize_decimal(payload.get("folha_pagamento_mensal", 0), 2)
    return DadosFinanceiros.model_validate(payload)


def _normalizar_financeiro_payload_body(body: dict) -> dict:
    """Pré-normaliza payload cru para manter compatibilidade com percentuais 0-100."""
    if not isinstance(body, dict):
        return body
    financeiro = body.get("financeiro")
    if not isinstance(financeiro, dict):
        return body
    fin = dict(financeiro)
    for k in ("aliquota_impostos", "percentual_contingencia", "outros_impostos_taxas_percentual"):
        if k in fin and fin[k] is not None:
            fin[k] = _normalize_percent(fin[k])
    if "encargos_pct_padrao" in fin and fin["encargos_pct_padrao"] is not None:
        fin["encargos_pct_padrao"] = _normalize_percent(fin["encargos_pct_padrao"])
    for k in ("beneficio_vale_transporte", "beneficio_vale_alimentacao"):
        if k in fin and fin[k] is not None:
            fin[k] = _quantize_decimal(fin[k], 2)
    funcs = fin.get("funcionarios")
    if isinstance(funcs, list):
        norm_funcs = []
        for f in funcs:
            if not isinstance(f, dict):
                norm_funcs.append(f)
                continue
            novo = {**f}
            usar_padrao = novo.get("usar_encargos_padrao")
            if usar_padrao is None:
                usar_padrao = novo.get("encargos_pct") in (None, "")
            novo["usar_encargos_padrao"] = bool(usar_padrao)
            if not novo["usar_encargos_padrao"]:
                if novo.get("encargos_pct") is not None:
                    novo["encargos_pct"] = _normalize_percent(novo.get("encargos_pct"))
                elif novo.get("encargos_percentual") is not None:
                    novo["encargos_pct"] = _normalize_percent(novo.get("encargos_percentual"))
            else:
                novo["encargos_pct"] = None
            norm_funcs.append(novo)
        fin["funcionarios"] = norm_funcs
    elif float(fin.get("folha_pagamento_mensal") or 0) > 0:
        # Persistência legado: mantém funcionarios vazio para evitar recálculo indevido.
        fin["funcionarios"] = []
    return {**body, "financeiro": fin}


def _ensure_funcionarios_from_legacy(financeiro: dict | None) -> dict:
    """Garante shape RH granular para respostas sem alterar arquivo em disco."""
    fin = dict(financeiro or {})
    funcs = fin.get("funcionarios")
    if isinstance(funcs, list) and len(funcs) > 0:
        return fin
    folha = float(fin.get("folha_pagamento_mensal") or 0)
    if folha > 0:
        fin["funcionarios"] = [{
            "cargo": "Equipe (legacy)",
            "quantidade": 1,
            "salario_base": round(folha, 2),
            "encargos_pct": None,
            "usar_encargos_padrao": True,
            "beneficios": 0.0,
        }]
    else:
        fin["funcionarios"] = []
    return fin


def _calcular_preco_direto_por_data(id_projeto: str, mes_ano: str | None, preco_booking) -> float | None:
    """Calcula preço direto unitário usando a regra canônica de desconto."""
    bruto_dec = safe_decimal_from(preco_booking)
    if bruto_dec is None:
        return None
    desconto_dec = obter_desconto_para_curadoria(id_projeto, mes_ano)
    preco_direto_dec = (bruto_dec * (Decimal("1") - desconto_dec)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format_decimal_for_display(preco_direto_dec)


def _calcular_media_decimal(valores) -> float | None:
    """Calcula média numérica com Decimal para consistência de arredondamento."""
    if not valores:
        return None
    decs = [safe_decimal_from(v) for v in valores]
    decs = [d for d in decs if d is not None]
    if not decs:
        return None
    media = (sum(decs) / Decimal(len(decs))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format_decimal_for_display(media)


def _resolver_preco_exibicao_preferida(preco_direto_por_data, preco_direto_media_periodo) -> tuple[str, float | None]:
    """Define origem e valor exibido de preço direto no dashboard."""
    if preco_direto_por_data is not None:
        return "por_data", preco_direto_por_data
    if preco_direto_media_periodo is not None:
        return "media_periodo", preco_direto_media_periodo
    return "nao_disponivel", None


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
    arrendamento_total: float | None = Field(default=None, ge=0)
    prazo_contrato_meses: int | None = Field(default=None, ge=1, le=600)
    investimento_reforma: float | None = Field(default=None, ge=0)


class CriarPousadaBody(BaseModel):
    """Payload para POST /api/pousada."""

    id: str | None = None
    nome: str = Field(min_length=1)
    booking_url: str = ""
    cidade: str | None = None
    timezone: str | None = None
    executar_scrape_imediato: bool = False


def _validar_booking_url(url: str) -> tuple[bool, str]:
    """Valida booking_url: esquema http/https, domínio esperado. Retorna (ok, mensagem)."""
    if not url or not isinstance(url, str) or not url.strip():
        return False, "URL do Booking é obrigatória."
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, "URL deve iniciar com http:// ou https://"
    if "booking.com" not in url.lower():
        return False, "URL deve ser do domínio booking.com"
    return True, ""


class AtualizarProjetoBody(BaseModel):
    """Payload para PUT /api/projeto/<id> (campos opcionais)."""

    nome: str | None = None
    url_booking: str | None = None
    numero_quartos: int | None = None
    faturamento_anual: float | None = None
    ano_referencia: int | None = None
    financeiro: DadosFinanceiros | None = None
    infraestrutura: Infraestrutura | None = None
    projetos_referencia: List[str] | None = None
    markup_referencia: float | None = None
    arrendamento_total: float | None = Field(default=None, ge=0)
    prazo_contrato_meses: int | None = Field(default=None, ge=1, le=600)
    investimento_reforma: float | None = Field(default=None, ge=0)


@app.get("/")
def index():
    """Serve a página principal (Single Page)."""
    return render_template("index.html")


@app.get("/api/projetos")
def api_listar_projetos():
    """Lista projetos em JSON (padrão R3)."""
    projetos = listar_projetos()
    dados = []
    for p in projetos:
        item = p.model_dump(mode="json")
        fin = _ensure_funcionarios_from_legacy(item.get("financeiro"))
        folha_total = float(
            _normalizar_financeiro_para_persistencia(DadosFinanceiros.model_validate(fin)).folha_total
        ) if fin is not None else 0.0
        fin["folha_total"] = round(folha_total, 2)
        item["financeiro"] = fin
        dados.append(item)
    return jsonify({"success": True, "message": "Projetos listados.", "data": dados})


@app.post("/api/system-events/frontend")
def api_system_events_frontend():
    """Endpoint leve para eventos de UX do frontend (fire-and-forget)."""
    body = request.get_json(force=True, silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"success": False, "message": "Payload inválido"}), 400
    action = str(body.get("action") or "").strip()
    if not action:
        return jsonify({"success": False, "message": "Campo 'action' é obrigatório"}), 400
    id_projeto = str(body.get("id_projeto") or "unknown").strip() or "unknown"
    extra = {k: v for k, v in body.items() if k not in {"action", "id_projeto"}}
    _log_system_event(action=action, id_projeto=id_projeto, extra=extra)
    return jsonify({"success": True}), 202


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


def _obter_checklist_pousada(id_projeto: str) -> dict:
    """Retorna checklist de validação para uma pousada/projeto."""
    path_projeto = get_projeto_json_path(id_projeto)
    path_scraper = get_scraper_config_path(id_projeto)
    path_bruto = get_market_bruto_path(id_projeto)
    path_backups = get_backups_dir(id_projeto)
    try:
        proj = carregar_projeto(id_projeto)
        url = proj.url_booking or ""
    except ArquivoProjetoNaoEncontrado:
        proj = None
        url = ""
    booking_url_valid = False
    if url:
        ok, _ = _validar_booking_url(url)
        booking_url_valid = ok
    return {
        "scraper_config_exists": path_scraper.exists() and path_scraper.is_file(),
        "booking_url_valid": booking_url_valid,
        "market_bruto_exists": path_bruto.exists() and path_bruto.is_file(),
        "permissions_ok": True,
        "backups_dir_exists": path_backups.exists() and path_backups.is_dir(),
    }


def _criar_pousada_internal(body: dict):
    """Lógica interna de criação de pousada. body já deve ter booking_url se houver url_booking."""
    payload = CriarPousadaBody.model_validate(body)
    url = (payload.booking_url or "").strip()
    ok, msg = _validar_booking_url(url)
    if not ok:
        return jsonify({"success": False, "message": msg, "data": None}), 400

    id_projeto = payload.id
    if not id_projeto or not str(id_projeto).strip():
        id_projeto = gerar_id_projeto(payload.nome)
    id_projeto = str(id_projeto).strip().lower()
    import re
    id_projeto = re.sub(r"[^a-z0-9\-]", "-", id_projeto).strip("-") or gerar_id_projeto(payload.nome)
    n = 1
    id_base = id_projeto
    while get_projeto_json_path(id_projeto).exists() or (PROJECTS_DIR / f"{id_projeto}.json").exists():
        id_projeto = f"{id_base}-{n}"
        n += 1

    metadata = {
        "nome": payload.nome,
        "booking_url": url,
        "url_booking": url,
        "timezone": payload.timezone or "America/Sao_Paulo",
        "cidade": payload.cidade,
        "noites_preferencial": 2,
        "max_tentativas": 5,
        "numero_quartos": 1,
        "faturamento_anual": 0,
        "ano_referencia": date.today().year,
    }
    scaffold = create_project_scaffold(id_projeto, metadata)
    checklist = _obter_checklist_pousada(id_projeto)
    created_files = scaffold["created"]

    if payload.executar_scrape_imediato:
        try:
            proj = carregar_projeto(id_projeto)
            market = coletar_dados_mercado_expandido(proj.url_booking, id_projeto)
            created_files.append("market_bruto.json (atualizado pelo scrape)")
            checklist = _obter_checklist_pousada(id_projeto)
        except Exception as e:
            logger.warning("Scrape imediato falhou para {}: {}", id_projeto, e)
            scaffold["errors"].append(f"Scrape: {e}")

    return jsonify({
        "success": True,
        "message": "Pousada criada.",
        "data": {
            "id": id_projeto,
            "created_files": created_files,
            "checklist": checklist,
            "scaffold": {
                "created": scaffold["created"],
                "already_existed": scaffold["already_existed"],
                "missing": scaffold["missing"],
                "errors": scaffold["errors"],
            },
        },
    }), 201


@app.post("/api/pousada")
def api_criar_pousada():
    """Cria nova pousada com scaffold completo."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        return _criar_pousada_internal(body)
    except Exception as e:
        logger.warning("Validação POST /api/pousada falhou: {}", e)
        return jsonify({"success": False, "message": str(e), "data": None}), 400


@app.post("/api/projeto")
def api_criar_projeto():
    """Alias de POST /api/pousada para compatibilidade. Aceita booking_url ou url_booking."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        if "url_booking" in body and "booking_url" not in body:
            body = {**body, "booking_url": body["url_booking"]}
        return _criar_pousada_internal(body)
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "data": None}), 400


@app.get("/api/pousada/<id>/validate")
def api_validate_pousada(id: str):
    """Retorna checklist de validação da pousada."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Pousada não encontrada", "data": None}), 404
    checklist = _obter_checklist_pousada(id)
    return jsonify({"success": True, "data": {"checklist": checklist}})


@app.post("/projeto")
def criar_projeto():
    """Cria novo projeto; id único com sufixo numérico se slug já existir."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        body = _normalizar_financeiro_payload_body(body)
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

    try:
        financeiro_raw = payload.financeiro if payload.financeiro is not None else DadosFinanceiros()
        financeiro = _normalizar_financeiro_para_persistencia(financeiro_raw)
    except (ValueError, InvalidOperation, ValidationError) as e:
        return jsonify({"success": False, "message": f"Payload financeiro inválido: {e}", "data": None}), 400
    projeto_kwargs: dict = dict(
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
    if payload.arrendamento_total is not None:
        projeto_kwargs["arrendamento_total"] = float(payload.arrendamento_total)
    if payload.prazo_contrato_meses is not None:
        projeto_kwargs["prazo_contrato_meses"] = int(payload.prazo_contrato_meses)
    if payload.investimento_reforma is not None:
        projeto_kwargs["investimento_reforma"] = float(payload.investimento_reforma)
    projeto = Projeto(**projeto_kwargs)
    salvar_projeto(projeto)
    logger.info("Projeto criado via POST: {}", id_projeto)
    return jsonify({
        "success": True,
        "message": "Projeto criado.",
        "data": {"id": projeto.id},
    }), 201


@app.put("/api/projeto/<id>")
def api_atualizar_projeto(id: str):
    """Atualiza projeto existente; aceita campos parciais.

    Campos cadastrais (nome, URL, quartos, faturamento, ano, infraestrutura, referências, markup)
    e financeiro são aplicados de forma explícita quando presentes no JSON (None = não alterar).
    """
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
        body = _normalizar_financeiro_payload_body(body)
        payload = AtualizarProjetoBody.model_validate(body)
    except Exception as e:
        logger.warning("Validação PUT /api/projeto/<id> falhou: {}", e)
        return jsonify({
            "success": False,
            "message": str(e),
            "data": None,
        }), 400

    # Cadastro e metadados centrais (não financeiros)
    if payload.nome is not None:
        nome_limpo = str(payload.nome).strip()
        if not nome_limpo:
            return jsonify({"success": False, "message": "Nome não pode ser vazio.", "data": None}), 400
        projeto.nome = nome_limpo
    if payload.url_booking is not None:
        projeto.url_booking = str(payload.url_booking).strip()
    if payload.numero_quartos is not None:
        projeto.numero_quartos = payload.numero_quartos
    if payload.faturamento_anual is not None:
        projeto.faturamento_anual = payload.faturamento_anual
    if payload.ano_referencia is not None:
        projeto.ano_referencia = payload.ano_referencia
    if payload.infraestrutura is not None:
        projeto.infraestrutura = payload.infraestrutura
    if payload.projetos_referencia is not None:
        refs = [str(x).strip() for x in payload.projetos_referencia if x and str(x).strip()]
        projeto.projetos_referencia = [r for r in refs if r != id]
    if payload.markup_referencia is not None:
        v = float(payload.markup_referencia)
        projeto.markup_referencia = v if 0.01 <= v <= 10.0 else None
    if payload.arrendamento_total is not None:
        projeto.arrendamento_total = float(payload.arrendamento_total)
    if payload.prazo_contrato_meses is not None:
        pr = int(payload.prazo_contrato_meses)
        projeto.prazo_contrato_meses = max(1, min(600, pr))
    if payload.investimento_reforma is not None:
        projeto.investimento_reforma = float(payload.investimento_reforma)

    # Financeiro (folha, custos, impostos, etc.)
    if payload.financeiro is not None:
        try:
            projeto.financeiro = _normalizar_financeiro_para_persistencia(payload.financeiro)
        except (ValueError, InvalidOperation, ValidationError) as e:
            return jsonify({"success": False, "message": f"Payload financeiro inválido: {e}", "data": None}), 400

    salvar_projeto(projeto)
    logger.info("Projeto atualizado via PUT: {}", id)
    _emit_correcao_curadoria_crud_event(projeto.id)
    return jsonify({
        "success": True,
        "message": "Projeto atualizado.",
        "data": {"id": projeto.id},
    }), 200


@app.delete("/api/projeto/<id>")
def api_excluir_projeto(id: str):
    """Exclui a pousada e todos os arquivos em data/projects/<id>/ (e artefatos legados na raiz)."""
    try:
        resultado = excluir_projeto_seguro(id)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e), "data": None}), 400
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado.", "data": None}), 404
    except OSError as e:
        logger.warning("Falha ao excluir projeto {}: {}", id, e)
        return jsonify({"success": False, "message": "Falha ao remover arquivos do projeto.", "data": None}), 500
    _emit_correcao_curadoria_crud_event(resultado.get("id_projeto") or id)
    return jsonify({
        "success": True,
        "message": "Pousada excluída.",
        "data": resultado,
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


def _build_cache_valores_referencia(id_projeto: str) -> tuple[list[str], dict[str, dict[str, float]], dict[str, str], float | None]:
    """
    Cache em memória dos valores (checkin -> valor_efetivo) dos projetos de referência.
    Retorna (refs, cache, nomes, markup).
    Cache: ref_id -> {checkin -> valor}; evita reabrir JSONs a cada linha.
    """
    proj = read_project_json(id_projeto)
    if not isinstance(proj, dict):
        return [], {}, {}, None
    refs = proj.get("projetos_referencia") or []
    if not isinstance(refs, list):
        return [], {}, {}, None
    refs = [str(r).strip() for r in refs if r and str(r).strip() != id_projeto]
    refs = [r for r in refs if get_projeto_json_path(r).exists()]

    markup = proj.get("markup_referencia")
    if markup is not None:
        try:
            markup = float(markup)
            if not (0.01 <= markup <= 10.0):
                markup = None
        except (TypeError, ValueError):
            markup = None

    cache: dict[str, dict[str, float]] = {}
    nomes: dict[str, str] = {}
    for ref_id in refs:
        nomes[ref_id] = (read_project_json(ref_id) or {}).get("nome") or ref_id
        path_bruto = get_market_bruto_path(ref_id)
        if not path_bruto.exists():
            path_bruto = PROJECTS_DIR / f"market_bruto_{ref_id}.json"
        if not path_bruto.exists() or not path_bruto.is_file():
            continue
        try:
            bruto = MarketBruto.model_validate(json.loads(path_bruto.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
        curado_por_checkin: dict[str, float] = {}
        path_curado = get_market_curado_path(ref_id)
        if not path_curado.exists():
            path_curado = PROJECTS_DIR / f"market_curado_{ref_id}.json"
        if path_curado.exists() and path_curado.is_file():
            try:
                raw_c = path_curado.read_text(encoding="utf-8")
                if raw_c.strip():
                    curado = MarketCurado.model_validate(json.loads(raw_c))
                    for r in curado.registros:
                        if r.preco_curado is not None and r.preco_curado > 0:
                            curado_por_checkin[r.checkin] = float(r.preco_curado)
            except (json.JSONDecodeError, ValidationError, ValueError):
                pass
        checkin_to_val: dict[str, float] = {}
        for r in bruto.registros:
            val = curado_por_checkin.get(r.checkin)
            if val is None and r.preco_booking is not None and r.preco_booking > 0:
                desconto = obter_desconto_para_curadoria(ref_id, r.mes_ano)
                bruto_dec = safe_decimal_from(r.preco_booking)
                if bruto_dec is not None:
                    preco_dec = (bruto_dec * (Decimal("1") - desconto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    val = format_decimal_for_display(preco_dec)
            if val is not None and val > 0:
                checkin_to_val[r.checkin] = float(val)
        if checkin_to_val:
            cache[ref_id] = checkin_to_val
    return refs, cache, nomes, markup


def _carregar_registros_com_valor_efetivo(id_projeto: str) -> list[dict] | None:
    """Carrega bruto + curado (se existir), retorna lista com valor_efetivo = preco_curado ou preco_direto.
    Fallback multi-base: quando valor nulo, busca em projetos_referencia (cache em memória)."""
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

    refs, cache_ref, nomes_ref, markup = _build_cache_valores_referencia(id_projeto)

    from core.config import _periodos_especiais_de_config, get_periodo_config_por_data
    periodos_ef = _periodos_especiais_de_config(id_projeto)
    cache_prop: dict[str, list[float]] = {}
    for r in bruto.registros:
        val = curado_por_checkin.get(r.checkin)
        if val is None:
            val = r.preco_direto
        if val is not None and val > 0:
            periodo = get_periodo_config_por_data(periodos_ef, r.checkin)
            if periodo and periodo.get("periodo_id"):
                cache_prop.setdefault(periodo["periodo_id"], []).append(float(val))

    registros = []
    for r in bruto.registros:
        valor_efetivo = curado_por_checkin.get(r.checkin)
        if valor_efetivo is None:
            valor_efetivo = r.preco_direto
        preco_fallback_de: str | None = None
        preco_fallback_nome: str | None = None
        preco_propagado_periodo = False
        if (valor_efetivo is None or valor_efetivo <= 0):
            periodo = get_periodo_config_por_data(periodos_ef, r.checkin)
            if periodo and periodo.get("periodo_id"):
                vals_p = cache_prop.get(periodo["periodo_id"], [])
                if vals_p:
                    valor_efetivo = round(sum(vals_p) / len(vals_p), 2)
                    preco_propagado_periodo = True
                    _log_system_event(
                        "etapa4_range_correction_applied",
                        id_projeto=id_projeto,
                        extra={"checkin": r.checkin, "periodo_id": periodo["periodo_id"], "tipo": "propagacao"},
                    )
        if (valor_efetivo is None or valor_efetivo <= 0) and refs:
            for ref_id in refs:
                checkin_map = cache_ref.get(ref_id, {})
                if r.checkin in checkin_map:
                    val = checkin_map[r.checkin]
                    if val and val > 0:
                        if markup is not None:
                            val = round(float(val) * markup, 2)
                        valor_efetivo = val
                        preco_fallback_de = ref_id
                        preco_fallback_nome = nomes_ref.get(ref_id, ref_id)
                        _log_system_event(
                            "etapa3_fallback_multibase_applied",
                            id_projeto=id_projeto,
                            extra={"checkin": r.checkin, "id_referencia": ref_id, "tipo": "preco"},
                        )
                        break
        categoria = getattr(r, "categoria_dia", "normal") or "normal"
        reg = {
            "valor_efetivo": valor_efetivo,
            "checkin": r.checkin,
            "mes_ano": r.mes_ano,
            "tipo_dia": r.tipo_dia,
            "categoria_dia": categoria,
        }
        if preco_fallback_de:
            reg["preco_fallback_de"] = preco_fallback_de
            reg["preco_fallback_nome"] = preco_fallback_nome
        if preco_propagado_periodo:
            reg["preco_propagado_periodo"] = True
        registros.append(reg)
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

    refs, cache_ref, nomes_ref, markup = _build_cache_valores_referencia(id_projeto)

    from datetime import date
    from core.config import (
        asegurar_scraper_config,
        obter_config_scraper_com_defaults,
        obter_desconto_dinamico,
        _periodos_especiais_de_config,
        get_periodo_config_por_id,
        get_periodo_config_por_data,
    )
    asegurar_scraper_config(id_projeto)
    scraper_cfg = obter_config_scraper_com_defaults(id_projeto)
    periodos_especiais = _periodos_especiais_de_config(id_projeto)

    def _build_cache_preco_por_periodo() -> dict[str, list[float]]:
        """Cache: periodo_id -> lista de valores coletados no período (para propagação Etapa 4)."""
        cache: dict[str, list[float]] = {}
        for r in bruto.registros:
            val = None
            if r.checkin in curado_por_checkin:
                pc = curado_por_checkin[r.checkin].get("preco_curado")
                if pc is not None and pc > 0:
                    val = float(pc)
            if val is None and r.preco_booking is not None and r.preco_booking > 0:
                if backend_unificado:
                    desconto_dec = obter_desconto_para_curadoria(id_projeto, r.mes_ano)
                    bruto_dec = safe_decimal_from(r.preco_booking)
                    if bruto_dec is not None:
                        val = format_decimal_for_display(
                            (bruto_dec * (Decimal("1") - desconto_dec)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        )
                else:
                    desc = obter_desconto_dinamico(scraper_cfg, r.mes_ano)
                    val = round(float(r.preco_booking) * (1 - desc), 2)
            elif val is None and r.preco_direto is not None and r.preco_direto > 0:
                val = float(r.preco_direto)
            if val is not None and val > 0:
                periodo = get_periodo_config_por_data(periodos_especiais, r.checkin)
                if periodo and periodo.get("periodo_id"):
                    cache.setdefault(periodo["periodo_id"], []).append(val)
        return cache

    backend_unificado = _backend_desconto_unificado_ativo()
    cache_preco_periodo = _build_cache_preco_por_periodo()
    strict_periodos = _strict_periodos_ativo(id_projeto)
    periodos_validos_ids: set[str] = {
        p.get("periodo_id")
        for p in periodos_especiais
        if isinstance(p, dict) and p.get("periodo_id")
    }

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
        for p in periodos_especiais:
            if not isinstance(p, dict):
                continue
            ini = p.get("inicio_date")
            fim = p.get("fim_date")
            nome = p.get("nome")
            if ini and fim and ini <= d <= fim:
                return nome
        return None

    def _normalizar_nome_periodo(txt: str | None) -> str:
        if not txt:
            return ""
        t = unicodedata.normalize("NFD", str(txt).strip().lower())
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
        return " ".join(t.split())

    periodos_por_nome_norm: dict[str, dict] = {}
    for p in periodos_especiais:
        if not isinstance(p, dict):
            continue
        nome_cfg = p.get("nome")
        key = _normalizar_nome_periodo(nome_cfg)
        if key:
            periodos_por_nome_norm[key] = p

    def _resolver_periodo_oficial_para_row(row: dict) -> dict | None:
        pid_meta = row.get("meta_periodo_id")
        if pid_meta:
            by_id = get_periodo_config_por_id(periodos_especiais, pid_meta)
            if by_id:
                return by_id
        nome_meta = row.get("meta_periodo_nome")
        if nome_meta:
            key = _normalizar_nome_periodo(nome_meta)
            by_nome = periodos_por_nome_norm.get(key)
            if by_nome:
                return by_nome
        return get_periodo_config_por_data(periodos_especiais, row.get("checkin"))

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
    # Incluir sempre registros de Datas Especiais já coletados, mesmo fora da janela rolling atual
    coletados = [
        r for r in bruto.registros
        if r.checkin in checkins_amostra or getattr(r, "categoria_dia", "normal") == "especial"
    ]

    registros_normais: list[dict] = []
    registros_especiais_raw: list[dict] = []
    inconsistencias_especiais: list[dict] = []
    for r in coletados:
        tem_curado = r.checkin in curado_por_checkin
        preco_curado = curado_por_checkin[r.checkin].get("preco_curado") if tem_curado else None
        status = "Editado (Manual)" if tem_curado else ("Original (Booking)" if r.preco_booking is not None else "Faltando")
        partes = (r.mes_ano.split("-") + ["", ""])[:2]
        ano, mes = partes[0], partes[1]
        mes_ano_label = f"{MESES_PT.get(mes, mes)}/{ano}" if mes and ano else r.mes_ano
        categoria = getattr(r, "categoria_dia", "normal") or "normal"
        if r.preco_booking is not None:
            if backend_unificado:
                desconto_dec = obter_desconto_para_curadoria(id_projeto, r.mes_ano)
                bruto_dec = safe_decimal_from(r.preco_booking)
                if bruto_dec is not None:
                    preco_direto_dec = (bruto_dec * (Decimal("1") - desconto_dec)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    preco_direto_exibicao = format_decimal_for_display(preco_direto_dec)
                    if len(registros_normais) + len(registros_especiais_raw) < 5:
                        _log_system_event(
                            action="calculo_preco_direto_sample",
                            id_projeto=id_projeto,
                            extra={
                                "checkin": r.checkin,
                                "desconto_source": "unificado_backend",
                                "desconto_value": str(desconto_dec),
                                "preco_booking": str(bruto_dec),
                                "preco_direto": str(preco_direto_dec),
                            },
                        )
                else:
                    preco_direto_exibicao = r.preco_direto
            else:
                desconto = obter_desconto_dinamico(scraper_cfg, r.mes_ano)
                preco_direto_exibicao = round(float(r.preco_booking) * (1 - desconto), 2)
        else:
            preco_direto_exibicao = r.preco_direto
        preco_fallback_de: str | None = None
        preco_fallback_nome: str | None = None
        preco_propagado_periodo = False
        if (preco_direto_exibicao is None or preco_direto_exibicao <= 0) and (preco_curado is None or preco_curado <= 0):
            periodo_cfg = get_periodo_config_por_data(periodos_especiais, r.checkin)
            if periodo_cfg and periodo_cfg.get("periodo_id"):
                vals_periodo = cache_preco_periodo.get(periodo_cfg["periodo_id"], [])
                if vals_periodo:
                    preco_direto_exibicao = round(sum(vals_periodo) / len(vals_periodo), 2)
                    preco_propagado_periodo = True
                    _log_system_event(
                        "etapa4_range_correction_applied",
                        id_projeto=id_projeto,
                        extra={"checkin": r.checkin, "periodo_id": periodo_cfg["periodo_id"], "tipo": "propagacao"},
                    )
        if (preco_direto_exibicao is None or preco_direto_exibicao <= 0) and (preco_curado is None or preco_curado <= 0) and refs:
            for ref_id in refs:
                checkin_map = cache_ref.get(ref_id, {})
                if r.checkin in checkin_map:
                    val = checkin_map[r.checkin]
                    if val and val > 0:
                        if markup is not None:
                            val = round(float(val) * markup, 2)
                        preco_direto_exibicao = val
                        preco_fallback_de = ref_id
                        preco_fallback_nome = nomes_ref.get(ref_id, ref_id)
                        _log_system_event(
                            "etapa3_fallback_multibase_applied",
                            id_projeto=id_projeto,
                            extra={"checkin": r.checkin, "id_referencia": ref_id, "tipo": "preco"},
                        )
                        break
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
            "preco_booking_por_data": r.preco_booking,
            "preco_direto_por_data": preco_direto_exibicao,
            "preco_direto_media_periodo": None,
            "preco_exibicao_preferida": "por_data" if preco_direto_exibicao is not None else "nao_disponivel",
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
        if preco_fallback_de:
            row["preco_fallback_de"] = preco_fallback_de
            row["preco_fallback_nome"] = preco_fallback_nome
        if preco_propagado_periodo:
            row["preco_propagado_periodo"] = True
        meta = getattr(r, "meta", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        row["meta_periodo_id"] = meta.get("periodo_id")
        row["meta_periodo_source"] = meta.get("periodo_source")
        row["meta_periodo_nome"] = meta.get("periodo_nome")
        periodo_oficial = _resolver_periodo_oficial_para_row(row) if categoria == "especial" else None
        row["periodo_id_resolvido"] = periodo_oficial.get("periodo_id") if isinstance(periodo_oficial, dict) else None
        row["periodo_nome_config"] = periodo_oficial.get("nome") if isinstance(periodo_oficial, dict) else None
        row["periodo_inicio_config"] = periodo_oficial.get("inicio") if isinstance(periodo_oficial, dict) else None
        row["periodo_fim_config"] = periodo_oficial.get("fim") if isinstance(periodo_oficial, dict) else None
        if categoria == "especial" and isinstance(periodo_oficial, dict):
            row["periodo_nome"] = periodo_oficial.get("nome") or row.get("periodo_nome")
        if categoria == "especial":
            if strict_periodos:
                pid = row.get("meta_periodo_id")
                psrc = row.get("meta_periodo_source")
                if psrc == "config" and pid in periodos_validos_ids:
                    registros_especiais_raw.append(row)
                else:
                    inconsistencias_especiais.append(row)
            else:
                registros_especiais_raw.append(row)
        else:
            registros_normais.append(row)

    if strict_periodos and inconsistencias_especiais:
        _log_system_event(
            action="curadoria_inconsistencias_periodos",
            id_projeto=id_projeto,
            extra={
                "total_inconsistencias": len(inconsistencias_especiais),
                "checkins": [r.get("checkin") for r in inconsistencias_especiais[:30]],
            },
        )

    periodos_agrupados: dict[str, list[dict]] = {}
    for row in registros_especiais_raw:
        pid = row.get("periodo_id_resolvido")
        if pid:
            chave = f"pid::{pid}"
        else:
            pn = row.get("periodo_nome")
            chave = f"nome::{pn}" if pn else "outro::Outro (especial)"
        periodos_agrupados.setdefault(chave, []).append(row)

    registros_especiais: list[dict] = []
    outros_count = 0
    for _agr_key, grupo in sorted(periodos_agrupados.items(), key=lambda x: (x[1][0]["checkin"] if x[1] else "")):
        checkins = [r["checkin"] for r in grupo]
        periodo_match = None
        pid_resolvido = grupo[0].get("periodo_id_resolvido") if grupo else None
        if pid_resolvido:
            periodo_match = get_periodo_config_por_id(periodos_especiais, pid_resolvido)
        if not periodo_match and grupo:
            periodo_match = get_periodo_config_por_data(periodos_especiais, grupo[0].get("checkin"))
        if periodo_match:
            periodo_nome = periodo_match.get("nome") or grupo[0].get("periodo_nome") or "Outro (especial)"
            checkin_ini = periodo_match.get("inicio")
            checkout_fim = periodo_match.get("fim")
        else:
            periodo_nome = grupo[0].get("periodo_nome") or "Outro (especial)"
            checkin_ini = min(g["checkin"] for g in grupo)
            checkout_fim = max(g["checkout"] for g in grupo)
            outros_count += 1
            try:
                ev_path = EVIDENCE_STABILITY_DIR / "Curadoria_INTERVALO_FALLBACK.jsonl"
                ev_path.parent.mkdir(parents=True, exist_ok=True)
                with open(ev_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now().isoformat(),
                        "evento": "intervalo_fallback",
                        "id_projeto": id_projeto,
                        "periodo_nome": periodo_nome or "",
                        "checkin_ini": checkin_ini,
                        "checkout_fim": checkout_fim,
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
        precos_direto = [g["preco_direto"] for g in grupo if g["preco_direto"] is not None]
        precos_curado = [g["preco_curado"] for g in grupo if g["preco_curado"] is not None]
        adr_medio = _calcular_media_decimal(precos_direto)
        preco_curado_periodo = _calcular_media_decimal(precos_curado)
        preco_booking_por_data = grupo[0].get("preco_booking") if grupo else None
        preco_direto_por_data = None
        if grupo:
            preco_direto_por_data = _calcular_preco_direto_por_data(id_projeto, grupo[0].get("mes_ano"), preco_booking_por_data)
        preco_direto_media_periodo = adr_medio if adr_medio is not None else None
        preco_exibicao_preferida, preco_direto_exibicao = _resolver_preco_exibicao_preferida(
            preco_direto_por_data, preco_direto_media_periodo
        )
        status = "Editado (Manual)" if all(g["status"] == "Editado (Manual)" for g in grupo) else ("Original (Booking)" if any(g.get("preco_booking") for g in grupo) else "Faltando")
        preco_falha_agregado = not any(g.get("preco_booking") for g in grupo)
        fb_de = next((g.get("preco_fallback_de") for g in grupo if g.get("preco_fallback_de")), None)
        fb_nome = next((g.get("preco_fallback_nome") for g in grupo if g.get("preco_fallback_nome")), None)
        prop_periodo = any(g.get("preco_propagado_periodo") for g in grupo)
        reg_esp = {
            "periodo_nome": periodo_nome,
            "checkin": checkin_ini,
            "checkout": checkout_fim,
            "periodo_inicio_config": checkin_ini if periodo_match else None,
            "periodo_fim_config": checkout_fim if periodo_match else None,
            "checkin_br": _data_br(checkin_ini),
            "checkout_br": _data_br(checkout_fim),
            "checkins": checkins,
            "mes_ano_label": grupo[0]["mes_ano_label"] if grupo else "",
            "preco_direto": preco_direto_exibicao,
            "preco_curado": preco_curado_periodo,
            "preco_direto_fmt": _moeda_br(preco_direto_exibicao) if preco_direto_exibicao is not None else None,
            "preco_curado_fmt": _moeda_br(preco_curado_periodo) if preco_curado_periodo is not None else None,
            "preco_booking_fmt": _moeda_br(grupo[0]["preco_booking"]) if grupo and grupo[0].get("preco_booking") else None,
            "preco_booking_por_data": preco_booking_por_data,
            "preco_direto_por_data": preco_direto_por_data,
            "preco_direto_media_periodo": preco_direto_media_periodo,
            "preco_exibicao_preferida": preco_exibicao_preferida,
            "preco_falha": preco_falha_agregado,
            "status": status,
            "nome_quarto": grupo[0].get("nome_quarto", "") if grupo else "",
            "tipo_tarifa": grupo[0].get("tipo_tarifa", "") if grupo else "",
            "noites": grupo[0].get("noites", 0) if grupo else 0,
        }
        if fb_de:
            reg_esp["preco_fallback_de"] = fb_de
            reg_esp["preco_fallback_nome"] = fb_nome
        if prop_periodo:
            reg_esp["preco_propagado_periodo"] = True
        registros_especiais.append(reg_esp)
    if registros_especiais:
        _log_system_event(
            action="curadoria_display_fix_applied",
            id_projeto=id_projeto,
            extra={
                "registros_especiais": len(registros_especiais),
                "por_data": len([r for r in registros_especiais if r.get("preco_exibicao_preferida") == "por_data"]),
                "media_periodo": len([r for r in registros_especiais if r.get("preco_exibicao_preferida") == "media_periodo"]),
                "nao_disponivel": len([r for r in registros_especiais if r.get("preco_exibicao_preferida") == "nao_disponivel"]),
            },
        )
        _log_system_event(
            action="curadoria_periodos_fix_applied",
            id_projeto=id_projeto,
            extra={
                "grupos_especiais": len(registros_especiais),
                "grupos_outro_especial": outros_count,
                "grupos_com_config": max(0, len(registros_especiais) - outros_count),
            },
        )

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
        "inconsistencias_especiais": inconsistencias_especiais,
        "strict_periodos_ativo": strict_periodos,
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
    from core.config import (
        descontos_config_para_template,
        obter_config_scraper_com_defaults,
        obter_desconto_dinamico,
    )
    scraper_cfg_curadoria = obter_config_scraper_com_defaults(id)
    descontos_config = descontos_config_para_template(scraper_cfg_curadoria)
    desconto_exibicao = f"{obter_desconto_dinamico(scraper_cfg_curadoria, None) * 100:.1f}".replace(".", ",")
    frontend_desconto_unificado_ativo = _frontend_desconto_unificado_ativo(id)
    resp = render_template(
        "dashboard.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="curadoria",
        grupos_mes=dados.get("grupos_mes", []),
        grupos_normais=dados.get("grupos_normais", []),
        grupos_especiais=dados.get("grupos_especiais", []),
        meses_sem_normais=dados.get("meses_sem_normais", []),
        inconsistencias_especiais=dados.get("inconsistencias_especiais", []),
        strict_periodos_ativo=dados.get("strict_periodos_ativo", False),
        registros=dados.get("registros", []),
        descontos_config=descontos_config,
        desconto_exibicao=desconto_exibicao,
        frontend_desconto_unificado_ativo=frontend_desconto_unificado_ativo,
    )
    # Evitar cache do navegador para garantir dados atualizados (desconto, etc.)
    r = app.make_response(resp)
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return r


@app.post("/api/projeto/<id>/curadoria")
def api_salvar_curadoria(id: str):
    """Recebe ajustes de curadoria e grava market_curado.json.

    Aceita preço digitado manualmente (`preco_curado`, `preco_curado_manual`) ou do preview
    (`preco_curado_sugerido`), nesta ordem de precedência.
    """
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

    _log_system_event(
        action="curadoria_save_start",
        id_projeto=id,
        extra={"total_payload": len(registros_payload), "backend_unificado": _backend_desconto_unificado_ativo()},
    )

    backend_unificado = _backend_desconto_unificado_ativo()
    bruto_por_checkin = {r.checkin: r for r in bruto.registros}
    curado_registros: list[MarketCuradoRegistro] = []
    itens_corrigidos: list[dict] = []
    itens_invalidos: list[dict] = []
    audit_registros: list[dict] = []
    threshold_correcao = Decimal("0.02")

    for idx, item in enumerate(registros_payload):
        if not isinstance(item, dict):
            itens_invalidos.append({"idx": idx, "erro": "item_nao_objeto"})
            continue
        checkin = item.get("checkin")
        if not checkin or checkin not in bruto_por_checkin:
            itens_invalidos.append({"idx": idx, "erro": "checkin_invalido", "checkin": checkin})
            continue
        base = bruto_por_checkin[checkin]

        preco_sugerido_raw = None
        for _key in ("preco_curado", "preco_curado_manual", "preco_curado_sugerido"):
            if item.get(_key) is not None:
                preco_sugerido_raw = item.get(_key)
                break
        if preco_sugerido_raw is None:
            # Mantém compatibilidade: sem valor curado explícito, não persiste registro.
            continue
        preco_sugerido_dec = safe_decimal_from(preco_sugerido_raw)
        if preco_sugerido_dec is None:
            itens_invalidos.append({"idx": idx, "erro": "preco_curado_invalido", "checkin": checkin})
            continue
        preco_sugerido_dec = preco_sugerido_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        status = item.get("status")
        if status is not None and not isinstance(status, str):
            status = "Editado (Manual)"

        preco_final_dec = preco_sugerido_dec
        desconto_aplicado = None
        preco_booking_base_dec = safe_decimal_from(base.preco_booking)
        if backend_unificado and preco_booking_base_dec is not None:
            desconto_dec = obter_desconto_para_curadoria(id, base.mes_ano)
            desconto_aplicado = str(desconto_dec)
            preco_backend_dec = (
                preco_booking_base_dec * (Decimal("1") - desconto_dec)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if abs(preco_backend_dec - preco_sugerido_dec) > threshold_correcao:
                preco_final_dec = preco_backend_dec
                item_corrigido = {
                    "checkin": checkin,
                    "preco_sugerido": float(preco_sugerido_dec),
                    "preco_backend": float(preco_backend_dec),
                    "delta": float((preco_backend_dec - preco_sugerido_dec).copy_abs()),
                    "desconto_aplicado": str(desconto_dec),
                }
                itens_corrigidos.append(item_corrigido)
                _log_system_event(
                    action="curadoria_saving_corrected",
                    id_projeto=id,
                    extra=item_corrigido,
                )

        curado_registros.append(
            MarketCuradoRegistro(
                checkin=base.checkin,
                checkout=base.checkout,
                mes_ano=base.mes_ano,
                tipo_dia=base.tipo_dia,
                preco_booking=base.preco_booking,
                preco_direto=base.preco_direto,
                preco_curado=float(preco_final_dec),
                status=(status or "Editado (Manual)")[:80],
                nome_quarto=base.nome_quarto,
                tipo_tarifa=base.tipo_tarifa,
                noites=base.noites,
                categoria_dia=base.categoria_dia,
            )
        )
        audit_registros.append(
            {
                "checkin": base.checkin,
                "source": "curadoria_ui",
                "version": "ato3.3",
                "saved_by": "cursor-job",
                "timestamp": datetime.now().isoformat(),
                "preco_booking_base": float(preco_booking_base_dec) if preco_booking_base_dec is not None else None,
                "preco_curado_sugerido": float(preco_sugerido_dec),
                "preco_curado_salvo": float(preco_final_dec),
                "desconto_aplicado": desconto_aplicado,
                "preco_exibicao_origem": item.get("preco_exibicao_origem"),
                "preco_base_usado": item.get("preco_base_usado"),
            }
        )

    if len(curado_registros) == 0 and len(registros_payload) > 0:
        return jsonify(
            {
                "success": False,
                "message": "Nenhum registro válido para salvar.",
                "data": {"itens_invalidos": itens_invalidos[:50]},
            }
        ), 400

    market_curado = MarketCurado(
        id_projeto=id,
        url=bruto.url,
        ano=bruto.ano,
        criado_em=datetime.now(),
        registros=curado_registros,
    )
    market_curado_payload = market_curado.model_dump(mode="json")
    market_curado_payload["meta"] = {
        "source": "curadoria_ui",
        "version": "ato3.3",
        "backend_desconto_unificado": backend_unificado,
        "audit": audit_registros,
        "itens_corrigidos_count": len(itens_corrigidos),
    }
    salvar_market_curado_com_backup(id, market_curado_payload)
    logger.info("Market curado salvo: {} ({} registros)", get_market_curado_path(id), len(curado_registros))
    _log_system_event(
        action="market_curado_written",
        id_projeto=id,
        extra={
            "registros_salvos": len(curado_registros),
            "itens_corrigidos": len(itens_corrigidos),
            "itens_invalidos": len(itens_invalidos),
        },
    )
    data_response = {
        "registros_salvos": len(curado_registros),
        "itens_corrigidos": itens_corrigidos,
        "itens_invalidos": itens_invalidos,
    }
    regs_efetivo = _carregar_registros_com_valor_efetivo(id)
    if regs_efetivo:
        analise = gerar_analise_curado(projeto, regs_efetivo)
        data_response["analise"] = analise.model_dump(mode="json")
    _emit_correcao_curadoria_crud_event(id)
    return jsonify({
        "success": True,
        "message": "Ajustes salvos e validados.",
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


@app.get("/projeto/<id_projeto>/relatorio")
def estudo_relatorio_legado(id_projeto: str):
    """Relatório legado (engenharia reversa) preservado para comparação histórica."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    registros = _carregar_registros_com_valor_efetivo(id_projeto)
    if not registros:
        return render_template(
            "relatorio_original.html",
            projeto=projeto.model_dump(mode="json"),
            nav_active="relatorio",
            analise=None,
            sem_dados=True,
        )
    analise = gerar_analise_curado(projeto, registros)
    return render_template(
        "relatorio_original.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="relatorio",
        analise=analise.model_dump(mode="json"),
        sem_dados=False,
    )


@app.route("/projeto/<id_projeto>/viabilidade", methods=["GET", "POST"])
def estudo_viabilidade(id_projeto: str):
    """Relatório executivo one-page da viabilidade (GET cenário salvo ou POST estado atual)."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404

    metas_mensais = None
    investimento_params: dict[str, Any] = {}
    auto_print = False

    if request.method == "POST":
        body = request.get_json(force=False, silent=True)
        if not isinstance(body, dict):
            payload_form = request.form.get("payload_json")
            if payload_form:
                try:
                    body = json.loads(payload_form)
                except (TypeError, ValueError, json.JSONDecodeError):
                    body = {}
            else:
                body = {}
        metas_c = body.get("metas_mensais") if isinstance(body, dict) else None
        if isinstance(metas_c, dict):
            metas_mensais = metas_c
        inv_body = body.get("investimento_params") if isinstance(body, dict) else None
        if isinstance(inv_body, dict):
            investimento_params.update(inv_body)
        for k in ("investimento_reforma", "arrendamento_total", "prazo_contrato_meses", "investimento_inicial", "margem_minima_pct"):
            if isinstance(body, dict) and body.get(k) is not None:
                investimento_params[k] = body.get(k)
        auto_print = bool(body.get("auto_print")) if isinstance(body, dict) else False
    else:
        cid = (request.args.get("cenario") or "").strip()
        if cid:
            investimento_params["cenario_id"] = cid
            cenarios = _carregar_cenarios(id_projeto)
            if not cenarios:
                cenarios = _migrar_simulacao_salva_para_cenarios(id_projeto)
            c = next((x for x in cenarios if x.get("id") == cid), None)
            if c:
                mm = c.get("metas_mensais")
                if isinstance(mm, dict):
                    metas_mensais = mm
                for k in ("investimento_reforma", "arrendamento_total", "prazo_contrato_meses", "investimento_inicial"):
                    if c.get(k) is not None:
                        investimento_params[k] = c.get(k)
        margem_q = request.args.get("margem")
        if margem_q not in (None, ""):
            try:
                investimento_params["margem_minima_pct"] = float(margem_q)
            except (TypeError, ValueError):
                pass
        auto_print = (request.args.get("print") == "1")

    contexto = gerar_contexto_completo_viabilidade(
        id_projeto,
        metas_mensais=metas_mensais,
        investimento_params=investimento_params,
    )
    if contexto.get("erro"):
        return jsonify({"success": False, "message": contexto.get("erro"), "data": contexto}), 400

    return render_template(
        "relatorio_viabilidade.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="relatorio",
        contexto=contexto,
        auto_print=auto_print,
    )


@app.get("/projeto/<id_projeto>/viabilidade/resumo")
def estudo_viabilidade_resumo(id_projeto: str):
    """Atalho para o relatório executivo one-page."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return "Projeto não encontrado", 404
    contexto = gerar_contexto_completo_viabilidade(id_projeto)
    if contexto.get("erro"):
        return jsonify({"success": False, "message": contexto.get("erro"), "data": contexto}), 400
    return render_template(
        "relatorio_viabilidade.html",
        projeto=projeto.model_dump(mode="json"),
        nav_active="relatorio",
        contexto=contexto,
        auto_print=False,
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
        from core.config import _normalizar_valor_desconto

        descontos = body.get("descontos") or {}
        global_desc = descontos.get("global")
        if global_desc is not None:
            try:
                val = _normalizar_valor_desconto(global_desc)
                if val < 0 or val > 1:
                    return jsonify({"success": False, "message": "Desconto global inválido."}), 400
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "Desconto global inválido."}), 400
        por_mes = descontos.get("por_mes") or {}
        for mes, v in list(por_mes.items()):
            try:
                val = _normalizar_valor_desconto(v)
                if val < 0 or val > 1:
                    return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
                por_mes[mes] = val
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
        cfg = obter_config_scraper_com_defaults(id_projeto)
        cfg_global = _normalizar_valor_desconto(descontos.get("global", cfg.get("descontos", {}).get("global", 0.20)))
        cfg["descontos"] = {"global": cfg_global, "por_mes": por_mes}
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
        tipo_coleta = str(p.get("tipo_coleta") or "amostragem").strip().lower()
        if tipo_coleta not in {"amostragem", "pacote"}:
            return jsonify({"success": False, "message": f"tipo_coleta inválido no período {p.get('nome', '')}"}), 400
        p["tipo_coleta"] = tipo_coleta
    # Validar descontos (se existirem); aceita decimal (0.15) ou percentual (15)
    from core.config import _normalizar_valor_desconto

    descontos = body.get("descontos") or {}
    global_desc = descontos.get("global")
    if global_desc is not None:
        try:
            val = _normalizar_valor_desconto(global_desc)
            if val < 0 or val > 1:
                return jsonify({"success": False, "message": "Desconto global inválido."}), 400
            descontos["global"] = val
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Desconto global inválido."}), 400
    por_mes = descontos.get("por_mes") or {}
    for mes, v in list(por_mes.items()):
        try:
            val = _normalizar_valor_desconto(v)
            if val < 0 or val > 1:
                return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
            por_mes[mes] = val
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": f"Desconto inválido para mês {mes}."}), 400
    descontos["por_mes"] = por_mes
    body["descontos"] = descontos
    # Validar urls_concorrentes (opcional)
    urls_concorrentes = body.get("urls_concorrentes", [])
    if urls_concorrentes is None:
        urls_concorrentes = []
    if not isinstance(urls_concorrentes, list):
        return jsonify({"success": False, "message": "urls_concorrentes deve ser uma lista de URLs."}), 400
    urls_norm: list[str] = []
    for u in urls_concorrentes:
        s = str(u or "").strip()
        if not s:
            continue
        if not (s.startswith("http://") or s.startswith("https://")):
            return jsonify({"success": False, "message": f"URL concorrente inválida: {s}"}), 400
        urls_norm.append(s)
    body["urls_concorrentes"] = urls_norm
    permitir_busca_externa = bool(body.get("permitir_busca_externa", False))
    body["permitir_busca_externa"] = permitir_busca_externa

    salvar_config_scraper(id_projeto, body)
    _log_system_event(
        "inteligencia_competitiva_applied",
        id_projeto,
        {
            "evento": "inteligencia_competitiva_applied",
            "urls_concorrentes_count": len(urls_norm),
        },
    )
    _log_system_event(
        "master_integridade_scraper_applied",
        id_projeto,
        {
            "evento": "master_integridade_scraper_applied",
            "permitir_busca_externa": bool(body.get("permitir_busca_externa", False)),
            "periodos_especiais_count": len(periodos),
        },
    )
    return jsonify({"success": True, "message": "Configurações salvas."})


@app.post("/api/projeto/<id_projeto>/scraper/importar_template")
def api_scraper_importar_template(id_projeto: str):
    """Importa períodos do template padrão no scraper_config, sem duplicar por nome (case-insensitive, strip)."""
    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    from core.config import (
        asegurar_scraper_config,
        carregar_config_scraper,
        salvar_config_scraper,
        _get_scraper_config_template,
    )

    asegurar_scraper_config(id_projeto)

    cfg = carregar_config_scraper(id_projeto)
    if not cfg:
        cfg = _get_scraper_config_template()

    backup_scraper_config_before_action(id_projeto, "importar_template")

    existentes = cfg.get("periodos_especiais") or cfg.get("datas_especiais") or []
    nomes_existentes = {str(p.get("nome") or "").strip().lower() for p in existentes if isinstance(p, dict)}

    template = _get_scraper_config_template()
    template_periodos = template.get("periodos_especiais") or []

    adicionados = 0
    for p in template_periodos:
        if not isinstance(p, dict):
            continue
        nome = str(p.get("nome") or "").strip()
        if nome and nome.lower() not in nomes_existentes:
            if "tipo_coleta" not in p:
                p["tipo_coleta"] = "amostragem"
            existentes.append(p)
            nomes_existentes.add(nome.lower())
            adicionados += 1

    cfg["periodos_especiais"] = existentes
    if "datas_especiais" in cfg:
        cfg["datas_especiais"] = existentes

    salvar_config_scraper(id_projeto, cfg)

    ev_dir = __import__("pathlib").Path(__file__).resolve().parent / "scripts" / "evidence_stability"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_path = ev_dir / "SYSTEM_EVENTS.jsonl"
    try:
        with open(ev_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "evento": "etapa2_template_datas_applied",
                        "id_projeto": id_projeto,
                        "periodos_adicionados": adicionados,
                        "periodos_total": len(existentes),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass

    return jsonify({
        "success": True,
        "message": f"Template importado. {adicionados} período(s) adicionado(s). Total: {len(existentes)}.",
        "periodos_adicionados": adicionados,
        "periodos_total": len(existentes),
    })


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
        folha_total = float(fin.folha_total) if hasattr(fin, "folha_total") else float(getattr(fin, "folha_pagamento_mensal", 0.0) or 0.0)
        financeiro = {
            "custos_fixos": fin.custos_fixos.model_dump() if hasattr(fin.custos_fixos, "model_dump") else {},
            "folha_pagamento_mensal": fin.folha_pagamento_mensal,
            "folha_total": round(folha_total, 2),
            "funcionarios": [f.model_dump(mode="json") for f in fin.funcionarios] if hasattr(fin, "funcionarios") else [],
            "encargos_pct_padrao": getattr(fin, "encargos_pct_padrao", 0),
            "beneficio_vale_transporte": getattr(fin, "beneficio_vale_transporte", 0),
            "beneficio_vale_alimentacao": getattr(fin, "beneficio_vale_alimentacao", 0),
            "custos_variaveis": fin.custos_variaveis.model_dump() if hasattr(fin.custos_variaveis, "model_dump") else {},
            "media_pessoas_por_diaria": media_pessoas_por_diaria,
            "comissao_venda_pct": getattr(fin, "comissao_venda_pct", 0.0) or 0.0,
            "aliquota_impostos": fin.aliquota_impostos,
            "outros_impostos_taxas_percentual": fin.outros_impostos_taxas_percentual,
        }
    logger.info(
        "Simulacao dados-base projeto {}: custos_fixos={}, custos_variaveis={}, media_pessoas={}",
        id,
        bool(financeiro and financeiro.get("custos_fixos")),
        bool(financeiro and financeiro.get("custos_variaveis")),
        media_pessoas_por_diaria,
    )
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
            "investimento_reforma": float(getattr(projeto, "investimento_reforma", 0) or 0),
            "arrendamento_total": float(getattr(projeto, "arrendamento_total", 0) or 0),
            "prazo_contrato_meses": int(getattr(projeto, "prazo_contrato_meses", 12) or 12),
        },
    })


@app.get("/api/projeto/<id>/simulacao/sugestao-arrendamento")
def api_simulacao_sugestao_arrendamento(id: str):
    """Sugere valor mensal de arrendamento com base no lucro operacional isolado e margem mínima sobre receita."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    margem_raw = request.args.get("margem", default="15")
    try:
        margem = float(margem_raw)
    except (TypeError, ValueError):
        margem = 15.0
    cid = (request.args.get("cenario") or "").strip() or None
    out = sugerir_arrendamento(id, cenario_id=cid, margem_minima_pct=margem)
    if out.get("erro"):
        code = 404 if out.get("codigo") == "projeto_nao_encontrado" else 400
        return jsonify({"success": False, "message": out.get("erro"), "data": out}), code
    return jsonify({"success": True, "data": out})


@app.post("/api/projeto/<id>/simulacao/salvar")
def api_simulacao_salvar(id: str):
    """Salva metas_mensais e parâmetros de investimento em simulacao_salva.json."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    body = request.get_json(force=True, silent=True) or {}
    metas_mensais = body.get("metas_mensais") or {}
    snap = _simulacao_investimento_para_persistencia(id, body)
    path = get_simulacao_salva_path(id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metas_mensais": metas_mensais,
        "investimento_reforma": snap["investimento_reforma"],
        "arrendamento_total": snap["arrendamento_total"],
        "prazo_contrato_meses": snap["prazo_contrato_meses"],
        "investimento_inicial": snap["investimento_inicial"],
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
    ov = _simulacao_investimento_from_body(body)
    resultado = calcular_projecao(
        id,
        metas_mensais,
        ov["investimento_reforma"],
        ov["arrendamento_total"],
        ov["prazo_contrato_meses"],
    )
    if "erro" in resultado:
        return jsonify({
            "success": False,
            "message": resultado.get("erro", "Erro na simulação"),
            "data": None,
        }), 404
    try:
        _persistir_overrides_simulacao_no_projeto(id, body)
    except Exception:
        logger.warning("Não foi possível persistir overrides de simulação no projeto {}", id)
    _log_system_event("etapa5_simulador_viabilidade_applied", id, {
        "evento": "etapa5_simulador_viabilidade_applied",
        "payback_meses": (resultado.get("resumo") or {}).get("payback_meses"),
    })
    return jsonify({"success": True, "data": resultado})


@app.post("/api/projeto/<id>/simulacao/projecao")
def api_simulacao_projecao(id: str):
    """
    Projeção simplificada: ocupacao_alvo (%), adr_override (opcional), investimento_inicial.
    Retorna projecao_mensal, totais_anuais, break_even_pct, payback_meses.
    """
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    from core.analise.simulacao import calcular_projecao, construir_metas_para_projecao

    body = request.get_json(force=True, silent=True) or {}
    ocupacao_alvo = body.get("ocupacao_alvo")
    if ocupacao_alvo is not None:
        ocupacao_alvo = float(ocupacao_alvo)
        ocupacao_alvo = max(0.0, min(1.0, ocupacao_alvo))
    adr_override = body.get("adr_override")
    ov = _simulacao_investimento_from_body(body)

    metas_mensais = body.get("metas_mensais")
    if not metas_mensais and ocupacao_alvo is not None:
        metas_mensais = construir_metas_para_projecao(id, ocupacao_alvo=ocupacao_alvo, adr_override=adr_override)
    if not metas_mensais:
        metas_mensais = construir_metas_para_projecao(id, ocupacao_alvo=ocupacao_alvo or 0.4, adr_override=adr_override)

    resultado = calcular_projecao(
        id,
        metas_mensais,
        ov["investimento_reforma"],
        ov["arrendamento_total"],
        ov["prazo_contrato_meses"],
    )
    if "erro" in resultado:
        return jsonify({
            "success": False,
            "message": resultado.get("erro", "Erro na simulação"),
            "data": None,
        }), 404
    try:
        _persistir_overrides_simulacao_no_projeto(id, body)
    except Exception:
        logger.warning("Não foi possível persistir overrides de simulação no projeto {}", id)

    resumo = resultado.get("resumo") or {}
    break_even_pct = None
    for m in resultado.get("meses") or []:
        if m.get("break_even_ocupacao_pct") is not None:
            break_even_pct = m.get("break_even_ocupacao_pct")
            break

    _log_system_event("etapa5_simulador_viabilidade_applied", id, {
        "evento": "etapa5_simulador_viabilidade_applied",
        "ocupacao_alvo": ocupacao_alvo,
        "payback_meses": resumo.get("payback_meses"),
    })

    return jsonify({
        "success": True,
        "data": {
            "projecao_mensal": resultado.get("meses"),
            "totais_anuais": {
                "receita_anual": resumo.get("receita_anual"),
                "lucro_anual": resumo.get("lucro_anual"),
                "ebitda_anual": resumo.get("ebitda_anual"),
                "lucro_medio_mensal": resumo.get("lucro_medio_mensal"),
                "investimento_total": resumo.get("investimento_total"),
                "roi_anual_pct": resumo.get("roi_anual_pct"),
            },
            "break_even_pct": break_even_pct,
            "break_even_receita_media": resumo.get("break_even_receita_media"),
            "payback_meses": resumo.get("payback_meses"),
            "payback_status": resumo.get("payback_status"),
        },
    })


@app.post("/api/projeto/<id>/simulacao/curva-sensibilidade")
def api_simulacao_curva_sensibilidade(id: str):
    """Retorna pontos (ocupacao_pct, lucro_anual, lucro_medio_mensal) para gráfico de sensibilidade."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    from core.analise.simulacao import calcular_curva_sensibilidade

    body = request.get_json(force=True, silent=True) or {}
    ov = _simulacao_investimento_from_body(body)
    metas_mensais = body.get("metas_mensais") or {}
    passo = float(body.get("passo_ocupacao") or 0.1)
    passo = max(0.05, min(0.25, passo))
    pontos = calcular_curva_sensibilidade(
        id,
        ov["investimento_reforma"],
        metas_mensais,
        passo_ocupacao=passo,
        arrendamento_total=ov["arrendamento_total"],
        prazo_contrato_meses=ov["prazo_contrato_meses"],
    )
    try:
        _persistir_overrides_simulacao_no_projeto(id, body)
    except Exception:
        logger.warning("Não foi possível persistir overrides de simulação no projeto {}", id)
    return jsonify({"success": True, "data": {"pontos": pontos}})


def _carregar_cenarios(id_projeto: str) -> list[dict]:
    """Carrega lista de cenários de cenarios.json (fallback legado simulacao_cenarios.json)."""
    path = get_cenarios_path(id_projeto)
    path_legado = get_simulacao_cenarios_path(id_projeto)
    if (not path.exists() or not path.is_file()) and path_legado.exists() and path_legado.is_file():
        path = path_legado
    if not path.exists() or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("cenarios") if isinstance(data.get("cenarios"), list) else []
    except (json.JSONDecodeError, OSError) as e:
        _log_io_error("carregar_cenarios", id_projeto, str(e))
        return []


def _salvar_cenarios(id_projeto: str, cenarios: list[dict]) -> None:
    """Persiste lista de cenários em cenarios.json com escrita atômica."""
    path = get_cenarios_path(id_projeto)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    content = json.dumps({"cenarios": cenarios}, ensure_ascii=False, indent=2)
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        _log_io_error("salvar_cenarios", id_projeto, str(e))
        raise


def _migrar_simulacao_salva_para_cenarios(id_projeto: str) -> list[dict]:
    """Se simulacao_cenarios.json não existir mas simulacao_salva.json existir, cria cenário inicial."""
    path_cenarios = get_cenarios_path(id_projeto)
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
    invest = float(
        dados.get("investimento_reforma")
        if dados.get("investimento_reforma") is not None
        else (dados.get("investimento_inicial") or 0)
    )
    arr_tot = dados.get("arrendamento_total")
    prazo_d = dados.get("prazo_contrato_meses")
    p = carregar_projeto(id_projeto)
    arr_f = float(arr_tot) if arr_tot is not None else float(p.arrendamento_total)
    prazo_i = int(prazo_d) if prazo_d is not None else int(p.prazo_contrato_meses or 12)
    prazo_i = max(1, min(600, prazo_i))
    import uuid
    from datetime import datetime
    cenario = {
        "id": str(uuid.uuid4())[:8],
        "nome": "Cenário atual",
        "criado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metas_mensais": metas,
        "investimento_reforma": invest,
        "arrendamento_total": arr_f,
        "prazo_contrato_meses": prazo_i,
        "investimento_inicial": invest,
    }
    cenarios = [cenario]
    _salvar_cenarios(id_projeto, cenarios)
    return cenarios


# -----------------------------------------------------------------------------
# BLOCO LEGADO / DEPRECATED (compatibilidade)
# -----------------------------------------------------------------------------
# As rotinas acima mantêm compatibilidade com formatos históricos:
# - simulacao_cenarios.json (legado)
# - simulacao_salva.json (legado de transição para cenarios.json)
# Novas funcionalidades devem usar somente cenarios.json via get_cenarios_path().
# -----------------------------------------------------------------------------


@app.get("/api/projeto/<id>/simulacao/cenarios")
def api_simulacao_listar_cenarios(id: str):
    """Lista cenários com KPIs recalculados (metas do cenário + custos/investimento atuais do projeto)."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    lista = comparar_cenarios_projeto(id)
    return jsonify({"success": True, "data": {"cenarios": lista}})


@app.get("/api/projeto/<id>/cenarios")
def api_cenarios_listar(id: str):
    """Lista cenários persistidos em data/projects/<id>/cenarios.json."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404
    cenarios = _carregar_cenarios(id)
    resp = jsonify({"success": True, "data": {"cenarios": cenarios}})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.post("/api/projeto/<id>/cenarios")
def api_cenarios_salvar(id: str):
    """Salva novo cenário validando payload mínimo via Pydantic."""
    try:
        carregar_projeto(id)
    except ArquivoProjetoNaoEncontrado:
        return jsonify({"success": False, "message": "Projeto não encontrado", "data": None}), 404

    body = request.get_json(force=True, silent=True) or {}
    try:
        payload = CenarioPayload.model_validate(body)
    except ValidationError as e:
        return jsonify({"success": False, "message": "Payload de cenário inválido", "errors": e.errors()}), 400

    import uuid
    cenario = {
        "id": str(uuid.uuid4())[:8],
        "criado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nome": payload.nome,
        "ocupacao_alvo": payload.ocupacao_alvo,
        "adr_projetado": payload.adr_projetado,
        "lucro_estimado": payload.lucro_estimado,
    }
    cenarios = _carregar_cenarios(id)
    cenarios.append(cenario)
    try:
        _salvar_cenarios(id, cenarios)
    except OSError:
        return jsonify({"success": False, "message": "Erro de IO ao salvar cenário"}), 500
    return jsonify({"success": True, "message": "Cenário salvo com sucesso.", "data": cenario}), 201


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
    snap = _simulacao_investimento_para_persistencia(id, body)
    # Fonte única de cálculo: não persistir resultado (payload pode enviar; ignoramos).
    cenarios = _carregar_cenarios(id)
    if not cenarios:
        cenarios = _migrar_simulacao_salva_para_cenarios(id)
    idx = next((i for i, c in enumerate(cenarios) if c.get("id") == cid), None)
    if cid and idx is not None:
        cenario = cenarios[idx]
        cenario["nome"] = (body.get("nome") or "").strip() or cenario.get("nome") or "Sem nome"
        cenario["metas_mensais"] = metas_mensais
        cenario["investimento_reforma"] = snap["investimento_reforma"]
        cenario["arrendamento_total"] = snap["arrendamento_total"]
        cenario["prazo_contrato_meses"] = snap["prazo_contrato_meses"]
        cenario["investimento_inicial"] = snap["investimento_inicial"]
        if "descricao" in body:
            d = body.get("descricao")
            if isinstance(d, str) and d.strip():
                cenario["descricao"] = d.strip()
            else:
                cenario.pop("descricao", None)
        cenario.pop("resultado", None)
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
        "investimento_reforma": snap["investimento_reforma"],
        "arrendamento_total": snap["arrendamento_total"],
        "prazo_contrato_meses": snap["prazo_contrato_meses"],
        "investimento_inicial": snap["investimento_inicial"],
    }
    d_new = body.get("descricao")
    if isinstance(d_new, str) and d_new.strip():
        cenario["descricao"] = d_new.strip()
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
            c_out = {k: v for k, v in c.items() if k != "resultado"}
            return jsonify({"success": True, "data": c_out})
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
