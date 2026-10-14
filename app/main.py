"""Servidor local (FastAPI): API JSON + interface estática. Escuta só em 127.0.0.1 (ver run.py)."""
import logging
import re

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cnj, config, db, rotas_agenda, rotas_financeiro, rotas_quadro
from .config import STATIC_DIR
from .sync import sincronizador

config.configurar_log()
db.iniciar()
log = logging.getLogger("app")

app = FastAPI(title="Processos", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(rotas_agenda.rotas)
app.include_router(rotas_quadro.rotas)
app.include_router(rotas_financeiro.rotas)

SEM_CACHE = {"Cache-Control": "no-cache"}


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


@app.get("/api/estado")
def estado():
    cfg = config.carregar()
    visiveis = f"{db.COOPERACAO_SQL} = 0" if cfg["ocultar_cooperacao"] else "1=1"
    with db.conexao() as con:
        total = con.execute(f"SELECT COUNT(*) FROM processos WHERE {visiveis}").fetchone()[0]
        novos = con.execute(f"SELECT COUNT(*) FROM processos WHERE {visiveis} AND novidade_em IS NOT NULL "
                            "AND (visto_em IS NULL OR novidade_em > visto_em)").fetchone()[0]
        ultima = db.meta_get(con, "ultima_atualizacao")
        advogadas = db.advogadas(con)
    return {
        "nome": cfg["nome_advogado"], "oab": f"{cfg['oab_numero']}/{cfg['oab_uf']}".strip("/"),
        "advogadas": advogadas, "tem_chave": bool(cfg["datajud_api_key"]), "ultima_atualizacao": ultima,
        "total": total, "novos": novos, "sync": sincronizador.status(),
    }


@app.get("/api/processos")
def processos(tribunal: str = "", q: str = "", novidades: bool = False, advogada: int | None = None,
              incluir_cooperacao: bool = False):
    """incluir_cooperacao: para as listas de escolha (vincular card/lançamento), que mostram todos os processos."""
    ocultar = config.carregar()["ocultar_cooperacao"] and not incluir_cooperacao
    with db.conexao() as con:
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
    if not p:
        raise HTTPException(404, "Processo não encontrado")
    return p


@app.post("/api/processos/{numero}/visto")
def marcar_visto(numero: str):
    with db.conexao() as con:
        con.execute("UPDATE processos SET visto_em=? WHERE numero=?", (db.agora(), _numero(numero)))
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
            con.execute("UPDATE processos SET visto_em=? WHERE numero IN "
                        "(SELECT numero FROM processo_advogada WHERE advogada_id=?)", (db.agora(), advogada))
        else:
            con.execute("UPDATE processos SET visto_em=?", (db.agora(),))
    return {"ok": True}


@app.post("/api/processos/{numero}/atualizar")
def atualizar_um(numero: str):
    return sincronizador.atualizar_um(_numero(numero))


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
    consultando = False
    if novos:
        consultando = sincronizador.iniciar(djen=False, datajud=True, numeros=novos) or sincronizador.rodando()
    log.info("Adicionados %d processos (%d já existiam, %d inválidos)", len(novos), len(existentes), len(invalidos))
    return {
        "encontrados": len(numeros), "novos": [cnj.formatar(n) for n in novos],
        "existentes": [cnj.formatar(n) for n in existentes], "invalidos": invalidos, "consultando": consultando,
    }


@app.post("/api/sync")
def iniciar_sync():
    iniciou = sincronizador.iniciar(djen=True, datajud=True)
    return {"iniciou": iniciou, "sync": sincronizador.status()}


@app.get("/api/sync")
def status_sync():
    return sincronizador.status()


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
    cfg = config.carregar()
    chave = cfg["datajud_api_key"]
    return {"tem_chave": bool(chave), "chave_final": chave[-6:] if chave else "", "backfill_dias": cfg["backfill_dias"],
            "oab": f"{cfg['oab_numero']}/{cfg['oab_uf']}", "nome": cfg["nome_advogado"], "advogadas": cfg["advogadas"],
            "ocultar_cooperacao": cfg["ocultar_cooperacao"], "advogados_cooperacao": cfg["advogados_cooperacao"]}


@app.post("/api/config")
def salvar_config(dados: Configuracao):
    cfg = config.carregar(com_env=False)  # não grava no arquivo uma chave que veio do .env
    if dados.datajud_api_key is not None:
        cfg["datajud_api_key"] = config.normalizar_chave(dados.datajud_api_key)
    if dados.backfill_dias is not None:
        cfg["backfill_dias"] = max(1, min(int(dados.backfill_dias), 730))
    for ed in dados.advogadas or []:
        for a in cfg["advogadas"]:
            if (a["oab_numero"], a["oab_uf"]) == (ed.oab_numero.strip(), ed.oab_uf.strip().upper()):
                if ed.nome and ed.nome.strip():
                    a["nome"] = ed.nome.strip()
                if ed.cor and re.fullmatch(r"#[0-9a-fA-F]{6}", ed.cor):
                    a["cor"] = ed.cor
    if dados.ocultar_cooperacao is not None:
        cfg["ocultar_cooperacao"] = dados.ocultar_cooperacao
    lista_antes = cfg["advogados_cooperacao"]
    if dados.advogados_cooperacao is not None:
        cfg["advogados_cooperacao"] = [a.model_dump() for a in dados.advogados_cooperacao]
    config.salvar(cfg)
    novo = config.carregar(com_env=False)["advogados_cooperacao"]
    if novo != lista_antes:  # lista mudou: refaz a marcação automática de todos os processos
        with db.conexao() as con:
            log.info("Advogados de cooperação alterados: %d processo(s) em cooperação",
                     db.atualizar_cooperacao(con, lista=novo))
    return ler_config()
