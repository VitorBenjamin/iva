"""Testes de labels na UI — valida que views expõem 'Pousada' em vez de 'Projeto'."""
import unittest

from app import app


class TestUILabels(unittest.TestCase):
    """Garante que a interface principal expõe 'Pousada' nos labels visíveis."""

    def setUp(self):
        self.client = app.test_client()

    def test_index_contem_criar_pousada(self):
        """Página principal contém o botão 'Criar Pousada'."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Criar Pousada", html)

    def test_index_contem_selecionar_pousada(self):
        """Dropdown contém label 'Selecionar pousada'."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Selecionar pousada", html)

    def test_index_contem_checklist_onboarding(self):
        """Página contém seção 'Checklist de Onboarding'."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Checklist de Onboarding", html)

    def test_index_contem_modal_criar_pousada(self):
        """Modal de criação tem título 'Criar Pousada'."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("modal-criar-pousada", html)
        self.assertIn("Criar Pousada", html)


if __name__ == "__main__":
    unittest.main()
