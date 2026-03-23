import unittest

from core.financeiro.modelos import DadosFinanceiros, Funcionario


class TestFuncionariosSchema(unittest.TestCase):
    def test_folha_total_por_funcionarios(self):
        fin = DadosFinanceiros(
            funcionarios=[
                Funcionario(cargo="Recepção", quantidade=2, salario_base=2000, encargos_pct=0.1, beneficios=300),
                Funcionario(cargo="Limpeza", quantidade=1, salario_base=1500, encargos_pct=0.2, beneficios=100),
            ]
        )
        self.assertEqual(fin.folha_total, 6600.0)

    def test_fallback_legacy_quando_sem_funcionarios(self):
        fin = DadosFinanceiros(folha_pagamento_mensal=4321.99, funcionarios=[])
        self.assertEqual(fin.folha_total, 4321.99)


if __name__ == "__main__":
    unittest.main()
