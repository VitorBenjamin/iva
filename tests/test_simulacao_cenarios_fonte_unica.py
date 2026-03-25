"""Persistência de cenários de simulação: não persiste `resultado` (fonte única = POST calcular)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from core.projetos import create_project_scaffold, get_cenarios_path


class TestSimulacaoCenariosFonteUnica(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_fonte_unica_")
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_post_com_resultado_no_body_nao_grava_resultado_no_disk(self):
        pid = "teste-fonte-unica"
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            create_project_scaffold(
                pid,
                {
                    "nome": "Teste Fonte Única",
                    "booking_url": "https://www.booking.com/hotel/br/teste",
                },
            )
            path = get_cenarios_path(pid)
            self.assertTrue(path.exists())

        body = {
            "nome": "Cenário X",
            "metas_mensais": {"2026-01": {"ocupacao": 0.5, "adr": 100}},
            "investimento_reforma": 0,
            "arrendamento_total": 0,
            "prazo_contrato_meses": 12,
            "resultado": {
                "meses": [],
                "resumo": {"lucro_anual": 999999.0, "lucro_operacional_anual": 999999.0},
            },
        }
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            resp = self.client.post(
                f"/api/projeto/{pid}/simulacao/cenarios",
                json=body,
            )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("success"))

        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            path = get_cenarios_path(pid)
            data = json.loads(path.read_text(encoding="utf-8"))
        cenarios = data.get("cenarios") or []
        self.assertEqual(len(cenarios), 1)
        c0 = cenarios[0]
        self.assertNotIn("resultado", c0)
        self.assertEqual(c0.get("nome"), "Cenário X")

    def test_put_atualiza_remove_resultado_legado_no_arquivo(self):
        pid = "teste-fonte-unica-b"
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            create_project_scaffold(
                pid,
                {
                    "nome": "Teste B",
                    "booking_url": "https://www.booking.com/hotel/br/teste",
                },
            )
            path = get_cenarios_path(pid)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["cenarios"] = [
                {
                    "id": "abc12345",
                    "nome": "Legado",
                    "criado_em": "2020-01-01T00:00:00Z",
                    "metas_mensais": {},
                    "investimento_reforma": 0,
                    "arrendamento_total": 0,
                    "prazo_contrato_meses": 12,
                    "investimento_inicial": 0,
                    "resultado": {"resumo": {"lucro_anual": 12345}},
                }
            ]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        body = {
            "id": "abc12345",
            "nome": "Atualizado",
            "metas_mensais": {"2026-02": {"ocupacao": 0.6, "adr": 200}},
            "investimento_reforma": 0,
            "arrendamento_total": 0,
            "prazo_contrato_meses": 12,
            "resultado": {"resumo": {"lucro_anual": 888888}},
        }
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            resp = self.client.post(
                f"/api/projeto/{pid}/simulacao/cenarios",
                json=body,
            )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("success"))

        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            path = get_cenarios_path(pid)
            data = json.loads(path.read_text(encoding="utf-8"))
        c0 = (data.get("cenarios") or [])[0]
        self.assertNotIn("resultado", c0)
        self.assertEqual(c0.get("nome"), "Atualizado")


if __name__ == "__main__":
    unittest.main()
