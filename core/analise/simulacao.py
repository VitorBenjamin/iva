"""
simulacao - Projeção financeira com metas de ocupação e ADR.
Responsabilidade: calcular receita, custos, lucro operacional, resultado do investidor e payback.
Usa calendário diário: meta aplicada a dias normais; dias especiais com ocupação 100%.

Dupla visão (Operação × Capital):
- EBITDA / Lucro nos meses são OPERACIONAIS (fixos = operacionais + folha; arrendamento NÃO diluído).
- Arrendamento total e reforma entram como cash out de capital no fechamento anual e no resultado do investidor.
- Payback: (Arrendamento + Reforma) ÷ Lucro líquido operacional médio mensal.

Fórmulas (custos variáveis por incidência em `CustosVariaveisPorNoite`):
- hospede_noite: valor × noites × média de pessoas/diária
- uh_noite: valor × noites
- reserva: valor × (noites ÷ permanência média)
- percentual_receita: receita_bruta × (valor ÷ 100)
- Comissão de venda: receita_bruta × comissao_venda_pct (0–1)
- EBITDA Operacional = Receita − Fixos operacionais (sem rateio de arrendamento) − Custos Variáveis
- Lucro Líquido Operacional = EBITDA Operacional − Impostos
- Resultado do investidor (ano 1) = Σ Lucro operacional − Arrendamento total − Reforma
"""
import calendar
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.projetos import ArquivoProjetoNaoEncontrado
from core.projetos import Projeto
from core.projetos import carregar_projeto
from core.projetos import get_cenarios_path
from core.projetos import get_projeto_json_path
from core.projetos import get_simulacao_cenarios_path
from core.projetos import get_simulacao_salva_path
from core.analise.adr_por_mes import obter_adr_por_mes
from core.financeiro.custos_variaveis_motor import (
    custo_variavel_operacional_mensal_total,
    incidencia_str,
    iter_itens_custos_variaveis,
    soma_fracoes_percentual_receita_itens,
    soma_marginal_linear_por_noite,
    subtotal_custo_item,
)
from core.financeiro.modelos import CustosVariaveisPorNoite, IncidenciaCustoVariavel
from core.analise.engenharia_reversa import (
    custo_fixo_mensal_sem_aluguel,
    custo_fixo_operacional_mensal_cadastro,
    folha_mensal_projeto,
    _dias_normais_especiais_por_mes,
    _impostos_sobre_faturamento,
)


def _calcular_break_even_ebitda(
    adr: float,
    custo_fixo_mensal: float,
    custo_var_marginal_linha_noite: float,
    comissao_pct: float,
    fracao_percentual_receita_itens: float,
    capacidade_mes: float,
) -> tuple[float, float | None]:
    """
    Break-even operacional (EBITDA operacional >= 0).
    Fixos = operacionais + folha (sem arrendamento).
    Considera comissão e itens % receita no fator (1 − Σ %) sobre o ADR.
    """
    if capacidade_mes <= 0:
        return 0.0, None
    comissao_pct = max(0.0, min(1.0, float(comissao_pct)))
    fr = max(0.0, min(0.999, float(fracao_percentual_receita_itens)))
    pct_total = min(0.999, comissao_pct + fr)
    adr_efetivo = adr * (1.0 - pct_total) if pct_total < 1.0 else 0.0
    denominador = adr_efetivo - max(custo_var_marginal_linha_noite, 0.0)
    if denominador <= 0 or custo_fixo_mensal <= 0:
        return 0.0, None
    noites = custo_fixo_mensal / denominador
    pct = min(noites / capacidade_mes, 1.0)
    return noites, pct


def _linha_detalhe_cv_ui(
    nome: str,
    item: Any,
    *,
    subtotal: float,
    noites_vendidas: float,
    receita_bruta: float,
    media_pessoas: float,
    permanencia_media: float,
) -> dict[str, Any]:
    """Metadados para UI (simulação) da composição de custos variáveis."""
    inc = incidencia_str(item)
    v = float(getattr(item, "valor", 0.0) or 0.0)
    nv = max(0.0, float(noites_vendidas))
    rb = max(0.0, float(receita_bruta))
    mp = max(0.1, min(10.0, float(media_pessoas)))
    pm = max(0.5, min(30.0, float(permanencia_media)))

    if inc == IncidenciaCustoVariavel.HOSPEDE_NOITE.value:
        qtd = nv * mp
        rot = "hóspede·noites"
    elif inc == IncidenciaCustoVariavel.UH_NOITE.value:
        qtd = nv
        rot = "noites (UH)"
    elif inc == IncidenciaCustoVariavel.RESERVA.value:
        qtd = (nv / pm) if pm > 0 else 0.0
        rot = "reservas"
    elif inc == IncidenciaCustoVariavel.PERCENTUAL_RECEITA.value:
        qtd = rb
        rot = "receita bruta"
    else:
        qtd = nv * mp
        rot = "hóspede·noites"

    return {
        "nome": nome,
        "valor_unitario": round(v, 4),
        "subtotal_mensal": round(subtotal, 2),
        "incidencia": inc,
        "quantidade_calculo": round(qtd, 4),
        "rotulo_quantidade": rot,
    }


def _carregar_metas_mensais_salvas_projeto(id_projeto: str) -> dict[str, dict]:
    """Lê `simulacao_salva.json` (path via `get_simulacao_salva_path`)."""
    path = get_simulacao_salva_path(id_projeto)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mm = raw.get("metas_mensais")
    return mm if isinstance(mm, dict) else {}


def _media_ponderada_dias(ano: int, mes_valor: dict[str, float]) -> float:
    """Média ponderada por dias de cada mês (calendário civil)."""
    num = 0.0
    den = 0
    for mes in range(1, 13):
        mes_ano = f"{ano}-{mes:02d}"
        if mes_ano not in mes_valor:
            continue
        dias = calendar.monthrange(ano, mes)[1]
        num += float(mes_valor[mes_ano]) * dias
        den += dias
    return num / den if den > 0 else 0.0


def construir_metas_para_projecao(
    id_projeto: str,
    ocupacao_alvo: float | None = None,
    adr_override: float | None | dict[str, float] = None,
) -> dict[str, dict]:
    """
    Constrói metas_mensais a partir de ocupacao_alvo e adr_override.
    Se ocupacao_alvo não informado, usa 0.4 (40%). Se adr_override não informado, usa obter_adr_por_mes.

    Se existir `simulacao_salva.json` com `metas_mensais`, usa a curva salva como base e aplica
    fator de escala para que a média ponderada (por dias) bata em `ocupacao_alvo` / `adr_override`
    escalar, preservando a sazonalidade relativa.
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {}
    ano_ref = projeto.ano_referencia or 2025
    adr_por_mes = obter_adr_por_mes(id_projeto)
    metas_salvas = _carregar_metas_mensais_salvas_projeto(id_projeto)
    ocup_default = max(0.0, min(1.0, ocupacao_alvo if ocupacao_alvo is not None else 0.4))
    adr_override_dict = adr_override if isinstance(adr_override, dict) else None
    adr_override_val = float(adr_override) if isinstance(adr_override, (int, float)) else None

    tem_ocup_salva = any(
        (metas_salvas.get(f"{ano_ref}-{m:02d}") or {}).get("ocupacao") is not None for m in range(1, 13)
    )

    base_ocup: dict[str, float] = {}
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        ms = metas_salvas.get(mes_ano) or {}
        o = ms.get("ocupacao")
        if o is not None:
            base_ocup[mes_ano] = max(0.0, min(1.0, float(o)))
        else:
            base_ocup[mes_ano] = ocup_default

    if tem_ocup_salva and ocupacao_alvo is not None:
        media_ocup = _media_ponderada_dias(ano_ref, base_ocup)
        if media_ocup > 0:
            f_ocup = max(0.0, min(1.0, float(ocupacao_alvo))) / media_ocup
            ocup_por_mes = {
                k: max(0.0, min(1.0, v * f_ocup)) for k, v in base_ocup.items()
            }
        else:
            u = max(0.0, min(1.0, float(ocupacao_alvo)))
            ocup_por_mes = {f"{ano_ref}-{m:02d}": u for m in range(1, 13)}
    elif tem_ocup_salva:
        ocup_por_mes = dict(base_ocup)
    else:
        u = ocup_default
        ocup_por_mes = {f"{ano_ref}-{m:02d}": u for m in range(1, 13)}

    base_adr: dict[str, float] = {}
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        info = adr_por_mes.get(mes_ano) or {}
        adr = None
        if adr_override_dict:
            adr = adr_override_dict.get(mes_ano)
        if adr is None:
            ms = metas_salvas.get(mes_ano) or {}
            if ms.get("adr") is not None:
                adr = float(ms["adr"])
        if adr is None:
            adr = info.get("adr") if isinstance(info, dict) else (info if isinstance(info, (int, float)) else 0)
        base_adr[mes_ano] = max(0.0, float(adr or 0))

    tem_adr_salva = any(
        (metas_salvas.get(f"{ano_ref}-{m:02d}") or {}).get("adr") is not None for m in range(1, 13)
    )
    adr_vals = list(base_adr.values())
    adr_diverge = len({round(x, 4) for x in adr_vals}) > 1

    adr_por_mes_out: dict[str, float] = dict(base_adr)
    if adr_override_val is not None and (tem_adr_salva or adr_diverge):
        media_adr = _media_ponderada_dias(ano_ref, base_adr)
        if media_adr > 0:
            f_adr = float(adr_override_val) / media_adr
            adr_por_mes_out = {k: max(0.0, v * f_adr) for k, v in base_adr.items()}
        else:
            adr_por_mes_out = {f"{ano_ref}-{m:02d}": max(0.0, float(adr_override_val)) for m in range(1, 13)}
    elif adr_override_val is not None:
        uadr = max(0.0, float(adr_override_val))
        adr_por_mes_out = {f"{ano_ref}-{m:02d}": uadr for m in range(1, 13)}

    metas: dict[str, dict] = {}
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        adr = adr_por_mes_out.get(mes_ano, 0.0)
        if adr_override_dict and mes_ano in adr_override_dict:
            adr = max(0.0, float(adr_override_dict[mes_ano]))
        metas[mes_ano] = {"ocupacao": ocup_por_mes[mes_ano], "adr": float(adr)}
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


def calcular_projecao_plurianual(
    projeto: Projeto,
    meses_ano1: list[dict[str, Any]],
    resumo_ano1: dict[str, Any],
    prazo_contrato_meses: int | None = None,
) -> dict[str, Any]:
    """
    Projeção operacional repetindo o ciclo sazonal de 12 meses até N meses de contrato.
    Payback real: primeiro mês em que o lucro operacional acumulado >= investimento total.
    """
    n_meses_ciclo = len(meses_ano1) if meses_ano1 else 12
    if n_meses_ciclo < 1:
        n_meses_ciclo = 12
    lucros_ciclo: list[float] = []
    for i in range(min(12, n_meses_ciclo)):
        lucros_ciclo.append(float(meses_ano1[i].get("lucro_liquido") or 0.0))
    while len(lucros_ciclo) < 12:
        lucros_ciclo.append(0.0)

    prazo = int(prazo_contrato_meses if prazo_contrato_meses is not None else getattr(projeto, "prazo_contrato_meses", 12) or 12)
    prazo = max(1, min(600, prazo))

    investimento_total = float(resumo_ano1.get("investimento_total") or 0.0)

    meses_out: list[dict[str, Any]] = []
    saldo = 0.0
    mes_payback: int | None = None
    eps = 1e-6

    for m in range(1, prazo + 1):
        idx = (m - 1) % 12
        lucro = lucros_ciclo[idx]
        saldo += lucro
        if mes_payback is None and investimento_total > 0 and saldo + eps >= investimento_total:
            mes_payback = m
        meses_out.append({
            "mes_contrato": m,
            "lucro_operacional_mes": round(lucro, 2),
            "saldo_acumulado": round(saldo, 2),
        })

    lucro_acumulado_final = saldo
    payback_atingido = mes_payback is not None
    if investimento_total <= 0:
        payback_atingido = True
        mes_payback = None

    num_anos = (prazo + 11) // 12
    anos_out: list[dict[str, Any]] = []
    for a in range(num_anos):
        start_m = a * 12 + 1
        end_m = min((a + 1) * 12, prazo)
        lucro_anual_seg = 0.0
        for mm in range(start_m, end_m + 1):
            lucro_anual_seg += lucros_ciclo[(mm - 1) % 12]
        saldo_fim = 0.0
        for mm in range(1, end_m + 1):
            saldo_fim += lucros_ciclo[(mm - 1) % 12]
        anos_out.append({
            "ano": a + 1,
            "lucro_operacional_anual": round(lucro_anual_seg, 2),
            "saldo_acumulado_fim_ano": round(saldo_fim, 2),
        })

    roi_total_pct: float | None = None
    if investimento_total > 0:
        roi_total_pct = ((lucro_acumulado_final - investimento_total) / investimento_total) * 100.0

    return {
        "horizonte_meses": prazo,
        "investimento_total": round(investimento_total, 2),
        "meses": meses_out,
        "anos": anos_out,
        "mes_payback": mes_payback,
        "lucro_final_contrato": round(lucro_acumulado_final, 2),
        "resultado_pos_investimento": round(lucro_acumulado_final - investimento_total, 2),
        "roi_total_contrato_pct": round(roi_total_pct, 2) if roi_total_pct is not None else None,
        "payback_atingido": payback_atingido,
    }


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
    dias_por_mes = _dias_normais_especiais_por_mes(projeto)

    fin = getattr(projeto, "financeiro", None)
    comissao_pct = float(getattr(fin, "comissao_venda_pct", 0.0) or 0.0)
    comissao_pct = max(0.0, min(1.0, comissao_pct))

    cv = getattr(fin, "custos_variaveis", None) if fin else None
    if cv is None:
        cv = CustosVariaveisPorNoite()
    media_pessoas = float(getattr(fin, "media_pessoas_por_diaria", 2.0) or 2.0)
    media_pessoas = max(0.1, min(10.0, media_pessoas))
    permanencia_media = float(getattr(fin, "permanencia_media", 2.0) or 2.0) if fin else 2.0
    permanencia_media = max(0.5, min(30.0, permanencia_media))
    fracao_pct_cv_itens = soma_fracoes_percentual_receita_itens(cv)
    custo_var_marginal_linha = soma_marginal_linear_por_noite(
        cv,
        media_pessoas=media_pessoas,
        permanencia_media=permanencia_media,
    )

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

        cv_itens_mes = custo_variavel_operacional_mensal_total(
            cv,
            noites_vendidas=noites_vendidas,
            receita_bruta=receita_bruta,
            media_pessoas=media_pessoas,
            permanencia_media=permanencia_media,
            comissao_pct=0.0,
        )
        cv_comissao = receita_bruta * comissao_pct
        custos_variaveis = cv_itens_mes + cv_comissao

        ebitda = receita_bruta - custo_fixo_mensal_operacional - custos_variaveis
        impostos = _impostos_sobre_faturamento(receita_bruta, projeto)
        lucro_liquido = ebitda - impostos

        receita_anual += receita_bruta
        lucro_operacional_anual += lucro_liquido
        ebitda_operacional_anual += ebitda
        impostos_anual += impostos
        custos_variaveis_anual += custos_variaveis

        noites_be, break_even_pct = _calcular_break_even_ebitda(
            adr,
            custo_fixo_mensal_operacional,
            custo_var_marginal_linha,
            comissao_pct,
            fracao_pct_cv_itens,
            capacidade_mes,
        )
        break_even_status = "inviavel" if break_even_pct is None else "ok"
        receita_be = 0.0
        if noites_be > 0 and adr > 0:
            receita_be = adr * noites_be
            break_even_receitas.append(receita_be)

        total_diarias_mes = round(noites_vendidas, 2)
        detalhe_custos_variaveis: list[dict[str, Any]] = []
        for _chave, nome, item in iter_itens_custos_variaveis(cv):
            sub_i = subtotal_custo_item(
                item,
                noites_vendidas=noites_vendidas,
                receita_bruta=receita_bruta,
                media_pessoas=media_pessoas,
                permanencia_media=permanencia_media,
            )
            detalhe_custos_variaveis.append(
                _linha_detalhe_cv_ui(
                    nome,
                    item,
                    subtotal=sub_i,
                    noites_vendidas=noites_vendidas,
                    receita_bruta=receita_bruta,
                    media_pessoas=media_pessoas,
                    permanencia_media=permanencia_media,
                )
            )
        if comissao_pct > 0:
            detalhe_custos_variaveis.append({
                "nome": "Comissão de venda (% receita)",
                "valor_unitario": round(comissao_pct * 100.0, 2),
                "subtotal_mensal": round(cv_comissao, 2),
                "incidencia": "comissao_venda",
                "quantidade_calculo": round(receita_bruta, 2),
                "rotulo_quantidade": "receita bruta",
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

    resumo_dict: dict[str, Any] = {
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
    }

    plurianual = calcular_projecao_plurianual(projeto, meses_result, resumo_dict, prazo)

    return {
        "meses": meses_result,
        "resumo": resumo_dict,
        "plurianual": plurianual,
    }


def _carregar_cenarios_arquivo_projeto(id_projeto: str) -> list[dict[str, Any]]:
    """Lê `cenarios.json` ou legado `simulacao_cenarios.json` (mesma ordem que app)."""
    path = Path(get_cenarios_path(id_projeto))
    path_legado = Path(get_simulacao_cenarios_path(id_projeto))
    if (not path.exists() or not path.is_file()) and path_legado.is_file():
        path = path_legado
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cenarios = data.get("cenarios")
    return cenarios if isinstance(cenarios, list) else []


def comparar_cenarios_projeto(id_projeto: str) -> list[dict[str, Any]]:
    """
    Para cada cenário em `cenarios.json`, reexecuta `calcular_projecao` com as `metas_mensais`
    salvas no cenário e com custos / investimento atuais em `projeto.json` (sem overrides de capital).

    Retorna KPIs comparáveis: lucro operacional anual (Ano 1), ROI %, payback, margem do investidor.
    """
    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return []

    cenarios = _carregar_cenarios_arquivo_projeto(id_projeto)
    out: list[dict[str, Any]] = []
    for c in cenarios:
        cid = c.get("id")
        nome = (c.get("nome") or "").strip() or "Sem nome"
        desc = (c.get("descricao") or "").strip() or ""
        criado = c.get("criado_em")
        metas = c.get("metas_mensais") or {}
        if not isinstance(metas, dict) or len(metas) == 0:
            out.append(
                {
                    "id": cid,
                    "nome_cenario": nome,
                    "nome": nome,
                    "descricao": desc,
                    "criado_em": criado,
                    "lucro_anual": None,
                    "roi_pct": None,
                    "payback_meses": None,
                    "margem_investidor": None,
                    "investimento_total": None,
                    "erro_calculo": "sem_metas_mensais",
                }
            )
            continue
        r = calcular_projecao(id_projeto, metas)
        if r.get("erro"):
            out.append(
                {
                    "id": cid,
                    "nome_cenario": nome,
                    "nome": nome,
                    "descricao": desc,
                    "criado_em": criado,
                    "lucro_anual": None,
                    "roi_pct": None,
                    "payback_meses": None,
                    "margem_investidor": None,
                    "investimento_total": None,
                    "erro_calculo": str(r.get("erro") or r.get("codigo") or "erro"),
                }
            )
            continue
        res = r.get("resumo") or {}
        out.append(
            {
                "id": cid,
                "nome_cenario": nome,
                "nome": nome,
                "descricao": desc,
                "criado_em": criado,
                "lucro_anual": res.get("lucro_anual"),
                "roi_pct": res.get("roi_anual_pct"),
                "payback_meses": res.get("payback_meses"),
                "margem_investidor": res.get("margem_investidor_pct"),
                "investimento_total": res.get("investimento_total"),
                "erro_calculo": None,
            }
        )
    return out


def _metas_para_sugestao_arrendamento(
    id_projeto: str, cenario_id: str | None
) -> tuple[dict[str, dict] | None, str | None]:
    """Metas do cenário salvo ou curva padrão (`construir_metas_para_projecao`)."""
    if cenario_id and str(cenario_id).strip():
        cid = str(cenario_id).strip()
        for c in _carregar_cenarios_arquivo_projeto(id_projeto):
            if c.get("id") == cid:
                mm = c.get("metas_mensais") or {}
                if isinstance(mm, dict) and len(mm) > 0:
                    return mm, None
                return None, "cenario_sem_metas_mensais"
        return None, "cenario_nao_encontrado"
    metas = construir_metas_para_projecao(id_projeto)
    if not metas:
        return None, "sem_metas"
    return metas, None


def sugerir_arrendamento(
    id_projeto: str,
    cenario_id: str | None = None,
    margem_minima_pct: float = 15.0,
) -> dict[str, Any]:
    """
    Isola o resultado operacional (arrendamento e reforma forçados a zero) e sugere um valor mensal
    de arrendamento compatível com uma margem mínima desejada sobre a receita média mensal.

    lucro_sem_arrendamento = lucro_operacional_anual / 12
    margem_minima_R = receita_media_mensal * (margem_minima_pct / 100)
    arrendamento_sugerido = lucro_sem_arrendamento - margem_minima_R
    """
    path = get_projeto_json_path(id_projeto)
    if not path.is_file():
        return {
            "erro": "Projeto não encontrado",
            "codigo": "projeto_nao_encontrado",
        }

    try:
        carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {
            "erro": "Projeto não encontrado",
            "codigo": "projeto_nao_encontrado",
        }

    metas, err_metas = _metas_para_sugestao_arrendamento(id_projeto, cenario_id)
    if err_metas == "cenario_nao_encontrado":
        return {"erro": "Cenário não encontrado", "codigo": "cenario_nao_encontrado"}
    if err_metas == "cenario_sem_metas_mensais":
        return {"erro": "Cenário sem metas mensais", "codigo": "cenario_sem_metas_mensais"}
    if err_metas == "sem_metas" or not metas:
        return {"erro": "Não foi possível obter metas para a projeção", "codigo": "sem_metas"}

    margem_minima_pct = max(0.0, min(100.0, float(margem_minima_pct)))

    r = calcular_projecao(
        id_projeto,
        metas,
        investimento_reforma=0.0,
        arrendamento_total=0.0,
    )
    if r.get("erro"):
        return {
            "erro": str(r.get("erro") or r.get("codigo") or "erro_calculo"),
            "codigo": str(r.get("codigo") or "erro_calculo"),
        }

    resumo = r.get("resumo") or {}
    lucro_op_anual = float(resumo.get("lucro_operacional_anual") or resumo.get("lucro_anual") or 0.0)
    receita_anual = float(resumo.get("receita_anual") or 0.0)

    lucro_sem_arrendamento = lucro_op_anual / 12.0
    receita_media_mensal = receita_anual / 12.0
    margem_minima_R = receita_media_mensal * (margem_minima_pct / 100.0)
    arrendamento_sugerido = lucro_sem_arrendamento - margem_minima_R

    base: dict[str, Any] = {
        "margem_minima_pct": round(margem_minima_pct, 2),
        "receita_media_mensal": round(receita_media_mensal, 2),
        "lucro_sem_arrendamento": round(lucro_sem_arrendamento, 2),
        "margem_minima_R": round(margem_minima_R, 2),
        "arrendamento_sugerido": round(arrendamento_sugerido, 2),
        "cenario_id": (str(cenario_id).strip() if cenario_id else None),
    }

    if arrendamento_sugerido <= 0:
        base["status"] = "inviavel"
        base["diagnostico"] = (
            "O lucro operacional médio mensal (sem arrendamento nem reforma no cálculo) "
            "não supera a margem mínima desejada sobre a receita média mensal; "
            "não há valor de arrendamento mensal positivo compatível com essa regra."
        )
        return base

    base["status"] = "viavel"
    return base


def gerar_contexto_completo_viabilidade(
    id_projeto: str,
    metas_mensais: dict[str, dict] | None = None,
    investimento_params: dict[str, Any] | None = None,
    cenario_id: str | None = None,
) -> dict[str, Any]:
    """
    Gera contexto completo para relatório Jinja da viabilidade:
    - projeção ano 1 (calcular_projecao)
    - projeção plurianual (já contida no retorno do motor)
    - sugestão de arrendamento (margem padrão 15% ou override)
    """
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        return {
            "erro": "Projeto não encontrado",
            "codigo": "projeto_nao_encontrado",
        }

    if metas_mensais is None:
        metas_mensais = construir_metas_para_projecao(id_projeto)
    if not metas_mensais:
        return {
            "erro": "Não foi possível obter metas mensais",
            "codigo": "sem_metas",
        }

    investimento_params = investimento_params or {}
    if not cenario_id:
        cenario_id = investimento_params.get("cenario_id")
    inv_reforma = investimento_params.get("investimento_reforma")
    if inv_reforma is None and investimento_params.get("investimento_inicial") is not None:
        inv_reforma = investimento_params.get("investimento_inicial")
    arr_total = investimento_params.get("arrendamento_total")
    prazo = investimento_params.get("prazo_contrato_meses")
    margem_pct = investimento_params.get("margem_minima_pct")
    try:
        margem_pct_f = float(margem_pct if margem_pct is not None else 15.0)
    except (TypeError, ValueError):
        margem_pct_f = 15.0

    proj = calcular_projecao(
        id_projeto,
        metas_mensais,
        investimento_reforma=None if inv_reforma is None else float(inv_reforma),
        arrendamento_total=None if arr_total is None else float(arr_total),
        prazo_contrato_meses=None if prazo is None else int(prazo),
    )
    if proj.get("erro"):
        return {
            "erro": str(proj.get("erro") or "Erro ao calcular projeção"),
            "codigo": str(proj.get("codigo") or "erro_calculo"),
        }

    sug = sugerir_arrendamento(
        id_projeto,
        cenario_id=cenario_id,
        margem_minima_pct=margem_pct_f,
    )
    if sug.get("erro"):
        sug = {
            "status": "inviavel",
            "arrendamento_sugerido": None,
            "lucro_sem_arrendamento": None,
            "margem_minima_R": None,
            "margem_minima_pct": margem_pct_f,
            "diagnostico": str(sug.get("erro")),
        }

    ano_ref = projeto.ano_referencia or 2025
    metas_linhas: list[dict[str, Any]] = []
    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        m = metas_mensais.get(mes_ano) or {}
        metas_linhas.append(
            {
                "mes_ano": mes_ano,
                "mes": mes,
                "ocupacao_pct": round(float(m.get("ocupacao", 0.0) or 0.0) * 100.0, 2),
                "adr": round(float(m.get("adr", 0.0) or 0.0), 2),
            }
        )

    nome_cenario_base = "Simulação Ad-hoc"
    cid = str(cenario_id).strip() if cenario_id else ""
    if cid:
        for c in _carregar_cenarios_arquivo_projeto(id_projeto):
            if c.get("id") == cid:
                nome_cenario_base = (c.get("nome") or "").strip() or "Cenário salvo"
                break
    elif isinstance(investimento_params.get("nome_cenario_base"), str) and investimento_params.get("nome_cenario_base").strip():
        nome_cenario_base = investimento_params.get("nome_cenario_base").strip()

    id_str = str(id_projeto or "")
    id_projeto_curto = id_str[:8] if len(id_str) > 8 else id_str

    return {
        "projeto": projeto.model_dump(mode="json"),
        "resumo": proj.get("resumo") or {},
        "meses": proj.get("meses") or [],
        "projecao_plurianual": proj.get("plurianual") or {},
        "sugestao_arrendamento": sug,
        "metas_mensais": metas_linhas,
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "id_projeto_curto": id_projeto_curto,
        "nome_cenario_base": nome_cenario_base,
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
