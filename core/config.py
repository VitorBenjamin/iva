"""
config - Configurações e constantes da aplicação.
Responsabilidade: centralizar variáveis de ambiente e parâmetros de configuração.
"""
import calendar
from datetime import date, timedelta


def _carnaval_checkin_checkout(ano: int) -> tuple[str, str]:
    """Retorna (checkin, checkout) para Carnaval; tabela 2026/2027 ou fallback março."""
    tabela = {
        2026: ("2026-02-15", "2026-02-19"),
        2027: ("2027-02-07", "2027-02-11"),
    }
    if ano in tabela:
        return tabela[ano]
    return (f"{ano}-03-01", f"{ano}-03-05")


def definir_periodos_sazonais(ano_base: int) -> list[dict]:
    """Retorna períodos sazonais com datas sempre futuras (janela móvel 12 meses)."""
    hoje = date.today()

    def _ano_efetivo(ano: int, mes: int, dia: int) -> int:
        if date(ano, mes, dia) >= hoje:
            return ano
        return ano + 1

    # Alta Janeiro: 15–20/01
    a1 = _ano_efetivo(ano_base, 1, 15)
    p_alta_jan = {
        "codigo": "alta_janeiro",
        "nome_periodo": "Alta Temporada - Janeiro",
        "checkin": f"{a1}-01-15",
        "checkout": f"{a1}-01-20",
        "noites": 5,
    }

    # Alta Julho: 15–20/07
    a2 = _ano_efetivo(ano_base, 7, 15)
    p_alta_jul = {
        "codigo": "alta_julho",
        "nome_periodo": "Alta Temporada - Julho",
        "checkin": f"{a2}-07-15",
        "checkout": f"{a2}-07-20",
        "noites": 5,
    }

    # Réveillon: 28/12 a 02/01 ano+1
    a3 = _ano_efetivo(ano_base, 12, 28)
    p_reveillon = {
        "codigo": "reveillon",
        "nome_periodo": "Réveillon",
        "checkin": f"{a3}-12-28",
        "checkout": f"{a3 + 1}-01-02",
        "noites": 5,
    }

    # Carnaval (datas variáveis)
    a4 = _ano_efetivo(ano_base, 2, 15)
    c_in, c_out = _carnaval_checkin_checkout(a4)
    p_carnaval = {
        "codigo": "carnaval",
        "nome_periodo": "Carnaval",
        "checkin": c_in,
        "checkout": c_out,
        "noites": 4,
    }

    # Baixa Maio: 10–14/05
    a5 = _ano_efetivo(ano_base, 5, 10)
    p_baixa_maio = {
        "codigo": "baixa_maio",
        "nome_periodo": "Baixa Temporada - Maio",
        "checkin": f"{a5}-05-10",
        "checkout": f"{a5}-05-14",
        "noites": 4,
    }

    # Baixa Setembro: 15–18/09
    a6 = _ano_efetivo(ano_base, 9, 15)
    p_baixa_set = {
        "codigo": "baixa_setembro",
        "nome_periodo": "Baixa Temporada - Setembro",
        "checkin": f"{a6}-09-15",
        "checkout": f"{a6}-09-18",
        "noites": 3,
    }

    return [p_alta_jan, p_alta_jul, p_reveillon, p_carnaval, p_baixa_maio, p_baixa_set]


def _nth_weekday(ano: int, mes: int, weekday: int, n: int) -> date:
    """weekday 0=seg, 5=sáb, 6=dom. n=1 é primeira ocorrência no mês."""
    primeiro = date(ano, mes, 1)
    # weekday() em Python: 0=segunda, 5=sábado, 6=domingo
    delta = (weekday - primeiro.weekday()) % 7
    if delta and n == 1:
        dia = 1 + delta
    else:
        dia = 1 + delta + (n - 1) * 7
    if dia > calendar.monthrange(ano, mes)[1]:
        dia = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, dia)


def definir_periodos_12meses(noites: int = 2) -> list[dict]:
    """4 datas por mês (2 fim de semana, 2 dia de semana) × 12 meses a partir do mês atual."""
    hoje = date.today()
    periodos = []
    for m in range(12):
        mes = hoje.month + m
        ano = hoje.year + (mes - 1) // 12
        mes = (mes - 1) % 12 + 1
        if date(ano, mes, 1) < hoje.replace(day=1):
            continue
        mes_ano = f"{ano}-{mes:02d}"
        sab1 = _nth_weekday(ano, mes, 5, 1)
        sab3 = _nth_weekday(ano, mes, 5, 3)
        ter2 = _nth_weekday(ano, mes, 1, 2)
        ter4 = _nth_weekday(ano, mes, 1, 4)
        for checkin, tipo in [(sab1, "fim_de_semana"), (sab3, "fim_de_semana"), (ter2, "dia_de_semana"), (ter4, "dia_de_semana")]:
            if checkin < hoje:
                continue
            checkout = checkin + timedelta(days=noites)
            periodos.append({
                "checkin": checkin.strftime("%Y-%m-%d"),
                "checkout": checkout.strftime("%Y-%m-%d"),
                "mes_ano": mes_ano,
                "tipo_dia": tipo,
                "noites": noites,
            })
    return periodos
