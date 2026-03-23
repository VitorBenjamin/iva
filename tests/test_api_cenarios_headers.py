import unittest
from unittest.mock import patch

from app import app


class TestApiCenariosHeaders(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_get_cenarios_tem_headers_anti_cache(self):
        with patch("app.carregar_projeto", return_value=object()):
            resp = self.client.get("/api/projeto/projeto-teste/cenarios")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("success"))

        cache_control = resp.headers.get("Cache-Control", "")
        pragma = resp.headers.get("Pragma", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", pragma)


if __name__ == "__main__":
    unittest.main()
