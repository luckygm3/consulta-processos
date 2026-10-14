"""Testes dos processos em cooperação. Rodar: python -m unittest discover -s tests -t . -v"""
import sqlite3
import unittest

from app import agenda, config, db

LISTA = [{"nome": "Jessica Delmoni", "oab_numero": "13043", "oab_uf": "AL"}]
COM_OAB, SEM_OAB, OUTRO_UF, NORMAL = ("00010000020268160001", "00020000020268160001", "00030000020268160001",
                                      "00040000020268160001")


def banco():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    return con


def publicacao(con, numero, *advogados):
    db.salvar_comunicacao(con, {"id": int(numero[:7]), "numero_processo": numero, "texto": "Intimação",
                                "data_disponibilizacao": "2026-10-01",
                                "destinatarioadvogados": [{"advogado": a} for a in advogados]})


BEATRIZ = {"nome": "BEATRIZ DAFFARA", "numero_oab": "130678", "uf_oab": "PR"}


class DeteccaoTest(unittest.TestCase):
    def setUp(self):
        self.con = banco()
        publicacao(self.con, COM_OAB, BEATRIZ, {"nome": "JESSICA FERREIRA DELMONI", "numero_oab": "13043", "uf_oab": "AL"})
        publicacao(self.con, SEM_OAB, BEATRIZ, {"nome": "Jéssica Ferreira Delmoni"})  # sem OAB: casa pelo nome
        publicacao(self.con, OUTRO_UF, BEATRIZ, {"nome": "JESSICA DELMONI", "numero_oab": "13043", "uf_oab": "SP"})
        publicacao(self.con, NORMAL, BEATRIZ)

    def test_pela_oab_e_sem_oab_pelo_nome(self):
        self.assertEqual(db.atualizar_cooperacao(self.con, lista=LISTA), 2)
        marcados = {r[0] for r in self.con.execute("SELECT numero FROM processos WHERE cooperacao=1")}
        # OAB de outra UF não casa, mesmo com o nome igual: com OAB dos dois lados, vale só a OAB
        self.assertEqual(marcados, {COM_OAB, SEM_OAB})

    def test_lista_vazia_ou_nome_parecido_nao_marca(self):
        self.assertEqual(db.atualizar_cooperacao(self.con, lista=[]), 0)
        self.assertEqual(db.atualizar_cooperacao(self.con, lista=[{"nome": "Jessica Silva", "oab_numero": "", "oab_uf": ""}]), 0)

    def test_marcacao_manual_vale_por_cima(self):
        db.atualizar_cooperacao(self.con, lista=LISTA)
        db.marcar_cooperacao(self.con, COM_OAB, False)  # desmarcado à mão
        db.marcar_cooperacao(self.con, NORMAL, True)    # marcado à mão
        db.atualizar_cooperacao(self.con, lista=LISTA)  # sincronizar de novo não desfaz a marcação à mão
        ps = {p["numero"]: p for p in db.listar(self.con)}
        self.assertEqual((ps[COM_OAB]["cooperacao"], ps[COM_OAB]["cooperacao_auto"]), (False, True))
        self.assertEqual((ps[NORMAL]["cooperacao"], ps[NORMAL]["cooperacao_auto"]), (True, False))
        # marcar igual à automática volta a seguir a automática
        db.marcar_cooperacao(self.con, COM_OAB, True)
        self.assertIsNone(self.con.execute("SELECT cooperacao_manual FROM processos WHERE numero=?", (COM_OAB,)).fetchone()[0])

    def test_monitoramento_esconde_tarefas_so_com_a_opcao_ligada(self):
        db.atualizar_cooperacao(self.con, lista=LISTA)
        agenda.criar(self.con, {"titulo": "Prazo da cooperação", "tipo": "prazo", "numero": COM_OAB, "prazo_fatal": "2026-10-20"})
        agenda.criar(self.con, {"titulo": "Prazo normal", "tipo": "prazo", "numero": NORMAL, "prazo_fatal": "2026-10-20"})
        agenda.criar(self.con, {"titulo": "Tarefa solta", "tipo": "tarefa"})
        titulos = lambda ocultar: sorted(t["titulo"] for t in agenda.listar(self.con, ocultar_cooperacao=ocultar))  # noqa: E731
        self.assertEqual(titulos(True), ["Prazo normal", "Tarefa solta"])
        self.assertEqual(titulos(False), ["Prazo da cooperação", "Prazo normal", "Tarefa solta"])
        # nada sai do banco
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM tarefas").fetchone()[0], 3)

    def test_migracao_marca_os_processos_existentes(self):
        db.meta_set(self.con, "schema_versao", "7")
        original = config.carregar
        config.carregar = lambda com_env=True: {**original(com_env), "advogados_cooperacao": LISTA}
        try:
            db._migrar(self.con)
        finally:
            config.carregar = original
        self.assertEqual({r[0] for r in self.con.execute("SELECT numero FROM processos WHERE cooperacao=1")},
                         {COM_OAB, SEM_OAB})


class ConfigTest(unittest.TestCase):
    def test_normaliza_lista(self):
        lista = config._cooperacao({"advogados_cooperacao": [
            {"nome": " Jessica  Delmoni ", "oab_numero": "13043AL"}, {"nome": "", "oab_numero": ""},
            {"nome": "Fulano", "oab_numero": "999/sp"}]})
        self.assertEqual(lista, [{"nome": "Jessica Delmoni", "oab_numero": "13043", "oab_uf": "AL"},
                                 {"nome": "Fulano", "oab_numero": "999", "oab_uf": "SP"}])

    def test_padrao_ligado_com_jessica(self):
        self.assertTrue(config.DEFAULTS["ocultar_cooperacao"])
        self.assertEqual(config.DEFAULTS["advogados_cooperacao"], LISTA)


if __name__ == "__main__":
    unittest.main()
