import json
import shutil
import unittest
import uuid

from app import app
from core.projetos import get_projeto_json_path


class TestDecimalRoundtrip(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.nome = f"Decimal Test {uuid.uuid4().hex[:8]}"
        self.created_id = None

    def tearDown(self):
        if not self.created_id:
            return
        projeto_path = get_projeto_json_path(self.created_id)
        base_dir = projeto_path.parent
        if base_dir.exists():
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_normaliza_percentual_financeiro_no_post(self):
        payload = {
            "nome": self.nome,
            "url_booking": "https://www.booking.com/hotel/br/decimal-test",
            "numero_quartos": 5,
            "faturamento_anual": 100000.0,
            "ano_referencia": 2026,
            "financeiro": {
                "custos_fixos": {"luz": 1000.1234},
                "folha_pagamento_mensal": 12345.6789,
                "custos_variaveis": {"cafe_manha": 20.556},
                "media_pessoas_por_diaria": 2.3456,
                "aliquota_impostos": 14,
                "percentual_contingencia": 7.12345,
                "outros_impostos_taxas_percentual": 0.333339,
                "funcionarios": [],
            },
        }
        resp = self.client.post("/projeto", json=payload, content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json() or {}
        self.created_id = body.get("data", {}).get("id")
        self.assertTrue(self.created_id)

        projeto_path = get_projeto_json_path(self.created_id)
        self.assertTrue(projeto_path.exists())
        raw = json.loads(projeto_path.read_text(encoding="utf-8"))
        fin = raw.get("financeiro", {})

        self.assertEqual(fin.get("aliquota_impostos"), 0.14)
        self.assertEqual(fin.get("percentual_contingencia"), 0.0712)
        self.assertEqual(fin.get("outros_impostos_taxas_percentual"), 0.3333)
        self.assertEqual(fin.get("folha_pagamento_mensal"), 12345.68)
        self.assertEqual(fin.get("media_pessoas_por_diaria"), 2.35)
        self.assertEqual(fin.get("custos_fixos", {}).get("luz"), 1000.12)
        self.assertEqual(fin.get("custos_variaveis", {}).get("cafe_manha"), 20.56)


if __name__ == "__main__":
    unittest.main()
