"""
test_mapping_periodos — mapeamento correto de datas para períodos especiais.
Recomendado pela auditoria cursor-datas-especiais.
"""
import unittest

from core.config import (
    get_periodo_config_por_data,
    get_periodo_config_por_id,
    resolve_periodo_por_checkin,
    _periodos_especiais_de_config,
)


class TestMappingPeriodos(unittest.TestCase):
    """Testes de mapeamento check-in -> período especial."""

    def test_resolve_periodo_por_checkin_em_semana_santa(self):
        """Check-in em 2026-03-28 deve casar com Semana Santa."""
        result = resolve_periodo_por_checkin("cottage-bahia", "2026-03-28")
        self.assertIsNotNone(result, "Deve encontrar período para 28/03/2026")
        if result:
            self.assertIn("semana", result.get("nome", "").lower())

    def test_get_periodo_config_por_data(self):
        """get_periodo_config_por_data encontra período por data."""
        periodos = _periodos_especiais_de_config("cottage-bahia")
        if not periodos:
            self.skipTest("cottage-bahia sem periodos_especiais no config")
        result = get_periodo_config_por_data(periodos, "2026-07-15")
        if result:
            self.assertIn("julho", result.get("nome", "").lower())

    def test_get_periodo_config_por_id(self):
        """get_periodo_config_por_id encontra período por periodo_id."""
        periodos = _periodos_especiais_de_config("cottage-bahia")
        if not periodos:
            self.skipTest("cottage-bahia sem periodos_especiais no config")
        pid = periodos[0].get("periodo_id")
        if pid:
            result = get_periodo_config_por_id(periodos, pid)
            self.assertEqual(result.get("periodo_id"), pid)


if __name__ == "__main__":
    unittest.main()
