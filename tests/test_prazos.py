"""Testes do cálculo de prazos. Rodar: python -m unittest discover -s tests -v"""
import unittest
from datetime import date

from app import prazos
from app.prazos import Calendario, calcular, pascoa, urgencia


def calendario(tribunal="TJPR", orgao="", extras=()):
    regs = [r for ano in (2025, 2026, 2027) for r in prazos.feriados_padrao(ano)] + list(extras)
    return Calendario(regs, tribunal, orgao)


class PascoaTest(unittest.TestCase):
    def test_datas_conhecidas(self):
        self.assertEqual(pascoa(2025), date(2025, 4, 20))
        self.assertEqual(pascoa(2026), date(2026, 4, 5))
        self.assertEqual(pascoa(2027), date(2027, 3, 28))

    def test_feriados_moveis_2026(self):
        cal = calendario()
        self.assertEqual(cal.motivo(date(2026, 4, 3)), "Sexta-feira Santa (Paixão de Cristo)")
        self.assertIn("Corpus Christi", cal.motivo(date(2026, 6, 4)))
        self.assertIn("Carnaval", cal.motivo(date(2026, 2, 17)))


class CalculoTest(unittest.TestCase):
    def test_disponibilizacao_na_sexta(self):
        # sex 02/10 -> publicação seg 05/10 -> início ter 06/10; 12/10 (feriado) é pulado
        self.assertEqual(date(2026, 10, 2).weekday(), 4)
        r = calcular(date(2026, 10, 2), 15, calendario())
        self.assertEqual(r["publicacao"], "2026-10-05")
        self.assertEqual(r["inicio"], "2026-10-06")
        self.assertEqual(r["vencimento"], "2026-10-27")
        self.assertIn("2026-10-12", [p["data"] for p in r["pulados"]])
        self.assertEqual(r["interno"], "2026-10-23")  # 2 dias úteis antes (seg 26 e sex 23)

    def test_vespera_de_feriado(self):
        # qui 19/11 -> sex 20/11 é feriado (Consciência Negra) -> publicação seg 23/11, início ter 24/11
        r = calcular(date(2026, 11, 19), 5, calendario())
        self.assertEqual(r["publicacao"], "2026-11-23")
        self.assertEqual(r["inicio"], "2026-11-24")
        self.assertEqual(r["vencimento"], "2026-11-30")

    def test_prazo_cruzando_recesso(self):
        # início seg 14/12; 5 dias até 18/12; recesso 20/12-20/01 suspende; volta 21/01; carnaval 2027 é 08-09/02
        r = calcular(date(2026, 12, 10), 15, calendario())
        self.assertEqual(r["inicio"], "2026-12-14")
        self.assertEqual(r["vencimento"], "2027-02-03")
        self.assertTrue(any("Recesso" in p["motivo"] for p in r["pulados"]))

    def test_disponibilizacao_durante_recesso(self):
        # publicação não é empurrada pelo recesso; a contagem só começa em 21/01
        r = calcular(date(2026, 12, 22), 5, calendario())
        self.assertEqual(r["publicacao"], "2026-12-23")
        self.assertEqual(r["inicio"], "2027-01-21")
        self.assertEqual(r["vencimento"], "2027-01-27")

    def test_uteis_x_corridos(self):
        cal = calendario()
        self.assertEqual(calcular(date(2026, 10, 5), 10, cal, "uteis")["vencimento"], "2026-10-21")
        self.assertEqual(calcular(date(2026, 10, 5), 10, cal, "corridos")["vencimento"], "2026-10-16")

    def test_corridos_terminando_em_dia_nao_util_prorroga(self):
        # início qua 07/10; 5 corridos = dom 11/10 -> seg 12/10 é feriado -> ter 13/10
        r = calcular(date(2026, 10, 5), 5, calendario(), "corridos")
        self.assertEqual(r["vencimento"], "2026-10-13")

    def test_vencimento_em_expediente_reduzido_prorroga(self):
        # 5 dias úteis terminariam na quarta-feira de cinzas (10/02/2027) -> qui 11/02
        r = calcular(date(2027, 1, 29), 5, calendario())
        self.assertEqual(r["inicio"], "2027-02-02")
        self.assertEqual(r["vencimento"], "2027-02-11")

    def test_regra_publicacao_no_proprio_dia(self):
        r = calcular(date(2026, 10, 5), 5, calendario(), regra_publicacao="disponibilizacao")
        self.assertEqual(r["publicacao"], "2026-10-05")
        self.assertEqual(r["inicio"], "2026-10-06")

    def test_feriado_estadual_so_no_tribunal_do_estado(self):
        dia = date(2025, 12, 19)  # sexta: Emancipação do Paraná
        self.assertFalse(calendario("TJPR").util(dia))
        self.assertTrue(calendario("TJSP").util(dia))

    def test_feriado_municipal_por_comarca(self):
        municipal = {"inicio": "06-10", "fim": None, "descricao": "Aniversário de Foz do Iguaçu", "tipo": "feriado",
                     "tribunais": "TJPR", "comarca": "Foz do Iguaçu", "recorrente": 1}
        dia = date(2026, 6, 10)
        self.assertFalse(calendario("TJPR", "FOZ DO IGUAÇU - 2ª VARA CÍVEL", [municipal]).util(dia))
        self.assertTrue(calendario("TJPR", "CURITIBA - 1ª VARA CÍVEL", [municipal]).util(dia))


class UrgenciaTest(unittest.TestCase):
    def test_faixas(self):
        cal = calendario()
        sexta = date(2026, 10, 16)
        self.assertEqual(urgencia("2026-10-15", cal, sexta)[0], "vencido")
        self.assertEqual(urgencia("2026-10-16", cal, sexta)[0], "hoje")
        self.assertEqual(urgencia("2026-10-19", cal, sexta)[0], "amanha")  # segunda = próximo dia útil
        self.assertEqual(urgencia("2026-10-23", cal, sexta)[0], "ate5")
        self.assertEqual(urgencia("2026-11-20", cal, sexta)[0], "folgado")


if __name__ == "__main__":
    unittest.main()
