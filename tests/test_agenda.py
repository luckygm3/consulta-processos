"""Testes da agenda: tarefa semanal de processo sigiloso, restaurar de Concluídos e checklist padrão.
Rodar: python -m unittest discover -s tests -v"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from app import agenda, config, db

SEG, QUA, SEG_SEGUINTE = date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 12)
SIGILOSO, COM_NIVEL, NORMAL, FORA = "00064937120268160030", "00010000020268160001", "00020000020268160001", "00030000020268160001"


def banco():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    con.execute("ALTER TABLE processos ADD COLUMN contagem TEXT")  # coluna que a migração v3 cria
    sigilo = lambda n: json.dumps([{"grau": "G1", "sigilo": n}])  # noqa: E731
    con.executemany("INSERT INTO processos(numero, tribunal, datajud_status, instancias) VALUES(?,?,?,?)", [
        (SIGILOSO, "TJPR", "sem_dados", None),      # DataJud respondeu completo e não achou: sigiloso
        (COM_NIVEL, "TJPR", "ok", sigilo(1)),       # DataJud achou, com nível de sigilo
        (NORMAL, "TJPR", "ok", sigilo(0)),
        (FORA, "TJPR", "sem_alias", None),          # tribunal fora do DataJud: não é sigilo
    ])
    con.execute("INSERT INTO processo_advogada(numero, advogada_id) VALUES(?, 1)", (SIGILOSO,))
    return con


def semanais(con):
    return [dict(r) for r in con.execute("SELECT * FROM tarefas WHERE origem='sigilo' ORDER BY id")]


class SigilososTest(unittest.TestCase):
    def test_criterio(self):
        self.assertEqual(sorted(agenda.sigilosos(banco())), sorted([SIGILOSO, COM_NIVEL]))

    def test_uma_por_processo_por_semana(self):
        con = banco()
        self.assertEqual(agenda.gerar_semanais(con, SEG), 2)
        self.assertEqual(agenda.gerar_semanais(con, SEG), 0)
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        t = next(x for x in semanais(con) if x["numero"] == SIGILOSO)
        self.assertEqual(t["titulo"], "Verificar processo sigiloso nº 0006493-71.2026.8.16.0030")
        self.assertEqual((t["prazo_fatal"], t["status"], t["advogada_id"]), ("2026-10-05", "a_fazer", 1))

    def test_concluir_so_reaparece_na_segunda_seguinte(self):
        con = banco()
        agenda.gerar_semanais(con, SEG)
        tid = next(x["id"] for x in semanais(con) if x["numero"] == SIGILOSO)
        agenda.atualizar(con, tid, {"status": "concluido"})
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        con.execute("DELETE FROM tarefas WHERE id=?", (tid,))  # excluir também não faz voltar na mesma semana
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        # segunda seguinte: volta a do concluído; a outra ainda está aberta e não é duplicada
        self.assertEqual(agenda.gerar_semanais(con, SEG_SEGUINTE), 1)
        nova = [x for x in semanais(con) if x["numero"] == SIGILOSO]
        self.assertEqual([x["prazo_fatal"] for x in nova], ["2026-10-12"])
        self.assertEqual(len([x for x in semanais(con) if x["numero"] == COM_NIVEL]), 1)

    def test_gerada_no_meio_da_semana_vence_no_dia(self):
        con = banco()
        agenda.gerar_semanais(con, QUA)
        self.assertEqual({x["prazo_fatal"] for x in semanais(con)}, {"2026-10-07"})


class ConcluidosTest(unittest.TestCase):
    def test_restaurar_volta_para_a_coluna_de_origem(self):
        con = banco()
        tid = agenda.criar(con, {"titulo": "Petição", "status": "aguardando"})
        agenda.atualizar(con, tid, {"status": "concluido"})
        r = con.execute("SELECT status, status_anterior, concluido_em FROM tarefas WHERE id=?", (tid,)).fetchone()
        self.assertEqual((r["status"], r["status_anterior"]), ("concluido", "aguardando"))
        self.assertIsNotNone(r["concluido_em"])
        self.assertTrue(agenda.restaurar(con, tid))
        r = con.execute("SELECT status, status_anterior, concluido_em FROM tarefas WHERE id=?", (tid,)).fetchone()
        self.assertEqual(tuple(r), ("aguardando", None, None))
        self.assertFalse(agenda.restaurar(con, tid))  # só restaura o que está em Concluídos

    def test_restaurar_sem_origem_vai_para_a_fazer(self):
        con = banco()
        tid = agenda.criar(con, {"titulo": "Antiga", "status": "concluido"})
        agenda.restaurar(con, tid)
        self.assertEqual(con.execute("SELECT status FROM tarefas WHERE id=?", (tid,)).fetchone()[0], "a_fazer")


class ChecklistPadraoTest(unittest.TestCase):
    def test_arquivo_do_projeto(self):
        itens = config.checklist_padrao()
        self.assertEqual(len(itens), 17)
        self.assertEqual((itens[0], itens[-1]), ("Reunião de Briefing", "Sentença (informado pelo juízo)"))

    def test_comentarios_linhas_vazias_e_bom(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "checklist.txt"
            arq.write_text("# comentário\n\n  Primeiro  \nSegundo\n", encoding="utf-8-sig")
            with mock.patch.object(config, "CHECKLIST_PATH", arq):
                self.assertEqual(config.checklist_padrao(), ["Primeiro", "Segundo"])
            with mock.patch.object(config, "CHECKLIST_PATH", Path(d) / "nao-existe.txt"):
                self.assertEqual(config.checklist_padrao(), [])


if __name__ == "__main__":
    unittest.main()
