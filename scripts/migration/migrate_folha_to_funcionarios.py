import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.projetos import PROJECTS_DIR, get_projeto_json_path, read_project_json, write_project_json


LOG_PATH = Path(__file__).resolve().parents[1] / "evidence_stability" / "MIGRATION_FOLHA_TO_FUNCIONARIOS.jsonl"


def _log(event: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _project_ids() -> list[str]:
    ids = []
    if not PROJECTS_DIR.exists():
        return ids
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir() and get_projeto_json_path(p.name).exists():
            ids.append(p.name)
    return sorted(ids)


def _needs_migration(data: dict) -> bool:
    fin = (data or {}).get("financeiro") or {}
    funcs = fin.get("funcionarios")
    folha = float(fin.get("folha_pagamento_mensal") or 0)
    return (not isinstance(funcs, list) or len(funcs) == 0) and folha > 0


def _apply_mapping(data: dict) -> dict:
    out = dict(data or {})
    fin = dict(out.get("financeiro") or {})
    folha = round(float(fin.get("folha_pagamento_mensal") or 0), 2)
    fin["funcionarios"] = [{
        "cargo": "Equipe (legacy)",
        "quantidade": 1,
        "salario_base": folha,
        "encargos_pct": 0.0,
        "beneficios": 0.0,
    }]
    out["financeiro"] = fin
    return out


def run(dry_run: bool) -> int:
    migraveis = 0
    for pid in _project_ids():
        original = read_project_json(pid)
        if not isinstance(original, dict):
            continue
        if not _needs_migration(original):
            continue
        migraveis += 1
        mapped = _apply_mapping(original)
        event = {
            "timestamp": datetime.now().isoformat(),
            "project_id": pid,
            "dry_run": dry_run,
            "before": {
                "folha_pagamento_mensal": ((original.get("financeiro") or {}).get("folha_pagamento_mensal")),
                "funcionarios_len": len(((original.get("financeiro") or {}).get("funcionarios") or [])),
            },
            "after": {
                "funcionarios_len": len(((mapped.get("financeiro") or {}).get("funcionarios") or [])),
                "funcionario_sample": ((mapped.get("financeiro") or {}).get("funcionarios") or [None])[0],
            },
        }
        _log(event)
        if not dry_run:
            write_project_json(pid, mapped, action="migrate_folha_to_funcionarios")
        print(f"{'DRY-RUN' if dry_run else 'APPLY'}: {pid}")
    print(f"Projetos migráveis: {migraveis}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra folha_pagamento_mensal para funcionarios (lazy/backfill).")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista projetos e mappings.")
    parser.add_argument("--apply", action="store_true", help="Aplica escrita com backup atômico.")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        print("Use apenas um modo por execução: --dry-run ou --apply")
        return 2
    return run(dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
