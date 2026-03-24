"""
simulacao - Projeção financeira com metas de ocupação e ADR.
Responsabilidade: calcular receita, custos, lucro, EBITDA, break-even e payback.
Usa calendário diário: meta aplicada a dias normais; dias especiais com ocupação 100%.

Fórmulas (conforme análise contábil):
- Custos Variáveis = (noites × custo_var_noite) + (Receita Bruta × comissao_venda_pct)
  → Comissão de venda (ex: Booking 13%) é custo variável SOBRE RECEITA, não por quarto.
- EBITDA = Receita Bruta - Custos Fixos - Custos Variáveis
- Lucro Líquido = EBITDA - Impostos (imposto deduzido após EBITDA)
"""
import calendar
from typing import Any

from core.projetos import carregar_projeto
from core.projetos import ArquivoProjetoNaoEncontrado
from core.analise.adr_por_mes import obter_adr_por_mes
from core.analise.engenharia_reversa import (
    _custo_fixo_mensal_total,
    _dias_normais_especiais_por_mes,
    _custo_variavel_por_noite,
    _impostos_sobre_faturamento,
)


def _calcular_break_even_ebitda(
    adr: float,
    custo_fixo_mensal: float,
    custo_var_noite: float,
    comissao_pct: float,
    capacidade_mes: float,
) -> tuple[float, float | None]:
    """
    Break-even operacional (EBITDA >= 0).
    Receita*(1-comissao) - Fixos - noites*custo_var = 0  =>  noites = Fixos / (ADR*(1-comissao) - custo_var)
    Retorna (noites, break_even_pct) ou (0, None) se inviável.
    """
    if capacidade_mes <= 0:
        return 0.0, None
    adr_efetivo = adr * (1.0 - comissao_pct) if comissao_pct < 1.0 else 0.0
    denominador = adr_efetivo - custo_var_noite
    if denominador <= 0 or custo_fixo_mensal <= 0:
        return 0.0, None
    noites = custo_fixo_mensal / denominador
    pct = min(noites / capacidade_mes, 1.0)
    return noites, pct


def construir_metas_para_projecao(
    id_projeto: str,
    ocupacao_alvo: float | None = None,
    adr_override: float | None | dict[str, float] = None,
) -> dict[str, dict]:
    """
    Constrói metas_mensais a partir de ocupacao_alvo e adr_override.
    Se ocupacao_alvo não informado, usa 0.4 (40%). Se adr_override não informado, usa obter_adr_por_mes.
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {}
    ano_ref = projeto.ano_referencia or 2025
    adr_por_mes = obter_adr_por_mes(id_projeto)
    ocup = max(0.0, min(1.0, ocupacao_alvo if ocupacao_alvo is not None else 0.4))
    adr_override_dict = adr_override if isinstance(adr_override, dict) else None
    adr_override_val = float(adr_override) if isinstance(adr_override, (int, float)) else None

    metas: dict[str, dict] = {}
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        info = adr_por_mes.get(mes_ano) or {}
        adr = adr_override_dict.get(mes_ano) if adr_override_dict else None
        if adr is None and adr_override_val is not None:
            adr = adr_override_val
        if adr is None:
            adr = info.get("adr") if isinstance(info, dict) else (info if isinstance(info, (int, float)) else 0)
        metas[mes_ano] = {"ocupacao": ocup, "adr": float(adr or 0)}
    return metas


def calcular_projecao(
    id_projeto: str,
    metas_mensais: dict[str, dict],
    investimento_inicial: float,
) -> dict[str, Any]:
    """
    Calcula projeção financeira mensal e anual.
    metas_mensais: {"2025-01": {"ocupacao": 0.65, "adr": 420}, ...}

    EBITDA = Receita - Custos Fixos - Custos Variáveis (imposto NÃO entra).
    Lucro Líquido = EBITDA - Impostos.
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
    custo_var_noite = _custo_variavel_por_noite(projeto)
    dias_por_mes = _dias_normais_especiais_por_mes(projeto)

    fin = getattr(projeto, "financeiro", None)
    comissao_pct = float(getattr(fin, "comissao_venda_pct", 0.0) or 0.0)
    comissao_pct = max(0.0, min(1.0, comissao_pct))

    cv = getattr(fin, "custos_variaveis", None) if fin else None
    media_pessoas = float(getattr(fin, "media_pessoas_por_diaria", 2.0) or 2.0)
    media_pessoas = max(0.1, min(10.0, media_pessoas))
    _itens_cv = [
        ("Café da Manhã", float(getattr(cv, "cafe_manha", 0.0) or 0.0)),
        ("Amenities", float(getattr(cv, "amenities", 0.0) or 0.0)),
        ("Lavanderia", float(getattr(cv, "lavanderia", 0.0) or 0.0)),
        ("Outros", float(getattr(cv, "outros", 0.0) or 0.0)),
    ]
    itens_cv_unitarios = [(nome, val * media_pessoas) for nome, val in _itens_cv]

    meses_result: list[dict[str, Any]] = []
    receita_anual = 0.0
    lucro_anual = 0.0
    ebitda_anual = 0.0
    break_even_receitas: list[float] = []

    ano_ref = projeto.ano_referencia or 2025

    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        metas = metas_mensais.get(mes_ano) or {}
        ocupacao_meta = float(metas.get("ocupacao", 0.0))
        adr = float(metas.get("adr", 0.0))
        adr = max(adr, 0.0)
        ocupacao_meta = max(0.0, min(1.0, ocupacao_meta))

        dias_mes = calendar.monthrange(ano_ref, mes)[1]
        dias_normais, dias_especiais = dias_por_mes.get(mes_ano, (dias_mes, 0))
        if dias_normais + dias_especiais != dias_mes:
            dias_normais = dias_mes - dias_especiais

        capacidade_normal = numero_quartos * dias_normais
        capacidade_especial = numero_quartos * dias_especiais
        ocupacao_especial = max(1.0, ocupacao_meta)
        noites_normais = capacidade_normal * ocupacao_meta
        noites_especiais = capacidade_especial * ocupacao_especial
        noites_vendidas = noites_normais + noites_especiais
        capacidade_mes = numero_quartos * dias_mes
        receita_bruta = adr * noites_vendidas

        # Custos variáveis: operacionais por noite + comissão sobre receita (%)
        cv_operacionais = noites_vendidas * custo_var_noite
        cv_comissao = receita_bruta * comissao_pct
        custos_variaveis = cv_operacionais + cv_comissao

        ebitda = receita_bruta - custo_fixo_mensal - custos_variaveis
        impostos = _impostos_sobre_faturamento(receita_bruta, projeto)
        lucro_liquido = ebitda - impostos

        receita_anual += receita_bruta
        lucro_anual += lucro_liquido
        ebitda_anual += ebitda

        noites_be, break_even_pct = _calcular_break_even_ebitda(
            adr, custo_fixo_mensal, custo_var_noite, comissao_pct, capacidade_mes
        )
        break_even_status = "inviavel" if break_even_pct is None else "ok"
        receita_be = 0.0
        if noites_be > 0 and adr > 0:
            receita_be = adr * noites_be
            break_even_receitas.append(receita_be)

        total_diarias_mes = round(noites_vendidas, 2)
        detalhe_custos_variaveis = [
            {
                "nome": nome,
                "valor_unitario": round(valor_unit, 2),
                "subtotal_mensal": round(valor_unit * noites_vendidas, 2),
            }
            for nome, valor_unit in itens_cv_unitarios
        ]
        if comissao_pct > 0:
            detalhe_custos_variaveis.append({
                "nome": "Comissão de venda (% receita)",
                "valor_unitario": round(cv_comissao / max(noites_vendidas, 1), 2),
                "subtotal_mensal": round(cv_comissao, 2),
            })

        meses_result.append({
            "mes_ano": mes_ano,
            "dias_mes": dias_mes,
            "adr": round(adr, 2),
            "noites_vendidas": total_diarias_mes,
            "total_diarias_mes": total_diarias_mes,
            "detalhe_custos_variaveis": detalhe_custos_variaveis,
            "receita_bruta": round(receita_bruta, 2),
            "custos_fixos": round(custo_fixo_mensal, 2),
            "custos_variaveis": round(custos_variaveis, 2),
            "impostos": round(impostos, 2),
            "ebitda": round(ebitda, 2),
            "lucro_liquido": round(lucro_liquido, 2),
            "break_even_ocupacao_pct": round(break_even_pct, 4) if break_even_pct is not None else None,
            "break_even_status": break_even_status,
            "break_even_receita_mensal": round(receita_be, 2) if receita_be > 0 else None,
        })

    lucro_medio_mensal = lucro_anual / 12.0 if lucro_anual else 0.0
    payback_meses: float | None = None
    payback_status = "ok"
    if lucro_medio_mensal > 0 and investimento_inicial > 0:
        payback_meses = investimento_inicial / lucro_medio_mensal
    elif investimento_inicial > 0 and lucro_anual <= 0:
        payback_status = "indefinido"

    break_even_receita_media = (
        sum(break_even_receitas) / len(break_even_receitas)
        if break_even_receitas else None
    )

    return {
        "meses": meses_result,
        "resumo": {
            "receita_anual": round(receita_anual, 2),
            "lucro_anual": round(lucro_anual, 2),
            "ebitda_anual": round(ebitda_anual, 2),
            "lucro_medio_mensal": round(lucro_medio_mensal, 2),
            "payback_meses": round(payback_meses, 2) if payback_meses is not None else None,
            "payback_status": payback_status,
            "break_even_receita_media": round(break_even_receita_media, 2) if break_even_receita_media is not None else None,
        },
    }


def calcular_curva_sensibilidade(
    id_projeto: str,
    investimento_inicial: float,
    metas_mensais: dict[str, dict] | None = None,
    passo_ocupacao: float = 0.1,
) -> list[dict[str, float]]:
    """
    Gera pontos (ocupacao_pct, lucro_anual, lucro_medio_mensal) para curva de sensibilidade.
    Reutiliza calcular_projecao com ocupação uniforme em [0, passo, ..., 1].
    metas_mensais: base para ADR por mês; ocupação é substituída uniformemente.
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return []

    ano_ref = projeto.ano_referencia or 2025
    if not metas_mensais:
        metas_mensais = {}
    base_metas = {f"{ano_ref}-{m:02d}": metas_mensais.get(f"{ano_ref}-{m:02d}") or {} for m in range(1, 13)}

    pontos: list[dict[str, float]] = []
    ocp = 0.0
    while ocp <= 1.0:
        metas_uniforme = {}
        for mes_ano, meta in base_metas.items():
            adr = float(meta.get("adr", 0.0))
            metas_uniforme[mes_ano] = {"ocupacao": ocp, "adr": adr}
        resultado = calcular_projecao(id_projeto, metas_uniforme, investimento_inicial)
        if "erro" in resultado:
            break
        resumo = resultado.get("resumo") or {}
        lucro_anual = float(resumo.get("lucro_anual", 0.0))
        lucro_medio_mensal = float(resumo.get("lucro_medio_mensal", 0.0))
        pontos.append({
            "ocupacao_pct": round(ocp, 2),
            "lucro_anual": round(lucro_anual, 2),
            "lucro_medio_mensal": round(lucro_medio_mensal, 2),
        })
        ocp = round(ocp + passo_ocupacao, 2)
        if ocp > 1.0:
            ocp = 1.0
            if pontos and pontos[-1]["ocupacao_pct"] >= 1.0:
                break
    return pontos
