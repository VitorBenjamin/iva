"""
modelos - Modelos Pydantic para dados de mercado (scraping).
Responsabilidade: schemas DadosMercado e DiariaPeriodo.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DiariaPeriodo(BaseModel):
    """Diária extraída para um período sazonal."""

    nome_periodo: str
    datas: str
    noites: int
    diaria_booking: float
    diaria_direta: float
    tipo_tarifa: str = "Padrão"
    nome_quarto: str = ""


class DadosMercado(BaseModel):
    """Dados de mercado coletados do Booking para um projeto."""

    id_projeto: str
    url: str
    ano: int
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    diarias_por_periodo: dict[str, DiariaPeriodo] = Field(default_factory=dict)


class MarketBrutoRegistro(BaseModel):
    """Um registro de preço na coleta expandida (market bruto)."""

    checkin: str
    checkout: str
    mes_ano: str
    tipo_dia: str
    preco_booking: float | None = None
    preco_direto: float | None = None
    nome_quarto: str = ""
    tipo_tarifa: str = "Padrão"
    noites: int = 2
    status: str | None = None
    categoria_dia: Literal["normal", "especial"] = "normal"


class MarketBruto(BaseModel):
    """Resultado bruto da coleta expandida (12 meses × 4 datas/mês)."""

    id_projeto: str
    url: str
    ano: int
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    registros: list[MarketBrutoRegistro] = Field(default_factory=list)


class MarketCuradoRegistro(BaseModel):
    """Registro com preço curado (manual).

    Observações:
    - preco_booking e preco_direto podem ser None quando o bruto veio de período com FALHA.
    - preco_curado None indica que o valor efetivo deve usar o preço direto/bruto.
    """

    checkin: str
    checkout: str
    mes_ano: str
    tipo_dia: str
    preco_booking: float | None = None
    preco_direto: float | None = None
    preco_curado: float | None = None
    status: str = "coletado"
    nome_quarto: str = ""
    tipo_tarifa: str = "Padrão"
    noites: int = 2
    categoria_dia: Literal["normal", "especial"] = "normal"


class MarketCurado(BaseModel):
    """Dados curados (edição manual); mesclado com bruto por check-in."""

    id_projeto: str
    url: str
    ano: int
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    registros: list[MarketCuradoRegistro] = Field(default_factory=list)
