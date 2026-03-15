"""
cli - Entry point de linha de comando para o scraper expandido.
Uso:
    python -m core.scraper.cli --url "https://..." --id "meu-projeto"
    python -m core.scraper.cli --url "https://..." --id "meu-projeto" --ano 2026
"""
import argparse
from datetime import date
from typing import Tuple

from loguru import logger

from core.projetos import ArquivoProjetoNaoEncontrado, Projeto, carregar_projeto, get_market_bruto_path, salvar_projeto
from core.scraper.scrapers import coletar_dados_mercado_expandido


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rodar coleta expandida de dados de mercado para um projeto IVA."
    )
    parser.add_argument("--url", required=True, help="URL do Booking.com do ativo.")
    parser.add_argument("--id", required=True, dest="id_projeto", help="ID do projeto (slug).")
    parser.add_argument(
        "--ano",
        type=int,
        default=None,
        help="Define o ciclo/rótulo do projeto (projeto.ano_referencia), não o intervalo de coleta. "
        "Opcional; padrão: ano atual.",
    )
    return parser.parse_args()


def _atualizar_projeto(id_projeto: str, url: str, ano: int) -> Projeto:
    """Carrega o projeto, atualiza url_booking/ano_referencia se necessário e persiste."""
    try:
        projeto = carregar_projeto(id_projeto)
    except ArquivoProjetoNaoEncontrado:
        from core.projetos import PROJECTS_DIR
        raise SystemExit(f"Projeto '{id_projeto}' não encontrado em {PROJECTS_DIR}.")

    alterado = False
    if projeto.url_booking != url:
        logger.info("Atualizando url_booking do projeto {}.", id_projeto)
        projeto.url_booking = url
        alterado = True
    if projeto.ano_referencia != ano:
        logger.info("Atualizando ano_referencia do projeto {} para {}.", id_projeto, ano)
        projeto.ano_referencia = ano
        alterado = True

    if alterado:
        salvar_projeto(projeto)
        logger.info("Projeto atualizado e salvo.")
    else:
        logger.info("Projeto já estava com url_booking e ano_referencia informados.")

    return projeto


def _resumo_registros(market) -> Tuple[int, int, int]:
    """Retorna (total, ok, falha) com base nos registros do MarketBruto."""
    registros = getattr(market, "registros", []) or []
    total = len(registros)
    ok = 0
    falha = 0
    for r in registros:
        status = getattr(r, "status", None)
        if status == "OK":
            ok += 1
        elif status == "FALHA" or r.preco_booking is None or r.preco_direto is None:
            falha += 1
    return total, ok, falha


def main() -> None:
    args = _parse_args()
    url = args.url
    id_projeto = args.id_projeto
    ano = args.ano if args.ano is not None else date.today().year

    logger.info("Iniciando CLI do scraper para projeto '{}' (ano rótulo: {}).", id_projeto, ano)
    projeto = _atualizar_projeto(id_projeto=id_projeto, url=url, ano=ano)

    # Usa a função de coleta expandida existente (não altera lógica interna).
    market = coletar_dados_mercado_expandido(url_booking=projeto.url_booking, id_projeto=projeto.id)
    total, ok, falha = _resumo_registros(market)
    path_bruto = get_market_bruto_path(projeto.id)

    print("=== Resumo da Coleta Expandida ===")
    print(f"Projeto.............: {projeto.id} ({projeto.nome})")
    print(f"URL Booking.........: {projeto.url_booking}")
    print(f"Ano de referência...: {projeto.ano_referencia}")
    print(f"Total de registros..: {total}")
    print(f"Registros OK........: {ok}")
    print(f"Registros FALHA.....: {falha}")
    print(f"Arquivo de saída....: {path_bruto}")


if __name__ == "__main__":
    main()

