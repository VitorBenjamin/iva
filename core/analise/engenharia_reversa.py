"""
engenharia_reversa - Cálculo de diária média ponderada, ocupação, RDM e viabilidade financeira.
Responsabilidade: transformar faturamento + dados de mercado + custos em relatório estruturado.
"""
import calendar
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from loguru import logger

from core.analise.modelos import (
    CenarioFinanceiro,
    DetalheMensal,
    ResultadoAnaliseCurado,
    ResultadoEngReversa,
)
from core.financeiro.custos_variaveis_motor import (
    custo_variavel_operacional_mensal_total,
    listar_itens_cadastro_relatorio,
    soma_fracoes_percentual_receita_itens,
    soma_marginal_linear_por_noite,
)
from core.financeiro.modelos import CustosVariaveisPorNoite
from core.projetos import Projeto
from core.scraper.modelos import DadosMercado

PERMANENCIA_MEDIA_DEFAULT = 3.0

# Pesos de sazonalidade por mês (1-12) para ADR.
PESO_MES_SAZONALIDADE = {
    1: 3,   # Janeiro - alta
    2: 2,   # Fevereiro - média (Carnaval)
    3: 2,   # Março
    4: 1,   # Abril - baixa
    5: 1,   # Maio - baixa
    6: 2,   # Junho
    7: 3,   # Julho - alta
    8: 2,   # Agosto
    9: 1,   # Setembro - baixa
    10: 2,  # Outubro
    11: 2,  # Novembro
    12: 3,  # Dezembro - alta (Réveillon)
}

# Pesos sazonais específicos para distribuição de faturamento (Arraial d'Ajuda - BA).
PESOS_SAZONALIDADE_ARRAIAL = {
    1: 1.35,  # Janeiro
    2: 1.25,  # Fevereiro
    3: 0.90,  # Março
    4: 1.05,  # Abril
    5: 0.60,  # Maio
    6: 0.65,  # Junho
    7: 1.20,  # Julho
    8: 0.85,  # Agosto
    9: 0.75,  # Setembro
    10: 0.80, # Outubro
    11: 0.70, # Novembro
    12: 1.10, # Dezembro
}

MESES_PT = {
    "01": "Janeiro",
    "02": "Fevereiro",
    "03": "Março",
    "04": "Abril",
    "05": "Maio",
    "06": "Junho",
    "07": "Julho",
    "08": "Agosto",
    "09": "Setembro",
    "10": "Outubro",
    "11": "Novembro",
    "12": "Dezembro",
}

PESOS_PERIODO = {
    "reveillon": 4,
    "alta_janeiro": 3,
    "alta_julho": 3,
    "carnaval": 3,
    "baixa_maio": 1,
    "baixa_setembro": 1,
}


def _peso(codigo: str) -> int:
    """Retorna peso do período; não mapeado → 1."""
    return PESOS_PERIODO.get(codigo, 1)


def _custo_arrendamento_mensal_projeto(projeto: Projeto) -> float:
    """Rateio mensal do contrato (única fonte de arrendamento; ignora custos_fixos.aluguel)."""
    arr = float(getattr(projeto, "arrendamento_total", 0.0) or 0.0)
    prazo = max(1, int(getattr(projeto, "prazo_contrato_meses", 12) or 12))
    return max(0.0, arr) / float(prazo)


def custo_fixo_operacional_mensal_cadastro(projeto: Projeto) -> float:
    """Custos fixos do cadastro (luz…outros), sem folha e sem arrendamento."""
    fin = getattr(projeto, "financeiro", None)
    if not fin or not getattr(fin, "custos_fixos", None):
        return 0.0
    cf = fin.custos_fixos
    base = (
        float(cf.luz)
        + float(cf.agua)
        + float(cf.internet)
        + float(cf.iptu)
        + float(cf.contabilidade)
        + float(cf.seguros)
        + float(cf.outros)
    )
    return max(base, 0.0)


def folha_mensal_projeto(projeto: Projeto) -> float:
    """Folha de pagamento mensal (valor efetivo, incluindo soma de funcionários quando aplicável)."""
    fin = getattr(projeto, "financeiro", None)
    if not fin:
        return 0.0
    if hasattr(fin, "calcular_folha_total_decimal"):
        return float(fin.calcular_folha_total_decimal())
    return float(getattr(fin, "folha_pagamento_mensal", 0.0) or 0.0)


def custo_fixo_mensal_sem_aluguel(projeto: Projeto) -> float:
    """Custos fixos mensais sem o campo aluguel (luz…outros + folha). Usado na simulação com arrendamento do contrato."""
    return max(custo_fixo_operacional_mensal_cadastro(projeto) + folha_mensal_projeto(projeto), 0.0)


def _custo_fixo_mensal_total(projeto: Projeto) -> float:
    """Fixos operacionais + folha + rateio do contrato (arrendamento_total ÷ prazo)."""
    return max(custo_fixo_mensal_sem_aluguel(projeto) + _custo_arrendamento_mensal_projeto(projeto), 0.0)


def _custo_variavel_por_noite(projeto: Projeto) -> float:
    """Marginal de custo variável por noite vendida (linear em noites); usado em break-even e metas."""
    fin = getattr(projeto, "financeiro", None)
    if not fin or not getattr(fin, "custos_variaveis", None):
        return 0.0
    media = float(getattr(fin, "media_pessoas_por_diaria", 2.0) or 2.0)
    media = max(0.1, min(10.0, media))
    perm = float(getattr(fin, "permanencia_media", 2.0) or 2.0)
    perm = max(0.5, min(30.0, perm))
    return max(
        soma_marginal_linear_por_noite(
            fin.custos_variaveis,
            media_pessoas=media,
            permanencia_media=perm,
        ),
        0.0,
    )


def _impostos_sobre_faturamento(faturamento: float, projeto: Projeto) -> float:
    """Calcula impostos (aliquota principal + outros impostos/taxas) sobre um faturamento."""
    fin = getattr(projeto, "financeiro", None)
    if not fin:
        return 0.0
    aliquota = float(getattr(fin, "aliquota_impostos", 0.0) or 0.0)
    outros = float(getattr(fin, "outros_impostos_taxas_percentual", 0.0) or 0.0)
    total_aliquota = max(aliquota + outros, 0.0)
    return max(faturamento, 0.0) * total_aliquota


def _calcular_break_even(
    adr_anual: float,
    projeto: Projeto,
    custo_var_marginal_noite: float,
    faturamento_anual_total: float,
) -> float:
    """
    Calcula o ponto de equilíbrio em noites/mês.
    Aproximação: (custo_fixo_mensal_total + impostos_mensais_est) / (ADR efetivo − custo marginal/noite),
    com ADR efetivo reduzido por comissão e itens % receita.
    """
    if adr_anual <= 0:
        return 0.0
    custo_fixo_mensal = _custo_fixo_mensal_total(projeto)
    if custo_fixo_mensal <= 0:
        return 0.0
    fin = getattr(projeto, "financeiro", None)
    aliquota = float(getattr(fin, "aliquota_impostos", 0.0) or 0.0) if fin else 0.0
    outros = float(getattr(fin, "outros_impostos_taxas_percentual", 0.0) or 0.0) if fin else 0.0
    total_aliquota = max(aliquota + outros, 0.0)
    faturamento_medio_mensal = max(faturamento_anual_total, 0.0) / 12.0
    impostos_mensais_estimados = faturamento_medio_mensal * total_aliquota
    comissao = float(getattr(fin, "comissao_venda_pct", 0.0) or 0.0) if fin else 0.0
    comissao = max(0.0, min(1.0, comissao))
    cv = getattr(fin, "custos_variaveis", None) if fin else None
    fr_frac = soma_fracoes_percentual_receita_itens(cv) if cv else 0.0
    pct_total = min(0.999, max(0.0, comissao + fr_frac))
    adr_efetivo = adr_anual * (1.0 - pct_total)
    denominador = adr_efetivo - max(custo_var_marginal_noite, 0.0)
    if denominador <= 0:
        return 0.0
    noites = (custo_fixo_mensal + impostos_mensais_estimados) / denominador
    return max(noites, 0.0)


def _calcular_cenarios(
    faturamento_anual_total: float,
    ocupacao_anual_media: float,
    custos_fixos_anuais_sem_aluguel: float,
    custo_anual_aluguel: float,
    folha_pagamento_anual: float,
    custos_variaveis_anuais: float,
    impostos_anuais: float,
) -> list[CenarioFinanceiro]:
    """
    Gera cenários Pessimista / Provável / Otimista escalando ocupação e componentes proporcionais
    (faturamento, custos variáveis, impostos).
    """
    cenarios: list[CenarioFinanceiro] = []
    base_fixos = max(custos_fixos_anuais_sem_aluguel, 0.0) + max(custo_anual_aluguel, 0.0) + max(
        folha_pagamento_anual, 0.0
    )

    definicoes = [
        ("Pessimista", 0.75),
        ("Provável", 1.0),
        ("Otimista", 1.25),
    ]

    for nome, fator in definicoes:
        ocupacao_cenario = max(ocupacao_anual_media * fator, 0.0)
        faturamento_cenario = max(faturamento_anual_total * fator, 0.0)
        custos_variaveis_cenario = max(custos_variaveis_anuais * fator, 0.0)
        impostos_cenario = max(impostos_anuais * fator, 0.0)
        custos_totais_proporcionais = custos_variaveis_cenario + impostos_cenario
        custos_totais = custos_totais_proporcionais + base_fixos
        ebitda_cenario = faturamento_cenario - custos_totais_proporcionais
        lucro_liquido_cenario = ebitda_cenario - base_fixos

        cenarios.append(
            CenarioFinanceiro(
                nome=nome,
                fator_ocupacao=fator,
                ocupacao_anual_media=ocupacao_cenario,
                faturamento_anual=round(faturamento_cenario, 2),
                custos_totais_anuais=round(custos_totais, 2),
                ebitda_anual=round(ebitda_cenario, 2),
                lucro_liquido_anual=round(lucro_liquido_cenario, 2),
            )
        )

    return cenarios


def gerar_relatorio_engenharia_reversa(projeto: Projeto, dados_mercado: DadosMercado) -> ResultadoEngReversa:
    """Gera relatório de engenharia reversa a partir de projeto e dados de mercado."""
    logger.info("Iniciando análise de engenharia reversa para projeto {}", projeto.id)
    diarias = dados_mercado.diarias_por_periodo
    periodos_processados = list(diarias.keys())
    pesos_usados = {cod: _peso(cod) for cod in periodos_processados}

    if not periodos_processados:
        logger.warning("Nenhum período presente em dados_mercado")
        return ResultadoEngReversa(
            diaria_media_ponderada=0.0,
            diarias_vendidas_estimadas=0.0,
            ocupacao_media_estimada=0.0,
            rdm_estimado=0.0,
            permanencia_media_assumida=PERMANENCIA_MEDIA_DEFAULT,
            faturamento_anual_usado=projeto.faturamento_anual,
            numero_quartos_usado=projeto.numero_quartos,
            periodos_processados=[],
            pesos_usados={},
            diaria_media_simples=0.0,
        )

    soma_ponderada = sum(diarias[c].diaria_direta * pesos_usados[c] for c in periodos_processados)
    soma_pesos = sum(pesos_usados[c] for c in periodos_processados)
    diaria_media_ponderada = soma_ponderada / soma_pesos if soma_pesos else 0.0

    medias = [diarias[c].diaria_direta for c in periodos_processados]
    diaria_media_simples = sum(medias) / len(medias) if medias else 0.0

    faturamento = projeto.faturamento_anual
    numero_quartos = max(projeto.numero_quartos, 1)
    diarias_vendidas_estimadas = faturamento / diaria_media_ponderada if diaria_media_ponderada else 0.0
    capacidade_anual = numero_quartos * 365
    ocupacao_media_estimada = diarias_vendidas_estimadas / capacidade_anual if capacidade_anual else 0.0
    permanencia = PERMANENCIA_MEDIA_DEFAULT
    denom_rdm = 365.0 * permanencia
    rdm_estimado = diarias_vendidas_estimadas / denom_rdm if denom_rdm else 0.0

    resultado = ResultadoEngReversa(
        diaria_media_ponderada=round(diaria_media_ponderada, 2),
        diarias_vendidas_estimadas=round(diarias_vendidas_estimadas, 2),
        ocupacao_media_estimada=round(ocupacao_media_estimada, 4),
        rdm_estimado=round(rdm_estimado, 2),
        permanencia_media_assumida=permanencia,
        faturamento_anual_usado=faturamento,
        numero_quartos_usado=projeto.numero_quartos,
        periodos_processados=periodos_processados,
        pesos_usados=pesos_usados,
        diaria_media_simples=round(diaria_media_simples, 2),
    )
    logger.info("Análise de engenharia reversa concluída: {} períodos", len(periodos_processados))
    return resultado


def gerar_relatorio_engenharia_reversa_registros(
    projeto: Projeto, registros: list[dict]
) -> ResultadoEngReversa:
    """Gera relatório a partir de lista de registros com valor_efetivo (curado ou bruto)."""
    logger.info("Iniciando análise por registros para projeto {} ({} registros)", projeto.id, len(registros))
    valores = [r["valor_efetivo"] for r in registros if isinstance(r.get("valor_efetivo"), (int, float))]
    if not valores:
        logger.warning("Nenhum valor_efetivo nos registros")
        return ResultadoEngReversa(
            diaria_media_ponderada=0.0,
            diarias_vendidas_estimadas=0.0,
            ocupacao_media_estimada=0.0,
            rdm_estimado=0.0,
            permanencia_media_assumida=PERMANENCIA_MEDIA_DEFAULT,
            faturamento_anual_usado=projeto.faturamento_anual,
            numero_quartos_usado=projeto.numero_quartos,
            periodos_processados=[],
            pesos_usados={},
            diaria_media_simples=0.0,
        )
    diaria_media = sum(valores) / len(valores)
    faturamento = projeto.faturamento_anual
    numero_quartos = max(projeto.numero_quartos, 1)
    diarias_vendidas = faturamento / diaria_media if diaria_media else 0.0
    capacidade_anual = numero_quartos * 365
    ocupacao = diarias_vendidas / capacidade_anual if capacidade_anual else 0.0
    permanencia = PERMANENCIA_MEDIA_DEFAULT
    rdm = diarias_vendidas / (365.0 * permanencia) if (365.0 * permanencia) else 0.0
    resultado = ResultadoEngReversa(
        diaria_media_ponderada=round(diaria_media, 2),
        diarias_vendidas_estimadas=round(diarias_vendidas, 2),
        ocupacao_media_estimada=round(ocupacao, 4),
        rdm_estimado=round(rdm, 2),
        permanencia_media_assumida=permanencia,
        faturamento_anual_usado=faturamento,
        numero_quartos_usado=projeto.numero_quartos,
        periodos_processados=[f"registro_{i}" for i in range(len(valores))],
        pesos_usados={},
        diaria_media_simples=round(diaria_media, 2),
    )
    logger.info("Análise por registros concluída: diária média {:.2f}", diaria_media)
    return resultado


def _mes_ano_para_peso(mes_ano: str) -> int:
    """Extrai o mês (1-12) de 'yyyy-mm' e retorna o peso de sazonalidade."""
    try:
        parts = mes_ano.strip().split("-")
        if len(parts) >= 2:
            mes = int(parts[1])
            return PESO_MES_SAZONALIDADE.get(mes, 1)
    except (ValueError, IndexError):
        pass
    return 1


def _mes_label(mes_ano: str) -> str:
    """Converte '2026-03' em 'Março/2026'."""
    try:
        parts = mes_ano.strip().split("-")
        if len(parts) >= 2:
            ano, mes = parts[0], parts[1]
            return f"{MESES_PT.get(mes, mes)}/{ano}"
    except IndexError:
        pass
    return mes_ano


def _dias_normais_especiais_por_mes(
    projeto: Projeto, rolling: bool = False
) -> dict[str, tuple[int, int]]:
    """Retorna {mes_ano: (dias_normais, dias_especiais)} do calendário do projeto.
    Com rolling=False: ano civil completo (Jan–Dez) para análise anual.
    Com rolling=True: janela rolling 12 meses a partir de hoje."""
    from core.config import gerar_calendario_diario_projeto
    ano_ref = projeto.ano_referencia or 2026
    calendario = gerar_calendario_diario_projeto(projeto.id, ano_ref, rolling=rolling)
    por_mes: dict[str, list[str]] = defaultdict(list)
    for d in calendario:
        por_mes[d["mes_ano"]].append(d["categoria_dia"])
    result: dict[str, tuple[int, int]] = {}
    for mes_ano, categorias in por_mes.items():
        esp = sum(1 for c in categorias if c == "especial")
        norm = len(categorias) - esp
        result[mes_ano] = (norm, esp)
    return result


def gerar_analise_curado(projeto: Projeto, registros: list[dict]) -> ResultadoAnaliseCurado:
    """
    Análise de engenharia reversa com preços curados: prioriza preco_curado, senão preco_direto.
    Agrupa por mês e tipo de dia; pondera por sazonalidade; calcula ocupação mensal e anual.
    Meses sem coleta usam a ADR anual como proxy (premissa: preços atuais refletem ano passado).
    """
    logger.info("Iniciando análise curado para projeto {} ({} registros)", projeto.id, len(registros))
    if not registros:
        logger.warning("Nenhum registro para análise curado")
        return ResultadoAnaliseCurado(
            faturamento_anual_total=projeto.faturamento_anual,
            diaria_media_anual_estimada=0.0,
            adr_normal_anual=0.0,
            adr_especial_media=0.0,
            ocupacao_anual_media=0.0,
            rdm_anual_medio=0.0,
            detalhamento_mensal=[],
        )

    # Separa registros normais x especiais (categoria_dia pode não existir em dados legados)
    registros_normais: list[dict] = []
    registros_especiais: list[dict] = []
    for r in registros:
        categoria = r.get("categoria_dia") or "normal"
        if categoria == "especial":
            registros_especiais.append(r)
        else:
            registros_normais.append(r)

    # Valor efetivo ponderado apenas com dias normais
    valores_normais = [
        (r["valor_efetivo"], _mes_ano_para_peso(r.get("mes_ano", "")))
        for r in registros_normais
        if isinstance(r.get("valor_efetivo"), (int, float))
    ]
    if not valores_normais:
        # Se não houver dias normais, cai para comportamento antigo usando todos
        valores_normais = [
            (r["valor_efetivo"], _mes_ano_para_peso(r.get("mes_ano", "")))
            for r in registros
            if isinstance(r.get("valor_efetivo"), (int, float))
        ]

    if not valores_normais:
        logger.warning("Nenhum valor_efetivo numérico nos registros (nem normais nem especiais)")
        return ResultadoAnaliseCurado(
            faturamento_anual_total=projeto.faturamento_anual,
            diaria_media_anual_estimada=0.0,
            adr_normal_anual=0.0,
            adr_especial_media=0.0,
            ocupacao_anual_media=0.0,
            rdm_anual_medio=0.0,
            detalhamento_mensal=[],
        )

    soma_ponderada = sum(v * p for v, p in valores_normais)
    soma_pesos = sum(p for _, p in valores_normais)
    adr_normal_anual = soma_ponderada / soma_pesos if soma_pesos else (
        sum(v for v, _ in valores_normais) / len(valores_normais)
    )

    # ADR "geral" para compatibilidade (pode ser igual à normal em dados novos)
    adr_anual = adr_normal_anual

    # ADR média em datas especiais (apenas para referência)
    valores_especiais = [
        r["valor_efetivo"]
        for r in registros_especiais
        if isinstance(r.get("valor_efetivo"), (int, float))
    ]
    adr_especial_media = sum(valores_especiais) / len(valores_especiais) if valores_especiais else 0.0

    # Preço médio por mês: normal e especial (para baldes)
    preco_por_mes_normais: dict[str, list[float]] = defaultdict(list)
    preco_por_mes_especiais: dict[str, list[float]] = defaultdict(list)
    for r in registros_normais:
        if isinstance(r.get("valor_efetivo"), (int, float)) and r.get("mes_ano"):
            preco_por_mes_normais[r["mes_ano"]].append(float(r["valor_efetivo"]))
    for r in registros_especiais:
        if isinstance(r.get("valor_efetivo"), (int, float)) and r.get("mes_ano"):
            preco_por_mes_especiais[r["mes_ano"]].append(float(r["valor_efetivo"]))
    preco_medio_mes: dict[str, float] = {
        ma: sum(v) / len(v) for ma, v in preco_por_mes_normais.items() if v
    }
    preco_medio_especial_mes: dict[str, float] = {
        ma: sum(v) / len(v) for ma, v in preco_por_mes_especiais.items() if v
    }

    faturamento_anual = projeto.faturamento_anual
    numero_quartos = max(projeto.numero_quartos, 1)
    ano_ref = projeto.ano_referencia or 2026
    permanencia = PERMANENCIA_MEDIA_DEFAULT

    detalhamento_mensal: list[DetalheMensal] = []
    total_noites_vendidas = 0.0
    custos_variaveis_anuais = 0.0
    impostos_anuais = 0.0
    custo_var_marginal_noite = _custo_variavel_por_noite(projeto)
    custo_fixo_mensal_total = _custo_fixo_mensal_total(projeto)
    fin_loop = getattr(projeto, "financeiro", None)
    comissao_pct = float(getattr(fin_loop, "comissao_venda_pct", 0.0) or 0.0) if fin_loop else 0.0
    comissao_pct = max(0.0, min(1.0, comissao_pct))
    media_p_loop = float(getattr(fin_loop, "media_pessoas_por_diaria", 2.0) or 2.0) if fin_loop else 2.0
    media_p_loop = max(0.1, min(10.0, media_p_loop))
    perm_loop = float(getattr(fin_loop, "permanencia_media", 2.0) or 2.0) if fin_loop else 2.0
    perm_loop = max(0.5, min(30.0, perm_loop))
    cv_loop = getattr(fin_loop, "custos_variaveis", None) if fin_loop else None
    if cv_loop is None:
        cv_loop = CustosVariaveisPorNoite()

    soma_pesos_sazonalidade = sum(PESOS_SAZONALIDADE_ARRAIAL.values())
    if soma_pesos_sazonalidade <= 0:
        soma_pesos_sazonalidade = 12.0

    dias_por_mes = _dias_normais_especiais_por_mes(projeto)

    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        dias_mes = calendar.monthrange(ano_ref, mes)[1]
        dias_normais, dias_especiais = dias_por_mes.get(mes_ano, (dias_mes, 0))
        if dias_normais + dias_especiais != dias_mes:
            dias_normais = dias_mes - dias_especiais
        capacidade_mes = numero_quartos * dias_mes

        peso_mes = PESOS_SAZONALIDADE_ARRAIAL.get(mes, 1.0)
        faturamento_mensal = faturamento_anual * (peso_mes / soma_pesos_sazonalidade)

        adr_norm_mes = preco_medio_mes.get(mes_ano) or adr_normal_anual
        adr_esp_mes = preco_medio_especial_mes.get(mes_ano) or adr_especial_media or adr_normal_anual

        if capacidade_mes > 0:
            fat_norm = faturamento_mensal * (dias_normais / dias_mes)
            fat_esp = faturamento_mensal * (dias_especiais / dias_mes)
            noites_norm = fat_norm / adr_norm_mes if adr_norm_mes else 0.0
            noites_esp = fat_esp / adr_esp_mes if adr_esp_mes else 0.0
        else:
            noites_norm = noites_esp = 0.0
        noites_vendidas = noites_norm + noites_esp
        ocupacao_pct = noites_vendidas / capacidade_mes if capacidade_mes else 0.0

        total_noites_vendidas += noites_vendidas
        custo_variavel_mensal = custo_variavel_operacional_mensal_total(
            cv_loop,
            noites_vendidas=noites_vendidas,
            receita_bruta=faturamento_mensal,
            media_pessoas=media_p_loop,
            permanencia_media=perm_loop,
            comissao_pct=comissao_pct,
        )
        impostos_mensais = _impostos_sobre_faturamento(faturamento_mensal, projeto)
        custos_variaveis_anuais += custo_variavel_mensal
        impostos_anuais += impostos_mensais

        detalhamento_mensal.append(
            DetalheMensal(
                mes_ano=mes_ano,
                mes_label=_mes_label(mes_ano),
                faturamento_mensal=round(faturamento_mensal, 2),
                preco_medio_mes=round(adr_norm_mes, 2),
                noites_vendidas=round(noites_vendidas, 2),
                ocupacao_pct=round(ocupacao_pct, 4),
                dias_no_mes=dias_mes,
                dias_normais_mes=dias_normais,
                dias_especiais_mes=dias_especiais,
                custo_variavel_mensal=round(custo_variavel_mensal, 2),
                impostos_mensais=round(impostos_mensais, 2),
            )
        )

    capacidade_anual = numero_quartos * 365
    ocupacao_anual_media = total_noites_vendidas / capacidade_anual if capacidade_anual else 0.0
    denom_rdm = 365.0 * permanencia
    rdm_anual_medio = total_noites_vendidas / denom_rdm if denom_rdm else 0.0
    custos_variaveis_anuais = max(custos_variaveis_anuais, 0.0)
    impostos_anuais = max(impostos_anuais, 0.0)

    # Quebra dos custos fixos anuais (arrendamento só via contrato no projeto)
    fin = getattr(projeto, "financeiro", None)
    cf = getattr(fin, "custos_fixos", None) if fin else None
    custo_mensal_arrend = _custo_arrendamento_mensal_projeto(projeto)
    if fin and hasattr(fin, "calcular_folha_total_decimal"):
        folha_mensal = float(fin.calcular_folha_total_decimal())
    else:
        folha_mensal = float(getattr(fin, "folha_pagamento_mensal", 0.0) or 0.0) if fin else 0.0

    # Custos fixos sem rateio de contrato: demais fixos + folha
    outros_fixos_mensais = 0.0
    if cf:
        outros_fixos_mensais = (
            float(cf.luz)
            + float(cf.agua)
            + float(cf.internet)
            + float(cf.iptu)
            + float(cf.contabilidade)
            + float(cf.seguros)
            + float(cf.outros)
        )

    # Custos fixos anuais sem contrato e sem folha (folha separada)
    custos_fixos_anuais_sem_aluguel = max(outros_fixos_mensais, 0.0) * 12.0
    custo_anual_aluguel = max(custo_mensal_arrend, 0.0) * 12.0
    folha_pagamento_anual = max(folha_mensal, 0.0) * 12.0
    folha_pagamento_anual = float(
        Decimal(str(folha_pagamento_anual)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

    custos_totais_anuais = (
        custos_fixos_anuais_sem_aluguel + custo_anual_aluguel + folha_pagamento_anual +
        custos_variaveis_anuais + impostos_anuais
    )

    ebitda_anual = faturamento_anual - (custos_variaveis_anuais + impostos_anuais)
    lucro_liquido_anual = ebitda_anual - (custos_fixos_anuais_sem_aluguel + custo_anual_aluguel + folha_pagamento_anual)

    noites_break_even = _calcular_break_even(
        adr_anual=adr_anual,
        projeto=projeto,
        custo_var_marginal_noite=custo_var_marginal_noite,
        faturamento_anual_total=faturamento_anual,
    )

    retorno_arrendamento_percentual = 0.0
    base_arrendamento_total = float(getattr(projeto, "arrendamento_total", 0.0) or 0.0)
    if base_arrendamento_total > 0:
        retorno_arrendamento_percentual = (lucro_liquido_anual / base_arrendamento_total) * 100.0

    cenarios = _calcular_cenarios(
        faturamento_anual_total=faturamento_anual,
        ocupacao_anual_media=ocupacao_anual_media,
        custos_fixos_anuais_sem_aluguel=custos_fixos_anuais_sem_aluguel,
        custo_anual_aluguel=custo_anual_aluguel,
        folha_pagamento_anual=folha_pagamento_anual,
        custos_variaveis_anuais=custos_variaveis_anuais,
        impostos_anuais=impostos_anuais,
    )

    fin_cv = getattr(projeto, "financeiro", None)
    cv_rel = getattr(fin_cv, "custos_variaveis", None) if fin_cv else None
    itens_cv_cad = listar_itens_cadastro_relatorio(cv_rel) if cv_rel else []

    resultado = ResultadoAnaliseCurado(
        faturamento_anual_total=round(faturamento_anual, 2),
        diaria_media_anual_estimada=round(adr_anual, 2),
        adr_normal_anual=round(adr_normal_anual, 2),
        adr_especial_media=round(adr_especial_media, 2),
        ocupacao_anual_media=round(ocupacao_anual_media, 4),
        rdm_anual_medio=round(rdm_anual_medio, 2),
        detalhamento_mensal=detalhamento_mensal,
        custo_fixo_mensal_total=round(custo_fixo_mensal_total, 2),
        custos_fixos_anuais_sem_aluguel=round(custos_fixos_anuais_sem_aluguel, 2),
        custo_anual_aluguel=round(custo_anual_aluguel, 2),
        folha_pagamento_anual=round(folha_pagamento_anual, 2),
        custos_variaveis_anuais=round(custos_variaveis_anuais, 2),
        impostos_anuais=round(impostos_anuais, 2),
        custos_totais_anuais=round(custos_totais_anuais, 2),
        ebitda_anual=round(ebitda_anual, 2),
        lucro_liquido_anual=round(lucro_liquido_anual, 2),
        noites_break_even=round(noites_break_even, 2),
        retorno_arrendamento_percentual=round(retorno_arrendamento_percentual, 2),
        cenarios=cenarios,
        itens_custos_variaveis_cadastro=itens_cv_cad,
    )
    logger.info(
        "Análise curado concluída: ADR {:.2f}, ocupação anual {:.2%}, RDM {:.2f}, lucro líquido anual {:.2f}",
        adr_anual,
        ocupacao_anual_media,
        rdm_anual_medio,
        lucro_liquido_anual,
    )
    return resultado
