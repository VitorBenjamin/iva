"""Testes do endpoint POST /api/projeto/<id>/scraper/importar_template."""
import json
import shutil
import unittest
import uuid
from pathlib import Path

from app import app
from core.projetos import (
    PROJECTS_DIR,
    create_project_scaffold,
    get_scraper_config_path,
)


class TestApiImportarTemplate(unittest.TestCase):
    """Testes do endpoint de importação de template de datas."""

    def setUp(self):
        self.client = app.test_client()
        self.id_teste = f"test-import-{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        base = PROJECTS_DIR / self.id_teste
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)

    def test_importar_template_projeto_inexistente_404(self):
        """Projeto inexistente retorna 404."""
        resp = self.client.post(
            f"/api/projeto/{self.id_teste}/scraper/importar_template",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))

    def test_importar_template_adiciona_periodos_em_config_vazio(self):
        """Importar em config com periodos vazios adiciona todos do template."""
        create_project_scaffold(
            self.id_teste,
            {
                "nome": "Test Import",
                "booking_url": "https://www.booking.com/hotel/br/test",
                "periodos_especiais": [],
            },
        )
        path_cfg = get_scraper_config_path(self.id_teste)
        with open(path_cfg) as f:
            cfg = json.load(f)
        cfg["periodos_especiais"] = []
        with open(path_cfg, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        resp = self.client.post(
            f"/api/projeto/{self.id_teste}/scraper/importar_template",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreater(data.get("periodos_adicionados", 0), 0)
        self.assertGreater(data.get("periodos_total", 0), 0)

        with open(path_cfg) as f:
            cfg = json.load(f)
        self.assertGreater(len(cfg["periodos_especiais"]), 0)

    def test_importar_template_nao_duplica_por_nome_case_insensitive(self):
        """Merge por nome case-insensitive: Carnaval e carnaval não duplicam."""
        create_project_scaffold(
            self.id_teste,
            {
                "nome": "Test Merge",
                "booking_url": "https://www.booking.com/hotel/br/test",
                "periodos_especiais": [
                    {"inicio": "15/02/2026", "fim": "19/02/2026", "nome": "Carnaval"},
                ],
            },
        )
        path_cfg = get_scraper_config_path(self.id_teste)
        with open(path_cfg) as f:
            cfg = json.load(f)
        n_antes = len(cfg["periodos_especiais"])

        resp = self.client.post(
            f"/api/projeto/{self.id_teste}/scraper/importar_template",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        # Carnaval já existe; não deve duplicar
        self.assertLess(data.get("periodos_adicionados", 0), 10)

        with open(path_cfg) as f:
            cfg = json.load(f)
        carnavais = [p for p in cfg["periodos_especiais"] if (p.get("nome") or "").lower().strip() == "carnaval"]
        self.assertEqual(len(carnavais), 1)


if __name__ == "__main__":
    unittest.main()
