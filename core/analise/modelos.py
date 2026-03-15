"""
modelos - Modelos Pydantic para resultado da engenharia reversa.
Responsabilidade: schema ResultadoEngReversa para auditoria e API.
"""
from pydantic import BaseModel, Field


class DetalheMensal(BaseModel):
    """Uma linha do detalhamento mensal da análise."""

    mes_ano: str = Field(description="Ex: 2026-03")
    mes_label: str = Field(description="Ex: Março/2026")
    faturamento_mensal: float
    preco_medio_mes: float = Field(description="ADR Normal do mês (métrica principal operacional)")
    noites_vendidas: float
    ocupacao_pct: float = Field(description="Ex: 0.45 para 45%")
    dias_no_mes: int
    dias_normais_mes: int = 0
    dias_especiais_mes: int = 0
    custo_variavel_mensal: float = 0.0
    impostos_mensais: float = 0.0


class CenarioFinanceiro(BaseModel):
    """Cenário financeiro (pessimista, provável, otimista) para o estudo de viabilidade."""

    nome: str
    fator_ocupacao: float = Field(description="Multiplicador sobre a ocupação estimada base (ex: 0.75, 1.0, 1.25)")
    ocupacao_anual_media: float = Field(
        default=0.0, description="Ocupação média anual do cenário (0–1)"
    )
    faturamento_anual: float = 0.0
    custos_totais_anuais: float = 0.0
    ebitda_anual: float = 0.0
    lucro_liquido_anual: float = 0.0


class ResultadoAnaliseCurado(BaseModel):
    """Resultado da análise de engenharia reversa com preços curados e detalhamento mensal."""

    faturamento_anual_total: float
    diaria_media_anual_estimada: float = Field(description="ADR estimado (geral)")
    adr_normal_anual: float = Field(default=0.0, description="ADR anual considerando apenas dias normais")
    adr_especial_media: float = Field(default=0.0, description="Média das diárias em datas especiais/comemorativas")
    ocupacao_anual_media: float = Field(description="Ex: 0.35 para 35%")
    rdm_anual_medio: float = Field(description="Reservas Diárias Médias")
    detalhamento_mensal: list[DetalheMensal] = Field(default_factory=list)
    # Novos agregados financeiros anuais / globais
    custo_fixo_mensal_total: float = 0.0
    custos_fixos_anuais_sem_aluguel: float = 0.0
    custo_anual_aluguel: float = 0.0
    folha_pagamento_anual: float = 0.0
    custos_variaveis_anuais: float = 0.0
    impostos_anuais: float = 0.0
    custos_totais_anuais: float = 0.0
    ebitda_anual: float = 0.0
    lucro_liquido_anual: float = 0.0
    noites_break_even: float = 0.0
    retorno_arrendamento_percentual: float = 0.0
    cenarios: list[CenarioFinanceiro] = Field(default_factory=list)


class ResultadoEngReversa(BaseModel):
    """Resultado da análise de engenharia reversa (faturamento + mercado → métricas)."""

    diaria_media_ponderada: float
    diarias_vendidas_estimadas: float
    ocupacao_media_estimada: float = Field(description="Ex: 0.172 para 17.2%")
    rdm_estimado: float
    permanencia_media_assumida: float = Field(default=3.0)
    faturamento_anual_usado: float
    numero_quartos_usado: int
    periodos_processados: list[str] = Field(default_factory=list)
    pesos_usados: dict[str, int] = Field(default_factory=dict)
    diaria_media_simples: float = Field(description="Média aritmética simples para comparação")
