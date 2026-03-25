"""
simulacao - Projeção financeira com metas de ocupação e ADR.
Responsabilidade: calcular receita, custos, lucro operacional, resultado do investidor e payback.
Usa calendário diário: meta aplicada a dias normais; dias especiais com ocupação 100%.

Dupla visão (Operação × Capital):
- EBITDA / Lucro nos meses são OPERACIONAIS (fixos = operacionais + folha; arrendamento NÃO diluído).
- Arrendamento total e reforma entram como cash out de capital no fechamento anual e no resultado do investidor.
- Payback: (Arrendamento + Reforma) ÷ Lucro líquido operacional médio mensal.

Fórmulas:
- Custos Variáveis = (noites × custo_var_noite) + (Receita Bruta × comissao_venda_pct)
- EBITDA Operacional = Receita − Fixos operacionais (sem rateio de arrendamento) − Custos Variáveis
- Lucro Líquido Operacional = EBITDA Operacional − Impostos
- Resultado do investidor (ano 1) = Σ Lucro operacional − Arrendamento total − Reforma
"""
import calendar
from typing import Any

from core.projetos import ArquivoProjetoNaoEncontrado
from core.projetos import Projeto
from core.projetos import carregar_projeto
from core.analise.adr_por_mes import obter_adr_por_mes
from core.analise.engenharia_reversa import (
    custo_fixo_mensal_sem_aluguel,
    custo_fixo_operacional_mensal_cadastro,
    folha_mensal_projeto,
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
    Break-even operacional (EBITDA operacional >= 0).
    Fixos = operacionais + folha (sem arrendamento).
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


def custo_arrendamento_mensal_contrato(arrendamento_total: float, prazo_contrato_meses: int) -> float:
    """Rateio do valor total do contrato pelo prazo (referência; não entra no EBITDA operacional mensal)."""
    prazo = max(1, int(prazo_contrato_meses or 12))
    return max(0.0, float(arrendamento_total)) / float(prazo)


def calcular_investimento_total(
    projeto: Projeto,
    investimento_reforma: float | None = None,
    arrendamento_total: float | None = None,
) -> float:
    """Investimento total para Payback: arrendamento total + reforma."""
    reforma = float(
        investimento_reforma if investimento_reforma is not None else projeto.investimento_reforma
    )
    arr_tot = float(
        arrendamento_total if arrendamento_total is not None else getattr(projeto, "arrendamento_total", 0.0)
    )
    return max(0.0, arr_tot) + max(0.0, reforma)


def calcular_projecao(
    id_projeto: str,
    metas_mensais: dict[str, dict],
    investimento_reforma: float | None = None,
    arrendamento_total: float | None = None,
    prazo_contrato_meses: int | None = None,
    investimento_inicial: float | None = None,
) -> dict[str, Any]:
    """
    Projeção com EBITDA e lucro OPERACIONAIS nos meses (sem diluir arrendamento no fixo).
    Fechamento: resultado do investidor e desembolso total no resumo anual.
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {
            "erro": "Projeto não encontrado",
            "codigo": "projeto_nao_encontrado",
        }

    if investimento_inicial is not None and investimento_reforma is None:
        investimento_reforma = float(investimento_inicial)

    arr_tot = float(
        arrendamento_total if arrendamento_total is not None else getattr(projeto, "arrendamento_total", 0.0)
    )
    prazo = int(
        prazo_contrato_meses if prazo_contrato_meses is not None else getattr(projeto, "prazo_contrato_meses", 12)
    )
    prazo = max(1, prazo)

    reforma_val = float(
        investimento_reforma if investimento_reforma is not None else getattr(projeto, "investimento_reforma", 0.0) or 0.0
    )

    investimento_total = calcular_investimento_total(
        projeto,
        investimento_reforma=investimento_reforma,
        arrendamento_total=arr_tot,
    )

    custo_arrend_mensal = custo_arrendamento_mensal_contrato(arr_tot, prazo)
    custo_fixo_operacional_m = custo_fixo_operacional_mensal_cadastro(projeto)
    folha_mensal = folha_mensal_projeto(projeto)
    # Fixos operacionais mensais (luz…outros + folha) — sem arrendamento
    custo_fixo_mensal_operacional = custo_fixo_mensal_sem_aluguel(projeto)

    despesa_fixos_operacionais_anual = 12.0 * custo_fixo_mensal_operacional

    numero_quartos = max(projeto.numero_quartos or 1, 1)
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
    lucro_operacional_anual = 0.0
    ebitda_operacional_anual = 0.0
    impostos_anual = 0.0
    custos_variaveis_anual = 0.0
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

        cv_operacionais = noites_vendidas * custo_var_noite
        cv_comissao = receita_bruta * comissao_pct
        custos_variaveis = cv_operacionais + cv_comissao

        ebitda = receita_bruta - custo_fixo_mensal_operacional - custos_variaveis
        impostos = _impostos_sobre_faturamento(receita_bruta, projeto)
        lucro_liquido = ebitda - impostos

        receita_anual += receita_bruta
        lucro_operacional_anual += lucro_liquido
        ebitda_operacional_anual += ebitda
        impostos_anual += impostos
        custos_variaveis_anual += custos_variaveis

        noites_be, break_even_pct = _calcular_break_even_ebitda(
            adr, custo_fixo_mensal_operacional, custo_var_noite, comissao_pct, capacidade_mes
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
            "ocupacao_meta": round(ocupacao_meta, 4),
            "adr": round(adr, 2),
            "noites_vendidas": total_diarias_mes,
            "total_diarias_mes": total_diarias_mes,
            "detalhe_custos_variaveis": detalhe_custos_variaveis,
            "receita_bruta": round(receita_bruta, 2),
            "custos_fixos": round(custo_fixo_mensal_operacional, 2),
            "custos_variaveis": round(custos_variaveis, 2),
            "impostos": round(impostos, 2),
            "ebitda": round(ebitda, 2),
            "lucro_liquido": round(lucro_liquido, 2),
            "break_even_ocupacao_pct": round(break_even_pct, 4) if break_even_pct is not None else None,
            "break_even_status": break_even_status,
            "break_even_receita_mensal": round(receita_be, 2) if receita_be > 0 else None,
        })

    lucro_medio_mensal = lucro_operacional_anual / 12.0 if lucro_operacional_anual else 0.0
    payback_meses: float | None = None
    payback_status = "ok"
    if lucro_medio_mensal > 0 and investimento_total > 0:
        payback_meses = investimento_total / lucro_medio_mensal
    elif investimento_total > 0 and lucro_operacional_anual <= 0:
        payback_status = "indefinido"

    resultado_investidor_ano1 = lucro_operacional_anual - max(0.0, arr_tot) - max(0.0, reforma_val)

    desembolso_total_ano1 = (
        despesa_fixos_operacionais_anual + custos_variaveis_anual + impostos_anual + max(0.0, arr_tot) + max(0.0, reforma_val)
    )

    # ROI: estritamente resultado do investidor ÷ capital investido (arrendamento + reforma).
    roi_anual_pct: float | None = None
    if investimento_total > 0:
        roi_anual_pct = (resultado_investidor_ano1 / investimento_total) * 100.0

    margem_investidor_pct: float | None = None
    if receita_anual > 0:
        margem_investidor_pct = (resultado_investidor_ano1 / receita_anual) * 100.0

    break_even_receita_media = (
        sum(break_even_receitas) / len(break_even_receitas)
        if break_even_receitas else None
    )

    return {
        "meses": meses_result,
        "resumo": {
            "receita_anual": round(receita_anual, 2),
            "lucro_anual": round(lucro_operacional_anual, 2),
            "lucro_operacional_anual": round(lucro_operacional_anual, 2),
            "ebitda_anual": round(ebitda_operacional_anual, 2),
            "ebitda_operacional_anual": round(ebitda_operacional_anual, 2),
            "impostos_anuais": round(impostos_anual, 2),
            "custos_variaveis_anuais": round(custos_variaveis_anual, 2),
            "resultado_investidor_ano1": round(resultado_investidor_ano1, 2),
            "desembolso_total_ano1": round(desembolso_total_ano1, 2),
            "despesa_fixos_operacionais_anual": round(despesa_fixos_operacionais_anual, 2),
            "custo_fixo_operacional_anual": round(12.0 * custo_fixo_operacional_m, 2),
            "folha_anual": round(12.0 * folha_mensal, 2),
            "arrendamento_total": round(max(0.0, arr_tot), 2),
            "investimento_reforma": round(max(0.0, reforma_val), 2),
            "arrendamento_rateado_anual": round(12.0 * custo_arrend_mensal, 2),
            "lucro_medio_mensal": round(lucro_medio_mensal, 2),
            "investimento_total": round(investimento_total, 2),
            "custo_arrendamento_mensal": round(custo_arrend_mensal, 2),
            "roi_anual_pct": round(roi_anual_pct, 2) if roi_anual_pct is not None else None,
            "margem_investidor_pct": round(margem_investidor_pct, 2) if margem_investidor_pct is not None else None,
            "payback_meses": round(payback_meses, 2) if payback_meses is not None else None,
            "payback_status": payback_status,
            "break_even_receita_media": round(break_even_receita_media, 2) if break_even_receita_media is not None else None,
        },
    }


def calcular_curva_sensibilidade(
    id_projeto: str,
    investimento_reforma: float | None = None,
    metas_mensais: dict[str, dict] | None = None,
    passo_ocupacao: float = 0.1,
    arrendamento_total: float | None = None,
    prazo_contrato_meses: int | None = None,
    investimento_inicial: float | None = None,
) -> list[dict[str, float]]:
    """
    Gera pontos (ocupacao_pct, lucro_anual, lucro_medio_mensal) para curva de sensibilidade.
    lucro_anual = soma dos lucros operacionais (visão consistente com o motor).
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return []

    if investimento_inicial is not None and investimento_reforma is None:
        investimento_reforma = float(investimento_inicial)

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
        resultado = calcular_projecao(
            id_projeto,
            metas_uniforme,
            investimento_reforma,
            arrendamento_total,
            prazo_contrato_meses,
        )
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
