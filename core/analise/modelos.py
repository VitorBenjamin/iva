"""
modelos - Modelos Pydantic para resultado da engenharia reversa.
Responsabilidade: schema ResultadoEngReversa para auditoria e API.
"""
from pydantic import BaseModel, Field


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
