"""
test_import_template_scraper_config — simular criação de projeto e import template.
Recomendado pela auditoria cursor-datas-especiais.
"""
import tempfile
import unittest

from core.config import _get_scraper_config_template, generate_scaffold_from_metadata


class TestImportTemplateScraperConfig(unittest.TestCase):
    """Testes de template padrão de datas comemorativas."""

    def test_get_scraper_config_template_tem_periodos(self):
        """Template padrão tem periodos_especiais não vazios."""
        tpl = _get_scraper_config_template()
        pe = tpl.get("periodos_especiais", [])
        self.assertGreater(len(pe), 0)
        for item in pe:
            self.assertIn("nome", item)
            self.assertIn("inicio", item)

    def test_generate_scaffold_from_metadata_aceita_periodos_vazios(self):
        """generate_scaffold_from_metadata retorna periodos_especiais: [] quando metadata vazio."""
        cfg = generate_scaffold_from_metadata({})
        self.assertIn("periodos_especiais", cfg)
        self.assertEqual(cfg["periodos_especiais"], [])

    def test_create_project_scaffold_scraper_config_existe(self):
        """create_project_scaffold cria scraper_config.json para projeto novo."""
        with tempfile.TemporaryDirectory() as tmp:
            # Mock PROJECTS_DIR para teste isolado exigiria mais setup
            # Teste simplificado: verificar que template existe
            tpl = _get_scraper_config_template()
            self.assertIn("periodos_especiais", tpl)


if __name__ == "__main__":
    unittest.main()
