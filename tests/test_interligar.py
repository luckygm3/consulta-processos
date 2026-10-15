"""Dados interligados: processo -> cliente (card criado sozinho), sugestão do Monitoramento -> aprovada vira item do
checklist do cliente (e daí vai para a Agenda), rejeitada sai do Monitoramento; e a migração do Kanban antigo.
Rodar: python -m unittest discover -s tests -t . -v"""
from datetime import date
from unittest import mock

from fastapi.testclient import TestClient

from app import agenda, auth, db, interligar, main, quadro
from tests.supabase_local import TesteComBanco, claims

P1 = "00064937120268160030"   # números CNJ válidos
P2 = "00074819220268160030"
P3 = "00010000020268160001"
PARTES = {"ativo": ["Joab Lima"], "passivo": ["Empresa X"]}


class Base(TesteComBanco):
    def banco(self):
        con = self.conexao()
        self.processo(con, P1, partes=PARTES, tribunal="TJPR")
        self.processo(con, P2, partes=PARTES, tribunal="TJPR")
        self.processo(con, P3, tribunal="TJPR", cooperacao=True)
        return con


def cards(con):
    return quadro.carregar(con)["cards"]


def card(con, cid):
    return next(c for c in cards(con) if c["id"] == cid)


def sugestao(con, numero=P1, **campos):
    return agenda.criar(con, {"titulo": "Contestação (15 dias úteis)", "tipo": "prazo", "status": "sugerido",
                              "numero": numero, "prazo_fatal": "2026-10-20", "data_interna": "2026-10-16",
                              "advogada_id": 1, "origem": "djen", "calculo": {"dias": 15}, **campos})


class ClientesTest(Base):
    def test_processo_ganha_cliente_um_por_processo(self):
        con = self.banco()
        self.assertEqual(interligar.garantir_clientes(con), 2)  # o de cooperação fica sem
        cs = cards(con)
        self.assertEqual(sorted(c["numero"] for c in cs), [P1, P2])  # mesmo cliente, dois processos: dois cards
        c = cs[0]
        self.assertEqual((c["titulo"], c["tipo"], c["coluna_id"], c["completar"], c["checklist"]),
                         ("Joab Lima × Empresa X", "processo", 1, True, []))
        self.assertEqual(interligar.garantir_clientes(con), 0)  # não duplica

    def test_novo_entra_no_topo_da_primeira_coluna(self):
        con = self.banco()
        quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "tipo": "inicial"})
        interligar.garantir_clientes(con, [P2])
        self.assertEqual([c["titulo"] for c in cards(con) if c["coluna_id"] == 1], ["Joab Lima × Empresa X", "Ana"])

    def test_card_excluido_nao_volta(self):
        con = self.banco()
        interligar.garantir_clientes(con, [P1])
        con.execute("DELETE FROM clientes WHERE numero=%s", (P1,))
        self.assertEqual(interligar.garantir_clientes(con, [P1]), 0)
        self.assertEqual(cards(con), [])

    def test_card_feito_a_mao_nao_duplica(self):
        con = self.banco()
        quadro.criar(con, {"titulo": "Joab", "coluna_id": 2, "numero": P1})
        self.assertEqual(interligar.garantir_clientes(con, [P1]), 0)
        self.assertEqual([c["titulo"] for c in cards(con)], ["Joab"])

    def test_sem_partes_usa_o_numero(self):
        con = self.banco()
        con.execute("UPDATE processos SET cooperacao=false WHERE numero=%s", (P3,))
        interligar.garantir_clientes(con, [P3])
        self.assertEqual(cards(con)[0]["titulo"], "Processo 0001000-00.2026.8.16.0001")

    def test_salvar_pelo_dialogo_tira_o_selo(self):
        con = self.banco()
        interligar.garantir_clientes(con, [P1])
        cid = cards(con)[0]["id"]
        quadro.ordenar(con, 2, [cid])  # arrastar não conta
        self.assertTrue(card(con, cid)["completar"])
        quadro.atualizar(con, cid, {"titulo": "Joab Lima"})
        self.assertFalse(card(con, cid)["completar"])


class AprovarTest(Base):
    def test_aprovada_vira_item_do_checklist_do_cliente(self):
        con = self.banco()
        cid = quadro.criar(con, {"titulo": "Joab", "coluna_id": 1, "numero": P1, "checklist": [{"texto": "Briefing"}]})
        con.execute("UPDATE clientes SET atualizado_em='2026-10-01T10:00:00' WHERE id=%s", (cid,))
        tid = sugestao(con, hora="09:30")
        self.assertEqual(card(con, cid)["sugestoes"], 1)
        self.assertEqual(interligar.aprovar(con, [tid]), {"aprovadas": 1, "sem_cliente": 0})
        c = card(con, cid)
        item = c["checklist"][-1]
        self.assertEqual((item["texto"], item["data"], item["hora"], item["resp"], item["feito"], item["origem_id"]),
                         ("Contestação (15 dias úteis)", "2026-10-20", "09:30", "a:1", False, tid))
        self.assertEqual((item["tipo"], item["prazo_tipo"]), ("prazo", "processual"))
        self.assertEqual(c["sugestoes"], 0)
        self.assertNotEqual(c["atualizado_em"], "2026-10-01T10:00:00")  # quem estiver com o card aberto é avisada ao salvar
        t = con.execute("SELECT status, cliente_id FROM tarefas WHERE id=%s", (tid,)).fetchone()
        self.assertEqual((t["status"], t["cliente_id"]), ("aprovado", cid))
        self.assertEqual(agenda.listar(con), [])  # saiu do Monitoramento

    def test_processo_sem_card_ganha_cliente(self):
        con = self.banco()
        tid = sugestao(con, numero=P2)
        interligar.aprovar(con, [tid])
        c = next(c for c in cards(con) if c["numero"] == P2)
        self.assertTrue(c["completar"])
        self.assertEqual([i["origem_id"] for i in c["checklist"]], [tid])

    def test_cliente_escolhido(self):
        con = self.banco()
        quadro.criar(con, {"titulo": "Joab", "coluna_id": 1, "numero": P1})
        outro = quadro.criar(con, {"titulo": "Joab (família)", "coluna_id": 1, "tipo": "preventivo", "checklist": []})
        tid = sugestao(con, cliente_id=outro)  # escolhido no diálogo antes de aprovar
        interligar.aprovar(con, [tid])
        self.assertEqual([i["origem_id"] for i in card(con, outro)["checklist"]], [tid])

    def test_sem_processo_e_sem_cliente_fica_esperando(self):
        con = self.banco()
        tid = sugestao(con, numero=None)
        self.assertEqual(interligar.aprovar(con, [tid]), {"aprovadas": 0, "sem_cliente": 1})
        self.assertEqual([t["id"] for t in agenda.listar(con)], [tid])
        cid = quadro.criar(con, {"titulo": "Ana", "coluna_id": 1, "tipo": "preventivo", "checklist": []})
        self.assertEqual(interligar.aprovar(con, [tid], cid)["aprovadas"], 1)

    def test_rejeitada_sai_e_nao_vai_para_o_cliente(self):
        con = self.banco()
        tid = sugestao(con)
        self.assertEqual(interligar.rejeitar(con, [tid]), 1)
        self.assertEqual(agenda.listar(con), [])
        self.assertEqual(con.execute("SELECT status FROM tarefas WHERE id=%s", (tid,)).fetchone()[0], "descartado")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM checklist_itens").fetchone()[0], 0)
        self.assertEqual(interligar.rejeitar(con, [tid]), 0)  # já saiu

    def test_salvar_o_card_mantem_a_ligacao_com_a_tarefa(self):
        con = self.banco()
        cid = quadro.criar(con, {"titulo": "Joab", "coluna_id": 1, "numero": P1, "checklist": []})
        tid = sugestao(con)
        interligar.aprovar(con, [tid])
        lista = card(con, cid)["checklist"]
        lista[0]["data"] = "2026-10-19"  # ela mudou a data no card
        quadro.atualizar(con, cid, {"checklist": lista})
        item = card(con, cid)["checklist"][0]
        self.assertEqual((item["origem_id"], item["tipo"], item["data"]), (tid, "prazo", "2026-10-19"))
        self.assertEqual(quadro.prazos_processuais(con, date(2026, 10, 7))[P1]["data"], "2026-10-19")

    def test_urgencia_do_item_aprovado(self):
        con = self.banco()
        cid = quadro.criar(con, {"titulo": "Joab", "coluna_id": 1, "numero": P1, "checklist": [{"texto": "Briefing"}]})
        interligar.aprovar(con, [sugestao(con, prazo_fatal="2026-10-01")])
        itens = quadro.carregar(con, date(2026, 10, 7))["cards"][0]["checklist"]
        self.assertNotIn("urgencia", itens[0])  # item comum: sem cor de urgência
        self.assertEqual(itens[1]["urgencia"], "vencido")
        con.execute("UPDATE checklist_itens SET feito=true WHERE cliente_id=%s", (cid,))
        self.assertNotIn("urgencia", quadro.carregar(con, date(2026, 10, 7))["cards"][0]["checklist"][1])  # feito


class SigilosoTest(Base):
    def test_verificacao_semanal_reaproveita_o_item_feito(self):
        con = self.banco()
        con.execute("UPDATE processos SET datajud_status='sem_dados' WHERE numero=%s", (P1,))
        self.assertEqual(agenda.gerar_semanais(con, date(2026, 10, 5)), 1)
        primeira = agenda.listar(con)[0]
        self.assertEqual(primeira["status"], "sugerido")  # passa pelo Monitoramento
        interligar.aprovar(con, [primeira["id"]])
        # aprovada e ainda não feita: a segunda seguinte não cria outra
        self.assertEqual(agenda.gerar_semanais(con, date(2026, 10, 12)), 0)
        cid = cards(con)[0]["id"]
        item = card(con, cid)["checklist"][0]
        con.execute("UPDATE checklist_itens SET feito=true WHERE cliente_id=%s", (cid,))
        self.assertEqual(agenda.gerar_semanais(con, date(2026, 10, 19)), 1)
        interligar.aprovar(con, [agenda.listar(con)[0]["id"]])
        itens = card(con, cid)["checklist"]
        self.assertEqual(len(itens), 1)  # reabriu o da semana anterior em vez de empilhar
        self.assertEqual((itens[0]["id"], itens[0]["feito"], itens[0]["data"]), (item["id"], False, "2026-10-19"))


class PrazoProcessualTest(Base):
    HOJE = date(2026, 10, 7)

    def prazo(self, con, cid):
        return next(c for c in quadro.carregar(con, self.HOJE)["cards"] if c["id"] == cid)["prazo"]

    def test_sugestao_e_item_aprovado(self):
        con = self.banco()
        cid = quadro.criar(con, {"titulo": "Joab", "coluna_id": 1, "numero": P1, "checklist": []})
        sugestao(con, titulo="Sugestão velha", prazo_fatal="2026-09-01")       # sugestão vencida: não conta
        self.assertIsNone(self.prazo(con, cid))
        sugestao(con, titulo="Réplica", prazo_fatal="2026-10-25")
        p = self.prazo(con, cid)
        self.assertEqual((p["descricao"], p["sugerido"]), ("Réplica", True))
        interligar.aprovar(con, [sugestao(con, titulo="Embargos", prazo_fatal="2026-09-20")])  # vencido em aberto
        interligar.aprovar(con, [sugestao(con, titulo="Contestação", prazo_fatal="2026-10-20")])
        p = self.prazo(con, cid)
        self.assertEqual((p["tipo"], p["descricao"], p["data"], p["sugerido"]), ("processual", "Contestação", "2026-10-20", False))
        con.execute("UPDATE checklist_itens SET feito=true WHERE texto='Contestação'")  # feito: sai
        self.assertEqual(self.prazo(con, cid)["descricao"], "Réplica")


class MigracaoTest(Base):
    def test_kanban_antigo_vai_para_os_clientes(self):
        con = self.banco()
        manual_ck = [{"id": "x1", "texto": "Minuta", "feito": True}, {"id": "x2", "texto": "Protocolar"}]
        ids = {
            "sugerida": sugestao(con),
            "djen": sugestao(con, status="a_fazer", titulo="Apelação"),
            "sigilo": agenda.criar(con, {"titulo": "Verificar sigiloso", "status": "a_fazer", "origem": "sigilo",
                                         "numero": P1, "prazo_fatal": "2026-10-05"}),
            "simples": agenda.criar(con, {"titulo": "Ligar para o cliente", "status": "andamento", "numero": P1}),
            "solta": agenda.criar(con, {"titulo": "Renovar certificado", "status": "aguardando",
                                        "prazo_fatal": "2026-11-30", "checklist": manual_ck}),
            "com_lista": agenda.criar(con, {"titulo": "Recurso", "status": "a_fazer", "numero": P2,
                                            "prazo_fatal": "2026-10-30", "checklist": [{"texto": "Pesquisa"}]}),
            "concluida": agenda.criar(con, {"titulo": "Antiga", "status": "concluido", "numero": P1}),
        }
        self.assertTrue(interligar.migrar(con))
        status = {k: con.execute("SELECT status FROM tarefas WHERE id=%s", (v,)).fetchone()[0] for k, v in ids.items()}
        self.assertEqual(status, {"sugerida": "sugerido", "djen": "aprovado", "sigilo": "aprovado", "simples": "aprovado",
                                  "solta": "aprovado", "com_lista": "aprovado", "concluida": "concluido"})
        cs = {c["titulo"]: c for c in cards(con)}
        # o processo P2 já ganha o card "Recurso" (vindo da tarefa com checklist): não ganha outro; o de cooperação, nenhum
        self.assertEqual(sorted((c["titulo"], c["numero"]) for c in cards(con)),
                         [("Joab Lima × Empresa X", P1), ("Recurso", P2), ("Renovar certificado", None)])
        do_p1 = cs["Joab Lima × Empresa X"]
        self.assertTrue(do_p1["completar"])
        self.assertEqual([i["texto"] for i in do_p1["checklist"]], ["Verificar sigiloso", "Apelação", "Ligar para o cliente"])
        solta = cs["Renovar certificado"]
        self.assertEqual((solta["tipo"], solta["prazo"]["data"], solta["completar"]), ("preventivo", "2026-11-30", False))
        self.assertEqual([(i["id"], i["texto"], i["feito"]) for i in solta["checklist"]],
                         [("x1", "Minuta", True), ("x2", "Protocolar", False)])  # a checklist dela, com os mesmos itens
        recurso = cs["Recurso"]
        self.assertEqual((recurso["tipo"], recurso["numero"]), ("processo", P2))
        self.assertEqual([i["texto"] for i in recurso["checklist"]], ["Pesquisa", "Recurso"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM checklist_itens WHERE tarefa_id IS NOT NULL").fetchone()[0], 0)
        self.assertFalse(interligar.migrar(con))  # uma vez só
        self.assertEqual(len(cards(con)), 3)


class RotasTest(Base):
    """Pela API, como a tela chama."""

    def setUp(self):
        self.con = self.banco()
        for alvo in (mock.patch.object(auth, "conferir", mock.AsyncMock(return_value=claims())),
                     mock.patch.object(db, "conexao", side_effect=lambda: _Contexto(self.con))):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.api = TestClient(main.app, headers={"Authorization": "Bearer teste"})

    def test_aprovar_e_rejeitar(self):
        a, b = sugestao(self.con), sugestao(self.con, titulo="Audiência", tipo="audiencia")
        self.assertEqual(len(self.api.get("/api/agenda").json()["tarefas"]), 2)
        self.assertEqual(self.api.post("/api/agenda/aprovar", json={"ids": [a]}).json()["aprovadas"], 1)
        self.assertEqual(self.api.post("/api/agenda/rejeitar", json={"ids": [b]}).json()["rejeitadas"], 1)
        self.assertEqual(self.api.get("/api/agenda").json()["tarefas"], [])
        itens = [i for c in self.api.get("/api/calendario?de=2026-10-01&ate=2026-10-31").json()["cards"]
                 for i in c["checklist"]]
        self.assertEqual([(i["texto"], i["data"]) for i in itens], [("Contestação (15 dias úteis)", "2026-10-20")])

    def test_nova_tarefa_vai_direto_para_o_cliente(self):
        r = self.api.post("/api/agenda", json={"titulo": "Ligar para o Joab", "tipo": "tarefa", "numero": P1,
                                               "prazo_fatal": "2026-10-09"}).json()
        self.assertEqual(r["cliente"], "Joab Lima × Empresa X")
        self.assertEqual([i["texto"] for i in card(self.con, r["cliente_id"])["checklist"]], ["Ligar para o Joab"])
        self.assertEqual(self.api.get("/api/agenda").json()["tarefas"], [])  # não passa pelo Monitoramento
        self.assertEqual(self.api.post("/api/agenda", json={"titulo": "Sem cliente"}).status_code, 400)

    def test_alerta_conta_tarefa_aprovada_e_sugestao(self):
        interligar.aprovar(self.con, [sugestao(self.con, prazo_fatal="2026-01-05")])  # aprovada e vencida
        sugestao(self.con, prazo_fatal="2026-01-06")                                   # sugestão vencida
        # verificação semanal de sigiloso não é prazo: aprovada e atrasada, não entra no alerta
        interligar.aprovar(self.con, [agenda.criar(self.con, {"titulo": "Verificar sigiloso", "origem": "sigilo",
                                                              "numero": P2, "prazo_fatal": "2026-01-05"})])
        a = self.api.get("/api/agenda/alertas").json()
        self.assertEqual((a["vencidos"], a["sugeridos"]), (2, 1))

    def test_telas_esperam_a_migracao(self):
        # a tela pede o quadro e o Monitoramento junto com /api/estado: quem chegar primeiro faz a migração
        self.assertEqual(len(self.api.get("/api/quadro").json()["cards"]), 2)
        self.assertEqual(len(self.api.get("/api/agenda").json()["cards"]), 2)

    def test_estado_faz_a_migracao(self):
        self.api.get("/api/estado")
        self.assertEqual(sorted(c["numero"] for c in cards(self.con)), [P1, P2])

    def test_adicionar_processo_cria_cliente(self):
        with mock.patch("app.sync.iniciar", return_value=False), mock.patch("app.sync.rodando", return_value=False):
            r = self.api.post("/api/processos/adicionar", json={"texto": "0000001-63.2026.8.16.0030\n0007481-92.2026.8.16.0030"})
        self.assertEqual((r.json()["novos"], len(r.json()["existentes"])), (["0000001-63.2026.8.16.0030"], 1))
        c = cards(self.con)  # só o novo: o que já existia ganha o card na migração (ou quando uma tarefa dele for aprovada)
        self.assertEqual([(x["numero"], x["titulo"], x["completar"]) for x in c],
                         [("00000016320268160030", "Processo 0000001-63.2026.8.16.0030", True)])


class _Contexto:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *erro):
        return False
