"""
config - Configurações e constantes da aplicação.
Responsabilidade: centralizar variáveis de ambiente e parâmetros de configuração.
"""
import calendar
from datetime import date, timedelta
from typing import Optional

from loguru import logger


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


# --- Fallback de períodos especiais (usado quando não há config ou falha na leitura) ---
FERIADOS_NACIONAIS: dict[tuple[int, int], str] = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (12, 25): "Natal",
}


def _periodos_especiais_fallback(ano: int) -> list[tuple[date, date, str]]:
    """Períodos especiais hardcoded. Usado como fallback quando config não existe/falha."""
    reveillon_ini = date(ano, 12, 28)
    reveillon_fim = date(ano + 1, 1, 2)
    carnaval_ini_str, carnaval_fim_str = _carnaval_checkin_checkout(ano)
    carnaval_ini = date.fromisoformat(carnaval_ini_str)
    carnaval_fim = date.fromisoformat(carnaval_fim_str)
    semana_santa_ini = date(ano, 3, 28)
    semana_santa_fim = date(ano, 3, 31)
    ferias_julho_ini = date(ano, 7, 10)
    ferias_julho_fim = date(ano, 7, 25)
    return [
        (reveillon_ini, reveillon_fim, "Réveillon"),
        (carnaval_ini, carnaval_fim, "Carnaval"),
        (semana_santa_ini, semana_santa_fim, "Semana Santa"),
        (ferias_julho_ini, ferias_julho_fim, "Férias de Julho"),
    ]


def _parse_ddmmyyyy(s: str) -> date | None:
    """Converte DD/MM/YYYY em date. Retorna None se inválido."""
    if not s or not isinstance(s, str):
        return None
    parts = s.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        dia, mes, ano = int(parts[0]), int(parts[1]), int(parts[2])
        return date(ano, mes, dia)
    except (ValueError, TypeError):
        return None


def _avancar_periodo_se_passado(
    d_ini: date, d_fim: date, hoje: date
) -> tuple[date, date]:
    """Se fim < hoje, avança o período para o próximo ano (dia/mês como template).
    Períodos que cruzam o ano (ex: Réveillon 30/12 → 02/01) são avançados de forma coerente.
    """
    if d_fim >= hoje:
        return d_ini, d_fim
    anos_avancar = 1
    while anos_avancar <= 10:
        novo_ini = date(d_ini.year + anos_avancar, d_ini.month, d_ini.day)
        novo_fim = date(d_fim.year + anos_avancar, d_fim.month, d_fim.day)
        if novo_fim >= hoje:
            return novo_ini, novo_fim
        anos_avancar += 1
    return novo_ini, novo_fim


def _periodos_especiais_de_config(id_projeto: str) -> list[tuple[date, date, str]]:
    """Lê periodos_especiais do scraper_config.json do projeto. Lista vazia em caso de erro.

    Os anos no config são tratados como template; o ano efetivo é calculado em runtime.
    Se fim < date.today(), o período é avançado automaticamente para o próximo ano
    (inclusive períodos que cruzam o ano, ex: Réveillon 30/12 → 02/01).
    """
    cfg = carregar_config_scraper(id_projeto)
    if not cfg:
        return []
    pe = cfg.get("periodos_especiais")
    if not pe or not isinstance(pe, list):
        return []
    hoje = date.today()
    result: list[tuple[date, date, str]] = []
    for item in pe:
        if not isinstance(item, dict):
            continue
        inicio_str = item.get("inicio")
        fim_str = item.get("fim")
        nome = item.get("nome") or ""
        d_ini = _parse_ddmmyyyy(str(inicio_str)) if inicio_str is not None else None
        d_fim = _parse_ddmmyyyy(str(fim_str)) if fim_str is not None else None
        if d_ini is None:
            logger.warning("periodos_especiais: início inválido '{}' ignorado", inicio_str)
            continue
        if d_fim is None:
            d_fim = d_ini
        if d_fim < d_ini:
            d_ini, d_fim = d_fim, d_ini
        d_ini, d_fim = _avancar_periodo_se_passado(d_ini, d_fim, hoje)
        result.append((d_ini, d_fim, nome))
    return result


def _eh_especial(
    d: date,
    periodos: list[tuple[date, date, str]],
    feriados: dict[tuple[int, int], str],
) -> bool:
    """Verifica se a data está em algum período especial ou é feriado nacional."""
    for ini, fim, _ in periodos:
        if ini <= d <= fim:
            return True
    if (d.month, d.day) in feriados:
        return True
    return False


def definir_periodos_12meses(noites: int = 2, id_projeto: Optional[str] = None) -> list[dict]:
    """4 datas por mês (2 fim de semana, 2 dia de semana) × 12 meses a partir do mês atual.

    Além da classificação por tipo_dia (fim_de_semana / dia_de_semana),
    marca categoria_dia = "especial" quando a data está em períodos de alta demanda.
    Usa periodos_especiais do scraper_config.json do projeto quando id_projeto é informado;
    caso contrário, usa fallback hardcoded (Réveillon, Carnaval, Semana Santa, julho, feriados).
    """
    hoje = date.today()

    # Carregar períodos: config do projeto ou fallback hardcoded
    periodos_list: list[tuple[date, date, str]] = []
    feriados_atuais: dict[tuple[int, int], str] = {}
    try:
        if id_projeto:
            periodos_list = _periodos_especiais_de_config(id_projeto)
        if not periodos_list:
            for a in (hoje.year, hoje.year + 1):
                periodos_list.extend(_periodos_especiais_fallback(a))
            feriados_atuais = FERIADOS_NACIONAIS
        else:
            feriados_atuais = {}  # Config tem prioridade; feriados ficam no config se necessário
    except Exception as e:
        logger.warning("Erro ao carregar periodos_especiais, usando fallback: {}", e)
        for a in (hoje.year, hoje.year + 1):
            periodos_list.extend(_periodos_especiais_fallback(a))
        feriados_atuais = FERIADOS_NACIONAIS

    def eh_especial(d: date) -> bool:
        return _eh_especial(d, periodos_list, feriados_atuais)

    periodos: list[dict] = []
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
        for checkin, tipo in [
            (sab1, "fim_de_semana"),
            (sab3, "fim_de_semana"),
            (ter2, "dia_de_semana"),
            (ter4, "dia_de_semana"),
        ]:
            if checkin < hoje:
                continue
            checkout = checkin + timedelta(days=noites)
            categoria = "especial" if eh_especial(checkin) else "normal"
            periodos.append(
                {
                    "checkin": checkin.strftime("%Y-%m-%d"),
                    "checkout": checkout.strftime("%Y-%m-%d"),
                    "mes_ano": mes_ano,
                    "tipo_dia": tipo,
                    "categoria_dia": categoria,
                    "noites": noites,
                }
            )
    return periodos


def definir_calendario_soberano_ano(
    ano_referencia: int,
    noites: int = 2,
    id_projeto: Optional[str] = None,
    rolling: bool = True,
) -> dict:
    """Calendário soberano: retorna duas listas — normais (4 datas/mês, excluindo especiais) e especiais (1–2 check-ins por período).

    Com rolling=True (padrão): janela [date.today(), date.today()+365 dias].
    Normais: 4 datas/mês na janela; qualquer data que pertença a período especial é EXCLUÍDA (deduplicação).
    Especiais: para cada período em periodos_especiais, 1 check-in (primeiro dia) se período ≤5 dias,
    ou 2 check-ins (primeiro + dia central) se >5 dias; nunca gera datas passadas.
    Retorno: {"normais": list[dict], "especiais": list[dict]}. Cada dict tem checkin, checkout, mes_ano, tipo_dia, categoria_dia, noites; especiais têm ainda "periodo_nome".
    """
    hoje = date.today()
    ano_fallback = hoje.year if rolling else ano_referencia

    periodos_list: list[tuple[date, date, str]] = []
    feriados_atuais: dict[tuple[int, int], str] = {}
    try:
        if id_projeto:
            periodos_list = _periodos_especiais_de_config(id_projeto)
        if not periodos_list:
            for a in (ano_fallback, ano_fallback + 1):
                periodos_list.extend(_periodos_especiais_fallback(a))
            feriados_atuais = FERIADOS_NACIONAIS
        else:
            feriados_atuais = {}
    except Exception as e:
        logger.warning("Erro ao carregar periodos_especiais (calendário soberano), usando fallback: {}", e)
        for a in (ano_fallback, ano_fallback + 1):
            periodos_list.extend(_periodos_especiais_fallback(a))
        feriados_atuais = FERIADOS_NACIONAIS

    def eh_especial(d: date) -> bool:
        return _eh_especial(d, periodos_list, feriados_atuais)

    fim_janela = hoje + timedelta(days=365) if rolling else date(ano_referencia, 12, 31)
    lista_normais: list[dict] = []
    lista_especiais: list[dict] = []

    def _append_normal(checkin: date, mes_ano: str, tipo: str) -> None:
        if checkin < hoje or checkin > fim_janela:
            return
        if eh_especial(checkin):
            return
        checkout = checkin + timedelta(days=noites)
        lista_normais.append({
            "checkin": checkin.strftime("%Y-%m-%d"),
            "checkout": checkout.strftime("%Y-%m-%d"),
            "mes_ano": mes_ano,
            "tipo_dia": tipo,
            "categoria_dia": "normal",
            "noites": noites,
            "periodo_nome": "",
        })

    if rolling:
        for m in range(12):
            mes = hoje.month + m
            ano = hoje.year + (mes - 1) // 12
            mes = (mes - 1) % 12 + 1
            if date(ano, mes, 1) > fim_janela:
                break
            mes_ano = f"{ano}-{mes:02d}"
            for checkin, tipo in [
                (_nth_weekday(ano, mes, 5, 1), "fim_de_semana"),
                (_nth_weekday(ano, mes, 5, 3), "fim_de_semana"),
                (_nth_weekday(ano, mes, 1, 2), "dia_de_semana"),
                (_nth_weekday(ano, mes, 1, 4), "dia_de_semana"),
            ]:
                _append_normal(checkin, mes_ano, tipo)
    else:
        for mes in range(1, 13):
            mes_ano = f"{ano_referencia}-{mes:02d}"
            for checkin, tipo in [
                (_nth_weekday(ano_referencia, mes, 5, 1), "fim_de_semana"),
                (_nth_weekday(ano_referencia, mes, 5, 3), "fim_de_semana"),
                (_nth_weekday(ano_referencia, mes, 1, 2), "dia_de_semana"),
                (_nth_weekday(ano_referencia, mes, 1, 4), "dia_de_semana"),
            ]:
                if checkin > fim_janela:
                    continue
                if eh_especial(checkin):
                    continue
                checkout = checkin + timedelta(days=noites)
                lista_normais.append({
                    "checkin": checkin.strftime("%Y-%m-%d"),
                    "checkout": checkout.strftime("%Y-%m-%d"),
                    "mes_ano": mes_ano,
                    "tipo_dia": tipo,
                    "categoria_dia": "normal",
                    "noites": noites,
                    "periodo_nome": "",
                })

    for d_ini, d_fim, nome in periodos_list:
        delta_dias = (d_fim - d_ini).days + 1
        if delta_dias <= 5:
            checkins_periodo = [d_ini]
        else:
            central = d_ini + timedelta(days=(d_fim - d_ini).days // 2)
            checkins_periodo = [d_ini, central]
        for d in checkins_periodo:
            if d < hoje:
                continue
            if d > fim_janela:
                continue
            if not rolling and d.year != ano_referencia:
                continue
            mes_ano = f"{d.year}-{d.month:02d}"
            tipo_dia = "fim_de_semana" if d.weekday() in (5, 6) else "dia_de_semana"
            checkout = d + timedelta(days=noites)
            lista_especiais.append({
                "checkin": d.strftime("%Y-%m-%d"),
                "checkout": checkout.strftime("%Y-%m-%d"),
                "mes_ano": mes_ano,
                "tipo_dia": tipo_dia,
                "categoria_dia": "especial",
                "noites": noites,
                "periodo_nome": nome or "Especial",
            })

    return {"normais": lista_normais, "especiais": lista_especiais}


def gerar_calendario_diario_projeto(
    id_projeto: str,
    ano_referencia: int,
    rolling: bool = True,
) -> list[dict]:
    """Gera calendário diário: rolling 12 meses a partir de hoje (padrão) ou ano civil completo.

    Com rolling=True (padrão): janela [date.today(), date.today()+365 dias].
    Com rolling=False: ano civil completo 01/01 a 31/12 do ano_referencia.
    Inclui dias de períodos que cruzam o ano (ex: Réveillon 01/01, 02/01).
    Fonte da Verdade para o Scraper.
    Cada objeto: checkin, checkout (checkin+1), mes_ano, categoria_dia, tipo_dia.
    """
    hoje = date.today()
    ano_fallback = hoje.year if rolling else ano_referencia
    periodos_list: list[tuple[date, date, str]] = []
    feriados_atuais: dict[tuple[int, int], str] = {}
    try:
        periodos_list = _periodos_especiais_de_config(id_projeto)
        if not periodos_list:
            for a in (ano_fallback, ano_fallback + 1):
                periodos_list.extend(_periodos_especiais_fallback(a))
            feriados_atuais = FERIADOS_NACIONAIS
    except Exception as e:
        logger.warning("Erro ao carregar periodos_especiais (calendário diário), usando fallback: {}", e)
        for a in (ano_fallback, ano_fallback + 1):
            periodos_list.extend(_periodos_especiais_fallback(a))
        feriados_atuais = FERIADOS_NACIONAIS

    def eh_especial(d: date) -> bool:
        return _eh_especial(d, periodos_list, feriados_atuais)

    calendario: list[dict] = []
    if rolling:
        inicio_janela = hoje
        fim_janela = hoje + timedelta(days=365)
    else:
        inicio_janela = date(ano_referencia, 1, 1)
        fim_janela = date(ano_referencia, 12, 31)
    dia_atual = inicio_janela
    while dia_atual <= fim_janela:
        checkin_str = dia_atual.strftime("%Y-%m-%d")
        checkout_date = dia_atual + timedelta(days=1)
        checkout_str = checkout_date.strftime("%Y-%m-%d")
        mes_ano = f"{dia_atual.year}-{dia_atual.month:02d}"
        categoria = "especial" if eh_especial(dia_atual) else "normal"
        wd = dia_atual.weekday()
        tipo_dia = "fim_de_semana" if wd in (5, 6) else "dia_de_semana"
        calendario.append({
            "checkin": checkin_str,
            "checkout": checkout_str,
            "mes_ano": mes_ano,
            "categoria_dia": categoria,
            "tipo_dia": tipo_dia,
        })
        dia_atual += timedelta(days=1)
    return calendario


def carregar_config_scraper(id_projeto: str) -> dict | None:
    """Lê scraper_config do projeto (projects/<id>/scraper_config.json ou legado). Retorna None se não existir."""
    from core.projetos import PROJECTS_DIR, get_scraper_config_path
    import json

    path = get_scraper_config_path(id_projeto)
    if not path.exists():
        path = PROJECTS_DIR / f"scraper_config_{id_projeto}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def salvar_config_scraper(id_projeto: str, cfg: dict) -> None:
    """Salva scraper_config em projects/<id>/scraper_config.json."""
    from core.projetos import get_scraper_config_path
    import json

    path = get_scraper_config_path(id_projeto)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def obter_config_scraper_com_defaults(id_projeto: str) -> dict:
    """Retorna config do scraper; se não existir, retorna defaults."""
    cfg = carregar_config_scraper(id_projeto)
    if cfg:
        return cfg
    return {
        "periodos_especiais": [
            {"inicio": "28/12/2026", "fim": "02/01/2027", "nome": "Réveillon"},
            {"inicio": "14/02/2026", "fim": "18/02/2026", "nome": "Carnaval"},
            {"inicio": "28/03/2026", "fim": "05/04/2026", "nome": "Semana Santa / Páscoa"},
            {"inicio": "10/07/2026", "fim": "25/07/2026", "nome": "Férias de Julho"},
            {"inicio": "07/09/2026", "fim": "07/09/2026", "nome": "Independência"},
            {"inicio": "12/10/2026", "fim": "12/10/2026", "nome": "Nossa Sra. Aparecida"},
            {"inicio": "02/11/2026", "fim": "02/11/2026", "nome": "Finados"},
            {"inicio": "15/11/2026", "fim": "15/11/2026", "nome": "Proclamação da República"},
            {"inicio": "25/12/2026", "fim": "25/12/2026", "nome": "Natal"},
        ],
        "amostragem": {
            "datas_normais_por_mes": 4,
            "incluir_fds": True,
            "incluir_dias_uteis": True,
        },
        "parametros_tecnicos": {
            "timeout_ms": 60000,
            "delay_min_s": 8,
            "delay_max_s": 18,
            "headless": True,
            "stealth": True,
        },
        "noites": {
            "preferencial": 2,
            "max_tentativas": 4,
        },
        "descontos": {
            "global": 0.20,
            "por_mes": {},
        },
    }
