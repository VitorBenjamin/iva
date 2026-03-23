import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import carregar_config_scraper
from core.projetos import (
    get_backups_dir,
    get_cenarios_path,
    get_market_bruto_path,
    get_market_curado_path,
    get_scraper_config_path,
)
from core.scraper.scrapers import _periodos_dinamicos_do_config
from core.scraper import scrapers as scrapers_mod


class TestPathHelpers(unittest.TestCase):
    def test_helpers_paths(self):
        pid = "hotel-teste"
        self.assertTrue(str(get_scraper_config_path(pid)).replace("\\", "/").endswith(f"data/projects/{pid}/scraper_config.json"))
        self.assertTrue(str(get_market_bruto_path(pid)).replace("\\", "/").endswith(f"data/projects/{pid}/market_bruto.json"))
        self.assertTrue(str(get_market_curado_path(pid)).replace("\\", "/").endswith(f"data/projects/{pid}/market_curado.json"))
        self.assertTrue(str(get_cenarios_path(pid)).replace("\\", "/").endswith(f"data/projects/{pid}/cenarios.json"))
        self.assertTrue(str(get_backups_dir(pid)).replace("\\", "/").endswith(f"data/projects/{pid}/backups"))


class TestScraperConfigRead(unittest.TestCase):
    def test_carrega_scraper_config_da_subpasta_do_projeto(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data" / "projects"
            pid = "pousada-x"
            cfg_path = root / pid / "scraper_config.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "datas_especiais": [
                    {"nome": "Reveillon", "checkin": "2026-12-30", "checkout": "2027-01-02"}
                ],
                "noites": {"preferencial": 2},
            }
            cfg_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with patch("core.projetos.PROJECTS_DIR", root):
                cfg = carregar_config_scraper(pid)

            self.assertIsNotNone(cfg)
            self.assertEqual(len(cfg.get("datas_especiais") or []), 1)
            self.assertEqual((cfg.get("datas_especiais") or [])[0].get("nome"), "Reveillon")

    def test_periodos_dinamicos_priorizam_datas_especiais(self):
        cfg = {
            "datas_especiais": [
                {"nome": "Carnaval", "checkin": "2027-02-08", "checkout": "2027-02-12"}
            ],
            "noites": {"preferencial": 2},
        }
        periodos = _periodos_dinamicos_do_config(cfg)
        self.assertEqual(len(periodos), 1)
        self.assertEqual(periodos[0]["checkin"], "2027-02-08")
        self.assertEqual(periodos[0]["checkout"], "2027-02-12")

    def test_periodos_dinamicos_aceita_dd_mm_yyyy(self):
        cfg = {
            "periodos_especiais": [
                {"nome": "Réveillon", "inicio": "28/12/2026", "fim": "02/01/2027"}
            ],
            "noites": {"preferencial": 2},
        }
        periodos = _periodos_dinamicos_do_config(cfg)
        self.assertEqual(len(periodos), 1)
        self.assertEqual(periodos[0]["checkin"], "2026-12-28")
        self.assertEqual(periodos[0]["checkout"], "2027-01-02")

    def test_log_scraper_config_trace_gera_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            fake_evidence = Path(td) / "evidence"
            cfg = {"datas_especiais": [{"nome": "Teste", "checkin": "2026-12-30"}]}
            cfg_path = Path(td) / "data" / "projects" / "pousada-z" / "scraper_config.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(scrapers_mod, "EVIDENCE_STABILITY_DIR", fake_evidence):
                scrapers_mod._log_scraper_config_trace("pousada-z", cfg_path, cfg)
            trace = fake_evidence / "SCRAPER_CONFIG_TRACE.jsonl"
            self.assertTrue(trace.exists())
            lines = [ln for ln in trace.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(lines), 1)
            payload = json.loads(lines[-1])
            self.assertEqual(payload["id_projeto"], "pousada-z")
            self.assertTrue(payload["scraper_config_path"].endswith("scraper_config.json"))


if __name__ == "__main__":
    unittest.main()
