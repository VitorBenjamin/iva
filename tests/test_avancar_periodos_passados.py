"""
test_avancar_periodos_passados — opt-out de avanço de períodos passados.
Caso A: avancar_periodos_passados=True -> período passado avança para próximo ano.
Caso B: avancar_periodos_passados=False -> período permanece como no config.
Caso C: chave ausente -> default True (comportamento legado).
"""
import unittest
from datetime import date
from unittest.mock import patch

from core.config import _periodos_especiais_de_config


# Carnaval 14-18/02/2026; em março 2026 já é passado -> avança para 2027
CONFIG_CARNAVAL_2026 = {
    "periodos_especiais": [
        {"inicio": "14/02/2026", "fim": "18/02/2026", "nome": "Carnaval"},
    ],
}


class TestAvancarPeriodosPassados(unittest.TestCase):
    """Testes do parâmetro avancar_periodos_passados."""

    @patch("core.config.carregar_config_scraper")
    def test_avancar_true_periodo_passado_avanca_ano(self, mock_carregar):
        """Caso A: avancar_periodos_passados=True -> período passado retorna com ano avançado."""
        mock_carregar.return_value = {
            **CONFIG_CARNAVAL_2026,
            "avancar_periodos_passados": True,
        }
        periodos = _periodos_especiais_de_config("projeto-teste")
        self.assertEqual(len(periodos), 1)
        p = periodos[0]
        # Carnaval 2026 passou em março; deve ter avançado para 2027
        self.assertIn("2027", p["inicio"], "Período passado deve avançar para 2027")
        self.assertIn("2027", p["fim"])
        self.assertIn("carnaval", p["periodo_id"].lower())

    @patch("core.config.carregar_config_scraper")
    def test_avancar_false_periodo_permanece_original(self, mock_carregar):
        """Caso B: avancar_periodos_passados=False -> período retornado exatamente como no config."""
        mock_carregar.return_value = {
            **CONFIG_CARNAVAL_2026,
            "avancar_periodos_passados": False,
        }
        periodos = _periodos_especiais_de_config("projeto-teste")
        self.assertEqual(len(periodos), 1)
        p = periodos[0]
        self.assertEqual(p["inicio"], "2026-02-14")
        self.assertEqual(p["fim"], "2026-02-18")
        self.assertIn("2026-02-14", p["periodo_id"])

    @patch("core.config.carregar_config_scraper")
    def test_ausencia_chave_default_true(self, mock_carregar):
        """Caso C: ausência da chave -> default True (avança período passado)."""
        mock_carregar.return_value = CONFIG_CARNAVAL_2026  # sem avancar_periodos_passados
        periodos = _periodos_especiais_de_config("projeto-teste")
        self.assertEqual(len(periodos), 1)
        p = periodos[0]
        # Default True = deve avançar
        self.assertIn("2027", p["inicio"])

    @patch("core.config.carregar_config_scraper")
    def test_alias_advance_periods_if_passed(self, mock_carregar):
        """Alias advance_periods_if_passed funciona como avancar_periodos_passados."""
        mock_carregar.return_value = {
            **CONFIG_CARNAVAL_2026,
            "advance_periods_if_passed": False,
        }
        periodos = _periodos_especiais_de_config("projeto-teste")
        self.assertEqual(len(periodos), 1)
        p = periodos[0]
        self.assertEqual(p["inicio"], "2026-02-14")

    @patch("core.config.carregar_config_scraper")
    def test_meta_avancado_presente(self, mock_carregar):
        """Períodos incluem _meta.avancado para auditoria."""
        mock_carregar.return_value = {
            **CONFIG_CARNAVAL_2026,
            "avancar_periodos_passados": False,
        }
        periodos = _periodos_especiais_de_config("projeto-teste")
        self.assertIn("_meta", periodos[0])
        self.assertIn("avancado", periodos[0]["_meta"])
        self.assertFalse(periodos[0]["_meta"]["avancado"])


if __name__ == "__main__":
    unittest.main()
