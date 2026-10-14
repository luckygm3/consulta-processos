"""Testes de acesso (RLS do supabase/schema.sql): só as advogadas cadastradas, com login confirmado, veem e mudam
os dados; o backend recusa consultas sem usuária logada. Rodar: python -m unittest discover -s tests -t . -v"""
import uuid

import psycopg

from app import db
from tests.supabase_local import BEATRIZ, KAZUZA, TesteComBanco, claims

PROC, OUTRO = "00064937120268160030", "00074819220268160030"


class AcessoTest(TesteComBanco):
    def test_as_duas_advogadas_veem_tudo(self):
        for quem, numero in ((BEATRIZ, PROC), (KAZUZA, OUTRO)):  # números diferentes: as transações ficam abertas
            con = self.conexao(claims(quem))
            self.assertTrue(db.autorizada(con))
            self.processo(con, numero, tribunal="TJPR")
            self.assertEqual(con.execute("SELECT count(*) FROM processos WHERE numero=%s", (numero,)).fetchone()[0], 1)
            self.assertEqual([a["nome"] for a in db.advogadas(con)], ["Beatriz Daffara", "Kazuza"])

    def test_conta_que_nao_e_advogada_nao_ve_nem_grava(self):
        estranha = claims(uid=str(uuid.uuid4()), email="intrusa@exemplo.com")
        con = self.conexao(estranha)
        self.assertFalse(db.autorizada(con))
        self.assertEqual(db.advogadas(con), [])
        self.assertEqual(con.execute("SELECT count(*) FROM clientes_colunas").fetchone()[0], 0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):  # RLS: "new row violates row-level security"
            self.processo(con, PROC)

    def test_anonimo_nao_tem_acesso(self):
        bruta = psycopg.connect(self.url)
        self.addCleanup(bruta.close)
        bruta.execute("SET LOCAL ROLE anon")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            bruta.execute("SELECT count(*) FROM public.processos")

    def test_pelo_app_so_muda_nome_e_cor_das_advogadas(self):
        con = self.conexao()
        con.execute("UPDATE advogadas SET nome='Beatriz D.', cor='#123456' WHERE id=1")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            con.execute("UPDATE advogadas SET email='outra@exemplo.com' WHERE id=1")

    def test_login_so_vincula_com_email_confirmado(self):
        bruta = psycopg.connect(self.url)  # como dono do banco (é o que o SQL Editor do Supabase faz)
        self.addCleanup(lambda: (bruta.rollback(), bruta.close()))
        bruta.execute("INSERT INTO advogadas(nome, oab_numero, oab_uf, email) VALUES('Nova', '1', 'SC', 'nova@exemplo.com')")
        uid = bruta.execute("INSERT INTO auth.users(email) VALUES('nova@exemplo.com') RETURNING id").fetchone()[0]
        vinculo = lambda: bruta.execute("SELECT user_id FROM advogadas WHERE email='nova@exemplo.com'").fetchone()[0]  # noqa: E731
        self.assertIsNone(vinculo())                      # cadastro ainda não confirmado: sem acesso
        bruta.execute("UPDATE auth.users SET email_confirmed_at=now() WHERE id=%s", (uid,))
        self.assertEqual(vinculo(), uid)                  # confirmou o e-mail: vinculado

    def test_email_cadastrado_depois_do_login_vincula_na_hora(self):
        bruta = psycopg.connect(self.url)  # SQL Editor: o login foi criado antes, o e-mail da advogada vem depois
        self.addCleanup(lambda: (bruta.rollback(), bruta.close()))
        uid = bruta.execute("INSERT INTO auth.users(email, email_confirmed_at) VALUES('depois@exemplo.com', now()) "
                            "RETURNING id").fetchone()[0]
        bruta.execute("INSERT INTO advogadas(nome, oab_numero, oab_uf) VALUES('Depois', '2', 'SC')")
        bruta.execute("UPDATE advogadas SET email=' Depois@Exemplo.com ' WHERE oab_numero='2'")  # do jeito que colarem
        self.assertEqual(bruta.execute("SELECT email, user_id FROM advogadas WHERE oab_numero='2'").fetchone(),
                         ("depois@exemplo.com", uid))
        bruta.execute("UPDATE advogadas SET email=NULL WHERE oab_numero='2'")  # tirar o e-mail tira o acesso
        self.assertIsNone(bruta.execute("SELECT user_id FROM advogadas WHERE oab_numero='2'").fetchone()[0])

    def test_backend_sem_usuaria_logada_nao_consulta(self):
        with self.assertRaises(PermissionError):
            with db.conexao():
                pass
