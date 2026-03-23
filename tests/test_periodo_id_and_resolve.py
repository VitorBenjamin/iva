import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import canonical_periodo_id, resolve_periodo_por_checkin


class TestPeriodoIdAndResolve(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_periodo_id_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_canonical_periodo_id_normaliza_nome(self):
        pid = canonical_periodo_id("Carnaval 2026", "2026-02-14", "2026-02-18")
        self.assertEqual(pid, "carnaval-2026-2026-02-14-2026-02-18")

    def test_resolve_periodo_por_checkin(self):
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            base = Path(self.tmpdir) / "pousada-x"
            base.mkdir(parents=True, exist_ok=True)
            cfg = {
                "periodos_especiais": [
                    {"nome": "Carnaval", "inicio": "14/02/2026", "fim": "18/02/2026"}
                ]
            }
            with open(base / "scraper_config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            p = resolve_periodo_por_checkin("pousada-x", "2027-02-15")
            self.assertIsNotNone(p)
            self.assertEqual(p.get("nome"), "Carnaval")
            self.assertEqual(p.get("periodo_source", "config"), "config")
            self.assertTrue(str(p.get("periodo_id", "")).startswith("carnaval-"))


if __name__ == "__main__":
    unittest.main()
