import unittest

from core.analise.engenharia_reversa import _custo_fixo_mensal_total
from core.financeiro.modelos import DadosFinanceiros, Funcionario
from core.projetos import Projeto


class TestFolhaTotalInAnalise(unittest.TestCase):
    def test_custo_fixo_usa_folha_total_quando_funcionarios(self):
        projeto = Projeto(
            id="t1",
            nome="Teste",
            url_booking="",
            numero_quartos=10,
            faturamento_anual=100000,
            ano_referencia=2026,
            arrendamento_total=2400.0,
            prazo_contrato_meses=12,
            financeiro=DadosFinanceiros(
                custos_fixos={"luz": 100, "agua": 50, "internet": 80, "iptu": 30, "contabilidade": 40, "seguros": 20, "outros": 10, "aluguel": 0},
                folha_pagamento_mensal=9999,
                funcionarios=[Funcionario(cargo="Equipe", quantidade=1, salario_base=1000, encargos_pct=0.1, beneficios=100)],
            ),
        )
        total = _custo_fixo_mensal_total(projeto)
        self.assertAlmostEqual(total, 1730.0, places=2)


if __name__ == "__main__":
    unittest.main()
