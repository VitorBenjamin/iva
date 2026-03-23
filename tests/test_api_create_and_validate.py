"""Testes dos endpoints POST /api/pousada e GET /api/pousada/<id>/validate."""
import json
import shutil
import unittest
import uuid
from pathlib import Path

from app import app


class TestApiCreateAndValidate(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.id_teste = f"test-api-{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        base = Path(__file__).resolve().parent.parent / "data" / "projects" / self.id_teste
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)

    def test_post_pousada_url_vazia_rejeitada(self):
        """URL vazia retorna 400."""
        resp = self.client.post(
            "/api/pousada",
            json={"nome": "Teste", "booking_url": ""},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))

    def test_post_pousada_url_invalida_rejeitada(self):
        """URL inválida (ftp) retorna 400."""
        resp = self.client.post(
            "/api/pousada",
            json={"nome": "Teste", "booking_url": "ftp://evil.com"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_pousada_url_valida_cria_projeto(self):
        """URL válida cria projeto e retorna 201 com checklist."""
        resp = self.client.post(
            "/api/pousada",
            json={
                "nome": "Pousada API Test",
                "booking_url": "https://www.booking.com/hotel/br/exemplo",
                "id": self.id_teste,
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("data", {}).get("id"), self.id_teste)
        checklist = data.get("data", {}).get("checklist", {})
        self.assertIsInstance(checklist, dict)
        self.assertIn("scraper_config_exists", checklist)
        self.assertIn("booking_url_valid", checklist)
        self.assertTrue(checklist.get("booking_url_valid"))

    def test_get_validate_projeto_existente(self):
        """GET validate para projeto existente retorna checklist."""
        resp_create = self.client.post(
            "/api/pousada",
            json={
                "nome": "Pousada Validate",
                "booking_url": "https://www.booking.com/hotel/br/validate",
                "id": self.id_teste,
            },
            content_type="application/json",
        )
        self.assertEqual(resp_create.status_code, 201)

        resp = self.client.get(f"/api/pousada/{self.id_teste}/validate")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        checklist = data.get("data", {}).get("checklist", {})
        self.assertTrue(checklist.get("scraper_config_exists"))
        self.assertTrue(checklist.get("booking_url_valid"))

    def test_get_validate_projeto_inexistente_404(self):
        """GET validate para projeto inexistente retorna 404."""
        resp = self.client.get("/api/pousada/projeto-inexistente-xyz123/validate")
        self.assertEqual(resp.status_code, 404)

    def test_post_projeto_alias_compatibilidade(self):
        """POST /api/projeto com url_booking funciona como alias."""
        resp = self.client.post(
            "/api/projeto",
            json={
                "nome": "Pousada Alias",
                "url_booking": "https://www.booking.com/hotel/br/alias",
                "id": self.id_teste,
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("data", {}).get("id"), self.id_teste)


if __name__ == "__main__":
    unittest.main()
