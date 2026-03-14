"""
simulacao - Projeção financeira com metas de ocupação e ADR.
Responsabilidade: calcular receita, custos, lucro, break-even e payback.
Reutiliza funções de engenharia_reversa.py; não modifica arquivos de dados.
"""
import calendar
from typing import Any

from core.projetos import carregar_projeto
from core.projetos import ArquivoProjetoNaoEncontrado
from core.analise.engenharia_reversa import (
    _calcular_break_even,
    _custo_fixo_mensal_total,
    _custo_variavel_por_noite,
    _impostos_sobre_faturamento,
)


def calcular_projecao(
    id_projeto: str,
    metas_mensais: dict[str, dict],
    investimento_inicial: float,
) -> dict[str, Any]:
    """
    Calcula projeção financeira mensal e anual.
    metas_mensais: {"2025-01": {"ocupacao": 0.65, "adr": 420}, ...}
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {
            "erro": "Projeto não encontrado",
            "codigo": "projeto_nao_encontrado",
        }

    numero_quartos = max(projeto.numero_quartos or 1, 1)
    custo_fixo_mensal = _custo_fixo_mensal_total(projeto)
    custo_var_noite = _custo_variavel_por_noite(projeto, ocupacao_media_pessoas=2.0)

    meses_result: list[dict[str, Any]] = []
    receita_anual = 0.0
    lucro_anual = 0.0

    ano_ref = projeto.ano_referencia or 2025

    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        metas = metas_mensais.get(mes_ano) or {}
        ocupacao = float(metas.get("ocupacao", 0.0))
        adr = float(metas.get("adr", 0.0))
        adr = max(adr, 0.0)
        ocupacao = max(0.0, min(1.0, ocupacao))

        dias_mes = calendar.monthrange(ano_ref, mes)[1]
        capacidade_mes = numero_quartos * dias_mes
        noites_vendidas = capacidade_mes * ocupacao
        receita_bruta = adr * noites_vendidas
        custos_variaveis = noites_vendidas * custo_var_noite
        impostos = _impostos_sobre_faturamento(receita_bruta, projeto)
        lucro_liquido = receita_bruta - custo_fixo_mensal - custos_variaveis - impostos

        receita_anual += receita_bruta
        lucro_anual += lucro_liquido

        noites_break_even = 0.0
        break_even_pct: float | None = None
        break_even_status = "ok"
        if adr > custo_var_noite and custo_fixo_mensal > 0:
            noites_break_even = _calcular_break_even(
                adr_anual=adr,
                projeto=projeto,
                custo_var_noite=custo_var_noite,
                faturamento_anual_total=receita_bruta * 12,
            )
            if capacidade_mes > 0:
                break_even_pct = min(noites_break_even / capacidade_mes, 1.0)
        else:
            break_even_status = "inviavel"

        meses_result.append({
            "mes_ano": mes_ano,
            "dias_mes": dias_mes,
            "noites_vendidas": round(noites_vendidas, 2),
            "receita_bruta": round(receita_bruta, 2),
            "custos_fixos": round(custo_fixo_mensal, 2),
            "custos_variaveis": round(custos_variaveis, 2),
            "impostos": round(impostos, 2),
            "lucro_liquido": round(lucro_liquido, 2),
            "break_even_ocupacao_pct": round(break_even_pct, 4) if break_even_pct is not None else None,
            "break_even_status": break_even_status,
        })

    lucro_medio_mensal = lucro_anual / 12.0 if lucro_anual else 0.0
    payback_meses: float | None = None
    payback_status = "ok"
    if lucro_medio_mensal > 0 and investimento_inicial > 0:
        payback_meses = investimento_inicial / lucro_medio_mensal
    elif investimento_inicial > 0 and lucro_anual <= 0:
        payback_status = "indefinido"

    return {
        "meses": meses_result,
        "resumo": {
            "receita_anual": round(receita_anual, 2),
            "lucro_anual": round(lucro_anual, 2),
            "lucro_medio_mensal": round(lucro_medio_mensal, 2),
            "payback_meses": round(payback_meses, 2) if payback_meses is not None else None,
            "payback_status": payback_status,
        },
    }
