"""Servidor (FastAPI): API JSON + interface estática. No computador escuta só em 127.0.0.1 (ver run.py); na
Vercel roda como função (api/index.py). Toda a API exige login (app/auth.py); os dados ficam no Supabase."""
import logging
import re

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, banco_antigo, cnj, config, db, interligar, rotas_agenda, rotas_financeiro, rotas_quadro, sync
from .config import STATIC_DIR

config.configurar_log()
log = logging.getLogger("app")

app = FastAPI(title="Processos", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(auth.ExigirLogin)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(rotas_agenda.rotas)
app.include_router(rotas_quadro.rotas)
app.include_router(rotas_financeiro.rotas)

SEM_CACHE = {"Cache-Control": "no-cache"}


@app.exception_handler(db.Conflito)
async def conflito(request, e: db.Conflito):
    """Card, tarefa ou lançamento salvo por outra pessoa depois que a tela o leu: a tela pergunta o que fazer."""
    return JSONResponse({"detail": str(e)}, status_code=409)


@app.middleware("http")
async def revalidar_estaticos(request, call_next):
    """Faz o navegador sempre conferir se CSS/JS mudaram (evita tela antiga após atualizar o app)."""
    resposta = await call_next(request)
    if request.url.path.startswith("/static/"):
        resposta.headers["Cache-Control"] = "no-cache"
    return resposta


def _numero(numero: str) -> str:
    n = cnj.so_digitos(numero)
    if len(n) != 20:
        raise HTTPException(400, "Número de processo inválido")
    return n


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers=SEM_CACHE)


@app.get("/api/ping")
def ping():
    return {"app": "processos-beatriz"}


@app.get("/api/publico")
def publico():
    """O que a tela precisa para o login: endereço do Supabase e a chave pública (anon). Nada de segredo aqui."""
    return {"supabase_url": config.ambiente("SUPABASE_URL"), "supabase_anon_key": config.ambiente("SUPABASE_ANON_KEY")}


@app.get("/api/estado")
def estado():
    with db.conexao() as con:
        db.garantir_padroes(con)  # tipos de ato e feriados dos próximos anos, se ainda não existirem
        interligar.migrar(con)  # uma vez só: clientes dos processos que já existiam e o Kanban antigo do Monitoramento
        cfg = config.efetiva(con)
        visiveis = f"NOT {db.COOPERACAO_SQL}" if cfg["ocultar_cooperacao"] else "true"
        total = con.execute(f"SELECT COUNT(*) FROM processos WHERE {visiveis}").fetchone()[0]
        novos = con.execute(f"SELECT COUNT(*) FROM processos WHERE {visiveis} AND novidade_em IS NOT NULL "
                            "AND (visto_em IS NULL OR novidade_em > visto_em)").fetchone()[0]
        ultima = db.meta_get(con, "ultima_atualizacao")
        advogadas = db.advogadas(con)
        banco_local = banco_antigo.situacao(con)  # "pendente": a pasta db/ deste computador tem dados fora do Supabase
    eu = db.usuaria_atual() or {}
    return {
        "advogadas": advogadas, "tem_chave": bool(cfg["datajud_api_key"]), "ultima_atualizacao": ultima,
        "total": total, "novos": novos, "sync": sync.status(), "usuaria": eu.get("email"), "banco_local": banco_local,
    }


@app.get("/api/processos")
def processos(tribunal: str = "", q: str = "", novidades: bool = False, advogada: int | None = None,
              incluir_cooperacao: bool = False):
    """incluir_cooperacao: para as listas de escolha (vincular card/lançamento), que mostram todos os processos."""
    with db.conexao() as con:
        ocultar = config.efetiva(con)["ocultar_cooperacao"] and not incluir_cooperacao
        lista = db.listar(con, tribunal=tribunal, q=q.strip(), so_novidades=novidades)
        filtros = db.opcoes_filtros(con)
        advogadas = db.advogadas(con)
    # Processos em cooperação: com a opção ligada, somem da lista e dos contadores (o aviso diz quantos)
    coop = [p for p in lista if p["cooperacao"] and (not advogada or advogada in p["advogadas"])]
    if ocultar:
        lista = [p for p in lista if not p["cooperacao"]]
    # Contadores por advogada respeitam os outros filtros (o de advogada é aplicado depois)
    contadores = {"todas": {"total": len(lista), "novos": sum(p["novo"] for p in lista)}}
    for a in advogadas:
        dela = [p for p in lista if a["id"] in p["advogadas"]]
        contadores[a["id"]] = {"total": len(dela), "novos": sum(p["novo"] for p in dela)}
    if advogada:
        lista = [p for p in lista if advogada in p["advogadas"]]
    filtros["advogadas"] = advogadas
    return {"processos": lista, "filtros": filtros, "contadores": contadores,
            "cooperacao": {"ocultar": ocultar, "qtd": len(coop)}}


@app.get("/api/processos/{numero}")
def processo(numero: str):
    with db.conexao() as con:
        p = db.detalhe(con, _numero(numero))
        if p:  # cliente(s) deste processo, para o painel abrir o card
            p["clientes"] = [dict(r) for r in con.execute("SELECT id, nome FROM clientes WHERE numero=%s ORDER BY id",
                                                          (p["numero"],))]
    if not p:
        raise HTTPException(404, "Processo não encontrado")
    return p


@app.post("/api/processos/{numero}/visto")
def marcar_visto(numero: str):
    with db.conexao() as con:
        con.execute("UPDATE processos SET visto_em=%s WHERE numero=%s", (db.agora(), _numero(numero)))
    return {"ok": True}


@app.post("/api/processos/{numero}/cooperacao")
def marcar_cooperacao(numero: str, dados: dict = Body(...)):
    """Marcação à mão: {"cooperacao": true|false|null}; null (ou igual à automática) volta a seguir a automática."""
    valor = dados.get("cooperacao")
    with db.conexao() as con:
        if not db.marcar_cooperacao(con, _numero(numero), None if valor is None else bool(valor)):
            raise HTTPException(404, "Processo não encontrado")
    return {"ok": True}


@app.post("/api/visto-todos")
def marcar_todos_vistos(advogada: int | None = None):
    with db.conexao() as con:
        if advogada:  # com o filtro de advogada ativo, só marca os processos dela
            con.execute("UPDATE processos SET visto_em=%s WHERE numero IN "
                        "(SELECT numero FROM processo_advogada WHERE advogada_id=%s)", (db.agora(), advogada))
        else:
            con.execute("UPDATE processos SET visto_em=%s", (db.agora(),))
    return {"ok": True}


@app.post("/api/processos/{numero}/atualizar")
def atualizar_um(numero: str):
    return sync.atualizar_um(_numero(numero))


@app.delete("/api/processos/{numero}")
def remover(numero: str):
    with db.conexao() as con:
        db.remover_processo(con, _numero(numero))
    return {"ok": True}


class Adicionar(BaseModel):
    texto: str
    advogadas: list[int] = []  # vazio = primeira advogada (comportamento de antes)


@app.post("/api/processos/adicionar")
def adicionar(dados: Adicionar):
    """Recebe texto livre (colado, CSV ou TXT), extrai números CNJ e cadastra os válidos para as advogadas escolhidas."""
    numeros = cnj.extrair_numeros(dados.texto)
    invalidos = [cnj.formatar(n) for n in numeros if not cnj.digito_valido(n)]
    novos, existentes = [], []
    with db.conexao() as con:
        validas = [a["id"] for a in db.advogadas(con)]
        escolhidas = [i for i in dados.advogadas if i in validas] or validas[:1]
        for n in numeros:
            if cnj.digito_valido(n):
                (novos if db.garantir_processo(con, n, "manual") else existentes).append(n)
                for adv_id in escolhidas:  # se já existia, só acrescenta a advogada
                    db.vincular(con, n, adv_id, "manual")
        for n in novos:
            db.recalcular_resumo(con, n)
        interligar.garantir_clientes(con, novos)  # cada processo novo já ganha o cliente (card em Clientes)
    consultando = False
    if novos:
        consultando = sync.iniciar(djen=False, datajud=True, numeros=novos) or sync.rodando()
    log.info("Adicionados %d processos (%d já existiam, %d inválidos)", len(novos), len(existentes), len(invalidos))
    return {
        "encontrados": len(numeros), "novos": [cnj.formatar(n) for n in novos],
        "existentes": [cnj.formatar(n) for n in existentes], "invalidos": invalidos, "consultando": consultando,
    }


@app.post("/api/sync")
def iniciar_sync():
    """Começa (ou retoma) a atualização; a tela chama /api/sync/passo até acabar."""
    iniciou = sync.iniciar(djen=True, datajud=True)
    return {"iniciou": iniciou, "sync": sync.status()}


@app.post("/api/sync/passo")
def passo_sync():
    return sync.passo()


@app.get("/api/sync")
def status_sync():
    return sync.status()


class AdvogadaEditavel(BaseModel):
    oab_numero: str
    oab_uf: str
    nome: str | None = None
    cor: str | None = None


class AdvogadoCooperacao(BaseModel):
    nome: str = ""
    oab_numero: str = ""
    oab_uf: str = ""


class Configuracao(BaseModel):
    datajud_api_key: str | None = None
    backfill_dias: int | None = None
    advogadas: list[AdvogadaEditavel] | None = None  # só nome e cor; a OAB identifica quem é
    ocultar_cooperacao: bool | None = None
    advogados_cooperacao: list[AdvogadoCooperacao] | None = None


@app.get("/api/config")
def ler_config():
    with db.conexao() as con:
        cfg = config.efetiva(con)
        advogadas = db.advogadas(con)
    chave = cfg["datajud_api_key"]
    return {"tem_chave": bool(chave), "chave_final": chave[-6:] if chave else "", "backfill_dias": cfg["backfill_dias"],
            "advogadas": advogadas, "ocultar_cooperacao": cfg["ocultar_cooperacao"],
            "advogados_cooperacao": cfg["advogados_cooperacao"]}


@app.post("/api/config")
def salvar_config(dados: Configuracao):
    """Ajustes da tela: ficam no banco (no servidor não dá para gravar o config.json)."""
    with db.conexao() as con:
        if dados.datajud_api_key is not None:
            config.ajustar(con, datajud_api_key=config.normalizar_chave(dados.datajud_api_key))
        if dados.backfill_dias is not None:
            config.ajustar(con, backfill_dias=max(1, min(int(dados.backfill_dias), 730)))
        for ed in dados.advogadas or []:
            nome = (ed.nome or "").strip()
            cor = ed.cor if ed.cor and re.fullmatch(r"#[0-9a-fA-F]{6}", ed.cor) else None
            con.execute("""UPDATE advogadas SET nome=COALESCE(NULLIF(%s, ''), nome), cor=COALESCE(%s, cor)
                           WHERE oab_numero=%s AND oab_uf=%s""", (nome, cor, ed.oab_numero.strip(), ed.oab_uf.strip().upper()))
        if dados.ocultar_cooperacao is not None:
            config.ajustar(con, ocultar_cooperacao=dados.ocultar_cooperacao)
        if dados.advogados_cooperacao is not None:
            antes = config.cooperacao(con)
            novo = config.salvar_cooperacao(con, [a.model_dump() for a in dados.advogados_cooperacao])
            if novo != antes:  # lista mudou: refaz a marcação automática de todos os processos
                log.info("Advogados de cooperação alterados: %d processo(s) em cooperação",
                         db.atualizar_cooperacao(con, lista=novo))
    return ler_config()
