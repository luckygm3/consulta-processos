"""Testes do quadro de clientes. Rodar: python -m unittest discover -s tests -v"""
import json
import sqlite3
import unittest
from datetime import date
from unittest import mock

from app import agenda, db, quadro

CADASTRADO = "00064937120268160030"   # número CNJ válido, já na lista de processos
OUTRO = "00074819220268160030"        # número CNJ válido, ainda não cadastrado


def banco():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    con.execute("ALTER TABLE processos ADD COLUMN contagem TEXT")  # coluna que a migração v3 cria
    db.semear_quadro(con)
    con.execute("INSERT INTO processos(numero, partes) VALUES(?, ?)",
                (CADASTRADO, json.dumps({"ativo": ["Maria"], "passivo": ["Empresa X", "Empresa Y"]})))
    return con


def cards(con, coluna=None):
    d = quadro.carregar(con)["cards"]
    return [c for c in d if coluna is None or c["coluna_id"] == coluna]


class QuadroTest(unittest.TestCase):
    def test_cinco_colunas_sem_nome(self):
        con = banco()
        db.semear_quadro(con)  # rodar de novo não duplica
        self.assertEqual([(c["id"], c["nome"]) for c in quadro.carregar(con)["colunas"]], [(i, "") for i in range(1, 6)])
        quadro.renomear_coluna(con, 2, "  Pro bono ")
        self.assertEqual(quadro.carregar(con)["colunas"][1]["nome"], "Pro bono")

    def test_tipos_e_processo(self):
        con = banco()
        with self.assertRaisesRegex(ValueError, "Escolha o processo"):
            quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "tipo": "processo"})
        with self.assertRaisesRegex(ValueError, "inválido"):
            quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "numero": "0006493-71.2026.8.16.0031"})
        with self.assertRaisesRegex(ValueError, "Coluna"):
            quadro.criar(con, {"titulo": "Ana", "coluna_id": 9, "tipo": "inicial"})
        a = quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "numero": "0006493-71.2026.8.16.0030"})
        b = quadro.criar(con, {"titulo": "Bruno", "coluna_id": 1, "tipo": "inicial", "numero": OUTRO})
        c = {x["id"]: x for x in cards(con)}
        self.assertEqual((c[a]["numero"], c[a]["cadastrado"], c[a]["partes"]), (CADASTRADO, True, "Maria × Empresa X e outros"))
        self.assertEqual((c[b]["tipo"], c[b]["numero"]), ("inicial", None))  # petição inicial fica sem processo
        # virou processo depois: vincula (mesmo um número que ainda não está na lista de processos)
        quadro.atualizar(con, b, {"tipo": "processo", "numero": OUTRO})
        c = {x["id"]: x for x in cards(con)}
        self.assertEqual((c[b]["numero"], c[b]["cadastrado"]), (OUTRO, False))

    def test_arrastar_entre_colunas_e_reordenar(self):
        con = banco()
        a, b, c = (quadro.criar(con, {"titulo": t, "coluna_id": 1, "tipo": "preventivo"}) for t in "ABC")
        self.assertEqual([x["titulo"] for x in cards(con, 1)], ["A", "B", "C"])  # novos entram no fim
        quadro.ordenar(con, 1, [c, a, b])
        self.assertEqual([x["titulo"] for x in cards(con, 1)], ["C", "A", "B"])
        quadro.ordenar(con, 3, [a])
        self.assertEqual(([x["titulo"] for x in cards(con, 1)], [x["titulo"] for x in cards(con, 3)]), (["C", "B"], ["A"]))

    def test_checklist_guardada(self):
        con = banco()
        lista = [{"id": "a1", "texto": "Reunião de Briefing", "feito": True, "data": "2026-10-20", "hora": "14:00", "resp": "a:1"},
                 {"id": "b2", "texto": "Solicitar Documentos", "feito": False, "data": None, "hora": None, "resp": None}]
        cid = quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "tipo": "inicial", "checklist": lista})
        self.assertEqual(cards(con)[0]["checklist"], lista)
        quadro.atualizar(con, cid, {"checklist": lista[::-1]})
        self.assertEqual(cards(con)[0]["checklist"], lista[::-1])

    def test_checklist_padrao_pelo_tipo(self):
        con = banco()
        modelos = {"processo": ["Reunião de Briefing", "Sentença"], "preventivo": ["Parecer", "Encerramento"]}
        with mock.patch.object(quadro.checklist.config, "checklist_padrao", lambda m="processo": modelos[m]):
            for tipo, esperado in (("inicial", modelos["processo"]), ("preventivo", modelos["preventivo"])):
                quadro.criar(con, {"titulo": tipo, "coluna_id": 1, "tipo": tipo})
                c = next(x for x in cards(con) if x["titulo"] == tipo)
                self.assertEqual([i["texto"] for i in c["checklist"]], esperado)
                self.assertTrue(all(i["id"] for i in c["checklist"]))


class PrazoFatalTest(unittest.TestCase):
    HOJE = date(2026, 10, 7)

    def prazo(self, con, titulo):
        return next(c for c in quadro.carregar(con, self.HOJE)["cards"] if c["titulo"] == titulo)["prazo"]

    def test_interno_so_sem_processo(self):
        con = banco()
        cid = quadro.criar(con, {"titulo": "Bruno", "coluna_id": 1, "tipo": "preventivo", "prazo_descricao": "Entregar parecer",
                                 "prazo_data": "2026-10-09", "prazo_hora": "18:00"})
        p = self.prazo(con, "Bruno")
        self.assertEqual((p["tipo"], p["descricao"], p["data"], p["hora"]), ("interno", "Entregar parecer", "2026-10-09", "18:00"))
        self.assertEqual(p["urgencia"], "ate5")
        # virou processo: o prazo interno sai (passa a valer o processual, que vem da agenda)
        quadro.atualizar(con, cid, {"tipo": "processo", "numero": CADASTRADO, "prazo_data": "2026-10-09"})
        self.assertIsNone(self.prazo(con, "Bruno"))
        with self.assertRaises(ValueError):
            quadro.criar(con, {"titulo": "X", "coluna_id": 1, "tipo": "inicial", "prazo_data": "2026-13-01"})

    def test_processual_vem_da_agenda(self):
        con = banco()
        quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "numero": CADASTRADO})
        self.assertIsNone(self.prazo(con, "Ana"))
        nova = lambda titulo, data, status="a_fazer": agenda.criar(con, {  # noqa: E731
            "titulo": titulo, "tipo": "prazo", "status": status, "numero": CADASTRADO, "prazo_fatal": data})
        nova("Sugestão velha", "2026-09-01", "sugerido")       # sugestão vencida: não conta
        self.assertIsNone(self.prazo(con, "Ana"))
        nova("Réplica", "2026-09-20")                          # vencido em aberto: vale enquanto não houver futuro
        self.assertEqual(self.prazo(con, "Ana")["descricao"], "Réplica")
        nova("Contestação", "2026-10-20")
        nova("Apelação", "2026-11-20")
        p = self.prazo(con, "Ana")
        self.assertEqual((p["tipo"], p["descricao"], p["data"]), ("processual", "Contestação", "2026-10-20"))
        self.assertEqual(quadro.prazos_processuais(con, self.HOJE)[CADASTRADO]["descricao"], "Contestação")


if __name__ == "__main__":
    unittest.main()
