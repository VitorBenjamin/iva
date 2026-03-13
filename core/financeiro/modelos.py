"""
modelos - Schemas Pydantic para dados financeiros.
Responsabilidade: validação de receitas, despesas e métricas financeiras.
"""
from typing import List

from pydantic import BaseModel, Field


class CustosFixosMensais(BaseModel):
    """Custos fixos mensais do empreendimento."""

    luz: float = Field(default=0.0, ge=0)
    agua: float = Field(default=0.0, ge=0)
    internet: float = Field(default=0.0, ge=0)
    iptu: float = Field(default=0.0, ge=0)
    contabilidade: float = Field(default=0.0, ge=0)
    seguros: float = Field(default=0.0, ge=0)
    outros: float = Field(default=0.0, ge=0)


class Funcionario(BaseModel):
    """Funcionário e seus custos."""

    nome: str
    salario: float = Field(ge=0)
    encargos_percentual: float = Field(default=0.0, ge=0, le=1)
    quantidade: int = Field(default=1, ge=1)


class CustosVariaveisPorNoite(BaseModel):
    """Custos variáveis por noite vendida."""

    cafe_manha: float = Field(default=0.0, ge=0)
    amenities: float = Field(default=0.0, ge=0)
    lavanderia: float = Field(default=0.0, ge=0)
    outros: float = Field(default=0.0, ge=0)


class DadosFinanceiros(BaseModel):
    """Dados financeiros consolidados do projeto."""

    custos_fixos: CustosFixosMensais = Field(default_factory=CustosFixosMensais)
    funcionarios: List[Funcionario] = Field(default_factory=list)
    custos_variaveis: CustosVariaveisPorNoite = Field(
        default_factory=CustosVariaveisPorNoite
    )
    aliquota_impostos: float = Field(default=0.06, ge=0, le=1)
    percentual_contingencia: float = Field(default=0.05, ge=0, le=1)
