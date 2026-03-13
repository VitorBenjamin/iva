"""
engenharia_reversa - Cálculo de diária média ponderada, ocupação e RDM.
Responsabilidade: transformar faturamento + dados de mercado em relatório estruturado.
"""
from loguru import logger

from core.analise.modelos import ResultadoEngReversa
from core.scraper.modelos import DadosMercado
from core.projetos import Projeto

PERMANENCIA_MEDIA_DEFAULT = 3.0
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
