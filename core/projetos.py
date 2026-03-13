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


PROJECTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "projects"


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
    """Persiste projeto em data/projects/<id>.json."""
    _assegurar_dir_projetos()
    caminho = PROJECTS_DIR / f"{projeto.id}.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(projeto.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    logger.info("Projeto salvo: {}", projeto.id)


def carregar_projeto(id_projeto: str) -> Projeto:
    """Carrega projeto de data/projects/<id>.json."""
    caminho = PROJECTS_DIR / f"{id_projeto}.json"
    if not caminho.exists() or not caminho.is_file():
        raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_projeto}' não encontrado.")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return Projeto.model_validate(dados)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Erro ao carregar projeto {}: {}", id_projeto, e)
        raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_projeto}' inválido.") from e


def listar_projetos() -> List[Projeto]:
    """Lista projetos em data/projects/, ignorando market_*.json e subpastas."""
    if not PROJECTS_DIR.exists():
        return []
    projetos: List[Projeto] = []
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir() or p.suffix != ".json":
            continue
        if p.name.startswith("market_") or p.name == "market_.json":
            continue
        try:
            projetos.append(carregar_projeto(p.stem))
        except ArquivoProjetoNaoEncontrado:
            continue
    return sorted(projetos, key=lambda x: x.nome)
