"""Sincronização: DJEN (descobrir processos e publicações) + DataJud (enriquecer com classe, órgão e movimentos).

Roda em passos curtos, comandados pela tela: POST /api/sync começa (ou retoma) e POST /api/sync/passo trabalha
no máximo PASSO_SEGUNDOS e devolve o progresso; a tela chama o próximo passo até acabar. Onde parou fica gravado
no banco (meta "sync_estado"), então funciona igual no computador e no servidor da Vercel (onde cada requisição
tem tempo máximo). Fechar a tela só pausa: "Atualizar tudo" de novo continua de onde estava.
"""
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

from . import cnj, config, db, interligar
from .datajud import TAMANHO_LOTE, DatajudChaveInvalida, DatajudClient, DatajudErro
from .djen import DjenClient, DjenErro
from .tempo import TempoEsgotado

log = logging.getLogger("sync")

SOBREPOSICAO_DIAS = 3    # na sincronização incremental, relê alguns dias (publicações chegam atrasadas)
PARALELO_DATAJUD = 3     # consultas simultâneas ao DataJud (tribunais diferentes)
PASSO_SEGUNDOS = float(os.environ.get("SYNC_PASSO_SEGUNDOS") or 20)  # trabalho novo só começa dentro deste tempo
FOLGA_SEGUNDOS = 25      # e nenhuma consulta passa deste limite extra (passo < 60 s, o máximo configurado na Vercel)
TENTATIVAS_POR_PEDACO = 3  # um período/lote que estoura o tempo do passo 3 vezes vira erro (e a sincronização segue)
MSG_PARCIAL = "O DataJud respondeu só parcialmente (servidor sobrecarregado). Tente de novo mais tarde."
NOME_FASE = {"djen": "Publicações (DJEN)", "datajud": "Movimentos (DataJud)", "fim": "Concluído"}


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# --- estado gravado no banco -------------------------------------------------------

def _ler(con) -> dict | None:
    valor = db.meta_get(con, "sync_estado")
    return json.loads(valor) if valor else None


def _gravar(con, estado: dict):
    db.meta_set(con, "sync_estado", json.dumps(estado, ensure_ascii=False))


def _erro(con, estado: dict, fonte: str, tribunal: str, mensagem: str):
    log.error("[%s %s] %s", fonte, tribunal, mensagem)
    con.execute("INSERT INTO sync_erros(sync_id, quando, fonte, tribunal, mensagem) VALUES(%s,%s,%s,%s,%s)",
                (estado["id"], db.agora(), fonte, tribunal, mensagem))


def status() -> dict:
    """O que a tela mostra: a sincronização em andamento, ou a última que terminou."""
    with db.conexao() as con:
        estado = _ler(con)
        if estado:
            saida = {k: estado.get(k) for k in ("id", "rodando", "inicio", "fim", "atual", "total", "mensagem", "completo")}
            saida["fase"] = NOME_FASE.get(estado.get("fase"), "")
            saida["resumo"] = " · ".join(estado.get("resumo") or [])
        else:  # nada rodou ainda neste banco (ou só o resumo antigo, de antes da migração)
            ultimo = json.loads(db.meta_get(con, "ultimo_sync") or "{}")
            saida = {"rodando": False, "fase": "", "atual": 0, "total": 0, "mensagem": "", "inicio": None, "fim": None,
                     "resumo": "", "id": None, **ultimo}
        saida["erros"] = [dict(r) for r in con.execute(
            "SELECT fonte, tribunal, mensagem, quando FROM sync_erros WHERE sync_id=%s ORDER BY id", (saida.get("id"),))]
    return saida


def rodando() -> bool:
    with db.conexao() as con:
        estado = _ler(con)
    return bool(estado and estado.get("rodando"))


def iniciar(djen: bool = True, datajud: bool = True, numeros: list[str] | None = None) -> bool:
    """Prepara uma sincronização. Se já houver uma em andamento (ou pausada), não começa outra: a tela só continua
    chamando os passos dela. Devolve True se começou uma nova."""
    with db.conexao() as con:
        atual = _ler(con)
        if atual and atual.get("rodando"):
            return False
        cfg = config.efetiva(con)
        estado = {
            "id": uuid.uuid4().hex[:12], "rodando": True, "inicio": db.agora(), "fim": None, "completo": djen,
            "pedido": {"djen": djen, "datajud": datajud, "numeros": numeros},
            "fase": "djen" if djen else "datajud", "atual": 0, "total": 0, "mensagem": "Preparando…", "resumo": [],
            "djen": _plano_djen(con, cfg) if djen else None, "datajud": None,
        }
        if djen:
            estado["total"] = sum(len(a["janelas"]) for a in estado["djen"]["advs"])
        _gravar(con, estado)
    log.info("Sincronização %s preparada (djen=%s, datajud=%s)", estado["id"], djen, datajud)
    return True


# --- trava: só um passo por vez (duas abas abertas não fazem o trabalho em dobro) ---------------

def _pegar_trava(con, segundos: float) -> bool:
    agora = datetime.now()
    ate = (agora + timedelta(seconds=segundos)).isoformat(timespec="seconds")
    r = con.execute("""INSERT INTO meta(chave, valor) VALUES('sync_trava', %s)
                       ON CONFLICT (chave) DO UPDATE SET valor=excluded.valor WHERE meta.valor < %s
                       RETURNING chave""", (ate, agora.isoformat(timespec="seconds"))).fetchone()
    return r is not None


def _soltar_trava(con):
    con.execute("DELETE FROM meta WHERE chave='sync_trava'")  # o próximo passo pode pegar na hora


def passo(segundos: float = PASSO_SEGUNDOS) -> dict:
    """Trabalha por até `segundos` e devolve o status (com "ocupado": True se outro passo estiver rodando)."""
    comeco = time.monotonic()
    ate, limite = comeco + segundos, comeco + segundos + FOLGA_SEGUNDOS
    with db.conexao() as con:
        if not _pegar_trava(con, segundos + FOLGA_SEGUNDOS + 10):
            return {**status_rapido(con), "ocupado": True}
        estado = _ler(con)
        cfg = config.efetiva(con)
    clientes: dict = {}  # cliente HTTP do DJEN reaproveitado no passo (respeita o intervalo entre consultas)
    try:
        while estado and estado.get("rodando") and time.monotonic() < ate:
            if estado["fase"] == "djen":
                _unidade_djen(estado, cfg, limite, clientes)
            elif estado["fase"] == "datajud":
                _unidade_datajud(estado, cfg, limite)
            else:
                _concluir(estado)
    except TempoEsgotado as e:
        log.info("Passo parou no limite de tempo (%s); continua no próximo", e)
    finally:
        for cli in clientes.values():
            cli.close()
        with db.conexao() as con:
            _soltar_trava(con)
    return status()


def status_rapido(con) -> dict:
    estado = _ler(con) or {}
    return {"rodando": bool(estado.get("rodando")), "fase": NOME_FASE.get(estado.get("fase"), ""),
            "atual": estado.get("atual", 0), "total": estado.get("total", 0), "mensagem": estado.get("mensagem", ""),
            "id": estado.get("id"), "erros": []}


def _concluir(estado: dict):
    estado.update(rodando=False, fim=db.agora(), fase="fim", mensagem="")
    with db.conexao() as con:
        _gravar(con, estado)
        db.meta_set(con, "ultimo_sync", json.dumps({k: estado[k] for k in ("id", "inicio", "fim", "completo")}
                                                   | {"resumo": " · ".join(estado["resumo"])}, ensure_ascii=False))
        if estado["pedido"]["djen"]:
            db.meta_set(con, "ultima_atualizacao", estado["fim"])
    log.info("Sincronização %s concluída: %s", estado["id"], " · ".join(estado["resumo"]))


# --- DJEN: uma janela de datas de uma advogada por vez ------------------------------------------

def _janelas(con, cfg, adv: dict) -> list[list[str]]:
    hoje = date.today()
    ultima = db.meta_get(con, db.chave_marco(adv))
    if ultima:
        inicio = date.fromisoformat(ultima) - timedelta(days=SOBREPOSICAO_DIAS)
    else:
        inicio = hoje - timedelta(days=int(cfg["backfill_dias"]))
    passo_dias = max(1, int(cfg["janela_dias"]))
    janelas, a = [], inicio
    while a <= hoje:
        b = min(a + timedelta(days=passo_dias - 1), hoje)
        janelas.append([a.isoformat(), b.isoformat()])
        a = b + timedelta(days=1)
    return janelas


def _plano_djen(con, cfg) -> dict:
    advs = [{"id": a["id"], "nome": a["nome"], "oab_numero": a["oab_numero"], "oab_uf": a["oab_uf"],
             "janelas": _janelas(con, cfg, a), "i": 0, "falhou": False, "tentativas": 0, "processos": []}
            for a in db.advogadas(con) if a["oab_numero"] and a["oab_uf"]]
    return {"advs": advs, "k": 0, "lidas": 0, "novas": 0}


def _buscar_janela(cli: DjenClient, cfg, adv: dict, a: date, b: date) -> list[dict]:
    oab, uf, nome = adv["oab_numero"], adv["oab_uf"], adv["nome"].strip()
    if len(nome.split()) < 2:
        nome = ""  # nome incompleto (ex.: só o primeiro) traria publicações de homônimos
    itens = []
    if oab and uf:
        try:
            itens = list(cli.comunicacoes(a, b, numero_oab=oab, uf_oab=uf))
        except DjenErro as e:
            if not nome:
                raise
            log.warning("Busca por OAB falhou (%s); tentando pelo nome", e)
            return list(cli.comunicacoes(a, b, nome_advogado=nome))
    if nome and (not (oab and uf) or cfg.get("buscar_tambem_por_nome")):
        itens += list(cli.comunicacoes(a, b, nome_advogado=nome))
    return itens


def _unidade_djen(estado: dict, cfg: dict, limite: float, clientes: dict):
    dj = estado["djen"]
    if dj["k"] >= len(dj["advs"]):  # todas as advogadas lidas: resumo e próxima fase
        processos = {n for a in dj["advs"] for n in a["processos"]}
        por_adv = [f"{a['nome']}: {len(a['processos'])}" for a in dj["advs"]]
        estado["resumo"].append(f"DJEN: {dj['lidas']} publicações lidas, {dj['novas']} novas, {len(processos)} processos"
                                + (f" ({', '.join(por_adv)})" if len(por_adv) > 1 else "")
                                + (f", {dj['clientes']} clientes novos em Clientes" if dj.get("clientes") else ""))
        estado["fase"] = "datajud" if estado["pedido"]["datajud"] else "fim"
        with db.conexao() as con:
            _gravar(con, estado)
        return
    adv = dj["advs"][dj["k"]]
    if adv["i"] >= len(adv["janelas"]):
        dj["k"] += 1
        return
    a, b = (date.fromisoformat(x) for x in adv["janelas"][adv["i"]])
    estado["mensagem"] = f"{adv['nome']}: publicações de {_br(a)} a {_br(b)}"
    if "djen" not in clientes:
        clientes["djen"] = DjenClient(prazo=limite)
    cli = clientes["djen"]
    try:
        itens = _buscar_janela(cli, cfg, adv, a, b)
    except TempoEsgotado:
        adv["tentativas"] += 1
        if adv["tentativas"] < TENTATIVAS_POR_PEDACO:
            with db.conexao() as con:
                _gravar(con, estado)
            raise
        itens, falha = None, "o DJEN demorou demais para responder"
    except DjenErro as e:
        itens, falha = None, str(e)
    with db.conexao() as con:
        if itens is None:
            _erro(con, estado, "DJEN", adv["nome"], f"Período {_br(a)} a {_br(b)}: {falha}")
            adv["falhou"] = True  # o marco desta advogada para aqui: o período é relido na próxima sincronização
        else:
            tocados = set()
            for it in itens:
                dj["lidas"] += 1
                try:
                    with db.savepoint(con):
                        if db.salvar_comunicacao(con, it, adv["id"]):
                            dj["novas"] += 1
                    tocados.add(cnj.so_digitos(it.get("numero_processo") or ""))
                except Exception as e:  # um item estranho não derruba a janela
                    log.exception("Erro ao gravar comunicação %s", it.get("id"))
                    _erro(con, estado, "DJEN", it.get("siglaTribunal") or "", f"Publicação {it.get('id')}: {e}")
            tocados.discard("")
            for n in tocados:
                db.recalcular_resumo(con, n)
            try:  # processo novo já ganha o cliente (card em Clientes), depois da marcação de cooperação acima
                with db.savepoint(con):
                    dj["clientes"] = dj.get("clientes", 0) + interligar.garantir_clientes(con, tocados)
            except Exception as e:  # não trava a sincronização: o card é criado na próxima janela que tocar o processo
                log.exception("Erro ao criar clientes dos processos")
                _erro(con, estado, "Clientes", "", f"Clientes dos processos novos não criados: {e}")
            adv["processos"] = sorted(set(adv["processos"]) | tocados)
            if not adv["falhou"]:
                db.meta_set(con, db.chave_marco(adv), b.isoformat())  # só avança em janelas contíguas sem erro
        adv["i"] += 1
        adv["tentativas"] = 0
        estado["atual"] += 1
        _gravar(con, estado)


# --- DataJud: alguns lotes (um tribunal cada) por vez ---------------------------------------------

def _plano_datajud(con, cfg, numeros: list[str] | None) -> dict:
    if numeros:
        linhas = list(con.execute("SELECT numero, alias, tribunal FROM processos WHERE numero = ANY(%s)", (numeros,)))
    else:
        linhas = list(con.execute("SELECT numero, alias, tribunal FROM processos"))
    for r in linhas:
        if not r["alias"]:
            db.marcar_datajud(con, r["numero"], "sem_alias", f"{r['tribunal']} não publica no DataJud")
    grupos = defaultdict(list)
    for r in linhas:
        if r["alias"]:
            grupos[r["alias"]].append(r["numero"])
    lotes = [[alias, nums[i:i + TAMANHO_LOTE]] for alias, nums in grupos.items() for i in range(0, len(nums), TAMANHO_LOTE)]
    return {"lotes": lotes, "tentativas": {}, "com_dados": 0, "sem_dados": 0, "movs_novos": 0, "incertos": 0,
            "extra_feito": bool(numeros), "consultados": [n for _, ns in lotes for n in ns]}


def _unidade_datajud(estado: dict, cfg: dict, limite: float):
    if estado["datajud"] is None:
        with db.conexao() as con:
            estado["datajud"] = _plano_datajud(con, cfg, estado["pedido"]["numeros"])
            estado["atual"], estado["total"] = 0, sum(len(ns) for _, ns in estado["datajud"]["lotes"])
            if not cfg["datajud_api_key"]:
                _erro(con, estado, "DataJud", "", "Chave do DataJud não configurada: só as publicações do DJEN foram "
                                                  "atualizadas. Clique em Configurações e cole a chave (veja o README).")
                estado["resumo"].append("DataJud: sem chave")
                estado["fase"] = "fim"
            _gravar(con, estado)
        return
    dt = estado["datajud"]
    if not dt["lotes"]:
        if not dt["extra_feito"]:  # processos que entraram durante a sincronização e ainda não foram consultados
            dt["extra_feito"] = True
            with db.conexao() as con:
                extra = [r[0] for r in con.execute("SELECT numero FROM processos WHERE datajud_status IS NULL AND alias IS NOT NULL")
                         if r[0] not in set(dt["consultados"])]
                if extra:
                    plano = _plano_datajud(con, cfg, extra)
                    dt["lotes"], dt["consultados"] = plano["lotes"], dt["consultados"] + plano["consultados"]
                    estado["total"] += len(plano["consultados"])
                _gravar(con, estado)
            return
        resumo = f"DataJud: {dt['com_dados']} com dados, {dt['sem_dados']} sem dados públicos, {dt['movs_novos']} movimentos novos"
        estado["resumo"].append(resumo + (f", {dt['incertos']} não confirmados" if dt["incertos"] else ""))
        estado["fase"] = "fim"
        with db.conexao() as con:
            _gravar(con, estado)
        return

    vez = dt["lotes"][:PARALELO_DATAJUD]
    estado["mensagem"] = "Consultando " + ", ".join(sorted({cnj.tribunal(ns[0])[0] for _, ns in vez}))

    def consultar(alias, nums):
        with DatajudClient(cfg["datajud_api_key"], prazo=limite) as cli:
            return cli.buscar_lote(alias, nums)

    resultados = []
    with ThreadPoolExecutor(max_workers=len(vez)) as ex:
        futuros = {ex.submit(consultar, alias, nums): (alias, nums) for alias, nums in vez}
        for fut in as_completed(futuros):
            alias, nums = futuros[fut]
            try:
                resultados.append((alias, nums, fut.result(), None))
            except Exception as e:  # noqa: BLE001 - cada lote decide o que fazer com o erro abaixo
                resultados.append((alias, nums, None, e))

    esgotou = False
    with db.conexao() as con:
        for alias, nums, resultado, erro in resultados:
            sigla = cnj.tribunal(nums[0])[0]
            chave_lote = f"{alias}|{nums[0]}"
            if isinstance(erro, TempoEsgotado):
                dt["tentativas"][chave_lote] = dt["tentativas"].get(chave_lote, 0) + 1
                if dt["tentativas"][chave_lote] < TENTATIVAS_POR_PEDACO:
                    esgotou = True
                    continue  # fica na fila; tenta no próximo passo
                erro = DatajudErro("o DataJud demorou demais para responder")
            dt["lotes"].remove([alias, nums])
            if isinstance(erro, DatajudChaveInvalida):
                _erro(con, estado, "DataJud", "", str(erro))
                dt["lotes"] = []  # sem chave válida, não adianta consultar o resto
            elif erro is not None:
                _erro(con, estado, "DataJud", sigla, f"{len(nums)} processo(s) não consultado(s): {erro}")
                for n in nums:
                    db.marcar_datajud(con, n, "erro", str(erro))
            else:
                hits_por_numero, completo = resultado
                nao_confirmados = 0
                for n, hits in hits_por_numero.items():
                    try:
                        with db.savepoint(con):
                            if hits:
                                dt["movs_novos"] += db.salvar_datajud(con, n, hits, completo)
                                dt["com_dados"] += 1
                            elif completo:
                                db.marcar_datajud(con, n, "sem_dados")
                                dt["sem_dados"] += 1
                            else:  # resposta parcial: não dá para afirmar que não há dados
                                db.marcar_datajud(con, n, "erro", MSG_PARCIAL)
                                nao_confirmados += 1
                            db.recalcular_resumo(con, n)
                    except Exception as e:  # dado estranho de um processo não estraga o lote
                        log.exception("Erro ao gravar %s", n)
                        _erro(con, estado, "DataJud", sigla, f"{cnj.formatar(n)}: erro ao gravar ({e})")
                if nao_confirmados:
                    dt["incertos"] += nao_confirmados
                    _erro(con, estado, "DataJud", sigla, f"{nao_confirmados} processo(s) sem resposta completa (servidor do "
                                                         "DataJud sobrecarregado); serão consultados de novo na próxima atualização")
            estado["atual"] += len(nums)
        estado["mensagem"] = f"{estado['atual']} de {estado['total']} processos consultados"
        _gravar(con, estado)
    if esgotou:
        raise TempoEsgotado("lote do DataJud continua no próximo passo")


# --- ações pontuais --------------------------------------------------------------------

def atualizar_um(numero: str) -> dict:
    """Consulta um único processo no DataJud agora (botão no painel lateral)."""
    _, alias = cnj.tribunal(numero)
    with db.conexao() as con:
        cfg = config.efetiva(con)
        if not alias:
            db.marcar_datajud(con, numero, "sem_alias", "Tribunal não publica no DataJud")
            return {"ok": False, "mensagem": "Este tribunal não publica no DataJud."}
    if not cfg["datajud_api_key"]:
        return {"ok": False, "mensagem": "Configure a chave do DataJud primeiro."}
    try:
        with DatajudClient(cfg["datajud_api_key"], prazo=time.monotonic() + PASSO_SEGUNDOS + FOLGA_SEGUNDOS) as cli:
            hits, completo = cli.buscar(numero)
    except TempoEsgotado:
        return {"ok": False, "mensagem": "O DataJud está demorando demais. Tente de novo daqui a pouco."}
    except DatajudErro as e:
        with db.conexao() as con:
            db.marcar_datajud(con, numero, "erro", str(e))
        return {"ok": False, "mensagem": str(e)}
    with db.conexao() as con:
        if hits:
            novos = db.salvar_datajud(con, numero, hits, completo)
            msg = f"{novos} movimento(s) novo(s)." if novos else "Nenhum movimento novo."
        elif completo:
            db.marcar_datajud(con, numero, "sem_dados")
            msg = "Sem dados públicos no DataJud (possível segredo de justiça)."
        else:
            db.marcar_datajud(con, numero, "erro", MSG_PARCIAL)
            msg = MSG_PARCIAL
        db.recalcular_resumo(con, numero)
    return {"ok": bool(hits or completo), "mensagem": msg}
