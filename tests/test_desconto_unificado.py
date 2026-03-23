import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core.analise.desconto import _normalizar_desconto_raw, obter_desconto_para_curadoria
from core.projetos import read_curadoria_desconto, write_curadoria_desconto


class TestDescontoUnificado(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_desconto_unificado_")
        self.id = "pousada-desc"
        self.base = Path(self.tmpdir) / self.id
        self.base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, name: str, payload: dict):
        (self.base / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_normalizar_desconto_raw(self):
        self.assertEqual(_normalizar_desconto_raw(15), Decimal("0.15"))
        self.assertEqual(_normalizar_desconto_raw("0.15"), Decimal("0.15"))
        self.assertEqual(_normalizar_desconto_raw("15"), Decimal("0.15"))
        self.assertIsNone(_normalizar_desconto_raw(None))
        self.assertEqual(_normalizar_desconto_raw(-5), Decimal("0"))

    def test_prioridade_projeto_curadoria(self):
        projeto = {
            "id": self.id,
            "nome": "Pousada Desconto",
            "url_booking": "https://www.booking.com/hotel/br/desc",
            "numero_quartos": 5,
            "faturamento_anual": 1000,
            "ano_referencia": 2026,
            "financeiro": {},
            "curadoria": {"desconto_padrao": 0.33},
        }
        self._write_json("projeto.json", projeto)
        self._write_json("market_curado.json", {"meta": {"desconto": 0.11}, "registros": []})
        self._write_json("scraper_config.json", {"descontos": {"global": 0.2, "por_mes": {"02": 0.4}}})
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            d = obter_desconto_para_curadoria(self.id, "2026-02")
        self.assertEqual(d, Decimal("0.33"))

    def test_prioridade_market_curado_quando_sem_projeto(self):
        projeto = {
            "id": self.id,
            "nome": "Pousada Desconto",
            "url_booking": "https://www.booking.com/hotel/br/desc",
            "numero_quartos": 5,
            "faturamento_anual": 1000,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        self._write_json("projeto.json", projeto)
        self._write_json("market_curado.json", {"meta": {"desconto_por_mes": {"2026-02": 0.12}}, "registros": []})
        self._write_json("scraper_config.json", {"descontos": {"global": 0.2, "por_mes": {"02": 0.4}}})
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            d = obter_desconto_para_curadoria(self.id, "2026-02")
        self.assertEqual(d, Decimal("0.12"))

    def test_fallback_scraper_config(self):
        projeto = {
            "id": self.id,
            "nome": "Pousada Desconto",
            "url_booking": "https://www.booking.com/hotel/br/desc",
            "numero_quartos": 5,
            "faturamento_anual": 1000,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        self._write_json("projeto.json", projeto)
        self._write_json("market_curado.json", {"meta": {}, "registros": []})
        self._write_json("scraper_config.json", {"descontos": {"global": 0.2, "por_mes": {"02": 15}}})
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            d = obter_desconto_para_curadoria(self.id, "2026-02")
        self.assertEqual(d, Decimal("0.15"))

    def test_write_read_curadoria_desconto(self):
        projeto = {
            "id": self.id,
            "nome": "Pousada Desconto",
            "url_booking": "https://www.booking.com/hotel/br/desc",
            "numero_quartos": 5,
            "faturamento_anual": 1000,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        self._write_json("projeto.json", projeto)
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            write_curadoria_desconto(self.id, Decimal("0.27"))
            d = read_curadoria_desconto(self.id)
        self.assertEqual(d, Decimal("0.27"))
        backups = self.base / "backups"
        self.assertTrue(backups.exists())


if __name__ == "__main__":
    unittest.main()
