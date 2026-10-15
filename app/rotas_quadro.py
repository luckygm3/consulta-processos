"""Rotas do quadro de clientes."""
from fastapi import APIRouter, Body, HTTPException

from . import cnj, db, interligar, quadro

rotas = APIRouter(prefix="/api/quadro")


def _ou_400(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dados inválidos")


@rotas.get("")
def carregar():
    with db.conexao() as con:
        interligar.migrar(con)  # uma vez só (ver interligar.py): a tela pode pedir o quadro antes de /api/estado
        return quadro.carregar(con)


@rotas.put("/colunas/{coluna_id}")
def renomear(coluna_id: int, dados: dict = Body(...)):
    with db.conexao() as con:
        if not quadro.renomear_coluna(con, coluna_id, dados.get("nome") or ""):
            raise HTTPException(404, "Coluna não encontrada")
    return {"ok": True}


@rotas.get("/prazo-processo")
def prazo_processo(numero: str = ""):
    """Prazo fatal processual que um card ligado a este processo mostraria (para o diálogo do card)."""
    with db.conexao() as con:
        return quadro.prazos_processuais(con).get(cnj.so_digitos(numero)) or {}


@rotas.post("/cards")
def criar(dados: dict = Body(...)):
    with db.conexao() as con:  # sem checklist, nasce com a padrão do tipo (a tela já manda preenchida)
        return {"id": _ou_400(quadro.criar, con, dados)}


@rotas.patch("/cards/{cid}")
def atualizar(cid: int, dados: dict = Body(...)):
    with db.conexao() as con:
        if not _ou_400(quadro.atualizar, con, cid, dados):
            raise HTTPException(404, "Card não encontrado")
    return {"ok": True}


@rotas.delete("/cards/{cid}")
def excluir(cid: int):
    with db.conexao() as con:
        con.execute("DELETE FROM clientes WHERE id=%s", (cid,))
    return {"ok": True}


@rotas.post("/ordem")
def ordenar(dados: dict = Body(...)):
    ids = [int(i) for i in dados.get("ids") or []]
    with db.conexao() as con:
        _ou_400(quadro.ordenar, con, int(dados.get("coluna_id") or 0), ids)
    return {"ok": True}
