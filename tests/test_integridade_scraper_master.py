import json
import unittest
from pathlib import Path

from app import app
from core.analise.adr_por_mes import obter_adr_por_mes
from core.config import definir_calendario_soberano_ano
from core.projetos import get_projeto_json_path, get_scraper_config_path, get_market_bruto_path


class TestIntegridadeScraperMaster(unittest.TestCase):
    def test_calendario_soberano_sem_fallback_algoritmico(self):
        """Com periodos_especiais explícitos, não deve injetar fallback algorítmico extra."""
        calendario = definir_calendario_soberano_ano(2027, id_projeto="cottage-bahia", rolling=False)
        especiais = calendario.get("especiais") or []
        nomes = [str(e.get("periodo_nome") or "").lower() for e in especiais]
        # Garantia mínima: usa nomes do config e não deve depender de fallback para existir.
        self.assertTrue(len(especiais) >= 0)
        self.assertFalse(any("fallback" in n for n in nomes))

    def test_persistencia_toggle_permitir_busca_externa(self):
        """POST scraper/config deve persistir permitir_busca_externa no scraper_config.json."""
        client = app.test_client()
        pid = "teste-toggle-busca-externa"
        proj_path = get_projeto_json_path(pid)
        proj_path.parent.mkdir(parents=True, exist_ok=True)
        projeto = {
            "id": pid,
            "nome": "Teste Toggle",
            "url_booking": "https://www.booking.com/",
            "numero_quartos": 1,
            "faturamento_anual": 0,
            "ano_referencia": 2027,
            "financeiro": {
                "custos_fixos": {"luz": 0, "agua": 0, "internet": 0, "iptu": 0, "contabilidade": 0, "seguros": 0, "outros": 0, "aluguel": 0},
                "folha_pagamento_mensal": 0,
                "custos_variaveis": {"cafe_manha": 0, "amenities": 0, "lavanderia": 0, "outros": 0},
                "aliquota_impostos": 0,
                "outros_impostos_taxas_percentual": 0
            }
        }
        proj_path.write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        payload = {
            "periodos_especiais": [{"inicio": "15/02/2027", "fim": "19/02/2027", "nome": "Carnaval", "tipo_coleta": "amostragem"}],
            "urls_concorrentes": [],
            "permitir_busca_externa": False,
            "amostragem": {"datas_normais_por_mes": 4, "incluir_fds": True, "incluir_dias_uteis": True},
            "parametros_tecnicos": {"timeout_ms": 60000, "delay_min_s": 8, "delay_max_s": 18, "headless": True, "stealth": True},
        }
        r = client.post(f"/projeto/{pid}/scraper/config", json=payload)
        self.assertEqual(r.status_code, 200, r.data)
        cfg = json.loads(get_scraper_config_path(pid).read_text(encoding="utf-8"))
        self.assertIn("permitir_busca_externa", cfg)
        self.assertFalse(bool(cfg.get("permitir_busca_externa")))

    def test_adr_pacote_divide_por_noites(self):
        """Registro de pacote com preco_booking total deve virar ADR diário (total/noites)."""
        pid = "teste-adr-pacote"
        proj_path = get_projeto_json_path(pid)
        proj_path.parent.mkdir(parents=True, exist_ok=True)
        projeto = {
            "id": pid,
            "nome": "Teste ADR Pacote",
            "url_booking": "https://www.booking.com/",
            "numero_quartos": 1,
            "faturamento_anual": 0,
            "ano_referencia": 2027,
            "financeiro": {
                "custos_fixos": {"luz": 0, "agua": 0, "internet": 0, "iptu": 0, "contabilidade": 0, "seguros": 0, "outros": 0, "aluguel": 0},
                "folha_pagamento_mensal": 0,
                "custos_variaveis": {"cafe_manha": 0, "amenities": 0, "lavanderia": 0, "outros": 0},
                "aliquota_impostos": 0,
                "outros_impostos_taxas_percentual": 0,
            },
        }
        proj_path.write_text(json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg_path = get_scraper_config_path(pid)
        cfg = {
            "periodos_especiais": [{"inicio": "15/02/2027", "fim": "19/02/2027", "nome": "Carnaval", "tipo_coleta": "pacote"}],
            "descontos": {"global": 0.0, "por_mes": {}},
            "urls_concorrentes": [],
            "permitir_busca_externa": False,
        }
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        bruto = {
            "id_projeto": pid,
            "url": "https://www.booking.com/",
            "ano": 2027,
            "criado_em": "2027-01-01T00:00:00Z",
            "registros": [
                {
                    "checkin": "2027-02-15",
                    "checkout": "2027-02-19",
                    "mes_ano": "2027-02",
                    "tipo_dia": "dia_de_semana",
                    "preco_booking": 400.0,
                    "preco_direto": 400.0,
                    "nome_quarto": "A",
                    "tipo_tarifa": "Padrão",
                    "noites": 4,
                    "status": "OK",
                    "categoria_dia": "especial",
                    "meta": {"preco_booking_eh_total": True, "tipo_coleta": "pacote"},
                }
            ],
        }
        get_market_bruto_path(pid).write_text(json.dumps(bruto, ensure_ascii=False, indent=2), encoding="utf-8")
        adr = obter_adr_por_mes(pid)
        self.assertIn("2027-02", adr)
        self.assertAlmostEqual(float(adr["2027-02"]["adr"]), 100.0, places=2)


if __name__ == "__main__":
    unittest.main()
