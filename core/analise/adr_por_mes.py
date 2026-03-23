"""
adr_por_mes - Extração de ADR mensal a partir de market_bruto + market_curado + scraper_config.
Responsabilidade: calcular ADR por mês com descontos aplicados on-the-fly (nunca persistir).
Prioridade: preco_curado > preco_direto com desconto > preco_booking bruto.
"""
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from pydantic import ValidationError

from core.projetos import PROJECTS_DIR, get_market_bruto_path, get_market_curado_path
from core.analise.desconto import obter_desconto_para_curadoria
from core.projetos import _log_system_event
from core.scraper.modelos import MarketBruto, MarketCurado


def obter_adr_por_mes(id_projeto: str) -> dict[str, dict]:
    """
    Retorna ADR por mês com fonte (curado | direto | fallback_media).
    Desconto aplicado on-the-fly, nunca persiste alterações nos arquivos.
    """
    result: dict[str, dict] = {}

    path_bruto = get_market_bruto_path(id_projeto)
    if not path_bruto.exists():
        path_bruto = PROJECTS_DIR / f"market_bruto_{id_projeto}.json"
    if not path_bruto.exists() or not path_bruto.is_file():
        return result

    try:
        raw = path_bruto.read_text(encoding="utf-8")
        if not raw or not raw.strip():
            return result
        bruto = MarketBruto.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, ValueError):
        return result

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
    for r in bruto.registros:
        valor_efetivo: float | None = None
        fonte = "fallback_media"
        if r.checkin in curado_por_checkin:
            valor_efetivo = curado_por_checkin[r.checkin]
            fonte = "curado"
        elif r.preco_booking is not None and r.preco_booking > 0:
            desconto = obter_desconto_para_curadoria(id_projeto, r.mes_ano)
            bruto_dec = Decimal(str(r.preco_booking))
            valor_efetivo_dec = (bruto_dec * (Decimal("1") - desconto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            valor_efetivo = float(valor_efetivo_dec)
            fonte = "direto"
        if valor_efetivo is not None and valor_efetivo > 0:
            valores_por_mes[r.mes_ano].append((valor_efetivo, fonte))

    for mes_ano, vals in valores_por_mes.items():
        if vals:
            adr = sum(v[0] for v in vals) / len(vals)
            fontes = set(v[1] for v in vals)
            result[mes_ano] = {
                "adr": round(adr, 2),
                "fonte": "curado" if "curado" in fontes else "direto",
            }

    if not result:
        return result

    media_geral = sum(d["adr"] for d in result.values()) / len(result)
    ano_ref = None
    for ma in result:
        if ma and "-" in ma:
            ano_ref = ma.split("-")[0]
            break
    ano_ref = ano_ref or "2025"
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        if mes_ano not in result:
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
