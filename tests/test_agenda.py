"""Testes do Monitoramento: sugestão semanal de processo sigiloso e checklist padrão. (Aprovar e rejeitar: em
test_interligar.py.) Rodar: python -m unittest discover -s tests -t . -v"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from app import agenda, config, interligar
from tests.supabase_local import TesteComBanco

SEG, QUA, SEG_SEGUINTE = date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 12)
SIGILOSO, COM_NIVEL, NORMAL, FORA = "00064937120268160030", "00010000020268160001", "00020000020268160001", "00030000020268160001"


class Base(TesteComBanco):
    def banco(self):
        con = self.conexao()
        sigilo = lambda n: [{"grau": "G1", "sigilo": n}]  # noqa: E731
        self.processo(con, SIGILOSO, tribunal="TJPR", datajud_status="sem_dados")  # completo e não achou: sigiloso
        self.processo(con, COM_NIVEL, tribunal="TJPR", datajud_status="ok", instancias=sigilo(1))  # nível de sigilo
        self.processo(con, NORMAL, tribunal="TJPR", datajud_status="ok", instancias=sigilo(0))
        self.processo(con, FORA, tribunal="TJPR", datajud_status="sem_alias")  # fora do DataJud: não é sigilo
        con.execute("INSERT INTO processo_advogada(numero, advogada_id) VALUES(%s, 1)", (SIGILOSO,))
        return con


def semanais(con):
    return [dict(r) for r in con.execute("SELECT * FROM tarefas WHERE origem='sigilo' ORDER BY id")]


class SigilososTest(Base):
    def test_criterio(self):
        self.assertEqual(sorted(agenda.sigilosos(self.banco())), sorted([SIGILOSO, COM_NIVEL]))

    def test_uma_por_processo_por_semana(self):
        con = self.banco()
        self.assertEqual(agenda.gerar_semanais(con, SEG), 2)
        self.assertEqual(agenda.gerar_semanais(con, SEG), 0)
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        t = next(x for x in semanais(con) if x["numero"] == SIGILOSO)
        self.assertEqual(t["titulo"], "Verificar processo sigiloso nº 0006493-71.2026.8.16.0030")
        self.assertEqual((t["prazo_fatal"], t["status"], t["advogada_id"]), ("2026-10-05", "sugerido", 1))

    def test_rejeitar_so_reaparece_na_segunda_seguinte(self):
        con = self.banco()
        agenda.gerar_semanais(con, SEG)
        tid = next(x["id"] for x in semanais(con) if x["numero"] == SIGILOSO)
        interligar.rejeitar(con, [tid])
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        con.execute("DELETE FROM tarefas WHERE id=%s", (tid,))  # excluir também não faz voltar na mesma semana
        self.assertEqual(agenda.gerar_semanais(con, QUA), 0)
        # segunda seguinte: volta a rejeitada; a outra ainda aguarda aprovação e não é duplicada
        self.assertEqual(agenda.gerar_semanais(con, SEG_SEGUINTE), 1)
        nova = [x for x in semanais(con) if x["numero"] == SIGILOSO]
        self.assertEqual([x["prazo_fatal"] for x in nova], ["2026-10-12"])
        self.assertEqual(len([x for x in semanais(con) if x["numero"] == COM_NIVEL]), 1)

    def test_gerada_no_meio_da_semana_vence_no_dia(self):
        con = self.banco()
        agenda.gerar_semanais(con, QUA)
        self.assertEqual({x["prazo_fatal"] for x in semanais(con)}, {"2026-10-07"})


class EditarSugestaoTest(Base):
    def test_editar_nao_muda_o_status(self):
        con = self.banco()
        tid = agenda.criar(con, {"titulo": "Petição", "tipo": "prazo", "prazo_fatal": "2026-10-20"})
        agenda.atualizar(con, tid, {"titulo": "Réplica", "status": "aprovado", "prazo_fatal": "2026-10-21"})
        t = agenda.obter(con, tid)
        self.assertEqual((t["titulo"], t["status"], t["prazo_fatal"]), ("Réplica", "sugerido", "2026-10-21"))
        with self.assertRaises(ValueError):
            agenda.atualizar(con, tid, {"cliente_id": 999999})


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
