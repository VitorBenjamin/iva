#!/usr/bin/env python3
"""
Marca periodo_id em market_bruto.json com base no scraper_config da pousada.

Uso:
  python scripts/migrations/mark_periodo_ids.py --id <id_projeto> --dry-run
  python scripts/migrations/mark_periodo_ids.py --id <id_projeto> --apply --force
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import resolve_periodo_por_checkin
from core.projetos import get_backups_dir, get_market_bruto_path


def _log_system_event(action: str, id_projeto: str, arquivos: list[str], extra: dict | None = None) -> None:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "id_projeto": id_projeto,
        "arquivos": arquivos,
        "time": datetime.now().isoformat(),
        "user": "cursor-job",
    }
    if extra:
        payload.update(extra)
    path = ROOT / "scripts" / "evidence_stability" / "SYSTEM_EVENTS.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _backup_atomico(id_projeto: str, origem: Path) -> Path:
    backups = get_backups_dir(id_projeto)
    backups.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = backups / f"{origem.stem}_before_mark_periodo_ids_{ts}{origem.suffix}"
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    shutil.copy2(origem, tmp)
    tmp.replace(destino)
    _log_system_event(
        action="backup_market_bruto_before_migration",
        id_projeto=id_projeto,
        arquivos=[str(origem), str(destino)],
    )
    return destino


def _carregar_market(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_market_atomico(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def marcar_periodo_ids(id_projeto: str, apply: bool) -> dict:
    path = get_market_bruto_path(id_projeto)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"market_bruto não encontrado: {path}")

    market = _carregar_market(path)
    registros = market.get("registros") if isinstance(market, dict) else None
    if not isinstance(registros, list):
        raise ValueError("Formato inválido de market_bruto.json: campo 'registros' ausente")

    total = len(registros)
    atualizados = 0
    sem_match = 0
    ja_marcados = 0
    amostras_sem_match: list[str] = []

    for r in registros:
        if not isinstance(r, dict):
            continue
        checkin = r.get("checkin")
        categoria = r.get("categoria_dia") or "normal"
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        if meta.get("periodo_id"):
            ja_marcados += 1
            continue
        match = resolve_periodo_por_checkin(id_projeto, checkin)
        if match:
            meta["periodo_id"] = match.get("periodo_id")
            meta["periodo_nome"] = match.get("nome")
            meta["periodo_source"] = "config"
            r["meta"] = meta
            atualizados += 1
        else:
            if categoria == "especial":
                meta["periodo_id"] = None
                meta["periodo_nome"] = meta.get("periodo_nome")
                meta["periodo_source"] = "fallback"
                r["meta"] = meta
                sem_match += 1
                if len(amostras_sem_match) < 20 and isinstance(checkin, str):
                    amostras_sem_match.append(checkin)

    backup_path = None
    if apply and atualizados > 0:
        backup_path = _backup_atomico(id_projeto, path)
        _salvar_market_atomico(path, market)
        _log_system_event(
            action="migration_mark_periodo_ids_apply",
            id_projeto=id_projeto,
            arquivos=[str(path)],
            extra={"atualizados": atualizados, "sem_match": sem_match},
        )
    else:
        _log_system_event(
            action="migration_mark_periodo_ids_dry_run",
            id_projeto=id_projeto,
            arquivos=[str(path)],
            extra={"atualizados": atualizados, "sem_match": sem_match, "ja_marcados": ja_marcados},
        )

    return {
        "id_projeto": id_projeto,
        "path": str(path),
        "total_registros": total,
        "atualizados": atualizados,
        "ja_marcados": ja_marcados,
        "sem_match": sem_match,
        "amostras_sem_match": amostras_sem_match,
        "modo": "apply" if apply else "dry-run",
        "backup": str(backup_path) if backup_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Marcar periodo_id em market_bruto")
    parser.add_argument("--id", required=True, help="ID da pousada/projeto")
    parser.add_argument("--dry-run", action="store_true", help="Executa sem alterar arquivos (padrão)")
    parser.add_argument("--apply", action="store_true", help="Aplica alteração no arquivo")
    parser.add_argument("--force", action="store_true", help="Confirma execução em modo apply")
    args = parser.parse_args()

    apply = bool(args.apply and not args.dry_run)
    if apply and not args.force:
        print("Uso de --apply exige --force para confirmação explícita.", file=sys.stderr)
        return 2

    report = marcar_periodo_ids(args.id, apply=apply)
    audits_dir = ROOT / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    report_path = audits_dir / "mark_periodo_ids_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Relatório salvo em: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
