"""Testes do financeiro e dos aniversários. Rodar: python -m unittest discover -s tests -t . -v"""
import sqlite3
import unittest
from datetime import date

from app import db, financeiro, quadro

HOJE = date(2026, 10, 13)


def banco():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    db.semear_quadro(con)
    return con


def lancamento(con, **extra):
    """R$ 5.000 = entrada R$ 1.000 (paga em 10/09) + 4 x R$ 1.000 a partir de 10/09 (venceram 10/09 e 10/10)."""
    dados = {"cliente": "Maria da Silva", "valor_total": 500000, "entrada": 100000, "entrada_data": "2026-09-10",
             "valor_parcela": 100000, "qtd_parcelas": 4, "primeiro_vencimento": "2026-09-10", **extra}
    lid = financeiro.salvar(con, dados)
    return next(l for l in financeiro.listar(con, HOJE) if l["id"] == lid)


class VencimentosTest(unittest.TestCase):
    def test_um_por_mes_a_partir_do_primeiro(self):
        self.assertEqual(financeiro.gerar_vencimentos(date(2026, 10, 15), 3),
                         [date(2026, 10, 15), date(2026, 11, 15), date(2026, 12, 15)])

    def test_fim_de_mes_nao_escorrega(self):
        # 31/01 -> 28/02 (não existe 31/02) -> volta a 31/03; ano bissexto -> 29/02
        self.assertEqual(financeiro.gerar_vencimentos(date(2027, 1, 31), 3),
                         [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)])
        self.assertEqual(financeiro.gerar_vencimentos(date(2028, 1, 31), 2)[1], date(2028, 2, 29))

    def test_virada_de_ano(self):
        self.assertEqual(financeiro.gerar_vencimentos(date(2026, 11, 5), 3)[2], date(2027, 1, 5))


class LancamentoTest(unittest.TestCase):
    def test_gera_entrada_e_parcelas(self):
        con = banco()
        l = lancamento(con)
        self.assertEqual([(p["rotulo"], p["vencimento"], p["valor"]) for p in l["parcelas"]], [
            ("Entrada", "2026-09-10", 100000), ("1/4", "2026-09-10", 100000), ("2/4", "2026-10-10", 100000),
            ("3/4", "2026-11-10", 100000), ("4/4", "2026-12-10", 100000)])
        self.assertEqual(l["diferenca"], 0)
        self.assertEqual((l["recebido"], l["falta"]), (0, 500000))

    def test_conferencia_quando_nao_bate(self):
        con = banco()
        l = lancamento(con, valor_parcela=90000)  # 1.000 + 4 x 900 = 4.600; faltam R$ 400 para 5.000
        self.assertEqual(l["diferenca"], 40000)

    def test_marcar_paga_recalcula_saldo(self):
        con = banco()
        l = lancamento(con)
        entrada, p1 = l["parcelas"][0], l["parcelas"][1]
        financeiro.marcar_paga(con, entrada["id"], True, "2026-09-10")
        financeiro.marcar_paga(con, p1["id"], True, hoje=HOJE)  # sem data: hoje
        l = financeiro.listar(con, HOJE)[0]
        self.assertEqual((l["recebido"], l["falta"]), (200000, 300000))
        self.assertEqual(l["parcelas"][1]["pago_em"], "2026-10-13")
        financeiro.marcar_paga(con, p1["id"], False)
        self.assertEqual(financeiro.listar(con, HOJE)[0]["falta"], 400000)

    def test_vencimentos_editados_e_validacao(self):
        con = banco()
        base = {"cliente": "João", "valor_total": 30000, "entrada": 0, "valor_parcela": 10000, "qtd_parcelas": 3}
        lid = financeiro.salvar(con, {**base, "parcelas": [
            {"numero": 1, "vencimento": "2026-10-20", "valor": 10000},
            {"numero": 2, "vencimento": "2026-11-25", "valor": 10000},  # data mudada à mão
            {"numero": 3, "vencimento": "2026-12-20", "valor": 10000}]})
        self.assertEqual(financeiro.listar(con)[0]["parcelas"][1]["vencimento"], "2026-11-25")
        with self.assertRaisesRegex(ValueError, "falta o vencimento"):
            financeiro.salvar(con, {**base, "parcelas": [{"numero": 1, "vencimento": "2026-10-20", "valor": 10000}]}, lid)
        with self.assertRaisesRegex(ValueError, "cliente"):
            financeiro.salvar(con, {**base, "cliente": "  ", "primeiro_vencimento": "2026-10-20"})
        with self.assertRaisesRegex(ValueError, "entrada"):
            financeiro.salvar(con, {**base, "entrada": 5000, "primeiro_vencimento": "2026-10-20"})  # entrada sem data


class PainelTest(unittest.TestCase):
    def test_resumo_do_mes_inadimplentes_e_proximas(self):
        con = banco()
        l = lancamento(con)
        financeiro.marcar_paga(con, l["parcelas"][0]["id"], True, "2026-09-10")  # entrada paga em setembro
        financeiro.marcar_paga(con, l["parcelas"][2]["id"], True, "2026-10-11")  # 2/4 (venc. 10/10) paga em outubro
        financeiro.salvar(con, {"cliente": "Empresa Y", "valor_total": 20000, "valor_parcela": 20000, "qtd_parcelas": 1,
                                "primeiro_vencimento": "2026-10-20"})
        lancs = financeiro.listar(con, HOJE)
        r = financeiro.resumo(lancs, "2026-10", HOJE)
        # outubro: 2/4 de Maria (paga) + parcela única da Empresa Y (pendente)
        self.assertEqual(r["a_receber_mes"], {"pendente": 20000, "pago": 100000, "previsto": 120000, "qtd_pendente": 1})
        self.assertEqual((r["recebido_mes"], r["recebido_ano"]), (100000, 200000))
        self.assertEqual(r["total_a_receber"], 320000)  # 1/4, 3/4, 4/4 de Maria + Empresa Y
        # 1/4 de Maria venceu em 10/09 e não foi paga: 33 dias de atraso em 13/10
        self.assertEqual(r["inadimplentes"], [{"cliente": "Maria da Silva", "valor": 100000, "parcelas": 1,
                                               "dias_atraso": 33, "desde": "2026-09-10", "lancamentos": [l["id"]]}])
        self.assertEqual([(p["cliente"], p["vencimento"]) for p in r["proximas"]],
                         [("Empresa Y", "2026-10-20"), ("Maria da Silva", "2026-11-10"), ("Maria da Silva", "2026-12-10")])

    def test_lembrete_um_dia_depois_do_vencimento(self):
        con = banco()
        lancamento(con)
        lembretes = financeiro.lembretes(financeiro.listar(con, HOJE), "2026-10-01", "2026-10-31")
        self.assertEqual([(p["rotulo"], p["vencimento"], p["data"]) for p in lembretes], [("2/4", "2026-10-10", "2026-10-11")])


class AniversarioTest(unittest.TestCase):
    def test_todo_ano_e_feito_por_ano(self):
        con = banco()
        cid = quadro.criar(con, {"coluna_id": 1, "titulo": "Ana", "tipo": "preventivo", "aniversario": "1980-02-29"})
        anivs = quadro.aniversarios(con, "2026-01-01", "2028-12-31")
        self.assertEqual([a["data"] for a in anivs], ["2026-02-28", "2027-02-28", "2028-02-29"])  # 29/02 só em ano bissexto
        quadro.marcar_lembrete(con, f"aniv:{cid}:2027", True)
        self.assertEqual([a["feito"] for a in quadro.aniversarios(con, "2026-01-01", "2028-12-31")], [False, True, False])
        with self.assertRaises(ValueError):
            quadro.atualizar(con, cid, {"aniversario": "1980-13-01"})


if __name__ == "__main__":
    unittest.main()
