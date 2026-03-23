#!/usr/bin/env python3
"""
Gera ou regenera o README_ONBOARDING.md de um projeto.

Uso:
  python scripts/generate_project_readme.py <id_projeto>
  python scripts/generate_project_readme.py --list

Exemplo:
  python scripts/generate_project_readme.py pousada-nova
"""
import argparse
import sys
from pathlib import Path

# Adicionar raiz do projeto ao path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.projetos import (
    get_projeto_dir,
    get_projeto_json_path,
    carregar_projeto,
)


def gerar_conteudo_readme(id_projeto: str, nome: str, booking_url: str) -> str:
    """Gera o conteúdo do README_ONBOARDING.md."""
    ano = __import__("datetime").date.today().year
    return f"""# Onboarding — {nome}

## Passos iniciais

1. **Executar Scraper**: Rode a coleta de dados do Booking para popular `market_bruto.json`:
   ```
   python -m core.scraper.cli --url "{booking_url or "<booking_url>"}" --id "{id_projeto}" --ano {ano}
   ```

2. **Curadoria**: Acesse a Curadoria na interface para revisar e ajustar preços manualmente.

3. **Backups**: Os ajustes salvos geram backups automáticos em `backups/`.

4. **Logs**: Traces do scraper em `scripts/evidence_stability/SCRAPER_CONFIG_TRACE.jsonl` e `LOG_AFTER.jsonl`.

5. **Documentação**: Veja `docs/GUIA_ONBOARDING_POUSADA.md` para o guia completo.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera README_ONBOARDING.md para um projeto")
    parser.add_argument("id_projeto", nargs="?", help="ID do projeto (slug)")
    parser.add_argument("--list", "-l", action="store_true", help="Lista projetos existentes")
    parser.add_argument("--force", "-f", action="store_true", help="Sobrescrever se já existir")
    args = parser.parse_args()

    projects_dir = ROOT / "data" / "projects"
    if not projects_dir.exists():
        print("Pasta data/projects não encontrada.", file=sys.stderr)
        return 1

    if args.list:
        dirs = [d for d in projects_dir.iterdir() if d.is_dir()]
        if not dirs:
            print("Nenhum projeto encontrado.")
            return 0
        print("Projetos disponíveis:")
        for d in sorted(dirs):
            pj = get_projeto_json_path(d.name)
            nome = d.name
            if pj.exists():
                try:
                    proj = carregar_projeto(d.name)
                    nome = proj.nome
                except Exception:
                    pass
            print(f"  {d.name}: {nome}")
        return 0

    if not args.id_projeto:
        parser.print_help()
        return 1

    id_projeto = args.id_projeto.strip()
    dir_projeto = get_projeto_dir(id_projeto)
    path_readme = dir_projeto / "README_ONBOARDING.md"

    if not dir_projeto.exists():
        print(f"Projeto '{id_projeto}' não encontrado em data/projects/", file=sys.stderr)
        return 1

    nome = id_projeto
    booking_url = ""
    pj_path = get_projeto_json_path(id_projeto)
    if pj_path.exists():
        try:
            proj = carregar_projeto(id_projeto)
            nome = proj.nome
            booking_url = proj.url_booking or ""
        except Exception as e:
            print(f"Aviso: não foi possível carregar projeto.json: {e}", file=sys.stderr)

    if path_readme.exists() and not args.force:
        print("README_ONBOARDING.md já existe. Use --force para sobrescrever.")
        return 0

    conteudo = gerar_conteudo_readme(id_projeto, nome, booking_url)
    path_readme.write_text(conteudo, encoding="utf-8")
    print(f"README_ONBOARDING.md gerado em {path_readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
