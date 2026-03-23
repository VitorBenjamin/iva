"""
desconto - Fonte única de desconto para Curadoria (ATO 3.1).
"""
from __future__ import annotations

import json
from decimal import Decimal

from core.config import carregar_config_scraper
from core.projetos import (
    _log_system_event,
    get_market_curado_path,
    read_curadoria_desconto,
)


def _normalizar_desconto_raw(v) -> Decimal | None:
    """Normaliza desconto para Decimal em [0, 1). Aceita 0.15 e 15."""
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(",", "."))
    except Exception:
        return None
    if d > 1:
        d = d / Decimal("100")
    if d < 0:
        d = Decimal("0")
    if d >= 1:
        d = Decimal("0.99")
    return d


def _mes_chave(mes_ano: str | None) -> str:
    if mes_ano and isinstance(mes_ano, str) and "-" in mes_ano:
        return mes_ano.split("-")[1]
    return ""


def _desconto_market_curado_meta(id_projeto: str, mes_ano: str | None) -> Decimal | None:
    path = get_market_curado_path(id_projeto)
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    # Período específico: aceita chave full (YYYY-MM) e MM.
    if mes_ano:
        por_mes = meta.get("desconto_por_mes") or meta.get("descontos_por_mes") or {}
        if isinstance(por_mes, dict):
            if mes_ano in por_mes:
                return _normalizar_desconto_raw(por_mes.get(mes_ano))
            mm = _mes_chave(mes_ano)
            if mm and mm in por_mes:
                return _normalizar_desconto_raw(por_mes.get(mm))
    return _normalizar_desconto_raw(meta.get("desconto"))


def _desconto_scraper_config(id_projeto: str, mes_ano: str | None) -> Decimal:
    cfg = carregar_config_scraper(id_projeto) or {}
    descontos = cfg.get("descontos") or {}
    por_mes = descontos.get("por_mes") or {}
    mm = _mes_chave(mes_ano)
    if mm and mm in por_mes:
        val = _normalizar_desconto_raw(por_mes.get(mm))
        if val is not None:
            return val
    global_desc = _normalizar_desconto_raw(descontos.get("global", 0.20))
    return global_desc if global_desc is not None else Decimal("0.20")


def obter_desconto_para_curadoria(id_projeto: str, mes_ano: str | None) -> Decimal:
    """Retorna desconto para Curadoria com prioridade:
    projeto.curadoria.desconto_padrao > market_curado.meta.desconto > scraper_config.descontos
    """
    desconto_projeto = read_curadoria_desconto(id_projeto)
    if desconto_projeto is not None:
        return desconto_projeto

    desconto_curado = _desconto_market_curado_meta(id_projeto, mes_ano)
    if desconto_curado is not None:
        _log_system_event(
            "desconto_fonte_market_curado_meta",
            action="obter_desconto_para_curadoria",
            id_projeto=id_projeto,
            mes_ano=mes_ano,
            user="cursor-job",
        )
        return desconto_curado

    fallback = _desconto_scraper_config(id_projeto, mes_ano)
    _log_system_event(
        "desconto_fallback_scraper_config",
        action="obter_desconto_para_curadoria",
        id_projeto=id_projeto,
        mes_ano=mes_ano,
        user="cursor-job",
    )
    return fallback
