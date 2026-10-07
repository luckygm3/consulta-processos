"""Rotas da agenda/kanban, verificação de prazos, feriados e tipos de ato."""
from fastapi import APIRouter, Body, HTTPException

from . import agenda, checklist, cnj, config, db, prazos, quadro

rotas = APIRouter(prefix="/api")


def _ou_400(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dados inválidos")


@rotas.get("/agenda")
def listar():
    """Tarefas + cards do quadro (a agenda mostra os itens de checklist com data e o prazo fatal dos cards)."""
    with db.conexao() as con:
        agenda.gerar_semanais(con)
        return {"tarefas": agenda.listar(con), "cards": quadro.carregar(con)["cards"], "pessoas": checklist.pessoas(con),
                "status": agenda.STATUS, "regras": agenda.regras()}


@rotas.get("/checklist-padrao")
def checklist_padrao():
    """{"processo": [...], "preventivo": [...]} (arquivo checklists_padrao.txt)."""
    return config.checklists_padrao()


@rotas.post("/checklist/feito")
def checklist_feito(dados: dict = Body(...)):
    """Marca/desmarca um item na própria demanda (vale para a agenda e para o card ao mesmo tempo)."""
    with db.conexao() as con:
        ok = _ou_400(checklist.marcar, con, dados.get("dono"), int(dados.get("dono_id") or 0),
                     str(dados.get("item") or ""), bool(dados.get("feito")))
    if not ok:
        raise HTTPException(404, "Item não encontrado")
    return {"ok": True}


@rotas.get("/pessoas")
def pessoas():
    with db.conexao() as con:
        return checklist.pessoas(con)


@rotas.post("/pessoas")
def adicionar_pessoa(dados: dict = Body(...)):
    with db.conexao() as con:
        _ou_400(checklist.adicionar_pessoa, con, dados.get("nome") or "")
        return checklist.pessoas(con)


@rotas.delete("/pessoas/{pid}")
def remover_pessoa(pid: int):
    with db.conexao() as con:
        checklist.remover_pessoa(con, pid)
        return checklist.pessoas(con)


@rotas.get("/agenda/alertas")
def alertas():
    with db.conexao() as con:
        agenda.gerar_semanais(con)  # roda ao abrir o app, antes de contar os alertas
        cont = agenda.alertas(con)
        # prazo fatal interno dos cards do quadro (o processual já é uma tarefa da agenda e já foi contado)
        for c in quadro.carregar(con)["cards"]:
            p = c["prazo"]
            if p and p["tipo"] == "interno" and p["urgencia"] in ("vencido", "hoje", "amanha"):
                cont["vencidos" if p["urgencia"] == "vencido" else p["urgencia"]] += 1
        return cont


@rotas.post("/agenda")
def criar(dados: dict = Body(...)):
    if not (dados.get("titulo") or "").strip():
        raise HTTPException(400, "Informe o título")
    if "checklist" not in dados:  # tarefa criada por ela nasce com a checklist padrão (a tela já manda preenchida)
        dados["checklist"] = checklist.padrao("processo")
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


@rotas.post("/agenda/{tid}/restaurar")
def restaurar(tid: int):
    with db.conexao() as con:
        if not agenda.restaurar(con, tid):
            raise HTTPException(404, "Tarefa não está em Concluídos")
        return agenda.obter(con, tid)


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
