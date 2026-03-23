"""Testes para fluxo de desconto e backup de market_curado."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.backup import salvar_market_curado_com_backup
from core.config import (
    descontos_config_para_template,
    obter_desconto_dinamico,
)
class TestObterDescontoDinamico(unittest.TestCase):
    """Testes para obter_desconto_dinamico com formatos decimal e percentual."""

    def test_formato_decimal_15_porcento(self):
        cfg = {"descontos": {"global": 0.15, "por_mes": {}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, None), 0.15)

    def test_formato_percentual_15(self):
        cfg = {"descontos": {"global": 15, "por_mes": {}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, None), 0.15)

    def test_formato_percentual_20(self):
        cfg = {"descontos": {"global": 20, "por_mes": {}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, None), 0.20)

    def test_por_mes_sobrescreve_global(self):
        cfg = {"descontos": {"global": 0.20, "por_mes": {"07": 0.10}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, "2026-07"), 0.10)

    def test_por_mes_percentual(self):
        cfg = {"descontos": {"global": 0.20, "por_mes": {"07": 15}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, "2026-07"), 0.15)

    def test_preco_direto_15_porcento(self):
        cfg = {"descontos": {"global": 0.15, "por_mes": {}}}
        desconto = obter_desconto_dinamico(cfg, None)
        preco_booking = 1000.0
        preco_direto = round(preco_booking * (1 - desconto), 2)
        self.assertAlmostEqual(preco_direto, 850.0)

    def test_config_none_usa_default(self):
        self.assertAlmostEqual(obter_desconto_dinamico(None, None), 0.20)

    def test_valor_invalido_usa_default(self):
        cfg = {"descontos": {"global": "invalido", "por_mes": {}}}
        self.assertAlmostEqual(obter_desconto_dinamico(cfg, None), 0.20)


class TestDescontosConfigParaTemplate(unittest.TestCase):
    """Testes para descontos_config_para_template."""

    def test_normaliza_global_percentual(self):
        cfg = {"descontos": {"global": 15, "por_mes": {}}}
        out = descontos_config_para_template(cfg)
        self.assertAlmostEqual(out["global"], 0.15)

    def test_normaliza_global_decimal(self):
        cfg = {"descontos": {"global": 0.15, "por_mes": {}}}
        out = descontos_config_para_template(cfg)
        self.assertAlmostEqual(out["global"], 0.15)

    def test_normaliza_por_mes_percentual(self):
        cfg = {"descontos": {"global": 0.20, "por_mes": {"07": 10, "12": 25}}}
        out = descontos_config_para_template(cfg)
        self.assertAlmostEqual(out["por_mes"]["07"], 0.10)
        self.assertAlmostEqual(out["por_mes"]["12"], 0.25)


class TestBackupMarketCurado(unittest.TestCase):
    """Testes para backup e gravação atômica de market_curado."""

    def test_salvar_cria_backup_se_existir_anterior(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data" / "projects"
            pid = "projeto-backup-test"
            dir_projeto = root / pid
            dir_projeto.mkdir(parents=True)

            path_curado = dir_projeto / "market_curado.json"
            dados_antigos = {"id_projeto": pid, "registros": [{"checkin": "2026-01-01"}]}
            path_curado.write_text(json.dumps(dados_antigos), encoding="utf-8")

            dados_novos = {"id_projeto": pid, "registros": [{"checkin": "2026-02-01"}]}

            with patch("core.projetos.PROJECTS_DIR", root):
                salvar_market_curado_com_backup(pid, dados_novos)
                dir_backups = root / pid / "backups"
                self.assertTrue(dir_backups.exists())
                backups = list(dir_backups.glob("market_curado_*.json"))
                self.assertGreaterEqual(len(backups), 1)
                backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
                self.assertEqual(backup_data["registros"][0]["checkin"], "2026-01-01")
                curado_atual = json.loads(path_curado.read_text(encoding="utf-8"))
                self.assertEqual(curado_atual["registros"][0]["checkin"], "2026-02-01")

    def test_salvar_grava_audit_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data" / "projects"
            pid = "projeto-audit-test"
            dir_projeto = root / pid
            dir_projeto.mkdir(parents=True)

            dados = {"id_projeto": pid, "registros": []}

            with patch("core.projetos.PROJECTS_DIR", root):
                salvar_market_curado_com_backup(pid, dados)
                path_audit = root / pid / "backups" / "audit_market_curado.jsonl"
                self.assertTrue(path_audit.exists())
                lines = [ln for ln in path_audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
                self.assertGreaterEqual(len(lines), 1)
                audit = json.loads(lines[-1])
                self.assertEqual(audit["evento"], "gravacao_ok")
                self.assertEqual(audit["id_projeto"], pid)

    def test_salvar_sem_arquivo_anterior_nao_falha(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data" / "projects"
            pid = "projeto-novo-test"
            dir_projeto = root / pid
            dir_projeto.mkdir(parents=True)

            dados = {"id_projeto": pid, "registros": [{"checkin": "2026-03-01"}]}

            with patch("core.projetos.PROJECTS_DIR", root):
                salvar_market_curado_com_backup(pid, dados)
                path_curado = root / pid / "market_curado.json"
                self.assertTrue(path_curado.exists())
                curado = json.loads(path_curado.read_text(encoding="utf-8"))
                self.assertEqual(len(curado["registros"]), 1)


if __name__ == "__main__":
    unittest.main()
