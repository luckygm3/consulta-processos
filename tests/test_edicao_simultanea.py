"""Duas pessoas editando ao mesmo tempo: salvar com a versão que a tela leu antes de a outra salvar (o atualizado_em
de quando o diálogo abriu) é recusado, em vez de apagar o que a outra fez. Rodar: python -m unittest discover -s tests -t . -v"""
import itertools
from datetime import datetime, timedelta
from unittest import mock

from fastapi.testclient import TestClient

from app import agenda, auth, checklist, db, financeiro, interligar, main, quadro
from tests.supabase_local import TesteComBanco, claims


class Base(TesteComBanco):
    def setUp(self):
        # db.agora() avança 1 min a cada chamada: na vida real passa tempo entre abrir o diálogo e salvar
        inicio = datetime(2026, 10, 15, 10, 0)
        relogio = mock.patch.object(db, "agora", side_effect=((inicio + timedelta(minutes=i)).isoformat(timespec="seconds")
                                                                for i in itertools.count()))
        relogio.start()
        self.addCleanup(relogio.stop)
        self.con = self.conexao()


def card(con, cid):
    return next(c for c in quadro.carregar(con)["cards"] if c["id"] == cid)


def lancamento(con, lid):
    return next(x for x in financeiro.listar(con) if x["id"] == lid)


class CardTest(Base):
    def setUp(self):
        super().setUp()
        self.cid = quadro.criar(self.con, {"titulo": "Ana", "coluna_id": 1, "tipo": "inicial"})
        self.lido = card(self.con, self.cid)  # o que as duas telas leram ao abrir o card

    def test_quem_salva_depois_com_versao_velha_e_recusada(self):
        quadro.atualizar(self.con, self.cid, {"titulo": "Ana Souza", "versao": self.lido["atualizado_em"]})
        with self.assertRaises(db.Conflito):
            quadro.atualizar(self.con, self.cid, {"titulo": "Ana S.", "checklist": [], "versao": self.lido["atualizado_em"]})
        c = card(self.con, self.cid)
        self.assertEqual(c["titulo"], "Ana Souza")                       # o que a primeira salvou continua
        self.assertEqual(len(c["checklist"]), len(self.lido["checklist"]))

    def test_tarefa_aprovada_no_monitoramento_tambem_conta(self):
        # salvar o card com a checklist lida antes apagaria a tarefa que acabou de entrar
        tid = agenda.criar(self.con, {"titulo": "Contestar", "tipo": "prazo", "prazo_fatal": "2026-10-20"})
        interligar.aprovar(self.con, [tid], self.cid)
        with self.assertRaises(db.Conflito):
            quadro.atualizar(self.con, self.cid, {"checklist": self.lido["checklist"], "versao": self.lido["atualizado_em"]})
        self.assertEqual(card(self.con, self.cid)["checklist"][-1]["origem_id"], tid)

    def test_item_marcado_na_agenda_tambem_conta(self):
        # salvar o card regrava a checklist inteira: com o item marcado por outra, desfaria a marcação
        checklist.marcar(self.con, "card", self.cid, self.lido["checklist"][0]["id"], True)
        with self.assertRaises(db.Conflito):
            quadro.atualizar(self.con, self.cid, {"checklist": self.lido["checklist"], "versao": self.lido["atualizado_em"]})
        self.assertTrue(card(self.con, self.cid)["checklist"][0]["feito"])

    def test_versao_atual_salva_e_muda_a_versao(self):
        self.assertTrue(quadro.atualizar(self.con, self.cid, {"titulo": "Ana Souza", "versao": self.lido["atualizado_em"]}))
        self.assertNotEqual(card(self.con, self.cid)["atualizado_em"], self.lido["atualizado_em"])

    def test_salvar_mesmo_assim_sem_versao(self):
        quadro.atualizar(self.con, self.cid, {"titulo": "Ana Souza", "versao": self.lido["atualizado_em"]})
        quadro.atualizar(self.con, self.cid, {"titulo": "Ana S."})
        self.assertEqual(card(self.con, self.cid)["titulo"], "Ana S.")

    def test_card_sem_data_de_alteracao(self):
        # cards antigos (migrados) podem não ter atualizado_em: a tela manda versao null
        self.con.execute("UPDATE clientes SET atualizado_em=NULL WHERE id=%s", (self.cid,))
        self.assertTrue(quadro.atualizar(self.con, self.cid, {"titulo": "Ana Souza", "versao": None}))
        with self.assertRaises(db.Conflito):
            quadro.atualizar(self.con, self.cid, {"titulo": "Ana S.", "versao": None})

    def test_card_excluido(self):
        self.con.execute("DELETE FROM clientes WHERE id=%s", (self.cid,))
        self.assertFalse(quadro.atualizar(self.con, self.cid, {"titulo": "Ana", "versao": self.lido["atualizado_em"]}))


class TarefaTest(Base):
    def setUp(self):
        super().setUp()
        self.tid = agenda.criar(self.con, {"titulo": "Contestar", "tipo": "prazo", "status": "sugerido"})
        self.lido = agenda.obter(self.con, self.tid)

    def test_quem_salva_depois_com_versao_velha_e_recusada(self):
        agenda.atualizar(self.con, self.tid, {"observacoes": "protocolar até 18h", "versao": self.lido["atualizado_em"]})
        with self.assertRaises(db.Conflito):
            agenda.atualizar(self.con, self.tid, {"observacoes": None, "versao": self.lido["atualizado_em"]})
        self.assertEqual(agenda.obter(self.con, self.tid)["observacoes"], "protocolar até 18h")

    def test_aprovada_em_outra_aba_conta_para_quem_esta_editando(self):
        cid = quadro.criar(self.con, {"titulo": "Ana", "coluna_id": 1, "tipo": "inicial"})
        interligar.aprovar(self.con, [self.tid], cid)  # a outra aprovou (sem versao)
        with self.assertRaises(db.Conflito):
            agenda.atualizar(self.con, self.tid, {"titulo": "Contestar", "versao": self.lido["atualizado_em"]})
        self.assertEqual(agenda.obter(self.con, self.tid)["status"], "aprovado")

    def test_tarefa_inexistente_nao_grava_checklist(self):
        agenda.atualizar(self.con, 999, {"checklist": [{"texto": "x"}], "versao": None})
        self.assertIsNone(agenda.obter(self.con, 999))


class LancamentoTest(Base):
    DADOS = {"cliente": "Maria da Silva", "valor_total": 200000, "entrada": 0, "valor_parcela": 100000,
             "qtd_parcelas": 2, "primeiro_vencimento": "2026-11-10"}

    def setUp(self):
        super().setUp()
        self.lid = financeiro.salvar(self.con, dict(self.DADOS))
        self.lido = lancamento(self.con, self.lid)
        # o que o diálogo manda ao salvar: as parcelas como estavam quando abriu (sem o pagamento lançado depois)
        self.tela = {**self.DADOS, "observacoes": "acordo verbal", "parcelas": [
            {"numero": p["numero"], "vencimento": p["vencimento"], "valor": p["valor"], "pagamentos": []}
            for p in self.lido["parcelas"]]}

    def test_pagamento_lancado_pela_tabela_nao_se_perde(self):
        financeiro.adicionar_pagamento(self.con, self.lido["parcelas"][0]["id"], {"valor": 50000, "data": "2026-10-15"})
        with self.assertRaises(db.Conflito):
            financeiro.salvar(self.con, {**self.tela, "versao": self.lido["atualizado_em"]}, self.lid)
        self.assertEqual(lancamento(self.con, self.lid)["recebido"], 50000)

    def test_versao_atual_salva(self):
        financeiro.salvar(self.con, {**self.tela, "versao": self.lido["atualizado_em"]}, self.lid)
        self.assertEqual(lancamento(self.con, self.lid)["observacoes"], "acordo verbal")


class RotaTest(Base):
    """Pela API, como a tela chama: 409 quando outra pessoa salvou antes."""

    def setUp(self):
        super().setUp()
        for alvo in (mock.patch.object(auth, "conferir", mock.AsyncMock(return_value=claims())),
                     mock.patch.object(db, "conexao", side_effect=lambda: _Contexto(self.con))):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.api = TestClient(main.app, headers={"Authorization": "Bearer teste"})
        self.cid = quadro.criar(self.con, {"titulo": "Ana", "coluna_id": 1, "tipo": "inicial"})
        self.versao = card(self.con, self.cid)["atualizado_em"]

    def test_409_com_versao_velha(self):
        url = f"/api/quadro/cards/{self.cid}"
        self.assertEqual(self.api.patch(url, json={"titulo": "Ana Souza", "versao": self.versao}).status_code, 200)
        r = self.api.patch(url, json={"titulo": "Ana S.", "versao": self.versao})
        self.assertEqual(r.status_code, 409)
        self.assertIn("outra pessoa", r.json()["detail"])
        self.assertEqual(self.api.patch(url, json={"titulo": "Ana S."}).status_code, 200)  # salvar mesmo assim
        self.assertEqual(card(self.con, self.cid)["titulo"], "Ana S.")

    def test_404_continua_404(self):
        self.assertEqual(self.api.patch("/api/quadro/cards/999", json={"titulo": "X", "versao": None}).status_code, 404)


class _Contexto:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *erro):
        return False
