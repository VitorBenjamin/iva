"""Taxonomia de incidência em custos variáveis (UH/noite vs hóspede/noite)."""

import unittest

from core.financeiro.custos_variaveis_motor import (
    custo_variavel_operacional_mensal_total,
    subtotal_custo_item,
)
from core.financeiro.modelos import CustoVariavelItem, CustosVariaveisPorNoite, IncidenciaCustoVariavel


class TestCustosVariaveisIncidencia(unittest.TestCase):
    def test_lavanderia_uh_noite_30_vezes_noites_independente_pessoas(self):
        """R$ 30 UH/noite → custo mensal = 30 × noites (não multiplica por pessoas)."""
        item = CustoVariavelItem(valor=30.0, incidencia=IncidenciaCustoVariavel.UH_NOITE)
        noites = 100.0
        receita = 50000.0
        sub = subtotal_custo_item(
            item,
            noites_vendidas=noites,
            receita_bruta=receita,
            media_pessoas=3.0,
            permanencia_media=2.0,
        )
        self.assertAlmostEqual(sub, 3000.0, places=4)

        hospede = CustoVariavelItem(valor=30.0, incidencia=IncidenciaCustoVariavel.HOSPEDE_NOITE)
        sub_h = subtotal_custo_item(
            hospede,
            noites_vendidas=noites,
            receita_bruta=receita,
            media_pessoas=3.0,
            permanencia_media=2.0,
        )
        self.assertAlmostEqual(sub_h, 9000.0, places=4)

    def test_custo_mensal_total_com_cv_uh_only(self):
        cv = CustosVariaveisPorNoite(
            lavanderia=CustoVariavelItem(valor=30.0, incidencia=IncidenciaCustoVariavel.UH_NOITE),
        )
        tot = custo_variavel_operacional_mensal_total(
            cv,
            noites_vendidas=100.0,
            receita_bruta=40000.0,
            media_pessoas=2.0,
            permanencia_media=2.0,
            comissao_pct=0.0,
        )
        self.assertAlmostEqual(tot, 3000.0, places=4)

    def test_percentual_receita_item(self):
        item = CustoVariavelItem(valor=5.0, incidencia=IncidenciaCustoVariavel.PERCENTUAL_RECEITA)
        sub = subtotal_custo_item(
            item,
            noites_vendidas=10.0,
            receita_bruta=10000.0,
            media_pessoas=2.0,
            permanencia_media=2.0,
        )
        self.assertAlmostEqual(sub, 500.0, places=4)


if __name__ == "__main__":
    unittest.main()
