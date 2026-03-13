"""
parsing - Tratamento de strings e preços extraídos.
Responsabilidade: normalização e conversão de dados brutos em estruturas utilizáveis.
"""


def parsear_valor_preco(texto: str) -> float:
    """Remove R$, espaços e pontos de milhar; troca vírgula por ponto; retorna float ou 0.0."""
    if not texto or not isinstance(texto, str):
        return 0.0
    limpo = (
        texto.replace("R$", "")
        .replace(" ", "")
        .replace(".", "")
        .strip()
        .replace(",", ".")
    )
    if not limpo:
        return 0.0
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def detectar_tipo_tarifa(texto: str) -> str:
    """Heurística simples: 'cancelamento grátis' → Reembolsável; senão Padrão."""
    if not texto or not isinstance(texto, str):
        return "Padrão"
    if "cancelamento grátis" in texto.lower() or "reembolsável" in texto.lower():
        return "Reembolsável"
    return "Padrão"
