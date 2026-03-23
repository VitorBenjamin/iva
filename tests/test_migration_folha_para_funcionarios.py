import unittest

from scripts.migration.migrate_folha_to_funcionarios import _apply_mapping, _needs_migration


class TestMigrationFolhaParaFuncionarios(unittest.TestCase):
    def test_needs_migration_quando_legacy(self):
        payload = {"financeiro": {"folha_pagamento_mensal": 5000, "funcionarios": []}}
        self.assertTrue(_needs_migration(payload))

    def test_apply_mapping_cria_funcionario_default(self):
        payload = {"financeiro": {"folha_pagamento_mensal": 5000, "funcionarios": []}}
        mapped = _apply_mapping(payload)
        funcs = mapped["financeiro"]["funcionarios"]
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0]["cargo"], "Equipe (legacy)")
        self.assertEqual(funcs[0]["salario_base"], 5000.0)


if __name__ == "__main__":
    unittest.main()
