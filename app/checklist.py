"""Checklist das demandas (tarefas da agenda e cards do quadro). Fonte única: os itens ficam só dentro da demanda
(coluna checklist, JSON); a agenda lê de lá e "marcar como feito" grava de volta no mesmo item.

Item: {"id", "texto", "feito", "data": "AAAA-MM-DD" | None, "hora": "HH:MM" | None (só com data),
       "resp": "a:<id da advogada>" | "p:<id da pessoa>" | None}
"""
import json
import re
import secrets
from datetime import date

from . import config, db

DONOS = {"tarefa": "tarefas", "card": "quadro_cards"}  # tipo de demanda -> tabela


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
        saida.append({"id": iid, "texto": texto, "feito": bool(c.get("feito")), "data": data, "hora": hora, "resp": resp})
    return saida


def ler(valor: str | None) -> list[dict]:
    try:
        return normalizar(json.loads(valor)) if valor else []
    except ValueError:
        return []


def padrao(modelo: str = "processo") -> list[dict]:
    return normalizar(config.checklist_padrao(modelo))


def marcar(con, dono: str, dono_id: int, item_id: str, feito: bool) -> bool:
    """Marca/desmarca um item onde quer que ele seja mostrado (agenda ou card): grava na própria demanda."""
    tabela = DONOS.get(dono)
    if not tabela:
        raise ValueError("Demanda inválida")
    r = con.execute(f"SELECT checklist FROM {tabela} WHERE id=?", (dono_id,)).fetchone()
    if not r:
        return False
    itens = ler(r["checklist"])
    item = next((c for c in itens if c["id"] == item_id), None)
    if not item:
        return False
    item["feito"] = bool(feito)
    con.execute(f"UPDATE {tabela} SET checklist=?, atualizado_em=? WHERE id=?",
                (json.dumps(itens, ensure_ascii=False), db.agora(), dono_id))
    return True


# --- pessoas (responsáveis dos itens): as advogadas do config.json + quem ela cadastrar -----------------

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
    cur = con.execute("INSERT INTO pessoas(nome, ativo, criado_em) VALUES(?, 1, ?)", (nome, db.agora()))
    return cur.lastrowid


def remover_pessoa(con, pid: int):
    """Só desativa: itens antigos continuam mostrando quem era o responsável."""
    con.execute("UPDATE pessoas SET ativo=0 WHERE id=?", (pid,))
