"""Checklist das demandas (tarefas do Monitoramento e clientes do Xablau). Fonte única: os itens ficam na tabela
checklist_itens, ligados à demanda; a agenda lê de lá e "marcar como feito" grava no mesmo item.

Item (como a tela vê): {"id", "texto", "feito", "data": "AAAA-MM-DD" | None, "hora": "HH:MM" | None (só com data),
                        "resp": "a:<id da advogada>" | "p:<id da pessoa>" | None,
                        "origem_id": id da tarefa aprovada no Monitoramento que virou este item | None}
No banco, "id" é item_id (estável) e "resp" vira advogada_id ou pessoa_id. Ao ler, item que veio do Monitoramento
traz também "tipo" (prazo, audiencia ou tarefa) e, se for prazo, "prazo_tipo" (processual ou interno).
"""
import re
import secrets
from datetime import date

from . import config, db

DONOS = {"tarefa": "tarefa_id", "card": "cliente_id"}  # tipo de demanda -> coluna em checklist_itens


def novo_id() -> str:
    return secrets.token_hex(4)


def normalizar(lista) -> list[dict]:
    """Garante id único e campos válidos em cada item (dados de tela, de versões antigas ou do arquivo padrão)."""
    saida, vistos = [], set()
    for c in lista or []:
        if isinstance(c, str):
            c = {"texto": c}
        if not isinstance(c, dict):
            continue
        texto = str(c.get("texto") or "").strip()
        if not texto:
            continue
        iid = str(c.get("id") or "")
        if not re.fullmatch(r"[0-9a-zA-Z_-]{1,32}", iid) or iid in vistos:
            iid = novo_id()
        vistos.add(iid)
        data = str(c.get("data") or "")[:10] or None
        if data:
            try:
                date.fromisoformat(data)
            except ValueError:
                data = None
        hora = str(c.get("hora") or "")[:5] or None
        if not data or (hora and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora)):
            hora = None  # horário só faz sentido com data
        resp = str(c.get("resp") or "") or None
        if resp and not re.fullmatch(r"[ap]:\d+", resp):
            resp = None
        origem = c.get("origem_id")
        origem = int(origem) if not isinstance(origem, bool) and re.fullmatch(r"\d{1,18}", str(origem or "")) else None
        saida.append({"id": iid, "texto": texto, "feito": bool(c.get("feito")), "data": data, "hora": hora, "resp": resp,
                      "origem_id": origem})
    return saida


def _item(r) -> dict:
    resp = f"a:{r['advogada_id']}" if r["advogada_id"] else (f"p:{r['pessoa_id']}" if r["pessoa_id"] else None)
    item = {"id": r["item_id"], "texto": r["texto"], "feito": r["feito"], "data": r["data"], "hora": r["hora"],
            "resp": resp, "origem_id": r["origem_id"]}
    if r["o_tipo"]:  # veio do Monitoramento: o tipo da tarefa (o pontinho de prazo processual/interno na tela)
        item["tipo"], item["origem"] = r["o_tipo"], r["o_origem"]
        if r["o_tipo"] == "prazo":
            item["prazo_tipo"] = "processual" if r["o_origem"] == "djen" or r["o_calculo"] else "interno"
    return item


def ler(con, dono: str, ids: list[int] | None = None) -> dict[int, list[dict]]:
    """Checklists de várias demandas de um tipo de uma vez: {id da demanda: [itens em ordem]}."""
    coluna = DONOS[dono]
    sql = f"""SELECT i.*, t.tipo AS o_tipo, t.origem AS o_origem, t.calculo IS NOT NULL AS o_calculo
              FROM checklist_itens i LEFT JOIN tarefas t ON t.id = i.origem_id WHERE i.{coluna} IS NOT NULL"""
    args = []
    if ids is not None:
        sql += f" AND i.{coluna} = ANY(%s)"
        args.append(list(ids))
    saida: dict[int, list[dict]] = {}
    for r in con.execute(sql + f" ORDER BY i.{coluna}, i.posicao", args):
        saida.setdefault(r[coluna], []).append(_item(r))
    return saida


def gravar(con, dono: str, dono_id: int, lista) -> list[dict]:
    """Substitui a checklist de uma demanda pela lista vinda da tela (já normalizada aqui)."""
    coluna = DONOS[dono]
    itens = normalizar(lista)
    advs = {r[0] for r in con.execute("SELECT id FROM advogadas")}
    pessoas_ids = {r[0] for r in con.execute("SELECT id FROM pessoas")}
    origens = {r[0] for r in con.execute("SELECT id FROM tarefas WHERE id = ANY(%s)",
                                         ([c["origem_id"] for c in itens if c["origem_id"]],))}
    con.execute(f"DELETE FROM checklist_itens WHERE {coluna}=%s", (dono_id,))
    linhas = []
    for pos, c in enumerate(itens, start=1):
        tipo, _, num = (c["resp"] or "").partition(":")
        adv = int(num) if tipo == "a" and int(num) in advs else None
        pes = int(num) if tipo == "p" and int(num) in pessoas_ids else None
        origem = c["origem_id"] if c["origem_id"] in origens else None
        linhas.append((dono_id, c["id"], pos, c["texto"], c["feito"], c["data"], c["hora"], adv, pes, origem))
    con.executemany(f"""INSERT INTO checklist_itens({coluna}, item_id, posicao, texto, feito, data, hora, advogada_id,
                                                    pessoa_id, origem_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", linhas)
    return itens


def padrao(modelo: str = "processo") -> list[dict]:
    return normalizar(config.checklist_padrao(modelo))


def marcar(con, dono: str, dono_id: int, item_id: str, feito: bool) -> bool:
    """Marca/desmarca um item onde quer que ele seja mostrado (agenda ou card): grava no próprio item."""
    coluna = DONOS.get(dono)
    if not coluna:
        raise ValueError("Demanda inválida")
    cur = con.execute(f"UPDATE checklist_itens SET feito=%s WHERE {coluna}=%s AND item_id=%s",
                      (bool(feito), dono_id, item_id))
    if not cur.rowcount:
        return False
    tabela = "tarefas" if dono == "tarefa" else "clientes"
    con.execute(f"UPDATE {tabela} SET atualizado_em=%s WHERE id=%s", (db.agora(), dono_id))
    return True


# --- pessoas (responsáveis dos itens): as advogadas + quem ela cadastrar -----------------

def pessoas(con) -> list[dict]:
    saida = [{"chave": f"a:{a['id']}", "nome": a["nome"].split()[0] if a["nome"] else a["nome"], "nome_completo": a["nome"],
              "cor": a["cor"], "advogada_id": a["id"], "ativo": True} for a in db.advogadas(con)]
    saida += [{"chave": f"p:{r['id']}", "nome": r["nome"], "nome_completo": r["nome"], "cor": None, "advogada_id": None,
               "ativo": bool(r["ativo"])} for r in con.execute("SELECT * FROM pessoas ORDER BY id")]
    return saida


def adicionar_pessoa(con, nome: str) -> int:
    nome = (nome or "").strip()[:60]
    if not nome:
        raise ValueError("Informe o nome")
    return con.execute("INSERT INTO pessoas(nome, ativo, criado_em) VALUES(%s, true, %s) RETURNING id",
                       (nome, db.agora())).fetchone()[0]


def remover_pessoa(con, pid: int):
    """Só desativa: itens antigos continuam mostrando quem era o responsável."""
    con.execute("UPDATE pessoas SET ativo=false WHERE id=%s", (pid,))
