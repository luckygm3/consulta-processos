"""Rotas do Monitoramento (sugestões: aprovar leva ao checklist do cliente), da Agenda (calendário), da verificação de
prazos, dos feriados e dos tipos de ato."""
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from . import agenda, checklist, cnj, config, db, financeiro, interligar, prazos, quadro

rotas = APIRouter(prefix="/api")


def _ou_400(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dados inválidos")


@rotas.get("/agenda")
def listar():
    """Monitoramento: sugestões aguardando aprovação + cards do quadro (para onde cada uma vai ao ser aprovada)."""
    with db.conexao() as con:
        interligar.migrar(con)
        agenda.gerar_semanais(con)
        return {"tarefas": agenda.listar(con), "cards": quadro.carregar(con)["cards"], "pessoas": checklist.pessoas(con),
                "regras": agenda.regras()}


@rotas.get("/calendario")
def calendario(de: str, ate: str):
    """Tudo o que vai para a Agenda (calendário único): cards do quadro (a tela tira deles os itens de checklist com
    data, inclusive as tarefas aprovadas no Monitoramento, e o prazo fatal interno), aniversários e lembretes das
    parcelas. Sugestões ainda não aprovadas não entram."""
    with db.conexao() as con:
        _ou_400(lambda: (date.fromisoformat(de), date.fromisoformat(ate)))
        interligar.migrar(con)
        return {"cards": quadro.carregar(con)["cards"], "pessoas": checklist.pessoas(con),
                "aniversarios": quadro.aniversarios(con, de, ate),
                "parcelas": financeiro.lembretes(financeiro.listar(con), de, ate)}


@rotas.post("/lembretes")
def lembrete(dados: dict = Body(...)):
    """Marca/desmarca um lembrete calculado (por ora, o aniversário de um ano) como feito."""
    with db.conexao() as con:
        _ou_400(quadro.marcar_lembrete, con, str(dados.get("chave") or ""), bool(dados.get("feito")))
    return {"ok": True}


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
        interligar.migrar(con)
        agenda.gerar_semanais(con)  # roda ao abrir o app, antes de contar os alertas
        cont = agenda.alertas(con)  # sugestões no Monitoramento
        # tarefas aprovadas (itens dos clientes vindos do Monitoramento, menos a verificação semanal de sigilosos) e
        # prazo fatal interno dos cards
        urgentes = ("vencido", "hoje", "amanha")
        for c in quadro.carregar(con)["cards"]:
            datas = [i["urgencia"] for i in c["checklist"] if i.get("urgencia") in urgentes and i.get("origem") != "sigilo"]
            p = c["prazo"]
            if p and p["tipo"] == "interno" and p["urgencia"] in urgentes:
                datas.append(p["urgencia"])
            for u in datas:
                cont["vencidos" if u == "vencido" else u] += 1
        return cont


@rotas.post("/agenda")
def criar(dados: dict = Body(...)):
    """Tarefa criada por ela (Agenda, painel do processo): não passa pelo Monitoramento, vai direto para o checklist do
    cliente escolhido (ou o do processo)."""
    if not (dados.get("titulo") or "").strip():
        raise HTTPException(400, "Informe o título")
    dados = {k: v for k, v in dados.items() if k != "checklist"}
    with db.conexao() as con:
        tid = _ou_400(agenda.criar, con, {**dados, "status": "sugerido", "origem": "manual"})
        cid = _ou_400(interligar.adicionar_ao_cliente, con, tid, dados.get("cliente_id"))
        nome = con.execute("SELECT nome FROM clientes WHERE id=%s", (cid,)).fetchone()[0]
        return {"id": tid, "cliente_id": cid, "cliente": nome}


@rotas.patch("/agenda/{tid}")
def atualizar(tid: int, dados: dict = Body(...)):
    with db.conexao() as con:
        _ou_400(agenda.atualizar, con, tid, dados)
        t = agenda.obter(con, tid)
    if not t:
        raise HTTPException(404, "Tarefa não encontrada")
    return t


@rotas.post("/agenda/aprovar")
def aprovar(dados: dict = Body(...)):
    """Aprova sugestões: cada uma vira item do checklist do cliente (o escolhido, ou o do processo; sem card, cria)."""
    ids = [int(i) for i in dados.get("ids") or []]
    cliente = int(dados["cliente_id"]) if str(dados.get("cliente_id") or "").isdigit() else None
    with db.conexao() as con:
        return interligar.aprovar(con, ids, cliente)


@rotas.post("/agenda/rejeitar")
def rejeitar(dados: dict = Body(...)):
    """Tira do Monitoramento (fica guardada como descartada: a publicação não sugere de novo)."""
    ids = [int(i) for i in dados.get("ids") or []]
    with db.conexao() as con:
        return {"rejeitadas": interligar.rejeitar(con, ids)}


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
        con.execute("UPDATE processos SET contagem=%s WHERE numero=%s", (valor, cnj.so_digitos(numero)))
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
        con.execute("DELETE FROM feriados WHERE id=%s", (fid,))
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
