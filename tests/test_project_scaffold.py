"""Testes do scaffold de projeto (create_project_scaffold)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projetos import (
    PROJECTS_DIR,
    create_project_scaffold,
    get_backups_dir,
    get_cenarios_path,
    get_market_bruto_path,
    get_market_curado_path,
    get_projeto_dir,
    get_projeto_json_path,
    get_scraper_config_path,
)


class TestProjectScaffold(unittest.TestCase):
    """Testa create_project_scaffold em diretório temporário."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_scaffold_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scaffold_cria_estrutura_completa(self):
        """Scaffold cria pasta, projeto.json, scraper_config, market_bruto, market_curado, cenarios, backups."""
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            result = create_project_scaffold(
                "pousada-teste",
                {
                    "nome": "Pousada Teste",
                    "booking_url": "https://www.booking.com/hotel/br/teste",
                },
            )
        self.assertIn("projeto.json", result["created"])
        self.assertIn("scraper_config.json", result["created"])
        self.assertIn("market_bruto.json", result["created"])
        self.assertIn("market_curado.json", result["created"])
        self.assertIn("cenarios.json", result["created"])
        self.assertIn("backups/", result["created"])
        self.assertIn("README_ONBOARDING.md", result["created"])

        base = Path(self.tmpdir) / "pousada-teste"
        self.assertTrue((base / "projeto.json").exists())
        self.assertTrue((base / "scraper_config.json").exists())
        self.assertTrue((base / "market_bruto.json").exists())
        self.assertTrue((base / "market_curado.json").exists())
        self.assertTrue((base / "cenarios.json").exists())
        self.assertTrue((base / "backups").is_dir())
        self.assertTrue((base / "README_ONBOARDING.md").exists())

        with open(base / "scraper_config.json") as f:
            cfg = json.load(f)
        self.assertIn("periodos_especiais", cfg)
        # Projetos novos recebem template padrão (feriados BR); não nascem vazios
        self.assertGreater(len(cfg["periodos_especiais"]), 0)
        self.assertIn("nome", cfg["periodos_especiais"][0])

    def test_scaffold_nao_sobrescreve_existente(self):
        """Não sobrescreve arquivos que já existem."""
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            create_project_scaffold(
                "pousada-existente",
                {"nome": "Original", "booking_url": "https://www.booking.com/hotel/br/x"},
            )
            # Cria config com conteúdo marcado
            path_cfg = Path(self.tmpdir) / "pousada-existente" / "scraper_config.json"
            with open(path_cfg) as f:
                original = json.load(f)
            original["_marcador_teste"] = "nao_sobrescrever"
            with open(path_cfg, "w") as f:
                json.dump(original, f, indent=2)

            result = create_project_scaffold(
                "pousada-existente",
                {"nome": "Novo", "booking_url": "https://www.booking.com/hotel/br/y"},
            )

        self.assertIn("scraper_config.json", result["already_existed"])
        with open(path_cfg) as f:
            cfg = json.load(f)
        self.assertEqual(cfg.get("_marcador_teste"), "nao_sobrescrever")

    def test_scaffold_respeita_periodos_do_payload(self):
        """Se metadata traz periodos_especiais, não usa template."""
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            create_project_scaffold(
                "pousada-custom",
                {
                    "nome": "Custom",
                    "booking_url": "https://www.booking.com/hotel/br/custom",
                    "periodos_especiais": [
                        {"inicio": "01/01/2027", "fim": "01/01/2027", "nome": "Ano Novo"},
                    ],
                },
            )
        path_cfg = Path(self.tmpdir) / "pousada-custom" / "scraper_config.json"
        with open(path_cfg) as f:
            cfg = json.load(f)
        self.assertEqual(len(cfg["periodos_especiais"]), 1)
        self.assertEqual(cfg["periodos_especiais"][0]["nome"], "Ano Novo")


if __name__ == "__main__":
    unittest.main()
