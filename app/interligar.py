"""Dados interligados: processo -> cliente -> checklist -> agenda.

- Cada processo das advogadas tem um cliente (card do quadro de Clientes). Processo novo captado pela OAB (DJEN) ou
  adicionado à mão ganha um card no topo da 1ª coluna, com o nome das partes como nome provisório e o selo
  "completar dados" (ela preenche o resto e o checklist depois). Um card por processo, mesmo que o cliente se repita
  (o mesmo cliente pode ter um processo trabalhista e outro de família). Processo em cooperação não ganha card.
  Cada processo ganha card uma vez só (tarefas_geradas, chave cliente:<numero>): card excluído não volta sozinho.
- O Monitoramento é só a passagem das sugestões do sistema (prazos, audiências, verificação de sigilosos): tarefas
  com status 'sugerido'. Aprovar põe a tarefa no checklist do cliente, como um item com a data do prazo, o horário e a
  responsável (o item é o que vale daí em diante: aparece na Agenda e é marcado como feito ali ou no card); a tarefa
  fica guardada como registro ('aprovado', com a memória de cálculo e o trecho da publicação). Rejeitar descarta
  ('descartado': a mesma publicação não sugere de novo).
"""
import logging

from . import checklist, cnj, db

log = logging.getLogger("interligar")

ABERTAS_ANTIGAS = ("a_fazer", "andamento", "aguardando")  # colunas do Kanban antigo do Monitoramento


def _chave(numero: str) -> str:
    return f"cliente:{numero}"


def _registrar(con, numero: str):
    con.execute("INSERT INTO tarefas_geradas(chave, criado_em) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (_chave(numero), db.agora()))


def card_do_processo(con, numero: str | None) -> int | None:
    """O card (cliente) de um processo: o mais antigo, se ela tiver feito mais de um."""
    if not numero:
        return None
    r = con.execute("SELECT id FROM clientes WHERE numero=%s ORDER BY id LIMIT 1", (numero,)).fetchone()
    return r[0] if r else None


def _topo_da_primeira_coluna(con) -> tuple[int, int]:
    coluna = con.execute("SELECT id FROM clientes_colunas ORDER BY posicao, id LIMIT 1").fetchone()[0]
    posicao = con.execute("SELECT COALESCE(MIN(posicao), 1) - 1 FROM clientes WHERE coluna_id=%s", (coluna,)).fetchone()[0]
    return coluna, posicao


def criar_card(con, numero: str) -> int:
    """Card de cliente para um processo, com o nome das partes provisório e o selo "completar dados"."""
    p = con.execute("SELECT partes FROM processos WHERE numero=%s", (numero,)).fetchone()
    nome = db.resumo_partes(p["partes"] if p else None) or f"Processo {cnj.formatar(numero)}"
    coluna, posicao = _topo_da_primeira_coluna(con)
    agora = db.agora()
    cid = con.execute("""INSERT INTO clientes(coluna_id, posicao, nome, tipo, numero, completar, criado_em, atualizado_em)
                         VALUES(%s,%s,%s,'processo',%s,true,%s,%s) RETURNING id""",
                      (coluna, posicao, nome[:200], numero, agora, agora)).fetchone()[0]
    _registrar(con, numero)
    return cid


def garantir_clientes(con, numeros=None) -> int:
    """Cria o card dos processos (os indicados, ou todos) que ainda não ganharam um. Devolve quantos criou."""
    sql = f"""SELECT numero FROM processos p
              WHERE NOT {db.COOPERACAO_SQL}
                AND NOT EXISTS (SELECT 1 FROM tarefas_geradas g WHERE g.chave = 'cliente:' || p.numero)"""
    args: list = []
    if numeros is not None:
        numeros = [n for n in numeros if n]
        if not numeros:
            return 0
        sql += " AND numero = ANY(%s)"
        args.append(numeros)
    # o mais recente entra por último, e fica no topo da coluna
    sql += " ORDER BY ult_atividade NULLS FIRST, criado_em, numero"
    criados = 0
    for numero in [r[0] for r in con.execute(sql, args)]:
        if card_do_processo(con, numero):  # ela já tinha feito o card deste processo: só registra
            _registrar(con, numero)
        else:
            criar_card(con, numero)
            criados += 1
    if criados:
        log.info("Clientes criados para processos: %d", criados)
    return criados


# --- tarefa aprovada -> item do checklist do cliente ------------------------------------------------

def _destino(con, t, cliente_id: int | None) -> int:
    for cid in (cliente_id, t["cliente_id"]):
        if cid and con.execute("SELECT 1 FROM clientes WHERE id=%s", (cid,)).fetchone():
            return cid
    if t["numero"]:
        return card_do_processo(con, t["numero"]) or criar_card(con, t["numero"])
    raise ValueError(f"Escolha o cliente de “{t['titulo']}” (a tarefa não tem processo)")


def adicionar_ao_cliente(con, tid: int, cliente_id: int | None = None) -> int | None:
    """Põe a tarefa no checklist do cliente (o escolhido, o do processo ou um card novo para o processo) e a marca como
    aprovada. Devolve o id do card (None se a tarefa não existe)."""
    t = con.execute("SELECT * FROM tarefas WHERE id=%s FOR UPDATE", (tid,)).fetchone()
    if not t:
        return None
    cid = _destino(con, t, cliente_id)
    con.execute("SELECT id FROM clientes WHERE id=%s FOR UPDATE", (cid,))  # dois salvamentos no mesmo card esperam
    data = t["prazo_fatal"]
    valores = (t["titulo"], data, t["hora"] if data else None, t["advogada_id"], tid)
    reaproveitar = None
    if t["origem"] == "sigilo":  # verificação semanal: reabre a da semana anterior (já feita) em vez de empilhar
        reaproveitar = con.execute("""SELECT i.id FROM checklist_itens i JOIN tarefas o ON o.id = i.origem_id
                                      WHERE i.cliente_id=%s AND o.origem='sigilo' AND i.feito
                                      ORDER BY i.posicao LIMIT 1""", (cid,)).fetchone()
    if reaproveitar:
        con.execute("""UPDATE checklist_itens SET texto=%s, data=%s, hora=%s, advogada_id=%s, pessoa_id=NULL,
                       origem_id=%s, feito=false WHERE id=%s""", (*valores, reaproveitar[0]))
    else:
        posicao = con.execute("SELECT COALESCE(MAX(posicao), 0) + 1 FROM checklist_itens WHERE cliente_id=%s",
                              (cid,)).fetchone()[0]
        con.execute("""INSERT INTO checklist_itens(cliente_id, item_id, posicao, texto, data, hora, advogada_id, origem_id)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (cid, checklist.novo_id(), posicao, *valores))
    agora = db.agora()
    con.execute("UPDATE tarefas SET status='aprovado', cliente_id=%s, atualizado_em=%s WHERE id=%s", (cid, agora, tid))
    con.execute("UPDATE clientes SET atualizado_em=%s WHERE id=%s", (agora, cid))  # quem está com o card aberto é avisada
    return cid


def aprovar(con, ids: list[int], cliente_id: int | None = None) -> dict:
    """Aprova sugestões (as que ainda estão no Monitoramento). Sem processo e sem cliente escolhido, fica onde está."""
    feitas, sem_cliente = 0, 0
    for tid in [r[0] for r in con.execute("SELECT id FROM tarefas WHERE status='sugerido' AND id = ANY(%s) "
                                          "ORDER BY prazo_fatal, id", (list(ids),))]:
        try:
            with db.savepoint(con):
                adicionar_ao_cliente(con, tid, cliente_id)
            feitas += 1
        except ValueError:
            sem_cliente += 1
    return {"aprovadas": feitas, "sem_cliente": sem_cliente}


def rejeitar(con, ids: list[int]) -> int:
    """Tira do Monitoramento. Fica guardada como descartada: a mesma publicação não volta a sugerir."""
    return con.execute("UPDATE tarefas SET status='descartado', atualizado_em=%s WHERE status='sugerido' AND id = ANY(%s)",
                       (db.agora(), list(ids))).rowcount


# --- migração (uma vez): clientes dos processos que já existiam e o Kanban antigo do Monitoramento ---------

def _virar_card(con, t):
    """Tarefa criada à mão sem processo (ou com checklist própria): vira um card de cliente com aquela checklist."""
    numero = t["numero"] if t["numero"] and len(t["numero"]) == 20 and cnj.digito_valido(t["numero"]) else None
    coluna, posicao = _topo_da_primeira_coluna(con)
    agora = db.agora()
    prazo = (None, None, None) if numero or not t["prazo_fatal"] else ("Prazo fatal", t["prazo_fatal"], t["hora"])
    cid = con.execute("""INSERT INTO clientes(coluna_id, posicao, nome, tipo, numero, prazo_descricao, prazo_data,
                                              prazo_hora, criado_em, atualizado_em)
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                      (coluna, posicao, t["titulo"], "processo" if numero else "preventivo", numero, *prazo,
                       agora, agora)).fetchone()[0]
    con.execute("UPDATE checklist_itens SET cliente_id=%s, tarefa_id=NULL WHERE tarefa_id=%s", (cid, t["id"]))
    if numero and t["prazo_fatal"]:
        adicionar_ao_cliente(con, t["id"], cid)  # o prazo da tarefa entra como item do card
    else:
        con.execute("UPDATE tarefas SET status='aprovado', cliente_id=%s, atualizado_em=%s WHERE id=%s",
                    (cid, agora, t["id"]))


def migrar(con) -> bool:
    """Uma vez só (meta "interligar_migrado"): cria os clientes dos processos já cadastrados e leva as tarefas abertas do
    Kanban antigo para os clientes. Sugestões continuam no Monitoramento; concluídas ficam guardadas, fora de vista.
    - prazo/audiência/verificação vinda do sistema, ou tarefa à mão com processo e sem checklist própria: vira item
      (aprovado) do checklist do cliente do processo;
    - tarefa à mão sem processo, ou com checklist própria: vira um card de cliente, com aquela checklist.
    Chamada no começo das rotas que leem clientes e tarefas (a tela abre várias ao mesmo tempo): a que chegar enquanto
    outra está migrando espera no INSERT e já lê o resultado."""
    if db.meta_get(con, "interligar_migrado"):
        return False
    if not con.execute("INSERT INTO meta(chave, valor) VALUES('interligar_migrado', %s) ON CONFLICT DO NOTHING "
                       "RETURNING chave", (db.agora(),)).fetchone():
        return False  # já foi feita (ou outra aba está fazendo agora: o INSERT esperou por ela)
    tarefas = con.execute("SELECT * FROM tarefas WHERE status = ANY(%s) ORDER BY prazo_fatal NULLS LAST, id",
                          (list(ABERTAS_ANTIGAS),)).fetchall()
    itens = []
    for t in tarefas:  # primeiro as que viram card: o card de uma tarefa com processo passa a ser o cliente dele
        propria = con.execute("SELECT 1 FROM checklist_itens WHERE tarefa_id=%s LIMIT 1", (t["id"],)).fetchone()
        if t["numero"] and (t["origem"] != "manual" or not propria):
            itens.append(t["id"])
        else:
            _virar_card(con, t)
    for tid in itens:
        adicionar_ao_cliente(con, tid)
    clientes = garantir_clientes(con)
    log.info("Dados interligados: %d clientes criados, %d tarefas levadas para os clientes", clientes, len(tarefas))
    return True
