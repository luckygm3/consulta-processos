"""Testes da detecção de prazos no texto (regex/palavras-chave)."""
import unittest

from app.extrair import TIPOS_PADRAO, analisar, numero

TIPOS = [dict(zip(("nome", "palavras", "dias", "contagem", "justica"), t)) for t in TIPOS_PADRAO]


def a(texto, tribunal="TJPR"):
    return analisar(texto, TIPOS, tribunal)


class NumeroTest(unittest.TestCase):
    def test_extenso(self):
        self.assertEqual(numero("quinze"), 15)
        self.assertEqual(numero("vinte e cinco"), 25)
        self.assertEqual(numero("quarenta e oito"), 48)
        self.assertEqual(numero("05"), 5)


class AnalisarTest(unittest.TestCase):
    def test_prazo_por_extenso_com_numero_entre_parenteses(self):
        r = a("Intime-se a parte autora para, no prazo de quinze (15) dias, emendar a inicial, sob pena de indeferimento.")
        self.assertEqual(r["dias"], 15)
        self.assertEqual(r["confianca"], "alta")
        self.assertEqual(r["tipo"], "Emenda à inicial")
        self.assertIn("quinze (15) dias", r["trecho"])

    def test_numero_seguido_de_extenso(self):
        r = a("Manifeste-se o réu em 10 (dez) dias sobre os documentos juntados.")
        self.assertEqual(r["dias"], 10)
        self.assertEqual(r["tipo"], "Manifestação")

    def test_dias_uteis_e_corridos_explicitos(self):
        self.assertEqual(a("Prazo de 5 dias úteis para pagar as custas.")["contagem"], "uteis")
        self.assertEqual(a("Cumpra-se no prazo de 30 dias corridos.")["contagem"], "corridos")

    def test_horas(self):
        r = a("Intime-se a parte para que se manifeste em 48 (quarenta e oito) horas.")
        self.assertEqual(r["horas"], 48)
        self.assertEqual(r["dias"], 2)
        self.assertEqual(r["contagem"], "corridos")

    def test_sem_numero_usa_tabela_e_pede_conferencia(self):
        r = a("Intime-se a parte ré para contestar, querendo.")
        self.assertEqual(r["tipo"], "Contestação")
        self.assertEqual(r["dias"], 15)
        self.assertEqual(r["confianca"], "baixa")
        self.assertTrue(any("Conferir manualmente" in x for x in r["avisos"]))

    def test_embargos_de_declaracao(self):
        r = a("Intimem-se as partes para, querendo, opor embargos de declaração.")
        self.assertEqual((r["tipo"], r["dias"]), ("Embargos de declaração", 5))

    def test_trabalhista_usa_8_dias_no_recurso(self):
        r = a("Isto posto, julgo procedente em parte o pedido. A reclamada anotará a CTPS no prazo de dez dias.", "TRT9")
        self.assertEqual(r["dias"], 8)
        self.assertEqual(r["tipo"], "Recurso ordinário (sentença)")

    def test_nao_e_prazo(self):
        self.assertIsNone(a("Pauta de julgamento. Pedidos de sustentação até 48 (quarenta e oito) horas antes da sessão."))
        self.assertIsNone(a("Condeno o réu a 30 dias-multa."))
        self.assertIsNone(a("Agravo de Instrumento; Comarca: Curitiba; Vara: 1ª Vara Cível."))
        # caso real (pauta de Turma Recursal): "-se" genérico não é ordem à parte
        self.assertIsNone(a("A Sustentação Oral deve observar o art. 714, admitindo-se a sustentação oral "
                            "exclusivamente no Recurso Inominado, por advogado constituído."))

    def test_audiencia(self):
        r = a("Designo audiência de instrução para o dia 02.09.2026, às 10h, devendo as partes comparecer.")
        self.assertEqual(r["audiencia"]["data"], "2026-09-02")
        self.assertEqual(r["audiencia"]["hora"], "10:00")

    def test_audiencia_com_instrucoes_nao_gera_prazo_generico(self):
        # caso real (TRT12): "para data de" e instruções às partes, sem número de dias para a parte
        r = a("Designa-se audiência telepresencial para data de 15/05/2028 às 15h. As partes deverão convidar "
              "diretamente as testemunhas. Deverão ter em mãos nome completo e CPF para informar via chat.", "TRT12")
        self.assertEqual((r["audiencia"]["data"], r["audiencia"]["hora"]), ("2028-05-15", "15:00"))
        self.assertIsNone(r["dias"])


if __name__ == "__main__":
    unittest.main()
