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

    def test_folha_total_com_beneficios_globais(self):
        fin = DadosFinanceiros(
            encargos_pct_padrao=0.1,
            beneficio_vale_transporte=100,
            beneficio_vale_alimentacao=200,
            funcionarios=[
                Funcionario(
                    cargo="Recepção",
                    quantidade=2,
                    salario_base=2000,
                    usar_encargos_padrao=True,
                    beneficios=300,
                ),
            ],
        )
        # (2000*2)*1.1 + 300 + (100+200)*2 = 5300
        self.assertEqual(fin.folha_total, 5300.0)

    def test_funcionario_pode_sobrescrever_encargos_padrao(self):
        fin = DadosFinanceiros(
            encargos_pct_padrao=0.2,
            funcionarios=[
                Funcionario(
                    cargo="Limpeza",
                    quantidade=1,
                    salario_base=1500,
                    usar_encargos_padrao=False,
                    encargos_pct=0.1,
                    beneficios=0,
                ),
            ],
        )
        # Deve usar 10% individual, não 20% global.
        self.assertEqual(fin.folha_total, 1650.0)


if __name__ == "__main__":
    unittest.main()
