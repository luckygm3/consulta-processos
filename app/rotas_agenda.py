"""Rotas da agenda/kanban, verificação de prazos, feriados e tipos de ato."""
from fastapi import APIRouter, Body, HTTPException

from . import agenda, cnj, db, prazos

rotas = APIRouter(prefix="/api")


def _ou_400(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dados inválidos")


@rotas.get("/agenda")
def listar():
    with db.conexao() as con:
        return {"tarefas": agenda.listar(con), "status": agenda.STATUS, "regras": agenda.regras()}


@rotas.get("/agenda/alertas")
def alertas():
    with db.conexao() as con:
        return agenda.alertas(con)


@rotas.post("/agenda")
def criar(dados: dict = Body(...)):
    if not (dados.get("titulo") or "").strip():
        raise HTTPException(400, "Informe o título")
    with db.conexao() as con:
        tid = _ou_400(agenda.criar, con, {**dados, "origem": "manual"})
        return agenda.obter(con, tid)


@rotas.patch("/agenda/{tid}")
def atualizar(tid: int, dados: dict = Body(...)):
    with db.conexao() as con:
        _ou_400(agenda.atualizar, con, tid, dados)
        t = agenda.obter(con, tid)
    if not t:
        raise HTTPException(404, "Tarefa não encontrada")
    return t


@rotas.delete("/agenda/{tid}")
def excluir(tid: int):
    with db.conexao() as con:
        r = con.execute("SELECT origem FROM tarefas WHERE id=?", (tid,)).fetchone()
        if r and r["origem"] == "djen":
            agenda.lote(con, [tid], "descartar")  # guarda como descartada: a publicação não sugere de novo
        else:
            con.execute("DELETE FROM tarefas WHERE id=?", (tid,))
    return {"ok": True}


@rotas.post("/agenda/lote")
def lote(dados: dict = Body(...)):
    ids = [int(i) for i in dados.get("ids") or []]
    if not ids:
        return {"alterados": 0}
    with db.conexao() as con:
        return {"alterados": _ou_400(agenda.lote, con, ids, dados.get("acao"))}


@rotas.post("/agenda/verificar")
def verificar(dados: dict = Body(default={})):
    with db.conexao() as con:
        return agenda.verificar(con, incluir_vencidos=bool(dados.get("incluir_vencidos")))


@rotas.get("/prazos/calcular")
def calcular(disponibilizacao: str, dias: int, numero: str = "", contagem: str = ""):
    with db.conexao() as con:
        return _ou_400(agenda.calcular_para, con, cnj.so_digitos(numero) or None, disponibilizacao, dias,
                       contagem if contagem in ("uteis", "corridos") else None)


@rotas.post("/processos/{numero}/contagem")
def contagem_processo(numero: str, dados: dict = Body(...)):
    valor = dados.get("contagem") if dados.get("contagem") in ("uteis", "corridos") else None
    with db.conexao() as con:
        con.execute("UPDATE processos SET contagem=? WHERE numero=?", (valor, cnj.so_digitos(numero)))
    return {"ok": True, "contagem": valor}


# --- feriados ---------------------------------------------------------------

@rotas.get("/feriados")
def feriados(ano: int | None = None):
    with db.conexao() as con:
        return {"feriados": agenda.listar_feriados(con, ano), "tipos": prazos.TIPOS}


@rotas.get("/feriados/dias")
def feriados_dias(de: str, ate: str):
    with db.conexao() as con:
        return _ou_400(agenda.dias_nao_uteis, con, de, ate)


@rotas.post("/feriados")
def criar_feriado(dados: dict = Body(...)):
    with db.conexao() as con:
        return {"id": _ou_400(agenda.salvar_feriado, con, dados)}


@rotas.put("/feriados/{fid}")
def editar_feriado(fid: int, dados: dict = Body(...)):
    with db.conexao() as con:
        return {"id": _ou_400(agenda.salvar_feriado, con, dados, fid)}


@rotas.delete("/feriados/{fid}")
def excluir_feriado(fid: int):
    with db.conexao() as con:
        con.execute("DELETE FROM feriados WHERE id=?", (fid,))
    return {"ok": True}


# --- tipos de ato -------------------------------------------------------------

@rotas.get("/tipos-ato")
def tipos_ato():
    with db.conexao() as con:
        return agenda.tipos(con)


@rotas.put("/tipos-ato")
def salvar_tipos_ato(lista: list[dict] = Body(...)):
    with db.conexao() as con:
        agenda.salvar_tipos(con, lista)
        return agenda.tipos(con)
