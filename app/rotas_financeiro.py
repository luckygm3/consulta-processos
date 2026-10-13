"""Rotas do financeiro (lançamentos, parcelas e painel)."""
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from . import db, financeiro

rotas = APIRouter(prefix="/api/financeiro")


def _ou_400(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dados inválidos")
    except LookupError as e:
        raise HTTPException(404, str(e))


@rotas.get("")
def painel(mes: str = ""):
    """Lançamentos (com parcelas e saldos) + números do painel para o mês navegado (AAAA-MM; padrão: o atual)."""
    hoje = date.today()
    if not (len(mes) == 7 and mes[:4].isdigit() and mes[5:].isdigit() and 1 <= int(mes[5:]) <= 12):
        mes = hoje.isoformat()[:7]
    with db.conexao() as con:
        lancs = financeiro.listar(con, hoje)
    return {"lancamentos": lancs, "resumo": financeiro.resumo(lancs, mes, hoje), "hoje": hoje.isoformat()}


@rotas.get("/atrasadas")
def atrasadas():
    """Só a contagem (selo do menu lateral)."""
    with db.conexao() as con:
        n = con.execute("SELECT COUNT(*) FROM parcelas WHERE pago=0 AND vencimento < ?", (date.today().isoformat(),)).fetchone()[0]
    return {"atrasadas": n}


@rotas.post("/lancamentos")
def criar(dados: dict = Body(...)):
    with db.conexao() as con:
        return {"id": _ou_400(financeiro.salvar, con, dados)}


@rotas.put("/lancamentos/{lid}")
def atualizar(lid: int, dados: dict = Body(...)):
    with db.conexao() as con:
        return {"id": _ou_400(financeiro.salvar, con, dados, lid)}


@rotas.delete("/lancamentos/{lid}")
def excluir(lid: int):
    with db.conexao() as con:
        financeiro.excluir(con, lid)
    return {"ok": True}


@rotas.post("/parcelas/{pid}/pagar")
def pagar(pid: int, dados: dict = Body(...)):
    """{"pago": true|false, "pago_em": "AAAA-MM-DD" (opcional; padrão hoje)}"""
    with db.conexao() as con:
        if not _ou_400(financeiro.marcar_paga, con, pid, bool(dados.get("pago")), dados.get("pago_em")):
            raise HTTPException(404, "Parcela não encontrada")
    return {"ok": True}
