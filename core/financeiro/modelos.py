"""
modelos - Schemas Pydantic para dados financeiros.
Responsabilidade: validação de receitas, despesas e métricas financeiras.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


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
    aluguel: float = Field(
        default=0.0,
        ge=0,
        description="Legado — ignorado; use projeto.arrendamento_total e prazo_contrato_meses.",
    )


class Funcionario(BaseModel):
    """Funcionário e seus custos detalhados (RH granular)."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    cargo: str
    quantidade: int = Field(default=1, ge=1)
    salario_base: Decimal = Field(default=Decimal("0"), ge=0)
    encargos_pct: Optional[Decimal] = Field(default=None, ge=0, le=1)
    usar_encargos_padrao: bool = Field(
        default=True,
        description="Quando true, usa encargos_pct_padrao global; quando false, usa encargos_pct individual.",
    )
    beneficios: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="before")
    @classmethod
    def _compat_legacy(cls, raw):
        """Aceita payload legado (nome/salario/encargos_percentual)."""
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        if "cargo" not in data:
            data["cargo"] = data.get("nome") or "Equipe"
        if "salario_base" not in data:
            data["salario_base"] = data.get("salario", 0)
        if "encargos_pct" not in data:
            legacy = data.get("encargos_percentual")
            data["encargos_pct"] = legacy if legacy is not None else None
        if "usar_encargos_padrao" not in data:
            data["usar_encargos_padrao"] = data.get("encargos_pct") is None
        if "beneficios" not in data:
            data["beneficios"] = Decimal("0")
        return data


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
    encargos_pct_padrao: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Alíquota padrão de encargos aplicada aos funcionários sem sobrescrita individual.",
    )
    beneficio_vale_transporte: float = Field(
        default=0.0,
        ge=0,
        description="Benefício global de vale transporte por funcionário.",
    )
    beneficio_vale_alimentacao: float = Field(
        default=0.0,
        ge=0,
        description="Benefício global de vale alimentação por funcionário.",
    )
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
    comissao_venda_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Comissão de venda (ex: Booking 13%) como % da Receita Bruta. Custo variável sobre faturamento, NÃO por quarto ocupado. 0-1 (ex: 0.13 = 13%).",
    )
    aliquota_impostos: float = Field(default=0.06, ge=0, le=1)
    percentual_contingencia: float = Field(default=0.05, ge=0, le=1)
    outros_impostos_taxas_percentual: float = Field(default=0.0, ge=0, le=1, description="Outros impostos/taxas (0-1)")

    def calcular_folha_total_decimal(self) -> Decimal:
        """
        Folha total mensal calculada por RH granular.
        Fórmula por funcionário: (salario_base * quantidade) * (1 + encargos_pct) + beneficios.
        """
        total = Decimal("0")
        if not self.funcionarios:
            return Decimal(str(self.folha_pagamento_mensal or 0))
        encargos_padrao = Decimal(str(self.encargos_pct_padrao or 0))
        beneficio_global_por_func = Decimal(
            str((self.beneficio_vale_transporte or 0) + (self.beneficio_vale_alimentacao or 0))
        )
        for f in self.funcionarios:
            salario = Decimal(str(f.salario_base or 0))
            qtd = Decimal(int(f.quantidade or 1))
            encargos = (
                encargos_padrao
                if bool(getattr(f, "usar_encargos_padrao", True))
                else Decimal(str(f.encargos_pct if f.encargos_pct is not None else encargos_padrao))
            )
            beneficios_individuais = Decimal(str(f.beneficios or 0))
            beneficios_globais = beneficio_global_por_func * qtd
            subtotal = (salario * qtd) * (Decimal("1") + encargos) + beneficios_individuais + beneficios_globais
            total += subtotal
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def folha_total(self) -> float:
        """Valor numérico da folha mensal derivada (compatível com serialização atual)."""
        return float(self.calcular_folha_total_decimal())
