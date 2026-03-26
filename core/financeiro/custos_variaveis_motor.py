"""
Motor de custos variáveis por incidência (hóspede·noite, UH·noite, reserva, % receita).
Usado por simulação e engenharia reversa.
"""
from __future__ import annotations

from typing import Iterator

from core.financeiro.modelos import CustoVariavelItem, CustosVariaveisPorNoite, IncidenciaCustoVariavel

ITENS_NOMES: tuple[tuple[str, str], ...] = (
    ("cafe_manha", "Café da Manhã"),
    ("amenities", "Amenities"),
    ("lavanderia", "Lavanderia"),
    ("outros", "Outros"),
)

ROTULO_UNIDADE: dict[str, str] = {
    "hospede_noite": "hóspede·noite",
    "uh_noite": "UH·noite",
    "reserva": "reserva",
    "percentual_receita": "% receita",
}


def incidencia_str(item: CustoVariavelItem) -> str:
    x = item.incidencia
    if isinstance(x, IncidenciaCustoVariavel):
        return str(x.value)
    return str(x or "hospede_noite")


def iter_itens_custos_variaveis(cv: CustosVariaveisPorNoite) -> Iterator[tuple[str, str, CustoVariavelItem]]:
    for chave, nome in ITENS_NOMES:
        item = getattr(cv, chave, None)
        if item is None:
            continue
        yield chave, nome, item


def subtotal_custo_item(
    item: CustoVariavelItem,
    *,
    noites_vendidas: float,
    receita_bruta: float,
    media_pessoas: float,
    permanencia_media: float,
) -> float:
    v = max(0.0, float(item.valor or 0.0))
    inc = incidencia_str(item)
    nv = max(0.0, float(noites_vendidas))
    rb = max(0.0, float(receita_bruta))
    mp = max(0.1, min(10.0, float(media_pessoas)))
    pm = max(0.5, min(30.0, float(permanencia_media or 2.0)))

    if inc == IncidenciaCustoVariavel.HOSPEDE_NOITE.value:
        return v * nv * mp
    if inc == IncidenciaCustoVariavel.UH_NOITE.value:
        return v * nv
    if inc == IncidenciaCustoVariavel.RESERVA.value:
        return v * (nv / pm) if pm > 0 else 0.0
    if inc == IncidenciaCustoVariavel.PERCENTUAL_RECEITA.value:
        return rb * (v / 100.0)
    return v * nv * mp


def soma_marginal_linear_por_noite(
    cv: CustosVariaveisPorNoite,
    *,
    media_pessoas: float,
    permanencia_media: float,
) -> float:
    """Parcela de custo variável que escala linearmente com noites vendidas (break-even)."""
    mp = max(0.1, min(10.0, float(media_pessoas)))
    pm = max(0.5, min(30.0, float(permanencia_media or 2.0)))
    total = 0.0
    for _c, _n, item in iter_itens_custos_variaveis(cv):
        v = max(0.0, float(item.valor or 0.0))
        inc = incidencia_str(item)
        if inc == IncidenciaCustoVariavel.HOSPEDE_NOITE.value:
            total += v * mp
        elif inc == IncidenciaCustoVariavel.UH_NOITE.value:
            total += v
        elif inc == IncidenciaCustoVariavel.RESERVA.value:
            total += (v / pm) if pm > 0 else 0.0
    return max(total, 0.0)


def soma_fracoes_percentual_receita_itens(cv: CustosVariaveisPorNoite) -> float:
    """Soma (valor/100) para itens com incidência percentual_receita (0–1)."""
    s = 0.0
    for _c, _n, item in iter_itens_custos_variaveis(cv):
        if incidencia_str(item) != IncidenciaCustoVariavel.PERCENTUAL_RECEITA.value:
            continue
        s += max(0.0, float(item.valor or 0.0)) / 100.0
    return min(max(s, 0.0), 0.999)


def custo_variavel_operacional_mensal_total(
    cv: CustosVariaveisPorNoite,
    *,
    noites_vendidas: float,
    receita_bruta: float,
    media_pessoas: float,
    permanencia_media: float,
    comissao_pct: float,
) -> float:
    """Soma itens cadastrais + comissão de venda (% receita bruta)."""
    total = 0.0
    for _c, _n, item in iter_itens_custos_variaveis(cv):
        total += subtotal_custo_item(
            item,
            noites_vendidas=noites_vendidas,
            receita_bruta=receita_bruta,
            media_pessoas=media_pessoas,
            permanencia_media=permanencia_media,
        )
    com = max(0.0, min(1.0, float(comissao_pct))) * max(0.0, float(receita_bruta))
    return total + com


def listar_itens_cadastro_relatorio(cv: CustosVariaveisPorNoite) -> list[dict[str, str | float]]:
    """Linhas para PDF / relatório com valor e unidade de incidência."""
    out: list[dict[str, str | float]] = []
    for _c, nome, item in iter_itens_custos_variaveis(cv):
        v = max(0.0, float(item.valor or 0.0))
        inc = incidencia_str(item)
        rot = ROTULO_UNIDADE.get(inc, inc)
        out.append(
            {
                "nome": nome,
                "valor": round(v, 2),
                "incidencia": inc,
                "rotulo_incidencia": rot,
            }
        )
    return out
