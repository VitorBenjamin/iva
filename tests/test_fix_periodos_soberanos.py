import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import _carregar_registros_dashboard
from core.config import canonical_periodo_id


class TestFixPeriodosSoberanos(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_periodos_soberanos_")
        self.root = Path(self.tmpdir)
        self.pid = "periodos-soberanos-pousada"
        self.base = self.root / self.pid
        self.base.mkdir(parents=True, exist_ok=True)
        self._write_base_files()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_base_files(self):
        projeto = {
            "id": self.pid,
            "nome": "Pousada Teste Periodos",
            "url_booking": "https://example.com/hotel",
            "numero_quartos": 10,
            "faturamento_anual": 0,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        cfg = {
            "periodos_especiais": [
                {"inicio": "28/03/2026", "fim": "05/04/2026", "nome": "Semana Santa"},
                {"inicio": "10/07/2026", "fim": "25/07/2026", "nome": "Férias de Julho"},
            ],
            "descontos": {"global": 0.0, "por_mes": {}},
            "noites": {"preferencial": 2, "max_tentativas": 3},
        }
        bruto = {"id_projeto": self.pid, "url": projeto["url_booking"], "ano": 2026, "registros": []}
        (self.base / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "scraper_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_registros(self, registros):
        bruto = json.loads((self.base / "market_bruto.json").read_text(encoding="utf-8"))
        bruto["registros"] = registros
        (self.base / "market_bruto.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_especiais(self):
        with patch("core.projetos.PROJECTS_DIR", self.root), patch("app.PROJECTS_DIR", self.root):
            dados = _carregar_registros_dashboard(self.pid)
        grupos = dados.get("grupos_especiais") or []
        if not grupos:
            return []
        return grupos[0].get("registros", [])

    def test_agrupa_por_periodo_id_mesmo_com_nome_divergente(self):
        pid_cfg = canonical_periodo_id("Semana Santa", "2026-03-28", "2026-04-05")
        self._write_registros(
            [
                {
                    "checkin": "2026-03-29",
                    "checkout": "2026-03-31",
                    "mes_ano": "2026-03",
                    "tipo_dia": "fim_de_semana",
                    "preco_booking": 300.0,
                    "preco_direto": 240.0,
                    "nome_quarto": "Q1",
                    "tipo_tarifa": "Padrão",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {
                        "periodo_id": pid_cfg,
                        "periodo_nome": "Semana Santa / Páscoa",
                        "periodo_source": "config",
                    },
                }
            ]
        )
        especiais = self._load_especiais()
        self.assertEqual(len(especiais), 1)
        self.assertEqual(especiais[0]["periodo_nome"], "Semana Santa")
        self.assertNotEqual(especiais[0]["periodo_nome"], "Outro (especial)")

    def test_exibe_intervalo_completo_do_config_para_data_interna(self):
        self._write_registros(
            [
                {
                    "checkin": "2026-03-29",
                    "checkout": "2026-03-30",
                    "mes_ano": "2026-03",
                    "tipo_dia": "fim_de_semana",
                    "preco_booking": 250.0,
                    "preco_direto": 200.0,
                    "nome_quarto": "Q2",
                    "tipo_tarifa": "Padrão",
                    "noites": 1,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {},
                }
            ]
        )
        especiais = self._load_especiais()
        self.assertEqual(len(especiais), 1)
        self.assertEqual(especiais[0]["periodo_inicio_config"], "2026-03-28")
        self.assertEqual(especiais[0]["periodo_fim_config"], "2026-04-05")
        self.assertEqual(especiais[0]["checkin"], "2026-03-28")
        self.assertEqual(especiais[0]["checkout"], "2026-04-05")

    def test_fallback_outro_para_data_fora_do_config(self):
        self._write_registros(
            [
                {
                    "checkin": "2026-06-10",
                    "checkout": "2026-06-12",
                    "mes_ano": "2026-06",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 220.0,
                    "preco_direto": 176.0,
                    "nome_quarto": "Q3",
                    "tipo_tarifa": "Padrão",
                    "noites": 2,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {},
                }
            ]
        )
        especiais = self._load_especiais()
        self.assertEqual(len(especiais), 1)
        self.assertEqual(especiais[0]["periodo_nome"], "Outro (especial)")
        self.assertIsNone(especiais[0]["periodo_inicio_config"])
        self.assertIsNone(especiais[0]["periodo_fim_config"])
        self.assertEqual(especiais[0]["checkin"], "2026-06-10")
        self.assertEqual(especiais[0]["checkout"], "2026-06-12")


if __name__ == "__main__":
    unittest.main()
