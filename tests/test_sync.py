"""Testes da sincronização em passos (sem rede): trava de um passo por vez e estado retomável.
Rodar: python -m unittest discover -s tests -t . -v"""
import json

from app import db, sync
from tests.supabase_local import TesteComBanco


class TravaTest(TesteComBanco):
    def test_um_passo_por_vez_e_o_proximo_pega_na_hora(self):
        con = self.conexao()
        self.assertTrue(sync._pegar_trava(con, 60))
        self.assertFalse(sync._pegar_trava(con, 60))   # outro passo (outra aba) espera
        sync._soltar_trava(con)
        self.assertTrue(sync._pegar_trava(con, 60))    # logo em seguida, sem esperar o relógio

    def test_trava_vencida_e_retomada(self):
        con = self.conexao()
        con.execute("INSERT INTO meta(chave, valor) VALUES('sync_trava', '2000-01-01T00:00:00')")  # passo que caiu
        self.assertTrue(sync._pegar_trava(con, 60))


class EstadoTest(TesteComBanco):
    def test_estado_gravado_no_banco(self):
        con = self.conexao()
        estado = {"id": "abc", "rodando": True, "fase": "datajud", "atual": 20, "total": 72, "mensagem": "", "resumo": ["DJEN: x"],
                  "inicio": "2026-10-14T11:57:03", "fim": None, "completo": True}
        sync._gravar(con, estado)
        self.assertEqual(sync._ler(con), estado)
        self.assertEqual(json.loads(db.meta_get(con, "sync_estado"))["atual"], 20)
