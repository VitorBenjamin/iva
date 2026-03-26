"""Sugestão automática de arrendamento (lucro operacional isolado − margem sobre receita)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.projetos import create_project_scaffold, get_projeto_json_path
from core.analise.simulacao import sugerir_arrendamento


class TestSugestaoArrendamento(unittest.TestCase):
    def test_formula_exemplo_documentacao(self):
        """Receita média 20k, lucro médio mensal 8k, margem 15% → arrendamento 5k/mês."""
        pid = "teste-sugestao-arr"
        with tempfile.TemporaryDirectory(prefix="iva_sug_arr_") as tmp:
            tdir = Path(tmp)
            with patch("core.projetos.PROJECTS_DIR", tdir):
                create_project_scaffold(
                    pid,
                    {
                        "nome": "Teste Sugestão",
                        "booking_url": "https://www.booking.com/hotel/br/teste",
                    },
                )
                assert get_projeto_json_path(pid).is_file()

            def fake_projecao(*_a, **_k):
                return {
                    "resumo": {
                        "receita_anual": 240_000.0,
                        "lucro_operacional_anual": 96_000.0,
                        "lucro_anual": 96_000.0,
                    }
                }

            def fake_metas(_id, _cid):
                return {"2025-01": {"ocupacao": 0.5, "adr": 100}}, None

            with patch("core.projetos.PROJECTS_DIR", tdir):
                with patch("core.analise.simulacao.calcular_projecao", side_effect=fake_projecao):
                    with patch(
                        "core.analise.simulacao._metas_para_sugestao_arrendamento",
                        side_effect=fake_metas,
                    ):
                        out = sugerir_arrendamento(pid, margem_minima_pct=15.0)

        self.assertEqual(out.get("status"), "viavel")
        self.assertAlmostEqual(out["receita_media_mensal"], 20_000.0, places=2)
        self.assertAlmostEqual(out["lucro_sem_arrendamento"], 8_000.0, places=2)
        self.assertAlmostEqual(out["margem_minima_R"], 3_000.0, places=2)
        self.assertAlmostEqual(out["arrendamento_sugerido"], 5_000.0, places=2)

    def test_inviavel_quando_margem_como_lucro(self):
        pid = "teste-sugestao-arr-2"
        with tempfile.TemporaryDirectory(prefix="iva_sug_arr2_") as tmp:
            tdir = Path(tmp)
            with patch("core.projetos.PROJECTS_DIR", tdir):
                create_project_scaffold(
                    pid,
                    {"nome": "T2", "booking_url": "https://www.booking.com/hotel/br/t2"},
                )

            def fake_projecao(*_a, **_k):
                return {
                    "resumo": {
                        "receita_anual": 120_000.0,
                        "lucro_operacional_anual": 12_000.0,
                    }
                }

            def fake_metas(_id, _cid):
                return {"2025-01": {"ocupacao": 0.5, "adr": 50}}, None

            with patch("core.projetos.PROJECTS_DIR", tdir):
                with patch("core.analise.simulacao.calcular_projecao", side_effect=fake_projecao):
                    with patch(
                        "core.analise.simulacao._metas_para_sugestao_arrendamento",
                        side_effect=fake_metas,
                    ):
                        out = sugerir_arrendamento(pid, margem_minima_pct=15.0)

        self.assertEqual(out.get("status"), "inviavel")
        self.assertIn("diagnostico", out)


if __name__ == "__main__":
    unittest.main()
