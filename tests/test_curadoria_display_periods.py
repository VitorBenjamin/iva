import unittest

from app import _resolver_preco_exibicao_preferida


class TestCuradoriaDisplayPeriods(unittest.TestCase):
    def test_prefere_preco_por_data(self):
        origem, valor = _resolver_preco_exibicao_preferida(351.0, 306.0)
        self.assertEqual(origem, "por_data")
        self.assertEqual(valor, 351.0)

    def test_usa_media_quando_sem_por_data(self):
        origem, valor = _resolver_preco_exibicao_preferida(None, 123.25)
        self.assertEqual(origem, "media_periodo")
        self.assertEqual(valor, 123.25)

    def test_nao_disponivel_quando_sem_dados(self):
        origem, valor = _resolver_preco_exibicao_preferida(None, None)
        self.assertEqual(origem, "nao_disponivel")
        self.assertIsNone(valor)


if __name__ == "__main__":
    unittest.main()
