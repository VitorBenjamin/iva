#!/usr/bin/env python3
"""Remove a chave legada `resultado` de todos os cenários em cenarios.json (e simulacao_cenarios.json).

Uso (na raiz do repo):
  python scripts/migrate_strip_resultado_cenarios.py

Idempotente: arquivos sem `resultado` não são alterados.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.projetos import PROJECTS_DIR  # noqa: E402


def _strip_cenarios_in_data(data: dict) -> bool:
    cenarios = data.get("cenarios")
    if not isinstance(cenarios, list):
        return False
    changed = False
    for c in cenarios:
        if isinstance(c, dict) and "resultado" in c:
            c.pop("resultado", None)
            changed = True
    return changed


def _migrate_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"SKIP (leitura/JSON): {path} — {e}")
        return False
    if not isinstance(data, dict):
        return False
    if not _strip_cenarios_in_data(data):
        return False
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        print(f"ERRO ao gravar: {path} — {e}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False
    print(f"OK: {path}")
    return True


def main() -> int:
    if not PROJECTS_DIR.is_dir():
        print(f"Pasta de projetos inexistente: {PROJECTS_DIR}")
        return 1
    n_ok = 0
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        for name in ("cenarios.json", "simulacao_cenarios.json"):
            if _migrate_file(d / name):
                n_ok += 1
    print(f"Total de arquivos alterados: {n_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
