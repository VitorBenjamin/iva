"""Testes de exclusão segura de projeto (core/projetos + API)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from core.projetos import (
    ArquivoProjetoNaoEncontrado,
    excluir_projeto_seguro,
    validar_id_projeto_para_escrita,
)


class TestExcluirProjetoSeguro(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="iva_test_excluir_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_validar_id_rejeita_invalidos(self):
        with self.assertRaises(ValueError):
            validar_id_projeto_para_escrita("")
        with self.assertRaises(ValueError):
            validar_id_projeto_para_escrita("../x")
        with self.assertRaises(ValueError):
            validar_id_projeto_para_escrita("id com espaço")
        self.assertEqual(validar_id_projeto_para_escrita("  Teste-Id "), "teste-id")

    def test_excluir_remove_pasta_do_projeto(self):
        pid = "pousada-excluir-teste"
        base = Path(self.tmpdir) / pid
        base.mkdir(parents=True)
        (base / "projeto.json").write_text(json.dumps({"id": pid, "nome": "X"}), encoding="utf-8")

        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            out = excluir_projeto_seguro(pid)

        self.assertEqual(out["id_projeto"], pid)
        self.assertFalse(base.exists())

    def test_excluir_sem_projeto_levanta(self):
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)):
            with self.assertRaises(ArquivoProjetoNaoEncontrado):
                excluir_projeto_seguro("nao-existe-xyz")

    def test_api_delete_projeto(self):
        pid = "api-delete-teste"
        base = Path(self.tmpdir) / pid
        base.mkdir(parents=True)
        projeto = {
            "id": pid,
            "nome": "Del",
            "url_booking": "https://www.booking.com/hotel/br/del",
            "numero_quartos": 1,
            "faturamento_anual": 0,
            "ano_referencia": 2026,
            "financeiro": {},
        }
        (base / "projeto.json").write_text(json.dumps(projeto), encoding="utf-8")

        client = app.test_client()
        with patch("core.projetos.PROJECTS_DIR", Path(self.tmpdir)), patch("app.PROJECTS_DIR", Path(self.tmpdir)):
            resp = client.delete(f"/api/projeto/{pid}")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(base.exists())
