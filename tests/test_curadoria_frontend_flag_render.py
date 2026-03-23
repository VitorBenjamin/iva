import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app


class TestCuradoriaFrontendFlagRender(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_front_flag_")
        self.client = app.test_client()
        self.id = "front-flag-pousada"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_files(self, frontend_override=None):
        base = Path(self.tmpdir) / self.id
        base.mkdir(parents=True, exist_ok=True)
        d = date.today() + timedelta(days=3)
        d2 = d + timedelta(days=2)
        mes_ano = f"{d.year}-{d.month:02d}"
        projeto = {
            "id": self.id,
            "nome": "Pousada Front Flag",
            "url_booking": "https://www.booking.com/hotel/br/front",
            "numero_quartos": 6,
            "faturamento_anual": 1000,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        if frontend_override is not None:
            projeto["curadoria"] = {"frontend_desconto_unificado": frontend_override}
        cfg = {
            "periodos_especiais": [],
            "descontos": {"global": 0.2, "por_mes": {}},
            "noites": {"preferencial": 2, "max_tentativas": 4},
        }
        bruto = {
            "id_projeto": self.id,
            "url": "https://www.booking.com/hotel/br/front",
            "ano": 2026,
            "registros": [
                {
                    "checkin": d.isoformat(),
                    "checkout": d2.isoformat(),
                    "mes_ano": mes_ano,
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 1000.0,
                    "preco_direto": 800.0,
                    "nome_quarto": "Q1",
                    "tipo_tarifa": "Padrão",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                }
            ],
        }
        (base / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        (base / "scraper_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        (base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_render_tem_data_preco_booking(self):
        self._write_files()
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn('data-preco-booking="', html)

    def test_badge_frontend_unificado_ativo_via_env(self):
        self._write_files()
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, {"FRONTEND_DESCONTO_UNIFICADO": "true"}):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Modo desconto unificado (frontend) ativo", html)

    def test_override_projeto_desliga_badge(self):
        self._write_files(frontend_override=False)
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)), patch.dict(os.environ, {"FRONTEND_DESCONTO_UNIFICADO": "true"}):
            resp = self.client.get(f"/projeto/{self.id}/curadoria")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("Modo desconto unificado (frontend) ativo", html)


if __name__ == "__main__":
    unittest.main()
