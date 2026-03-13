"""
engenharia_reversa - Cálculo de diária média ponderada, ocupação e RDM.
Responsabilidade: transformar faturamento + dados de mercado em relatório estruturado.
"""
import calendar
from collections import defaultdict
from loguru import logger

from core.analise.modelos import DetalheMensal, ResultadoAnaliseCurado, ResultadoEngReversa
from core.scraper.modelos import DadosMercado
from core.projetos import Projeto

PERMANENCIA_MEDIA_DEFAULT = 3.0

# Pesos de sazonalidade por mês (1-12): Alta ~70-80%, Média ~40-50%, Baixa ~20-30%
# Usados para calcular a Diária Média Ponderada Anual (ADR).
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

MESES_PT = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
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
            ocupacao_anual_media=0.0,
            rdm_anual_medio=0.0,
            detalhamento_mensal=[],
        )

    # Valor efetivo por registro (já vem preco_curado ou preco_direto)
    valores_com_peso = [
        (r["valor_efetivo"], _mes_ano_para_peso(r.get("mes_ano", "")))
        for r in registros
        if isinstance(r.get("valor_efetivo"), (int, float))
    ]
    if not valores_com_peso:
        logger.warning("Nenhum valor_efetivo numérico nos registros")
        return ResultadoAnaliseCurado(
            faturamento_anual_total=projeto.faturamento_anual,
            diaria_media_anual_estimada=0.0,
            ocupacao_anual_media=0.0,
            rdm_anual_medio=0.0,
            detalhamento_mensal=[],
        )

    # Diária Média Ponderada Anual (ADR) por sazonalidade
    soma_ponderada = sum(v * p for v, p in valores_com_peso)
    soma_pesos = sum(p for _, p in valores_com_peso)
    adr_anual = soma_ponderada / soma_pesos if soma_pesos else (sum(v for v, _ in valores_com_peso) / len(valores_com_peso))

    # Preço médio por mês (apenas meses que têm coleta)
    preco_por_mes: dict[str, list[float]] = defaultdict(list)
    for r in registros:
        if isinstance(r.get("valor_efetivo"), (int, float)) and r.get("mes_ano"):
            preco_por_mes[r["mes_ano"]].append(float(r["valor_efetivo"]))
    preco_medio_mes: dict[str, float] = {
        mes_ano: sum(vals) / len(vals) for mes_ano, vals in preco_por_mes.items() if vals
    }

    faturamento_anual = projeto.faturamento_anual
    numero_quartos = max(projeto.numero_quartos, 1)
    ano_ref = projeto.ano_referencia or 2026
    permanencia = PERMANENCIA_MEDIA_DEFAULT

    detalhamento_mensal: list[DetalheMensal] = []
    total_noites_vendidas = 0.0

    for mes in range(1, 13):
        mes_ano = f"{ano_ref}-{mes:02d}"
        dias_mes = calendar.monthrange(ano_ref, mes)[1]
        faturamento_mensal = faturamento_anual * (dias_mes / 365.0)
        preco_medio = preco_medio_mes.get(mes_ano) or adr_anual  # Meses sem coleta: usa ADR como proxy
        noites_vendidas = faturamento_mensal / preco_medio if preco_medio else 0.0
        capacidade_mes = numero_quartos * dias_mes
        ocupacao_pct = noites_vendidas / capacidade_mes if capacidade_mes else 0.0
        total_noites_vendidas += noites_vendidas
        detalhamento_mensal.append(DetalheMensal(
            mes_ano=mes_ano,
            mes_label=_mes_label(mes_ano),
            faturamento_mensal=round(faturamento_mensal, 2),
            preco_medio_mes=round(preco_medio, 2),
            noites_vendidas=round(noites_vendidas, 2),
            ocupacao_pct=round(ocupacao_pct, 4),
            dias_no_mes=dias_mes,
        ))

    capacidade_anual = numero_quartos * 365
    ocupacao_anual_media = total_noites_vendidas / capacidade_anual if capacidade_anual else 0.0
    denom_rdm = 365.0 * permanencia
    rdm_anual_medio = total_noites_vendidas / denom_rdm if denom_rdm else 0.0

    resultado = ResultadoAnaliseCurado(
        faturamento_anual_total=round(faturamento_anual, 2),
        diaria_media_anual_estimada=round(adr_anual, 2),
        ocupacao_anual_media=round(ocupacao_anual_media, 4),
        rdm_anual_medio=round(rdm_anual_medio, 2),
        detalhamento_mensal=detalhamento_mensal,
    )
    logger.info(
        "Análise curado concluída: ADR {:.2f}, ocupação anual {:.2%}, RDM {:.2f}",
        adr_anual, ocupacao_anual_media, rdm_anual_medio,
    )
    return resultado
