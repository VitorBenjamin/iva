"""
backup - Backup e versionamento de market_curado.json.
Responsabilidade: gravação atômica, versionamento automático e log de auditoria JSONL.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

from core.projetos import (
    get_backup_audit_path,
    get_backups_dir,
    get_market_curado_path,
)


def _escrever_linha_jsonl(path: Path, obj: dict) -> None:
    """Append de uma linha JSON ao arquivo JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def salvar_market_curado_com_backup(
    id_projeto: str,
    dados: dict,
) -> None:
    """Salva market_curado.json com backup versionado e gravação atômica.
    - Copia o arquivo atual para backups/market_curado_YYYYMMDD_HHMMSS.json (se existir)
    - Grava atomicamente via arquivo .tmp + rename
    - Registra cada gravação em backups/audit_market_curado.jsonl
    """
    path_curado = get_market_curado_path(id_projeto)
    dir_backups = get_backups_dir(id_projeto)
    path_audit = get_backup_audit_path(id_projeto)

    dir_backups.mkdir(parents=True, exist_ok=True)
    path_curado.parent.mkdir(parents=True, exist_ok=True)

    # Backup do arquivo atual (se existir e não estiver vazio)
    if path_curado.exists() and path_curado.is_file() and path_curado.stat().st_size > 0:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path_backup = dir_backups / f"market_curado_{timestamp}.json"
        try:
            shutil.copy2(path_curado, path_backup)
            logger.info("Backup criado: {} -> {}", path_curado, path_backup)
        except OSError as e:
            logger.warning("Falha ao criar backup {}: {}", path_backup, e)
            _escrever_linha_jsonl(
                path_audit,
                {
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "id_projeto": id_projeto,
                    "evento": "backup_falha",
                    "path_backup": str(path_backup),
                    "erro": str(e),
                },
            )

    # Gravação atômica: escreve em .tmp e depois renomeia
    path_tmp = path_curado.with_suffix(".json.tmp")
    try:
        with open(path_tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        path_tmp.replace(path_curado)
    except OSError as e:
        if path_tmp.exists():
            try:
                path_tmp.unlink()
            except OSError:
                pass
        logger.error("Falha ao gravar market_curado {}: {}", id_projeto, e)
        _escrever_linha_jsonl(
            path_audit,
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "id_projeto": id_projeto,
                "evento": "gravacao_falha",
                "path_curado": str(path_curado),
                "erro": str(e),
            },
        )
        raise

    # Log de auditoria
    _escrever_linha_jsonl(
        path_audit,
        {
            "ts": datetime.utcnow().isoformat() + "Z",
            "id_projeto": id_projeto,
            "evento": "gravacao_ok",
            "path_curado": str(path_curado),
            "registros": len(dados.get("registros", [])),
        },
    )
