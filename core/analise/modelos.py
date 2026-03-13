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
    preco_medio_mes: float
    noites_vendidas: float
    ocupacao_pct: float = Field(description="Ex: 0.45 para 45%")
    dias_no_mes: int


class ResultadoAnaliseCurado(BaseModel):
    """Resultado da análise de engenharia reversa com preços curados e detalhamento mensal."""

    faturamento_anual_total: float
    diaria_media_anual_estimada: float = Field(description="ADR estimado")
    ocupacao_anual_media: float = Field(description="Ex: 0.35 para 35%")
    rdm_anual_medio: float = Field(description="Reservas Diárias Médias")
    detalhamento_mensal: list[DetalheMensal] = Field(default_factory=list)


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
