import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app


class TestCuradoriaSaveValidation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_curadoria_save_")
        self.client = app.test_client()
        self.id = "curadoria-save-pousada"
        self.base = Path(self.tmpdir) / self.id
        self.base.mkdir(parents=True, exist_ok=True)
        self._write_fixture()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_fixture(self):
        projeto = {
            "id": self.id,
            "nome": "Pousada Save",
            "url_booking": "https://www.booking.com/hotel/br/save",
            "numero_quartos": 8,
            "faturamento_anual": 10000,
            "ano_referencia": 2026,
            "financeiro": {},
            "curadoria": {"desconto_padrao": 0.15},
        }
        bruto = {
            "id_projeto": self.id,
            "url": "https://www.booking.com/hotel/br/save",
            "ano": 2026,
            "registros": [
                {
                    "checkin": "2026-01-10",
                    "checkout": "2026-01-12",
                    "mes_ano": "2026-01",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 1000.0,
                    "preco_direto": 800.0,
                    "nome_quarto": "Q1",
                    "tipo_tarifa": "Padrao",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "normal",
                }
            ],
        }
        cfg = {"descontos": {"global": 0.2, "por_mes": {}}}
        (self.base / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "scraper_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _post_curadoria(self, payload, env=None):
        env = env or {}
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, env, clear=False):
            return self.client.post(
                f"/api/projeto/{self.id}/curadoria",
                json=payload,
            )

    def test_corrige_preco_sugerido_quando_unificado_ativo(self):
        resp = self._post_curadoria(
            {
                "registros": [
                    {
                        "checkin": "2026-01-10",
                        "preco_curado_sugerido": 700.0,  # backend deve corrigir para 850.00 (15%)
                        "desconto_pct_sugerido": 15,
                        "preco_booking_base": 1000.0,
                    }
                ]
            },
            env={"BACKEND_DESCONTO_UNIFICADO": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["registros_salvos"], 1)
        self.assertEqual(len(data["data"]["itens_corrigidos"]), 1)
        self.assertEqual(data["data"]["itens_corrigidos"][0]["checkin"], "2026-01-10")
        self.assertEqual(data["data"]["itens_corrigidos"][0]["preco_backend"], 850.0)

        path_curado = self.base / "market_curado.json"
        saved = json.loads(path_curado.read_text(encoding="utf-8"))
        self.assertIn("meta", saved)
        self.assertTrue(saved["meta"]["backend_desconto_unificado"])
        self.assertEqual(saved["registros"][0]["preco_curado"], 850.0)
        self.assertEqual(saved["meta"]["audit"][0]["source"], "curadoria_ui")
        self.assertEqual(saved["meta"]["audit"][0]["version"], "ato3.3")

    def test_modo_legado_nao_corrige(self):
        resp = self._post_curadoria(
            {"registros": [{"checkin": "2026-01-10", "preco_curado": 700.0}]},
            env={"BACKEND_DESCONTO_UNIFICADO": "false"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["registros_salvos"], 1)
        self.assertEqual(len(data["data"]["itens_corrigidos"]), 0)
        saved = json.loads((self.base / "market_curado.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["meta"]["backend_desconto_unificado"])
        self.assertEqual(saved["registros"][0]["preco_curado"], 700.0)

    def test_preco_curado_manual_precede_sugerido(self):
        """Ordem de leitura: preco_curado antes de preco_curado_sugerido."""
        resp = self._post_curadoria(
            {
                "registros": [
                    {
                        "checkin": "2026-01-10",
                        "preco_curado": 400.0,
                        "preco_curado_sugerido": 700.0,
                    }
                ]
            },
            env={"BACKEND_DESCONTO_UNIFICADO": "false"},
        )
        self.assertEqual(resp.status_code, 200)
        saved = json.loads((self.base / "market_curado.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["registros"][0]["preco_curado"], 400.0)

    def test_rejeita_payload_invalido(self):
        resp = self._post_curadoria({"registros": [{"checkin": "2026-01-10", "preco_curado_sugerido": "abc"}]})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Nenhum registro válido", data["message"])
        self.assertGreaterEqual(len(data["data"]["itens_invalidos"]), 1)


if __name__ == "__main__":
    unittest.main()
