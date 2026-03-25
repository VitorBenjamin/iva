"""
projetos - CRUD de projetos de viabilidade.
Responsabilidade: persistência e recuperação de projetos em data/projects/.
"""
import json
import re
import shutil
import unicodedata
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger
from pydantic import BaseModel, Field, model_validator

from core.financeiro.modelos import DadosFinanceiros, Infraestrutura


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
    infraestrutura: Optional[Infraestrutura] = Field(
        default=None,
        description="Características de infraestrutura para sugestões de custo (opcional, compatível com projetos antigos).",
    )
    # Será substituído por DadosMercado quando o módulo scraper for implementado.
    dados_mercado: Optional[Any] = None
    # Fallback multi-base: IDs de projetos cujos dados (ADR/preços) podem ser usados quando ausentes.
    projetos_referencia: List[str] = Field(default_factory=list)
    # Multiplicador para preços vindos de referência (ex: 1.10 = +10%). Preparado para uso futuro.
    markup_referencia: Optional[float] = Field(default=None, ge=0.01, le=10.0)
    arrendamento_total: float = Field(
        default=0.0,
        ge=0,
        description="Valor total pago pelo contrato de arrendamento (visão de caixa).",
    )
    prazo_contrato_meses: int = Field(
        default=12,
        ge=1,
        le=600,
        description="Duração do contrato em meses (para ratear o custo mensal na simulação).",
    )
    investimento_reforma: float = Field(
        default=0.0,
        ge=0,
        description="CAPEX de reforma/enxoval (antecipado). Antigo investimento_inicial.",
    )

    @model_validator(mode="before")
    @classmethod
    def _compat_investimento_e_arrendamento(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "investimento_reforma" not in out and "investimento_inicial" in out:
            out["investimento_reforma"] = float(out.get("investimento_inicial") or 0)
        total = float(out.get("arrendamento_total") or 0)
        if total <= 0:
            av = float(out.get("arrendamento_valor") or 0)
            if av > 0:
                tipo = str(out.get("arrendamento_tipo") or "mensal").strip().lower()
                out["arrendamento_total"] = av if tipo == "anual" else av * 12.0
            else:
                fin = out.get("financeiro")
                if isinstance(fin, dict):
                    cf = fin.get("custos_fixos") or {}
                    alug = float(cf.get("aluguel") or 0) if isinstance(cf, dict) else 0.0
                    if alug > 0:
                        out["arrendamento_total"] = alug * 12.0
        if out.get("prazo_contrato_meses") is None:
            out["prazo_contrato_meses"] = 12
        return out


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


def get_backups_dir(id_projeto: str) -> Path:
    """Retorna o diretório de backups: data/projects/<id>/backups/."""
    return get_projeto_dir(id_projeto) / "backups"


def get_backup_audit_path(id_projeto: str) -> Path:
    """Retorna o path do log de auditoria de gravações: data/projects/<id>/backups/audit_market_curado.jsonl."""
    return get_backups_dir(id_projeto) / "audit_market_curado.jsonl"


def get_scraper_config_path(id_projeto: str) -> Path:
    """Retorna o path da config do scraper: data/projects/<id>/scraper_config.json."""
    return get_projeto_dir(id_projeto) / "scraper_config.json"


def get_simulacao_salva_path(id_projeto: str) -> Path:
    """[LEGADO] Retorna o path da simulação salva: data/projects/<id>/simulacao_salva.json."""
    return get_projeto_dir(id_projeto) / "simulacao_salva.json"


def get_simulacao_cenarios_path(id_projeto: str) -> Path:
    """[LEGADO] Retorna o path da lista de cenários salvos: data/projects/<id>/simulacao_cenarios.json."""
    return get_projeto_dir(id_projeto) / "simulacao_cenarios.json"


def get_cenarios_path(id_projeto: str) -> Path:
    """Retorna o path padrão dos cenários: data/projects/<id>/cenarios.json."""
    return get_projeto_dir(id_projeto) / "cenarios.json"


_ID_PROJETO_OPERACAO_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validar_id_projeto_para_escrita(id_projeto: str) -> str:
    """Normaliza e valida ID (slug) para operações de escrita/exclusão."""
    s = str(id_projeto or "").strip().lower()
    if not s or len(s) > 200 or not _ID_PROJETO_OPERACAO_RE.fullmatch(s):
        raise ValueError("ID de projeto inválido.")
    return s


def excluir_projeto_seguro(id_projeto: str) -> dict[str, Any]:
    """Remove o projeto apenas dentro de data/projects/ (pasta + artefatos legados na raiz).

    - Exige que o path resolvido da pasta seja filho direto de PROJECTS_DIR.
    - Nunca remove arquivos fora de data/projects/.
    """
    id_norm = validar_id_projeto_para_escrita(id_projeto)
    root = PROJECTS_DIR.resolve()
    dir_proj = get_projeto_dir(id_norm).resolve()
    if dir_proj.parent.resolve() != root or dir_proj.name != id_norm:
        raise ValueError("Caminho do projeto inválido.")

    removed: List[str] = []
    if dir_proj.exists() and dir_proj.is_dir():
        shutil.rmtree(dir_proj)
        removed.append(str(dir_proj))

    for suffix in (
        f"{id_norm}.json",
        f"market_bruto_{id_norm}.json",
        f"market_curado_{id_norm}.json",
        f"scraper_config_{id_norm}.json",
    ):
        p = (PROJECTS_DIR / suffix).resolve()
        if p.parent.resolve() != root:
            continue
        if p.exists() and p.is_file():
            p.unlink()
            removed.append(str(p))

    if not removed:
        raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_norm}' não encontrado para exclusão.")

    _log_system_event(
        "projeto_excluido_seguro",
        id_projeto=id_norm,
        paths_removidos=removed,
    )
    logger.info("Projeto excluído com segurança: {} ({} itens)", id_norm, len(removed))
    return {"id_projeto": id_norm, "paths_removidos": removed}


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
    data = projeto.model_dump(mode="json")
    fin = data.get("financeiro")
    if isinstance(fin, dict):
        cf = fin.get("custos_fixos")
        if isinstance(cf, dict):
            cf["aluguel"] = 0.0
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
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


def _log_system_event(evento: str, **kwargs: Any) -> None:
    """Registra evento em SYSTEM_EVENTS.jsonl."""
    from datetime import datetime

    ev_dir = Path(__file__).resolve().parent.parent / "scripts" / "evidence_stability"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_path = ev_dir / "SYSTEM_EVENTS.jsonl"
    try:
        with open(ev_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"timestamp": datetime.now().isoformat(), "evento": evento, **kwargs},
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError as e:
        logger.warning("Falha ao gravar SYSTEM_EVENTS: {}", e)


def read_project_json(id_projeto: str) -> dict | None:
    """Lê projeto.json bruto (dict), com fallback legado <id>.json."""
    path = get_projeto_json_path(id_projeto)
    if not path.exists() or not path.is_file():
        path_legado = PROJECTS_DIR / f"{id_projeto}.json"
        if path_legado.exists() and path_legado.is_file():
            path = path_legado
        else:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _backup_atomico_arquivo(id_projeto: str, origem: Path, action: str) -> Path:
    """Cria backup atômico de arquivo do projeto em backups/."""
    backups_dir = get_backups_dir(id_projeto)
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = backups_dir / f"{origem.stem}_before_{action}_{ts}{origem.suffix}"
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    shutil.copy2(origem, tmp)
    tmp.replace(destino)
    _log_system_event(
        "backup_atomico",
        action=action,
        id_projeto=id_projeto,
        arquivos=[str(origem), str(destino)],
        time=__import__("datetime").datetime.now().isoformat(),
        user="cursor-job",
    )
    return destino


def backup_scraper_config_before_action(id_projeto: str, action: str) -> Path | None:
    """Backup do scraper_config.json em backups/ com timestamp e .bak no projeto.
    Retorna Path do backup em backups/ ou None se arquivo não existir."""
    path = get_scraper_config_path(id_projeto)
    if not path.exists() or not path.is_file():
        return None
    destino = _backup_atomico_arquivo(id_projeto, path, action)
    bak_path = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, bak_path)
    except OSError:
        pass
    return destino


def write_project_json(id_projeto: str, payload: dict, action: str = "write_project_json") -> None:
    """Grava projeto.json com backup atômico prévio quando já existe."""
    path = get_projeto_json_path(id_projeto)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_file():
        _backup_atomico_arquivo(id_projeto, path, action=action)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    _log_system_event(
        "project_json_updated",
        action=action,
        id_projeto=id_projeto,
        arquivos=[str(path)],
        time=__import__("datetime").datetime.now().isoformat(),
        user="cursor-job",
    )


def read_curadoria_desconto(id_projeto: str) -> Optional[Decimal]:
    """Lê projeto.json.curadoria.desconto_padrao como Decimal (0..1), se existir."""
    data = read_project_json(id_projeto)
    if not isinstance(data, dict):
        return None
    curadoria = data.get("curadoria")
    if not isinstance(curadoria, dict):
        return None
    raw = curadoria.get("desconto_padrao")
    if raw is None:
        return None
    try:
        d = Decimal(str(raw).replace(",", "."))
    except Exception:
        return None
    if d > 1:
        d = d / Decimal("100")
    if d < 0:
        d = Decimal("0")
    if d >= 1:
        d = Decimal("0.99")
    return d


def write_curadoria_desconto(id_projeto: str, valor: Decimal) -> None:
    """Escreve projeto.json.curadoria.desconto_padrao com backup atômico."""
    data = read_project_json(id_projeto)
    if not isinstance(data, dict):
        raise ArquivoProjetoNaoEncontrado(f"Projeto '{id_projeto}' não encontrado para salvar desconto.")
    curadoria = data.get("curadoria")
    if not isinstance(curadoria, dict):
        curadoria = {}
    # Persistimos float para compatibilidade com JSON atual do projeto.
    curadoria["desconto_padrao"] = float(valor)
    data["curadoria"] = curadoria
    write_project_json(id_projeto, data, action="write_curadoria_desconto")


def create_project_scaffold(id_projeto: str, metadata: dict) -> dict:
    """Cria estrutura completa do projeto (pousada) se não existir.
    - Cria pasta data/projects/<id_projeto>/
    - Cria projeto.json com metadados básicos se não existir
    - Cria scraper_config.json via generate_scaffold_from_metadata se não existir
    - Cria market_bruto.json, market_curado.json, cenarios.json e pasta backups/ vazios se não existirem
    Nunca sobrescreve arquivos existentes.
    Retorna dict: { created: list[str], already_existed: list[str], missing: list[str], errors: list[str] }
    """
    from datetime import date

    created: List[str] = []
    already_existed: List[str] = []
    missing: List[str] = []
    errors: List[str] = []

    dir_projeto = get_projeto_dir(id_projeto)
    dir_projeto.mkdir(parents=True, exist_ok=True)

    # projeto.json
    path_projeto = get_projeto_json_path(id_projeto)
    if not path_projeto.exists():
        try:
            from core.financeiro.modelos import DadosFinanceiros

            ano = int(metadata.get("ano_referencia", date.today().year))
            ano = max(2000, min(2100, ano))
            financeiro = metadata.get("financeiro")
            if financeiro is not None and hasattr(financeiro, "model_dump"):
                financeiro = financeiro.model_dump(mode="json")
            elif not isinstance(financeiro, dict):
                financeiro = DadosFinanceiros().model_dump(mode="json")
            infr = metadata.get("infraestrutura")
            if isinstance(infr, dict):
                infr = Infraestrutura.model_validate(infr)
            projeto = Projeto(
                id=id_projeto,
                nome=str(metadata.get("nome", id_projeto)),
                url_booking=str(metadata.get("booking_url", metadata.get("url_booking", ""))),
                numero_quartos=max(1, int(metadata.get("numero_quartos", 1))),
                faturamento_anual=float(metadata.get("faturamento_anual", 0)),
                ano_referencia=ano,
                financeiro=DadosFinanceiros.model_validate(financeiro),
                infraestrutura=infr,
                dados_mercado=None,
            )
            salvar_projeto(projeto)
            created.append("projeto.json")
            _log_system_event("project_scaffold_created", id_projeto=id_projeto, item="projeto.json")
        except Exception as e:
            errors.append(f"projeto.json: {e}")
            missing.append("projeto.json")
    else:
        already_existed.append("projeto.json")

    # scraper_config.json
    path_scraper = get_scraper_config_path(id_projeto)
    if not path_scraper.exists():
        try:
            from core.config import generate_scaffold_from_metadata, salvar_config_scraper, _get_scraper_config_template

            cfg = generate_scaffold_from_metadata(metadata)
            pe_payload = metadata.get("periodos_especiais")
            if pe_payload is None or (isinstance(pe_payload, list) and len(pe_payload) == 0):
                template = _get_scraper_config_template()
                cfg["periodos_especiais"] = template.get("periodos_especiais", [])
            else:
                cfg["periodos_especiais"] = pe_payload
            salvar_config_scraper(id_projeto, cfg)
            created.append("scraper_config.json")
            _log_system_event("project_scaffold_created", id_projeto=id_projeto, item="scraper_config.json")
        except Exception as e:
            errors.append(f"scraper_config.json: {e}")
            missing.append("scraper_config.json")
    else:
        already_existed.append("scraper_config.json")

    # market_bruto.json
    path_bruto = get_market_bruto_path(id_projeto)
    if not path_bruto.exists():
        try:
            url = metadata.get("booking_url", metadata.get("url_booking", ""))
            bruto = {
                "id_projeto": id_projeto,
                "url": url,
                "ano": date.today().year,
                "registros": [],
            }
            with open(path_bruto, "w", encoding="utf-8") as f:
                json.dump(bruto, f, ensure_ascii=False, indent=2)
            created.append("market_bruto.json")
        except Exception as e:
            errors.append(f"market_bruto.json: {e}")
            missing.append("market_bruto.json")
    else:
        already_existed.append("market_bruto.json")

    # market_curado.json
    path_curado = get_market_curado_path(id_projeto)
    if not path_curado.exists():
        try:
            url = metadata.get("booking_url", metadata.get("url_booking", ""))
            curado = {
                "id_projeto": id_projeto,
                "url": url,
                "ano": date.today().year,
                "registros": [],
            }
            with open(path_curado, "w", encoding="utf-8") as f:
                json.dump(curado, f, ensure_ascii=False, indent=2)
            created.append("market_curado.json")
        except Exception as e:
            errors.append(f"market_curado.json: {e}")
            missing.append("market_curado.json")
    else:
        already_existed.append("market_curado.json")

    # cenarios.json
    path_cenarios = get_cenarios_path(id_projeto)
    if not path_cenarios.exists():
        try:
            with open(path_cenarios, "w", encoding="utf-8") as f:
                json.dump({"cenarios": []}, f, ensure_ascii=False, indent=2)
            created.append("cenarios.json")
        except Exception as e:
            errors.append(f"cenarios.json: {e}")
            missing.append("cenarios.json")
    else:
        already_existed.append("cenarios.json")

    # backups/
    dir_backups = get_backups_dir(id_projeto)
    if not dir_backups.exists():
        try:
            dir_backups.mkdir(parents=True, exist_ok=True)
            created.append("backups/")
        except Exception as e:
            errors.append(f"backups/: {e}")
            missing.append("backups/")
    else:
        already_existed.append("backups/")

    # README_ONBOARDING.md
    path_readme = dir_projeto / "README_ONBOARDING.md"
    if not path_readme.exists():
        try:
            nome = metadata.get("nome", id_projeto)
            readme_content = f"""# Onboarding — {nome}

## Passos iniciais

1. **Executar Scraper**: Rode a coleta de dados do Booking para popular `market_bruto.json`:
   ```
   python -m core.scraper.cli --url "<booking_url>" --id "{id_projeto}" --ano <ano>
   ```

2. **Curadoria**: Acesse a Curadoria na interface para revisar e ajustar preços manualmente.

3. **Backups**: Os ajustes salvos geram backups automáticos em `backups/`.

4. **Logs**: Traces do scraper em `scripts/evidence_stability/SCRAPER_CONFIG_TRACE.jsonl` e `LOG_AFTER.jsonl`.

5. **Documentação**: Veja `docs/GUIA_ONBOARDING_POUSADA.md` para o guia completo.
"""
            path_readme.write_text(readme_content, encoding="utf-8")
            created.append("README_ONBOARDING.md")
        except Exception as e:
            errors.append(f"README_ONBOARDING.md: {e}")
    else:
        already_existed.append("README_ONBOARDING.md")

    return {
        "created": created,
        "already_existed": already_existed,
        "missing": missing,
        "errors": errors,
    }


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
