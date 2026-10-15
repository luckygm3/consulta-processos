"""Testes da checklist com data/horário/responsável, fonte única (agenda e card) e modelos padrão.
Rodar: python -m unittest discover -s tests -t . -v"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import agenda, checklist, config, quadro
from tests.supabase_local import TesteComBanco


class Base(TesteComBanco):
    def banco(self):
        return self.conexao()


class NormalizarTest(unittest.TestCase):
    def test_campos(self):
        itens = checklist.normalizar([
            "Reunião de Briefing",                                                      # texto solto (arquivo padrão)
            {"texto": " Protocolo ", "data": "2026-10-20", "hora": "09:30", "resp": "a:1", "feito": 1},
            {"texto": "Hora sem data", "hora": "10:00"},                                # horário só com data
            {"texto": "Lixo", "data": "20/10/2026", "hora": "25:00", "resp": "admin"},  # inválidos viram vazio
            {"texto": "   "},                                                           # sem texto: sai
        ])
        self.assertEqual([c["texto"] for c in itens], ["Reunião de Briefing", "Protocolo", "Hora sem data", "Lixo"])
        self.assertEqual({k: itens[1][k] for k in ("feito", "data", "hora", "resp")},
                         {"feito": True, "data": "2026-10-20", "hora": "09:30", "resp": "a:1"})
        self.assertEqual((itens[2]["data"], itens[2]["hora"]), (None, None))
        self.assertEqual((itens[3]["data"], itens[3]["hora"], itens[3]["resp"]), (None, None, None))
        self.assertEqual(len({c["id"] for c in itens}), 4)  # todos com id, sem repetir

    def test_mantem_id_e_troca_repetido(self):
        itens = checklist.normalizar([{"id": "abc", "texto": "A"}, {"id": "abc", "texto": "B"}])
        self.assertEqual(itens[0]["id"], "abc")
        self.assertNotEqual(itens[1]["id"], "abc")

    def test_origem_do_monitoramento(self):
        itens = checklist.normalizar([{"texto": "A", "origem_id": 12}, {"texto": "B", "origem_id": "13"},
                                      {"texto": "C", "origem_id": True}, {"texto": "D", "origem_id": "x"}, {"texto": "E"}])
        self.assertEqual([c["origem_id"] for c in itens], [12, 13, None, None, None])


class FonteUnicaTest(Base):
    """Marcar como feito (na agenda ou no card) grava no mesmo item, na própria demanda."""

    def test_marcar_em_tarefa_e_em_card(self):
        con = self.banco()
        lista = [{"id": "x1", "texto": "Elaboração do Mérito", "data": "2026-10-12"}, {"id": "x2", "texto": "Revisão"}]
        tid = agenda.criar(con, {"titulo": "Contestação", "checklist": lista})
        cid = quadro.criar(con, {"titulo": "Fulano", "coluna_id": 1, "tipo": "inicial", "checklist": lista})
        self.assertTrue(checklist.marcar(con, "tarefa", tid, "x1", True))
        self.assertTrue(checklist.marcar(con, "card", cid, "x2", True))
        t = agenda.obter(con, tid)
        c = quadro.carregar(con)["cards"][0]
        self.assertEqual([i["feito"] for i in t["checklist"]], [True, False])
        self.assertEqual([i["feito"] for i in c["checklist"]], [False, True])
        self.assertFalse(checklist.marcar(con, "card", cid, "nao-existe", True))
        with self.assertRaises(ValueError):
            checklist.marcar(con, "processo", 1, "x1", True)


class ModelosTest(unittest.TestCase):
    def test_arquivo_do_projeto(self):
        m = config.checklists_padrao()
        self.assertEqual((len(m["processo"]), m["processo"][0], m["processo"][-1]),
                         (17, "Reunião de Briefing", "Sentença (informado pelo juízo)"))
        self.assertEqual((len(m["preventivo"]), m["preventivo"][3], m["preventivo"][-1]),
                         (9, "Pesquisa de Legislação e Jurisprudência", "Encerramento"))

    def test_secoes(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "c.txt"
            arq.write_text("# comentário\nSolto\n[processo]\nA\n\n[Preventivo]\nB\n", encoding="utf-8-sig")
            with mock.patch.object(config, "CHECKLIST_PATH", arq):
                self.assertEqual(config.checklists_padrao(), {"processo": ["Solto", "A"], "preventivo": ["B"]})


class PessoasTest(Base):
    def test_equipe(self):
        con = self.banco()
        advs = [{"nome": "Beatriz Daffara", "oab_numero": "1", "oab_uf": "PR", "cor": "#111", "id": 1}]
        with mock.patch.object(checklist.db, "advogadas", lambda con: advs):
            pid = checklist.adicionar_pessoa(con, "  Ana Estagiária ")
            self.assertEqual([(p["chave"], p["nome"]) for p in checklist.pessoas(con)],
                             [("a:1", "Beatriz"), (f"p:{pid}", "Ana Estagiária")])
            checklist.remover_pessoa(con, pid)  # só desativa: itens antigos ainda acham o nome
            self.assertFalse(checklist.pessoas(con)[1]["ativo"])
            with self.assertRaises(ValueError):
                checklist.adicionar_pessoa(con, " ")


class TipoPrazoTest(unittest.TestCase):
    def test_processual_ou_interno(self):
        self.assertEqual(agenda.tipo_prazo("djen", None), "processual")
        self.assertEqual(agenda.tipo_prazo("manual", {"vencimento": "2026-10-20"}), "processual")  # "Calcular prazo"
        self.assertEqual(agenda.tipo_prazo("manual", None), "interno")


if __name__ == "__main__":
    unittest.main()
