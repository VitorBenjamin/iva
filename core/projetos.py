"""
projetos - CRUD de projetos de viabilidade.
Responsabilidade: persistência e recuperação de projetos em data/projects/.
"""
import json
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from core.financeiro.modelos import DadosFinanceiros


class ArquivoProjetoNaoEncontrado(Exception):
    """Projeto não encontrado em data/projects/."""

    pass


class Projeto(BaseModel):
    """Entidade projeto – pousada / análise de viabilidade."""

    id: str
    nome: str
    url_booking: str = ""
    numero_quartos: int = Field(ge=1)
    faturamento_anual: float = Field(ge=0)
    ano_referencia: int = Field(ge=2000, le=2100)
    financeiro: DadosFinanceiros = Field(default_factory=DadosFinanceiros)
    # Será substituído por DadosMercado quando o módulo scraper for implementado.
    dados_mercado: Optional[Any] = None


PROJECTS_DIR = Path(__file__).resolve().parent.parent / "data" / "projects"


def get_projeto_dir(id_projeto: str) -> Path:
    """Retorna o diretório do projeto: data/projects/<id>/."""
    return PROJECTS_DIR / id_projeto


def get_projeto_json_path(id_projeto: str) -> Path:
    """Retorna o path do arquivo principal do projeto: data/projects/<id>/projeto.json."""
    return get_projeto_dir(id_projeto) / "projeto.json"


def get_market_bruto_path(id_projeto: str) -> Path:
    """Retorna o path do market bruto: data/projects/<id>/market_bruto.json."""
    return get_projeto_dir(id_projeto) / "market_bruto.json"


def get_market_curado_path(id_projeto: str) -> Path:
    """Retorna o path do market curado: data/projects/<id>/market_curado.json."""
    return get_projeto_dir(id_projeto) / "market_curado.json"


def get_scraper_config_path(id_projeto: str) -> Path:
    """Retorna o path da config do scraper: data/projects/<id>/scraper_config.json."""
    return get_projeto_dir(id_projeto) / "scraper_config.json"


def _assegurar_dir_projetos() -> None:
    """Garante que data/projects existe."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def gerar_id_projeto(nome: str) -> str:
    """Gera ID slug a partir do nome (seguro para nomes de arquivo)."""
    if not nome or not nome.strip():
        return f"projeto-{uuid.uuid4().hex[:8]}"
    nfd = unicodedata.normalize("NFD", nome.strip().lower())
    sem_acentos = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acentos).strip("-")
    return slug if slug else f"projeto-{uuid.uuid4().hex[:8]}"


def salvar_projeto(projeto: Projeto) -> None:
    """Persiste projeto em data/projects/<id>/projeto.json."""
    _assegurar_dir_projetos()
    caminho = get_projeto_json_path(projeto.id)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(projeto.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    logger.info("Projeto salvo: {}", projeto.id)


def carregar_projeto(id_projeto: str) -> Projeto:
    """Carrega projeto: tenta data/projects/<id>/projeto.json, depois data/projects/<id>.json (legado)."""
    caminho = get_projeto_json_path(id_projeto)
    if not caminho.exists() or not caminho.is_file():
        caminho_legado = PROJECTS_DIR / f"{id_projeto}.json"
        if caminho_legado.exists() and caminho_legado.is_file():
            caminho = caminho_legado
        else:
            raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_projeto}' não encontrado.")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return Projeto.model_validate(dados)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Erro ao carregar projeto {}: {}", id_projeto, e)
        raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_projeto}' inválido.") from e


def listar_projetos() -> List[Projeto]:
    """Lista projetos: subpastas com projeto.json e arquivos <id>.json na raiz (legado), sem duplicar IDs."""
    if not PROJECTS_DIR.exists():
        return []
    ids_vistos: set[str] = set()
    projetos: List[Projeto] = []
    # Novos: subpastas com projeto.json
    for p in PROJECTS_DIR.iterdir():
        if not p.is_dir():
            continue
        proj_json = p / "projeto.json"
        if proj_json.exists() and proj_json.is_file() and p.name not in ids_vistos:
            try:
                projetos.append(carregar_projeto(p.name))
                ids_vistos.add(p.name)
            except ArquivoProjetoNaoEncontrado:
                continue
    # Legado: arquivos .json na raiz (exceto market_*, scraper_config_*)
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir() or p.suffix != ".json":
            continue
        if p.name.startswith("market_") or p.name.startswith("scraper_config_"):
            continue
        if p.stem in ids_vistos:
            continue
        try:
            projetos.append(carregar_projeto(p.stem))
            ids_vistos.add(p.stem)
        except ArquivoProjetoNaoEncontrado:
            continue
    return sorted(projetos, key=lambda x: x.nome)


def migrar_estrutura_legada() -> None:
    """Migra arquivos do formato legado para projects/<id>/projeto.json, market_bruto.json, etc."""
    _assegurar_dir_projetos()
    if not PROJECTS_DIR.exists():
        return
    import shutil
    for p in PROJECTS_DIR.iterdir():
        if p.is_file() and p.suffix == ".json" and not p.name.startswith("market_") and not p.name.startswith("scraper_config_"):
            id_projeto = p.stem
            dir_projeto = get_projeto_dir(id_projeto)
            destino_projeto = get_projeto_json_path(id_projeto)
            if destino_projeto.exists():
                continue
            try:
                dir_projeto.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(destino_projeto))
                logger.info("Migrado projeto: {} -> {}", p.name, destino_projeto)
            except Exception as e:
                logger.warning("Falha ao migrar {}: {}", p.name, e)
    for p in PROJECTS_DIR.iterdir():
        if p.is_file() and p.name.startswith("market_bruto_") and p.suffix == ".json":
            id_projeto = p.name.replace("market_bruto_", "").replace(".json", "")
            dir_projeto = get_projeto_dir(id_projeto)
            destino = get_market_bruto_path(id_projeto)
            if destino.exists():
                continue
            try:
                dir_projeto.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(destino))
                logger.info("Migrado market bruto: {} -> {}", p.name, destino)
            except Exception as e:
                logger.warning("Falha ao migrar {}: {}", p.name, e)
    for p in PROJECTS_DIR.iterdir():
        if p.is_file() and p.name.startswith("market_curado_") and p.suffix == ".json":
            id_projeto = p.name.replace("market_curado_", "").replace(".json", "")
            dir_projeto = get_projeto_dir(id_projeto)
            destino = get_market_curado_path(id_projeto)
            if destino.exists():
                continue
            try:
                dir_projeto.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(destino))
                logger.info("Migrado market curado: {} -> {}", p.name, destino)
            except Exception as e:
                logger.warning("Falha ao migrar {}: {}", p.name, e)
    for p in PROJECTS_DIR.iterdir():
        if p.is_file() and p.name.startswith("scraper_config_") and p.suffix == ".json":
            id_projeto = p.name.replace("scraper_config_", "").replace(".json", "")
            dir_projeto = get_projeto_dir(id_projeto)
            destino = get_scraper_config_path(id_projeto)
            if destino.exists():
                continue
            try:
                dir_projeto.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(destino))
                logger.info("Migrado scraper config: {} -> {}", p.name, destino)
            except Exception as e:
                logger.warning("Falha ao migrar {}: {}", p.name, e)
