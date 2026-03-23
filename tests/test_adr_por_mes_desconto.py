import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.analise.adr_por_mes import obter_adr_por_mes


class TestAdrPorMesDesconto(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_adr_desc_")
        self.id = "pousada-adr"
        self.base = Path(self.tmpdir) / self.id
        self.base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, payload: dict):
        (self.base / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_adr_usa_desconto_unificado_com_prioridade(self):
        self._write(
            "projeto.json",
            {
                "id": self.id,
                "nome": "Pousada ADR",
                "url_booking": "https://www.booking.com/hotel/br/adr",
                "numero_quartos": 5,
                "faturamento_anual": 1000,
                "ano_referencia": 2026,
                "financeiro": {},
                "curadoria": {"desconto_padrao": 0.15},
            },
        )
        self._write(
            "market_bruto.json",
            {
                "id_projeto": self.id,
                "url": "https://www.booking.com/hotel/br/adr",
                "ano": 2026,
                "registros": [
                    {
                        "checkin": "2026-02-10",
                        "checkout": "2026-02-12",
                        "mes_ano": "2026-02",
                        "tipo_dia": "dia_de_semana",
                        "preco_booking": 1000.0,
                        "preco_direto": 0,
                        "nome_quarto": "Q",
                        "tipo_tarifa": "Padrão",
                        "noites": 2,
                        "status": "OK",
                        "categoria_dia": "normal",
                    }
                ],
            },
        )
        self._write("market_curado.json", {"id_projeto": self.id, "url": "", "ano": 2026, "registros": []})
        self._write("scraper_config.json", {"descontos": {"global": 0.2, "por_mes": {"02": 0.4}}})

        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            adr = obter_adr_por_mes(self.id)

        self.assertIn("2026-02", adr)
        self.assertEqual(adr["2026-02"]["adr"], 850.0)
        self.assertEqual(adr["2026-02"]["fonte"], "direto")


if __name__ == "__main__":
    unittest.main()
