"""Teste do script de migração (SQLite antigo -> Supabase) com dados de todas as áreas: processos, publicações,
tarefas e clientes com checklist (JSON -> checklist_itens), financeiro, feriados, lembretes e meta.
Dois bancos de origem: v6 (antes dos pagamentos parciais e da cooperação) e v8 (com histórico de pagamentos,
cliente inadimplente e processos em cooperação). Rodar: python -m unittest discover -s tests -t . -v"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import psycopg

from app import agenda, banco_antigo as antigo, db, financeiro, quadro
from tests import supabase_local as sl

sys.path.insert(0, str(sl.RAIZ / "scripts"))
import migrar_para_supabase as mig  # noqa: E402

PROC = "00064937120268160030"
COOP = "00074819220268160030"  # processo com a Jessica Delmoni (advogada de cooperação da lista padrão)
DADOS = Path(__file__).with_name("dados")
JESSICA = '[{"nome": "JESSICA FERREIRA DELMONI", "numero_oab": "13043", "uf_oab": "AL"}]'


def banco_antigo(caminho: Path) -> sqlite3.Connection:
    o = sqlite3.connect(caminho)
    o.executescript((DADOS / "schema_sqlite_v6.sql").read_text(encoding="utf-8"))
    o.executescript(f"""
        ALTER TABLE processos ADD COLUMN contagem TEXT;
        INSERT INTO processos(numero, tribunal, criado_em) VALUES ('{COOP}', 'TJPR', '2026-09-01T10:00:00');
        INSERT INTO comunicacoes(hash, numero, data_disp, texto, advogados, capturado_em)
            VALUES ('h2', '{COOP}', '2026-10-02', 'Intimação.', '{JESSICA}', '2026-10-02T09:00:00');
        INSERT INTO advogadas(id, oab_numero, oab_uf, nome, cor) VALUES (1, '130678', 'PR', 'Beatriz Daffara', '#41ecb9'),
                                                                        (2, '130152', 'PR', 'Kazuza', '#c144ee');
        INSERT INTO pessoas(id, nome, ativo, criado_em) VALUES (1, 'Ana Estagiária', 0, '2026-10-01T09:00:00');
        INSERT INTO processos(numero, tribunal, partes, novidade_em, visto_em, criado_em, contagem, data_ajuizamento)
            VALUES ('{PROC}', 'TJPR', '{{"ativo": ["Maria"], "passivo": ["Empresa X"]}}', '2026-10-10T14:30:00',
                    '2026-10-09T08:00:00', '2026-09-01T10:00:00', 'corridos', 'lixo');
        INSERT INTO processo_advogada VALUES ('{PROC}', 1, 'djen', '2026-09-01T10:00:00'), ('{PROC}', 2, 'manual', NULL);
        INSERT INTO comunicacoes(hash, numero, data_disp, texto, destinatarios, capturado_em)
            VALUES ('h1', '{PROC}', '2026-10-01', 'Intime-se.', '[]', '2026-10-01T22:15:00');
        INSERT INTO comunicacao_advogada VALUES ('h1', 1);
        INSERT INTO comunicacao_analise VALUES ('h1', '2026-10-02T08:00:00', 'sem_prazo', NULL);
        INSERT INTO movimentos VALUES ('m1', '{PROC}', 'G1', 26, '2026-09-30T16:25:35', 'Distribuído', '', 'Vara', '2026-10-01T09:00:00');
        INSERT INTO tarefas(id, titulo, tipo, status, numero, advogada_id, prazo_fatal, hora, conferir, origem, calculo,
                            checklist, criado_em, status_anterior)
            VALUES (7, 'Contestação', 'prazo', 'concluido', '{PROC}', 2, '2026-10-20', '13:55', 1, 'djen', '{{"dias": 15}}',
                    '[{{"id": "a1", "texto": "Minuta", "feito": true, "data": "2026-10-15", "hora": "10:00", "resp": "a:2"}},
                      {{"id": "a2", "texto": "Revisar", "resp": "p:1"}}, {{"texto": "  "}}]',
                    '2026-10-01T10:00:00', 'andamento');
        INSERT INTO tarefas_geradas VALUES ('sigilo:{PROC}:2026-10-05', '2026-10-05T08:00:00');
        INSERT INTO quadro_colunas(id, posicao, nome) VALUES (1, 1, 'Trabalhista'), (2, 2, ''), (3, 3, ''), (4, 4, ''), (5, 5, '');
        INSERT INTO quadro_cards(id, coluna_id, posicao, titulo, tipo, checklist, aniversario, prazo_data, prazo_hora, criado_em)
            VALUES (3, 1, 1, 'Maria da Silva', 'preventivo', '[{{"id": "c1", "texto": "Parecer"}}]', '1985-02-28',
                    '2026-11-01', '18:00', '2026-10-01T10:00:00');
        INSERT INTO lancamentos(id, cliente, numero, valor_total, entrada, entrada_data, valor_parcela, qtd_parcelas, criado_em)
            VALUES (5, ' maria da silva', '{PROC}', 300000, 100000, '2026-09-10', 100000, 2, '2026-09-10T11:00:00');
        INSERT INTO parcelas(id, lancamento_id, numero, vencimento, valor, pago, pago_em)
            VALUES (11, 5, 0, '2026-09-10', 100000, 1, '2026-09-10'), (12, 5, 1, '2026-10-10', 100000, 0, NULL),
                   (13, 5, 2, '2026-11-10', 100000, 1, NULL);
        INSERT INTO feriados(id, inicio, descricao, tipo, tribunais, comarca, recorrente, origem, ativo)
            VALUES (40, '06-10', 'Aniversário de Foz', 'feriado', 'TJPR', 'Foz do Iguaçu', 1, 'manual', 0);
        INSERT INTO tipos_ato(id, ordem, nome, palavras, dias, contagem, justica, ativo) VALUES (1, 1, 'Réplica', 'replica', 15, 'uteis', '', 1);
        INSERT INTO lembretes_feitos VALUES ('aniv:3:2026', '2026-02-28T09:00:00');
        INSERT INTO meta VALUES ('djen_ultima_data:130678/PR', '2026-10-10'), ('schema_versao', '6'), ('sync_trava', 'x'),
                                ('ultima_atualizacao', '2026-10-10T15:00:00');
        INSERT INTO sync_erros(id, sync_id, quando, fonte, tribunal, mensagem) VALUES (9, 's1', '2026-10-10T15:00:00', 'DJEN', '', 'x');
    """)
    o.commit()
    return o


@unittest.skipUnless(sl.disponivel(), "pgserver não instalado (pip install -r requirements-dev.txt)")
class MigracaoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = sl.criar_banco("migracao")
        cls.pasta = tempfile.TemporaryDirectory()
        origem = banco_antigo(Path(cls.pasta.name) / "antigo.sqlite3")
        origem.row_factory = sqlite3.Row
        with psycopg.connect(cls.url, autocommit=True) as c:  # login de uma delas já criado no Auth
            cls.uid = str(c.execute("INSERT INTO auth.users(email, email_confirmed_at) VALUES ('kazuza@exemplo.com', now())"
                                    " RETURNING id").fetchone()[0])
        try:
            with psycopg.connect(cls.url) as destino:
                destino.execute("SET TIME ZONE " + ("'<-03>+03'" if sl.os.environ.get("FUSO_BANCO") else "'America/Sao_Paulo'"))
                cls.copia = mig.Copia(origem, destino)
                mig.copiar(cls.copia, {"130152/PR": "kazuza@exemplo.com"})
                mig.finalizar(destino)
                cls.conferiu = mig.conferir(cls.copia)
                destino.commit()
        finally:
            origem.close()

    @classmethod
    def tearDownClass(cls):
        cls.pasta.cleanup()

    def conexao(self):
        bruta = psycopg.connect(self.url, prepare_threshold=None)
        db.preparar(bruta)
        db.entrar(bruta, {"sub": self.uid, "email": "kazuza@exemplo.com", "role": "authenticated"})
        self.addCleanup(lambda: (bruta.rollback(), bruta.close()))
        return db.Conexao(bruta)

    def test_contagens_conferidas(self):
        self.assertTrue(self.conferiu)
        self.assertEqual(self.copia.contagem["pagamentos"][0], 2)  # 2 parcelas pagas viraram 2 pagamentos
        self.assertIn("processo 00064937120268160030: data inválida 'lixo' gravada como vazia", self.copia.avisos)
        self.assertTrue(any("sem texto descartado" in a for a in self.copia.avisos))

    def test_login_vinculado_e_acesso_pela_rls(self):
        con = self.conexao()
        self.assertTrue(db.autorizada(con))
        self.assertEqual([(a["id"], a["nome"], a["cor"]) for a in db.advogadas(con)],
                         [(1, "Beatriz Daffara", "#41ecb9"), (2, "Kazuza", "#c144ee")])

    def test_processo_com_horarios_de_brasilia(self):
        con = self.conexao()
        p = db.detalhe(con, PROC)
        self.assertEqual((p["novidade_em"], p["visto_em"], p["contagem"], p["data_ajuizamento"]),
                         ("2026-10-10T14:30:00", "2026-10-09T08:00:00", "corridos", None))
        self.assertEqual(p["advogadas"], [1, 2])
        self.assertEqual([(e["fonte"], e["data"]) for e in p["eventos"]],
                         [("djen", "2026-10-01"), ("datajud", "2026-09-30T16:25:35")])

    def test_tarefa_e_checklist_viram_linhas(self):
        con = self.conexao()
        t = agenda.obter(con, 7)
        self.assertEqual((t["status"], t["status_anterior"], t["hora"], t["conferir"], t["calculo"]),
                         ("concluido", "andamento", "13:55", True, {"dias": 15}))
        self.assertEqual(t["checklist"], [
            {"id": "a1", "texto": "Minuta", "feito": True, "data": "2026-10-15", "hora": "10:00", "resp": "a:2"},
            {"id": "a2", "texto": "Revisar", "feito": False, "data": None, "hora": None, "resp": "p:1"}])

    def test_cliente_aniversario_e_lancamento_ligado(self):
        con = self.conexao()
        q = quadro.carregar(con)
        card = q["cards"][0]
        self.assertEqual((q["colunas"][0]["nome"], card["id"], card["titulo"], card["aniversario"], card["prazo"]["hora"]),
                         ("Trabalhista", 3, "Maria da Silva", "1985-02-28", "18:00"))
        self.assertEqual([i["texto"] for i in card["checklist"]], ["Parecer"])
        self.assertTrue(quadro.aniversarios(con, "2026-01-01", "2026-12-31")[0]["feito"])
        lanc = financeiro.listar(con)[0]
        self.assertEqual(con.execute("SELECT cliente_id FROM lancamentos WHERE id=5").fetchone()[0], 3)
        self.assertEqual([(p["id"], p["pago"], p["pago_em"]) for p in lanc["parcelas"]],
                         [(11, True, "2026-09-10"), (12, False, None), (13, True, "2026-11-10")])  # paga sem data: usa o vencimento
        self.assertEqual([[(g["valor"], g["data"]) for g in p["pagamentos"]] for p in lanc["parcelas"]],
                         [[(100000, "2026-09-10")], [], [(100000, "2026-11-10")]])  # parcela paga = pagamento do valor cheio
        self.assertFalse(lanc["inadimplente"])
        self.assertEqual((lanc["recebido"], lanc["falta"]), (200000, 100000))

    def test_ids_continuam_depois_dos_copiados(self):
        con = self.conexao()
        tid = agenda.criar(con, {"titulo": "Nova"})
        self.assertGreater(tid, 7)
        self.assertGreater(quadro.criar(con, {"titulo": "Novo", "coluna_id": 2, "tipo": "inicial", "checklist": []}), 3)

    def test_cooperacao_marcada_pela_lista(self):
        con = self.conexao()
        self.assertEqual([a["nome"] for a in mig.config.cooperacao(con)], ["Jessica Delmoni"])
        self.assertEqual(db.cooperacao_de(con, COOP, mig.config.cooperacao(con))["oab_numero"], "13043")
        ps = {p["numero"]: p for p in db.listar(con)}
        self.assertEqual((ps[COOP]["cooperacao"], ps[PROC]["cooperacao"]), (True, False))
        self.assertEqual(db.meta_get(con, "cooperacao_semeada") is not None, True)  # o app não semeia de novo

    def test_feriados_meta_e_resto(self):
        con = self.conexao()
        f = con.execute("SELECT recorrente, ativo, comarca FROM feriados WHERE id=40").fetchone()
        self.assertEqual((f["recorrente"], f["ativo"], f["comarca"]), (True, False, "Foz do Iguaçu"))
        self.assertEqual(db.meta_get(con, "djen_ultima_data:130678/PR"), "2026-10-10")
        self.assertIsNone(db.meta_get(con, "sync_trava"))      # controle de sincronização antiga não vem
        self.assertIsNone(db.meta_get(con, "schema_versao"))
        self.assertEqual(con.execute("SELECT count(*) FROM tarefas_geradas").fetchone()[0], 1)


def banco_antigo_v8(caminho: Path) -> sqlite3.Connection:
    o = sqlite3.connect(caminho)
    o.executescript((DADOS / "schema_sqlite_v8.sql").read_text(encoding="utf-8"))
    o.executescript(f"""
        ALTER TABLE processos ADD COLUMN contagem TEXT;
        INSERT INTO advogadas(id, oab_numero, oab_uf, nome, cor) VALUES (1, '130678', 'PR', 'Beatriz Daffara', '#41ecb9');
        INSERT INTO processos(numero, tribunal, criado_em, cooperacao, cooperacao_manual)
            VALUES ('{PROC}', 'TJPR', '2026-09-01T10:00:00', 1, 0),    -- automática sim, desmarcado à mão
                   ('{COOP}', 'TJPR', '2026-09-01T10:00:00', 0, NULL);
        INSERT INTO lancamentos(id, cliente, valor_total, entrada, valor_parcela, qtd_parcelas, inadimplente, criado_em)
            VALUES (8, 'João', 30000, 0, 15000, 2, 1, '2026-09-10T11:00:00');
        INSERT INTO parcelas(id, lancamento_id, numero, vencimento, valor, pago, pago_em)
            VALUES (21, 8, 1, '2026-10-20', 15000, 0, NULL), (22, 8, 2, '2026-11-20', 15000, 1, '2026-11-25');
        INSERT INTO pagamentos(id, parcela_id, valor, data, criado_em)
            VALUES (31, 21, 5000, '2026-10-21', '2026-10-21T10:00:00'), (32, 21, 2000, '2026-10-02', '2026-10-02T10:00:00'),
                   (33, 22, 15000, '2026-11-25', '2026-11-25T10:00:00');
    """)
    o.commit()
    return o


@unittest.skipUnless(sl.disponivel(), "pgserver não instalado (pip install -r requirements-dev.txt)")
class MigracaoV8Test(unittest.TestCase):
    """Banco antigo já com pagamentos parciais (histórico), cliente inadimplente e cooperação marcada à mão."""

    @classmethod
    def setUpClass(cls):
        cls.url = sl.criar_banco("migracao8")
        cls.pasta = tempfile.TemporaryDirectory()
        origem = banco_antigo_v8(Path(cls.pasta.name) / "antigo8.sqlite3")
        origem.row_factory = sqlite3.Row
        with psycopg.connect(cls.url, autocommit=True) as c:
            cls.uid = str(c.execute("INSERT INTO auth.users(email, email_confirmed_at) VALUES ('beatriz@exemplo.com', now())"
                                    " RETURNING id").fetchone()[0])
        try:
            with psycopg.connect(cls.url) as destino:
                destino.execute("SET TIME ZONE " + ("'<-03>+03'" if sl.os.environ.get("FUSO_BANCO") else "'America/Sao_Paulo'"))
                cls.copia = mig.Copia(origem, destino)
                mig.copiar(cls.copia, {"130678/PR": "beatriz@exemplo.com"})
                mig.finalizar(destino)
                cls.conferiu = mig.conferir(cls.copia)
                destino.commit()
        finally:
            origem.close()

    @classmethod
    def tearDownClass(cls):
        cls.pasta.cleanup()

    def conexao(self):
        bruta = psycopg.connect(self.url, prepare_threshold=None)
        db.preparar(bruta)
        db.entrar(bruta, {"sub": self.uid, "email": "beatriz@exemplo.com", "role": "authenticated"})
        self.addCleanup(lambda: (bruta.rollback(), bruta.close()))
        return db.Conexao(bruta)

    def test_historico_de_pagamentos_e_inadimplente(self):
        self.assertTrue(self.conferiu)
        con = self.conexao()
        lanc = financeiro.listar(con)[0]
        p1, p2 = lanc["parcelas"]
        self.assertEqual([(g["id"], g["valor"], g["data"]) for g in p1["pagamentos"]],
                         [(32, 2000, "2026-10-02"), (31, 5000, "2026-10-21")])
        self.assertEqual((p1["status"], p1["falta"], p2["status"], p2["pago_em"]), ("parcial", 8000, "paga", "2026-11-25"))
        self.assertTrue(lanc["inadimplente"])
        self.assertGreater(financeiro.adicionar_pagamento(con, p1["id"], {"valor": 100, "data": "2026-10-22"}), 33)

    def test_cooperacao_copiada_como_estava(self):
        con = self.conexao()
        ps = {p["numero"]: p for p in db.listar(con)}
        self.assertEqual((ps[PROC]["cooperacao_auto"], ps[PROC]["cooperacao"]), (True, False))  # a marcação à mão vale
        self.assertFalse(ps[COOP]["cooperacao"])


@unittest.skipUnless(sl.disponivel(), "pgserver não instalado (pip install -r requirements-dev.txt)")
class SubstituirTest(unittest.TestCase):
    """--substituir: o Supabase tinha a migração de outro computador (v6); troca tudo pelo banco que vale (v8)."""

    def setUp(self):
        self.url = sl.criar_banco("substituir")
        pasta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(pasta.cleanup)
        self.v6, self.v8 = Path(pasta.name) / "pc-dele.sqlite3", Path(pasta.name) / "pc-dela.sqlite3"
        banco_antigo(self.v6).close()
        banco_antigo_v8(self.v8).close()
        self.migrar(self.v6, substituir=False)

    def migrar(self, caminho: Path, substituir: bool, falhar: bool = False) -> bool:
        with antigo.copia(caminho) as origem, psycopg.connect(self.url) as destino:
            destino.execute("SET TIME ZONE " + ("'<-03>+03'" if sl.os.environ.get("FUSO_BANCO") else "'America/Sao_Paulo'"))
            if substituir:
                mig.limpar(destino)
            if falhar:
                raise RuntimeError("queda no meio da cópia")
            c = mig.Copia(origem, destino)
            mig.copiar(c, {"130678/PR": "beatriz@exemplo.com"})
            mig.registrar_origem(c, caminho, antigo.impressao(origem))
            mig.finalizar(destino)
            ok = mig.conferir(c)
            destino.commit()
            return ok

    def contar(self, sql: str):
        with psycopg.connect(self.url) as c:
            return c.execute(sql).fetchall()

    def test_troca_tudo_pelo_banco_dela(self):
        self.assertTrue(self.migrar(self.v8, substituir=True))
        self.assertEqual(self.contar("SELECT id FROM lancamentos"), [(8,)])           # só o lançamento dela
        self.assertEqual(self.contar("SELECT count(*) FROM tarefas"), [(0,)])         # as do outro banco saíram
        self.assertEqual(self.contar("SELECT count(*) FROM checklist_itens"), [(0,)])
        self.assertEqual(self.contar("SELECT nome FROM advogadas"), [("Beatriz Daffara",)])
        self.assertEqual(self.contar("SELECT count(*), max(nome) FROM clientes_colunas"), [(5, "")])  # 5, sem nome
        with antigo.copia(self.v8) as o:
            esperada = antigo.impressao(o)
        origem = json.loads(self.contar(f"SELECT valor FROM meta WHERE chave = '{antigo.CHAVE_META}'")[0][0])
        self.assertEqual(origem["impressao"], esperada)

    def test_falha_no_meio_nao_apaga_nada(self):
        with self.assertRaises(RuntimeError):
            self.migrar(self.v8, substituir=True, falhar=True)
        self.assertEqual(self.contar("SELECT id FROM lancamentos"), [(5,)])           # continua o que estava
        self.assertEqual(self.contar("SELECT count(*) FROM tarefas"), [(1,)])
