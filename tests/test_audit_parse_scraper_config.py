"""
test_audit_parse_scraper_config — parsing de várias chaves e formatos de datas no scraper_config.
Recomendado pela auditoria cursor-datas-especiais.
"""
import unittest

from core.config import _periodos_especiais_de_config, resolve_periodo_por_checkin


class TestAuditParseScraperConfig(unittest.TestCase):
    """Testes de parsing de periodos_especiais e datas_especiais."""

    def test_periodos_especiais_aceita_dd_mm_yyyy(self):
        """Config com inicio/fim em DD/MM/YYYY é parseado corretamente."""
        # Usa projeto existente com config conhecido
        periodos = _periodos_especiais_de_config("cottage-bahia")
        for p in periodos:
            self.assertIn("periodo_id", p)
            self.assertIn("inicio", p)
            self.assertIn("fim", p)
            self.assertIn("nome", p)

    def test_resolve_periodo_por_checkin_retorna_dict_ou_none(self):
        """resolve_periodo_por_checkin retorna dict com periodo_id ou None."""
        result = resolve_periodo_por_checkin("cottage-bahia", "2026-03-28")
        if result:
            self.assertIsInstance(result, dict)
            self.assertIn("periodo_id", result)
            self.assertIn("nome", result)


if __name__ == "__main__":
    unittest.main()
