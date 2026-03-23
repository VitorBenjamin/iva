import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app


class TestCuradoriaStrictPeriodos(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_strict_periodos_")
        self.client = app.test_client()
        self.id = "strict-pousada"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_files(self, strict_override=None):
        base = Path(self.tmpdir) / self.id
        base.mkdir(parents=True, exist_ok=True)

        hoje = date.today()
        inicio = hoje + timedelta(days=1)
        fim = hoje + timedelta(days=2)
        inicio_s = inicio.strftime("%d/%m/%Y")
        fim_s = fim.strftime("%d/%m/%Y")
        inicio_iso = inicio.isoformat()
        fim_iso = fim.isoformat()
        pid = f"carnaval-{inicio_iso}-{fim_iso}"

        projeto = {
            "id": self.id,
            "nome": "Pousada Strict",
            "url_booking": "https://www.booking.com/hotel/br/strict",
            "numero_quartos": 10,
            "faturamento_anual": 1000000,
            "ano_referencia": hoje.year,
            "financeiro": {},
            "infrastructure": None,
            "dados_mercado": None,
        }
        if strict_override is not None:
            projeto["strict_periodos"] = strict_override

        cfg = {
            "periodos_especiais": [
                {"nome": "Carnaval", "inicio": inicio_s, "fim": fim_s}
            ],
            "descontos": {"global": 0.2, "por_mes": {}},
            "noites": {"preferencial": 2, "max_tentativas": 4},
        }
        bruto = {
            "id_projeto": self.id,
            "url": "https://www.booking.com/hotel/br/strict",
            "ano": hoje.year,
            "criado_em": "2026-01-01T00:00:00",
            "registros": [
                {
                    "checkin": inicio_iso,
                    "checkout": (inicio + timedelta(days=2)).isoformat(),
                    "mes_ano": f"{inicio.year}-{inicio.month:02d}",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 500.0,
                    "preco_direto": 400.0,
                    "nome_quarto": "Q1",
                    "tipo_tarifa": "Padrão",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {"periodo_id": pid, "periodo_nome": "Carnaval", "periodo_source": "config"},
                },
                {
                    "checkin": (inicio + timedelta(days=4)).isoformat(),
                    "checkout": (inicio + timedelta(days=6)).isoformat(),
                    "mes_ano": f"{inicio.year}-{inicio.month:02d}",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 480.0,
                    "preco_direto": 384.0,
                    "nome_quarto": "Q2",
                    "tipo_tarifa": "Padrão",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {"periodo_id": "nao-existe", "periodo_nome": "Legado", "periodo_source": "fallback"},
                },
            ],
        }

        (base / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        (base / "scraper_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        (base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_strict_true_separa_inconsistencias(self):
        self._write_files()
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, {"STRICT_PERIODOS": "true"}):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("STRICT_PERIODOS ativo", html)
        self.assertIn("Inconsistências — registros especiais sem match no config", html)
        self.assertIn("Inconsistente", html)

    def test_strict_false_mantem_comportamento_atual(self):
        self._write_files()
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, {"STRICT_PERIODOS": "false"}):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("STRICT_PERIODOS ativo", html)
        self.assertNotIn("Inconsistências — registros especiais sem match no config", html)

    def test_override_projeto_desativa_strict(self):
        self._write_files(strict_override=False)
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, {"STRICT_PERIODOS": "true"}):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("STRICT_PERIODOS ativo", html)


if __name__ == "__main__":
    unittest.main()
