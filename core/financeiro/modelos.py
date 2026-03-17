"""
modelos - Schemas Pydantic para dados financeiros.
Responsabilidade: validação de receitas, despesas e métricas financeiras.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Infraestrutura(BaseModel):
    """Características de infraestrutura que impactam custos operacionais (sugestões/benchmarks)."""

    tipo_unidade: Optional[str] = Field(
        default=None,
        description="Valores: quarto_standard, chale_com_cozinha, apartamento",
    )
    matriz_energetica: Optional[str] = Field(
        default=None,
        description="Valores: rede_concessionaria, energia_solar",
    )
    matriz_hidrica: Optional[str] = Field(
        default=None,
        description="Valores: rede_concessionaria, poco_artesiano",
    )
    modelo_lavanderia: Optional[str] = Field(
        default=None,
        description="Valores: interna, externa_terceirizada",
    )


class CustosFixosMensais(BaseModel):
    """Custos fixos mensais do empreendimento."""

    luz: float = Field(default=0.0, ge=0)
    agua: float = Field(default=0.0, ge=0)
    internet: float = Field(default=0.0, ge=0)
    iptu: float = Field(default=0.0, ge=0)
    contabilidade: float = Field(default=0.0, ge=0)
    seguros: float = Field(default=0.0, ge=0)
    outros: float = Field(default=0.0, ge=0)
    aluguel: float = Field(default=0.0, ge=0, description="Aluguel/Arrendamento pretendido (mensal)")


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
    folha_pagamento_mensal: float = Field(default=0.0, ge=0, description="Folha de pagamento total mensal (R$)")
    funcionarios: List[Funcionario] = Field(default_factory=list)
    custos_variaveis: CustosVariaveisPorNoite = Field(
        default_factory=CustosVariaveisPorNoite
    )
    media_pessoas_por_diaria: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Média de pessoas por diária vendida. Usado para calcular custo variável por noite. Default 2.0 (backward compatible).",
    )
    aliquota_impostos: float = Field(default=0.06, ge=0, le=1)
    percentual_contingencia: float = Field(default=0.05, ge=0, le=1)
    outros_impostos_taxas_percentual: float = Field(default=0.0, ge=0, le=1, description="Outros impostos/taxas (0-1)")
