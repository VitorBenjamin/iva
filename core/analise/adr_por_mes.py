"""
adr_por_mes - Extração de ADR mensal a partir de market_bruto + market_curado + scraper_config.
Responsabilidade: calcular ADR por mês com descontos aplicados on-the-fly (nunca persistir).
Prioridade: curado > direto > propagação de evento > url concorrente > referência > média.
Fallback multi-base: se ADR ausente/zero, tenta projetos_referencia (cache implícito por chamada).
Etapa 4: expansão de dias do evento — dias no range [inicio,fim] sem coleta recebem preço do período.
"""
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from pydantic import ValidationError

from core.projetos import (
    PROJECTS_DIR,
    get_market_bruto_path,
    get_market_curado_path,
    get_projeto_json_path,
    read_project_json,
    _log_system_event,
)
from core.analise.desconto import obter_desconto_para_curadoria
from core.scraper.modelos import MarketBruto, MarketCurado


def _obter_projetos_referencia(id_projeto: str) -> list[str]:
    """Lê projetos_referencia do projeto; exclui o próprio ID e refs inexistentes."""
    path = get_projeto_json_path(id_projeto)
    if not path.exists() or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        refs = data.get("projetos_referencia") or []
        if not isinstance(refs, list):
            return []
        return [
            str(r).strip() for r in refs
            if r and str(r).strip() != id_projeto
            and get_projeto_json_path(str(r).strip()).exists()
        ]
    except (json.JSONDecodeError, OSError):
        return []


def obter_adr_por_mes(id_projeto: str, *, _skip_ref_fallback: bool = False) -> dict[str, dict]:
    """
    Retorna ADR por mês com fonte (curado | direto | fallback_ref | fallback_media).
    Desconto aplicado on-the-fly, nunca persiste alterações nos arquivos.
    _skip_ref_fallback: quando True, não tenta projetos_referencia (evita recursão).
    """
    result: dict[str, dict] = {}

    path_bruto = get_market_bruto_path(id_projeto)
    if not path_bruto.exists():
        path_bruto = PROJECTS_DIR / f"market_bruto_{id_projeto}.json"
    bruto: MarketBruto | None = None
    if path_bruto.exists() and path_bruto.is_file():
        try:
            raw = path_bruto.read_text(encoding="utf-8")
            if raw and raw.strip():
                bruto = MarketBruto.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    curado_por_checkin: dict[str, float] = {}
    path_curado = get_market_curado_path(id_projeto)
    if not path_curado.exists():
        path_curado = PROJECTS_DIR / f"market_curado_{id_projeto}.json"
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

    valores_por_mes: dict[str, list[tuple[float, str]]] = defaultdict(list)
    if bruto:
        for r in bruto.registros:
            valor_efetivo: float | None = None
            fonte = "fallback_media"
            if r.checkin in curado_por_checkin:
                valor_efetivo = curado_por_checkin[r.checkin]
                fonte = "curado"
            elif r.preco_booking is not None and r.preco_booking > 0:
                desconto = obter_desconto_para_curadoria(id_projeto, r.mes_ano)
                meta = r.meta or {}
                preco_base = float(r.preco_booking)
                if bool(meta.get("preco_booking_eh_total")) and (r.noites or 0) > 0:
                    preco_base = float(r.preco_booking) / float(r.noites)
                bruto_dec = Decimal(str(preco_base))
                valor_efetivo_dec = (bruto_dec * (Decimal("1") - desconto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                valor_efetivo = float(valor_efetivo_dec)
                if str(meta.get("fonte_url") or "").strip().lower() == "concorrente":
                    fonte = "concorrente_url"
                else:
                    fonte = "direto"
            if valor_efetivo is not None and valor_efetivo > 0:
                valores_por_mes[r.mes_ano].append((valor_efetivo, fonte))

    # Etapa 4: expandir dias do evento — dias no range sem coleta recebem preço do período
    if bruto:
        from core.config import _periodos_especiais_de_config, get_periodo_config_por_data
        periodos = _periodos_especiais_de_config(id_projeto)
        checkins_com_valor = set()
        periodo_vals: dict[str, list[float]] = {}
        for r in bruto.registros:
            val = None
            if r.checkin in curado_por_checkin:
                val = curado_por_checkin[r.checkin]
            elif r.preco_booking is not None and r.preco_booking > 0:
                desconto = obter_desconto_para_curadoria(id_projeto, r.mes_ano)
                meta = r.meta or {}
                preco_base = float(r.preco_booking)
                if bool(meta.get("preco_booking_eh_total")) and (r.noites or 0) > 0:
                    preco_base = float(r.preco_booking) / float(r.noites)
                val = float((Decimal(str(preco_base)) * (Decimal("1") - desconto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            elif r.preco_direto is not None and r.preco_direto > 0:
                val = float(r.preco_direto)
            if val is not None and val > 0:
                checkins_com_valor.add(r.checkin)
                periodo = get_periodo_config_por_data(periodos, r.checkin)
                if periodo and periodo.get("periodo_id"):
                    periodo_vals.setdefault(periodo["periodo_id"], []).append(val)
        for p in periodos:
            if not isinstance(p, dict):
                continue
            pid = p.get("periodo_id")
            d_ini = p.get("inicio_date")
            d_fim = p.get("fim_date")
            if not pid or not d_ini or not d_fim:
                continue
            vals_p = periodo_vals.get(pid, [])
            if not vals_p:
                continue
            avg_p = round(sum(vals_p) / len(vals_p), 2)
            d = d_ini
            while d <= d_fim:
                checkin = d.isoformat()
                if checkin not in checkins_com_valor:
                    mes_ano = f"{d.year}-{d.month:02d}"
                    valores_por_mes[mes_ano].append((avg_p, "propagado_periodo"))
                    _log_system_event(
                        "etapa4_range_correction_applied",
                        action="obter_adr_por_mes",
                        id_projeto=id_projeto,
                        mes_ano=mes_ano,
                        checkin=checkin,
                        periodo_id=pid,
                        user="cursor-job",
                    )
                d += timedelta(days=1)

    for mes_ano, vals in valores_por_mes.items():
        if vals:
            adr = sum(v[0] for v in vals) / len(vals)
            fontes = {v[1] for v in vals}
            if "curado" in fontes:
                fonte = "curado"
            elif "direto" in fontes:
                fonte = "direto"
            elif "propagado_periodo" in fontes:
                fonte = "propagado_periodo"
            elif "concorrente_url" in fontes:
                fonte = "concorrente_url"
            else:
                fonte = "fallback_ref" if "fallback_ref" in fontes else "fallback_media"
            result_item = {
                "adr": round(adr, 2),
                "fonte": fonte,
            }
            if fonte == "concorrente_url":
                # Busca primeira URL concorrente usada no mês para tooltip e rastreabilidade.
                concorrente_url = None
                for r in (bruto.registros if bruto else []):
                    if r.mes_ano != mes_ano:
                        continue
                    meta = r.meta or {}
                    if str(meta.get("fonte_url") or "").strip().lower() == "concorrente":
                        concorrente_url = meta.get("url_fonte")
                        if concorrente_url:
                            break
                if concorrente_url:
                    result_item["concorrente_url"] = str(concorrente_url)
            result[mes_ano] = result_item

    ano_ref = "2025"
    for ma in list(result.keys()):
        if ma and "-" in ma:
            ano_ref = ma.split("-")[0]
            break
    meses_alvo = [f"{ano_ref}-{m:02d}" for m in range(1, 13)]

    # Fallback multi-base: tenta projetos_referencia antes de fallback_media (sem recursão)
    if not _skip_ref_fallback:
        refs = _obter_projetos_referencia(id_projeto)
        proj_data = read_project_json(id_projeto) or {}
        markup = proj_data.get("markup_referencia")
        if markup is not None:
            try:
                markup = float(markup)
                if not (0.01 <= markup <= 10.0):
                    markup = None
            except (TypeError, ValueError):
                markup = None

        ref_adr_cache: dict[str, dict[str, dict]] = {}
        for ref_id in refs:
            if ref_id not in ref_adr_cache:
                ref_adr_cache[ref_id] = obter_adr_por_mes(ref_id, _skip_ref_fallback=True)

        for mes_ano in meses_alvo:
            adr_atual = result.get(mes_ano, {}).get("adr", 0) or 0
            if adr_atual > 0:
                continue
            for ref_id in refs:
                ref_data = ref_adr_cache.get(ref_id, {})
                ref_entry = ref_data.get(mes_ano, {})
                ref_adr = ref_entry.get("adr", 0) or 0
                if ref_adr <= 0:
                    continue
                if markup is not None:
                    ref_adr = round(ref_adr * markup, 2)
                ref_proj = read_project_json(ref_id) or {}
                nome_ref = ref_proj.get("nome") or ref_id
                result[mes_ano] = {
                    "adr": ref_adr,
                    "fonte": "fallback_ref",
                    "id_referencia": ref_id,
                    "nome_referencia": str(nome_ref),
                }
                _log_system_event(
                    "etapa3_fallback_multibase_applied",
                    action="obter_adr_por_mes",
                    id_projeto=id_projeto,
                    mes_ano=mes_ano,
                    id_referencia=ref_id,
                    user="cursor-job",
                )
                break

    if not result:
        return result

    media_geral = sum(d["adr"] for d in result.values()) / len(result)
    for mes_ano in meses_alvo:
        if mes_ano not in result or not (result[mes_ano].get("adr") or 0):
            result[mes_ano] = {
                "adr": round(media_geral, 2),
                "fonte": "fallback_media",
            }
            _log_system_event(
                "adr_fallback_media",
                action="obter_adr_por_mes",
                id_projeto=id_projeto,
                mes_ano=mes_ano,
                user="cursor-job",
            )

    return dict(sorted(result.items()))
