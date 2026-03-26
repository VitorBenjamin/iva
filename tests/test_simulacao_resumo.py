"""Resumo da projeção: dupla visão operação × capital."""

import unittest

from core.analise.simulacao import calcular_projecao, construir_metas_para_projecao


class TestSimulacaoResumo(unittest.TestCase):
    def test_despesa_fixos_operacionais_igual_12_vezes_custos_fixos_mes(self):
        pid = "village-arraial"
        metas = construir_metas_para_projecao(pid)
        r = calcular_projecao(pid, metas)
        if r.get("erro"):
            self.skipTest("projeto de teste indisponível: " + str(r.get("erro")))
        self.assertIn("resumo", r)
        res = r["resumo"]
        self.assertIn("despesa_fixos_operacionais_anual", res)
        meses = r["meses"]
        self.assertEqual(len(meses), 12)
        cf = meses[0]["custos_fixos"]
        esperado = 12.0 * float(cf)
        self.assertAlmostEqual(float(res["despesa_fixos_operacionais_anual"]), esperado, places=1)
        self.assertIn("ocupacao_meta", meses[0])

    def test_soma_componentes_sem_arrendamento_na_despesa_fixa(self):
        pid = "village-arraial"
        metas = construir_metas_para_projecao(pid)
        r = calcular_projecao(pid, metas)
        if r.get("erro"):
            self.skipTest("projeto de teste indisponível")
        res = r["resumo"]
        op = float(res.get("custo_fixo_operacional_anual") or 0)
        fol = float(res.get("folha_anual") or 0)
        total = float(res.get("despesa_fixos_operacionais_anual") or 0)
        self.assertAlmostEqual(op + fol, total, places=1)

    def test_resultado_investidor_e_desembolso(self):
        pid = "village-arraial"
        metas = construir_metas_para_projecao(pid)
        r = calcular_projecao(pid, metas)
        if r.get("erro"):
            self.skipTest("projeto de teste indisponível")
        res = r["resumo"]
        luc = float(res.get("lucro_operacional_anual") or res.get("lucro_anual") or 0)
        arr = float(res.get("arrendamento_total") or 0)
        ref = float(res.get("investimento_reforma") or 0)
        ri = float(res.get("resultado_investidor_ano1") or 0)
        self.assertAlmostEqual(ri, luc - arr - ref, places=1)
        des = float(res.get("desembolso_total_ano1") or 0)
        imp = float(res.get("impostos_anuais") or 0)
        cv = float(res.get("custos_variaveis_anuais") or 0)
        dfo = float(res.get("despesa_fixos_operacionais_anual") or 0)
        self.assertAlmostEqual(des, dfo + cv + imp + arr + ref, places=1)

    def test_margem_investidor_pct_e_roi_coerentes_com_resumo(self):
        pid = "village-arraial"
        metas = construir_metas_para_projecao(pid)
        r = calcular_projecao(pid, metas)
        if r.get("erro"):
            self.skipTest("projeto de teste indisponível")
        res = r["resumo"]
        rec = float(res.get("receita_anual") or 0)
        ri = float(res.get("resultado_investidor_ano1") or 0)
        inv = float(res.get("investimento_total") or 0)
        if rec > 0:
            esperado_m = (ri / rec) * 100.0
            self.assertAlmostEqual(float(res["margem_investidor_pct"]), esperado_m, places=1)
        if inv > 0:
            esperado_roi = (ri / inv) * 100.0
            self.assertAlmostEqual(float(res["roi_anual_pct"]), esperado_roi, places=1)

    def test_plurianual_presente_e_saldo_final(self):
        pid = "village-arraial"
        metas = construir_metas_para_projecao(pid)
        r = calcular_projecao(pid, metas, prazo_contrato_meses=24)
        if r.get("erro"):
            self.skipTest("projeto de teste indisponível")
        self.assertIn("plurianual", r)
        pl = r["plurianual"]
        self.assertEqual(pl["horizonte_meses"], 24)
        self.assertEqual(len(pl["meses"]), 24)
        lucros = [float(m["lucro_liquido"]) for m in r["meses"]]
        esperado_m13 = lucros[0]
        self.assertAlmostEqual(float(pl["meses"][12]["lucro_operacional_mes"]), esperado_m13, places=1)
        saldo_esperado = sum(lucros) * 2.0
        self.assertAlmostEqual(float(pl["lucro_final_contrato"]), saldo_esperado, places=0)


if __name__ == "__main__":
    unittest.main()
