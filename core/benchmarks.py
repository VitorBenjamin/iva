"""
benchmarks - Tabela de benchmarks calibrados (Sonhos de Praia 2025 e referências).
Responsabilidade: presets por tipo de unidade, fatores matriz energética/hídrica, referências absolutas.
"""
from typing import Any, Optional

# Presets por tipo de unidade (dados reais calibrados).
PRESETS_TIPO_UNIDADE: dict[str, dict[str, Any]] = {
    "chale_com_cozinha": {
        "media_pessoas_por_diaria": 2.46,
        "cafe_manha_por_pessoa_noite": 13.92,
        "lavanderia_interna_por_pessoa_noite": 2.20,  # R$5,42/diária ÷ 2,46
        "lavanderia_externa_por_pessoa_noite": 11.38,  # R$28/diária ÷ 2,46
    },
    "quarto_standard": {
        "media_pessoas_por_diaria": 2.10,
        "cafe_manha_por_pessoa_noite": 11.83,
        "lavanderia_interna_por_pessoa_noite": 2.14,  # R$4,50/diária ÷ 2,10
        "lavanderia_externa_por_pessoa_noite": 11.90,  # R$25/diária ÷ 2,10
    },
    "apartamento": {
        "media_pessoas_por_diaria": 2.20,
        "cafe_manha_por_pessoa_noite": 12.50,
        "lavanderia_interna_por_pessoa_noite": 2.27,  # R$5,00/diária ÷ 2,20
        "lavanderia_externa_por_pessoa_noite": 11.36,  # R$25/diária ÷ 2,20
    },
}

# Fatores por matriz (energia solar → 10% do valor rede; poço → 20% do valor rede).
PRESETS_MATRIZ: dict[str, dict[str, float]] = {
    "energia_solar": {"fator_luz": 0.10},
    "poco_artesiano": {"fator_agua": 0.20},
}

# Referências absolutas mensais (Sonhos de Praia, 10 chalés, rede). Agosto excluído (outlier R$65.447).
REFERENCIA_LUZ_MENSAL: float = 2117.36
REFERENCIA_AGUA_MENSAL: float = 169.13


def obter_presets_infraestrutura(
    tipo_unidade: Optional[str] = None,
    matriz_energetica: Optional[str] = None,
    matriz_hidrica: Optional[str] = None,
    modelo_lavanderia: Optional[str] = None,
    numero_quartos: int = 10,
) -> dict[str, Any]:
    """
    Retorna presets para o front aplicar: media_pessoas_por_diaria, cafe_manha, lavanderia,
    sugestao_luz, sugestao_agua. Luz e água escalados por (numero_quartos / 10).
    Lavanderia: interna ou externa conforme modelo_lavanderia.
    Se tipo_unidade não informado, usa quarto_standard como base.
    """
    base = tipo_unidade if tipo_unidade and tipo_unidade in PRESETS_TIPO_UNIDADE else "quarto_standard"
    presets_tipo = PRESETS_TIPO_UNIDADE[base]
    escala = max(0.1, numero_quartos) / 10.0

    media = presets_tipo["media_pessoas_por_diaria"]
    cafe_manha = presets_tipo["cafe_manha_por_pessoa_noite"]
    if modelo_lavanderia == "externa_terceirizada":
        lavanderia = presets_tipo["lavanderia_externa_por_pessoa_noite"]
    else:
        lavanderia = presets_tipo["lavanderia_interna_por_pessoa_noite"]

    luz_base = REFERENCIA_LUZ_MENSAL * escala
    agua_base = REFERENCIA_AGUA_MENSAL * escala
    if matriz_energetica == "energia_solar":
        fator = PRESETS_MATRIZ.get("energia_solar", {}).get("fator_luz", 0.10)
        sugestao_luz = round(luz_base * fator, 2)
    else:
        sugestao_luz = round(luz_base, 2)
    if matriz_hidrica == "poco_artesiano":
        fator = PRESETS_MATRIZ.get("poco_artesiano", {}).get("fator_agua", 0.20)
        sugestao_agua = round(agua_base * fator, 2)
    else:
        sugestao_agua = round(agua_base, 2)

    return {
        "media_pessoas_por_diaria": media,
        "cafe_manha": round(cafe_manha, 2),
        "lavanderia": round(lavanderia, 2),
        "sugestao_luz": sugestao_luz,
        "sugestao_agua": sugestao_agua,
    }
