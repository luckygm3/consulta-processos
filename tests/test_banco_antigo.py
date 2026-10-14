"""Banco antigo (SQLite) no computador: leitura com o -wal, impressão digital e o aviso de dados fora do Supabase.
Rodar: python -m unittest discover -s tests -t . -v"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import banco_antigo, config, db
from tests.supabase_local import TesteComBanco


def criar(caminho: Path) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.execute("PRAGMA journal_mode=WAL")  # como o app antigo
    con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT)")
    con.execute("INSERT INTO clientes(nome) VALUES ('Maria')")
    con.commit()
    return con


class CopiaTest(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.pasta.cleanup)
        self.caminho = Path(self.pasta.name) / "processos.sqlite3"

    def test_le_o_que_so_esta_no_wal_sem_mexer_no_original(self):
        viva = criar(self.caminho)  # app "aberto": o registro novo fica no -wal
        self.addCleanup(viva.close)
        viva.execute("PRAGMA wal_autocheckpoint=0")
        viva.execute("INSERT INTO clientes(nome) VALUES ('João, registrado por último')")
        viva.commit()
        self.assertTrue(self.caminho.with_name("processos.sqlite3-wal").stat().st_size > 0)
        antes = self.caminho.read_bytes()
        with banco_antigo.copia(self.caminho) as c:
            self.assertEqual([r["nome"] for r in c.execute("SELECT nome FROM clientes ORDER BY id")],
                             ["Maria", "João, registrado por último"])
            self.assertEqual(banco_antigo.impressao(c), banco_antigo.impressao(viva))
        self.assertEqual(self.caminho.read_bytes(), antes)

    def test_impressao_muda_com_qualquer_registro(self):
        viva = criar(self.caminho)
        self.addCleanup(viva.close)
        with banco_antigo.copia(self.caminho) as c:
            primeira = banco_antigo.impressao(c)
        with banco_antigo.copia(self.caminho) as c:
            self.assertEqual(banco_antigo.impressao(c), primeira)  # mesmo conteúdo, mesma impressão
        viva.execute("UPDATE clientes SET nome = 'Maria S.'")
        viva.commit()
        with banco_antigo.copia(self.caminho) as c:
            self.assertNotEqual(banco_antigo.impressao(c), primeira)


class SituacaoTest(TesteComBanco):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / "processos.sqlite3"
        p = mock.patch.object(config, "DB_PATH", self.caminho)
        p.start()
        self.addCleanup(p.stop)
        banco_antigo._calculada.clear()

    def migrado(self, con):
        with banco_antigo.copia(self.caminho) as c:
            valor = {"impressao": banco_antigo.impressao(c)}
        con.execute("INSERT INTO meta(chave, valor) VALUES(%s, %s)", (banco_antigo.CHAVE_META, json.dumps(valor)))

    def test_sem_banco_antigo_nao_avisa(self):
        self.assertIsNone(banco_antigo.situacao(self.conexao()))

    def test_banco_que_nao_foi_migrado(self):
        criar(self.caminho).close()
        self.assertEqual(banco_antigo.situacao(self.conexao()), "pendente")

    def test_migrado_e_depois_usado_na_versao_antiga(self):
        viva = criar(self.caminho)
        self.addCleanup(viva.close)
        con = self.conexao()
        self.migrado(con)
        self.assertEqual(banco_antigo.situacao(con), "migrado")
        viva.execute("INSERT INTO clientes(nome) VALUES ('cadastrado depois da migração')")
        viva.commit()
        self.assertEqual(banco_antigo.situacao(con), "pendente")

    def test_na_vercel_nao_olha_arquivo(self):
        criar(self.caminho).close()
        with mock.patch.object(config, "na_vercel", return_value=True):
            self.assertIsNone(banco_antigo.situacao(self.conexao()))

    def test_estado_da_api_leva_o_aviso(self):
        criar(self.caminho).close()
        from app import main
        con = self.conexao()
        with mock.patch.object(db, "conexao", side_effect=lambda: _Contexto(con)):
            self.assertEqual(main.estado()["banco_local"], "pendente")


class _Contexto:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *erro):
        return False
