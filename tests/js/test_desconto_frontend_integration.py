import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app


class TestDescontoFrontendIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_front_integration_")
        self.client = app.test_client()
        self.id = "front-back-integration-pousada"
        self.base = Path(self.tmpdir) / self.id
        self.base.mkdir(parents=True, exist_ok=True)
        self._write_fixture()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_fixture(self):
        checkin_d = date.today() + timedelta(days=3)
        checkout_d = checkin_d + timedelta(days=2)
        self.fixture_checkin = checkin_d.isoformat()
        projeto = {
            "id": self.id,
            "nome": "Pousada Integracao",
            "url_booking": "https://www.booking.com/hotel/br/integration",
            "numero_quartos": 10,
            "faturamento_anual": 250000,
            "ano_referencia": 2026,
            "financeiro": {},
            "curadoria": {
                "desconto_padrao": 0.15,
                "frontend_desconto_unificado": True,
            },
        }
        bruto = {
            "id_projeto": self.id,
            "url": projeto["url_booking"],
            "ano": 2026,
            "registros": [
                {
                    "checkin": self.fixture_checkin,
                    "checkout": checkout_d.isoformat(),
                    "mes_ano": f"{checkin_d.year}-{checkin_d.month:02d}",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 1000.0,
                    "preco_direto": 800.0,
                    "nome_quarto": "Q1",
                    "tipo_tarifa": "Padrao",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                }
            ],
        }
        cfg = {"descontos": {"global": 0.2, "por_mes": {}}}
        (self.base / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "scraper_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_fluxo_preview_e_save_sem_correcao(self):
        # 1) carrega página da curadoria e valida sinais de frontend unificado.
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)):
            resp_page = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp_page.status_code, 200)
        html = resp_page.data.decode("utf-8")
        self.assertIn("window.FRONTEND_DESCONTO_UNIFICADO = true", html)
        self.assertIn('data-preco-booking="', html)

        # 2) simula resultado do preview frontend (15% sobre 1000 => 850).
        payload = {
            "registros": [
                {
                    "checkin": self.fixture_checkin,
                    "preco_booking_base": 1000.0,
                    "preco_curado_sugerido": 850.0,
                    "desconto_pct_sugerido": 15,
                }
            ]
        }
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(
            os.environ, {"BACKEND_DESCONTO_UNIFICADO": "true"}, clear=False
        ):
            resp_save = self.client.post(f"/api/projeto/{self.id}/curadoria", json=payload)

        self.assertEqual(resp_save.status_code, 200)
        data = resp_save.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["registros_salvos"], 1)
        self.assertEqual(data["data"]["itens_corrigidos"], [])
        # A UI pode exibir toast de sucesso e manter valor salvo canônico.
        self.assertIn("validados", data["message"])

    def test_fluxo_save_com_correcao_backend(self):
        payload = {
            "registros": [
                {
                    "checkin": self.fixture_checkin,
                    "preco_booking_base": 1000.0,
                    "preco_curado_sugerido": 700.0,
                    "desconto_pct_sugerido": 15,
                }
            ]
        }
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(
            os.environ, {"BACKEND_DESCONTO_UNIFICADO": "true"}, clear=False
        ):
            resp_save = self.client.post(f"/api/projeto/{self.id}/curadoria", json=payload)
        self.assertEqual(resp_save.status_code, 200)
        data = resp_save.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["data"]["itens_corrigidos"]), 1)
        self.assertEqual(data["data"]["itens_corrigidos"][0]["preco_backend"], 850.0)

        saved = json.loads((self.base / "market_curado.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["registros"][0]["preco_curado"], 850.0)
        self.assertEqual(saved["meta"]["audit"][0]["preco_curado_salvo"], 850.0)


if __name__ == "__main__":
    unittest.main()
