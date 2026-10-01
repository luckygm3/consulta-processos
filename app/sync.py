"""Sincronização em segundo plano: DJEN (descobrir processos) + DataJud (enriquecer), com progresso para a interface."""
import json
import logging
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from . import cnj, config, db
from .datajud import TAMANHO_LOTE, DatajudChaveInvalida, DatajudClient, DatajudErro
from .djen import DjenClient, DjenErro

log = logging.getLogger("sync")

SOBREPOSICAO_DIAS = 3   # na sincronização incremental, relê alguns dias (publicações chegam atrasadas)
PARALELO_DATAJUD = 3    # consultas simultâneas ao DataJud (tribunais diferentes)
MSG_PARCIAL = "O DataJud respondeu só parcialmente (servidor sobrecarregado). Tente de novo mais tarde."


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class Sincronizador:
    def __init__(self):
        self._lock = threading.Lock()
        self._estado = self._vazio()

    @staticmethod
    def _vazio() -> dict:
        return {"rodando": False, "fase": "", "atual": 0, "total": 0, "mensagem": "", "erros": [],
                "inicio": None, "fim": None, "resumo": "", "id": None}

    # --- estado compartilhado com a interface -----------------------------

    def status(self) -> dict:
        with self._lock:
            estado = json.loads(json.dumps(self._estado))
        if not estado["rodando"] and not estado["id"]:
            # Nada rodou desde que o app abriu: mostra a última sincronização gravada no banco
            with db.conexao() as con:
                ultimo = db.meta_get(con, "ultimo_sync")
                if ultimo:
                    estado.update(json.loads(ultimo))
                    estado["erros"] = [dict(r) for r in con.execute(
                        "SELECT fonte, tribunal, mensagem, quando FROM sync_erros WHERE sync_id=? ORDER BY id",
                        (estado["id"],))]
        return estado

    def _set(self, **kw):
        with self._lock:
            self._estado.update(kw)

    def _fase(self, nome: str, total: int):
        self._set(fase=nome, total=total, atual=0, mensagem="")
        log.info("Fase: %s (%d itens)", nome, total)

    def _progresso(self, atual: int, mensagem: str = ""):
        self._set(atual=atual, mensagem=mensagem)

    def _erro(self, fonte: str, tribunal: str, mensagem: str):
        """Registra um erro na tela e no banco. Nunca chamar com uma conexão de escrita aberta."""
        log.error("[%s %s] %s", fonte, tribunal, mensagem)
        item = {"fonte": fonte, "tribunal": tribunal, "mensagem": mensagem, "quando": db.agora()}
        with self._lock:
            self._estado["erros"].append(item)
            sync_id = self._estado["id"]
        try:
            with db.conexao() as con:
                con.execute("INSERT INTO sync_erros(sync_id, quando, fonte, tribunal, mensagem) VALUES(?,?,?,?,?)",
                            (sync_id, item["quando"], fonte, tribunal, mensagem))
        except Exception:
            log.exception("Não foi possível gravar o erro no banco")

    # --- disparo ----------------------------------------------------------

    def rodando(self) -> bool:
        with self._lock:
            return self._estado["rodando"]

    def iniciar(self, djen: bool = True, datajud: bool = True, numeros: list[str] | None = None) -> bool:
        with self._lock:
            if self._estado["rodando"]:
                return False
            self._estado = self._vazio()
            self._estado.update(rodando=True, inicio=db.agora(), id=uuid.uuid4().hex[:12], completo=djen)
        threading.Thread(target=self._rodar, args=(djen, datajud, numeros), daemon=True).start()
        return True

    def _rodar(self, djen: bool, datajud: bool, numeros: list[str] | None):
        cfg = config.carregar()
        resumo = []
        try:
            if djen:
                resumo.append(self._fase_djen(cfg))
            if datajud:
                resumo.append(self._fase_datajud(cfg, numeros))
                # Processos adicionados durante a sincronização ainda não consultados
                with db.conexao() as con:
                    pendentes = [r[0] for r in con.execute("SELECT numero FROM processos WHERE datajud_status IS NULL")]
                if pendentes and cfg["datajud_api_key"]:
                    self._fase_datajud(cfg, pendentes)
        except Exception as e:  # nunca derruba o app
            log.exception("Falha inesperada na sincronização")
            self._erro("app", "", f"Falha inesperada: {e}")
        finally:
            self._set(rodando=False, fim=db.agora(), resumo=" · ".join(filter(None, resumo)), fase="Concluído")
            estado = self.status()
            with db.conexao() as con:
                gravar = {k: estado[k] for k in ("id", "inicio", "fim", "resumo", "completo")}
                db.meta_set(con, "ultimo_sync", json.dumps(gravar, ensure_ascii=False))
                if djen:
                    db.meta_set(con, "ultima_atualizacao", estado["fim"])
            log.info("Sincronização concluída: %s (%d erros)", estado["resumo"], len(estado["erros"]))

    # --- DJEN -------------------------------------------------------------

    def _janelas(self, cfg, adv: dict) -> list[tuple[date, date]]:
        hoje = date.today()
        with db.conexao() as con:
            ultima = db.meta_get(con, db.chave_marco(adv))
        if ultima:
            inicio = date.fromisoformat(ultima) - timedelta(days=SOBREPOSICAO_DIAS)
        else:
            inicio = hoje - timedelta(days=int(cfg["backfill_dias"]))
        passo = max(1, int(cfg["janela_dias"]))
        janelas, a = [], inicio
        while a <= hoje:
            b = min(a + timedelta(days=passo - 1), hoje)
            janelas.append((a, b))
            a = b + timedelta(days=1)
        return janelas

    def _buscar_janela(self, cli: DjenClient, cfg, adv: dict, a: date, b: date) -> list[dict]:
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

    def _fase_djen(self, cfg) -> str:
        """Busca por OAB de cada advogada; cada publicação/processo fica vinculado a quem o encontrou."""
        with db.conexao() as con:
            lista = [a for a in db.advogadas(con) if a["oab_numero"] and a["oab_uf"]]
        plano = [(adv, self._janelas(cfg, adv)) for adv in lista]
        self._fase("Publicações (DJEN)", sum(len(j) for _, j in plano))
        lidas = novas = feitos = 0
        processos: set[str] = set()
        por_advogada = []
        with DjenClient() as cli:
            for adv, janelas in plano:
                deste: set[str] = set()
                marco, falhou = None, False
                for a, b in janelas:
                    self._progresso(feitos, f"{adv['nome']}: publicações de {_br(a)} a {_br(b)}")
                    try:
                        itens = self._buscar_janela(cli, cfg, adv, a, b)
                    except DjenErro as e:
                        self._erro("DJEN", adv["nome"], f"Período {_br(a)} a {_br(b)}: {e}")
                        falhou = True
                        feitos += 1
                        continue
                    problemas = []
                    with db.conexao() as con:
                        tocados = set()
                        for it in itens:
                            lidas += 1
                            try:
                                with db.savepoint(con):
                                    if db.salvar_comunicacao(con, it, adv["id"]):
                                        novas += 1
                                tocados.add(cnj.so_digitos(it.get("numero_processo") or ""))
                            except Exception as e:  # um item estranho não derruba a janela
                                log.exception("Erro ao gravar comunicação %s", it.get("id"))
                                problemas.append((it.get("siglaTribunal") or "", f"Publicação {it.get('id')}: {e}"))
                        for n in filter(None, tocados):
                            db.recalcular_resumo(con, n)
                    for trib, msg in problemas:
                        self._erro("DJEN", trib, msg)
                    deste |= tocados
                    if not falhou:
                        marco = b  # só avança o marco em janelas contíguas sem erro
                    feitos += 1
                    self._progresso(feitos)
                if marco:
                    with db.conexao() as con:
                        db.meta_set(con, db.chave_marco(adv), marco.isoformat())
                deste.discard("")
                processos |= deste
                por_advogada.append(f"{adv['nome']}: {len(deste)}")
        return (f"DJEN: {lidas} publicações lidas, {novas} novas, {len(processos)} processos"
                + (f" ({', '.join(por_advogada)})" if len(por_advogada) > 1 else ""))

    # --- DataJud ----------------------------------------------------------

    def _fase_datajud(self, cfg, numeros: list[str] | None = None) -> str:
        with db.conexao() as con:
            if numeros:
                marcas = ",".join("?" * len(numeros))
                linhas = list(con.execute(f"SELECT numero, alias, tribunal FROM processos WHERE numero IN ({marcas})", numeros))
            else:
                linhas = list(con.execute("SELECT numero, alias, tribunal FROM processos"))
            for r in linhas:
                if not r["alias"]:
                    db.marcar_datajud(con, r["numero"], "sem_alias", f"{r['tribunal']} não publica no DataJud")

        chave = cfg["datajud_api_key"]
        if not chave:
            self._erro("DataJud", "", "Chave do DataJud não configurada: só as publicações do DJEN foram atualizadas. "
                                      "Clique em ⚙ Configurações e cole a chave (veja o README).")
            return "DataJud: sem chave"

        grupos = defaultdict(list)
        for r in linhas:
            if r["alias"]:
                grupos[r["alias"]].append(r["numero"])
        lotes = [(alias, nums[i:i + TAMANHO_LOTE]) for alias, nums in grupos.items()
                 for i in range(0, len(nums), TAMANHO_LOTE)]
        self._fase("Movimentos (DataJud)", sum(len(n) for _, n in lotes))

        chave_ruim = threading.Event()

        def consultar(alias, nums):
            if chave_ruim.is_set():
                raise DatajudChaveInvalida("chave recusada")
            with DatajudClient(chave) as cli:
                return cli.buscar_lote(alias, nums)

        feitos = com_dados = sem_dados = movs_novos = incertos = 0
        with ThreadPoolExecutor(max_workers=PARALELO_DATAJUD) as ex:
            futuros = {ex.submit(consultar, alias, nums): (alias, nums) for alias, nums in lotes}
            for fut in as_completed(futuros):
                alias, nums = futuros[fut]
                sigla = cnj.tribunal(nums[0])[0]
                try:
                    resultado, completo = fut.result()
                except DatajudChaveInvalida as e:
                    if not chave_ruim.is_set():
                        chave_ruim.set()
                        self._erro("DataJud", "", str(e))
                except Exception as e:
                    self._erro("DataJud", sigla, f"{len(nums)} processo(s) não consultado(s): {e}")
                    with db.conexao() as con:
                        for n in nums:
                            db.marcar_datajud(con, n, "erro", str(e))
                else:
                    problemas = []
                    nao_confirmados = 0
                    with db.conexao() as con:
                        for n, hits in resultado.items():
                            try:
                                with db.savepoint(con):
                                    if hits:
                                        movs_novos += db.salvar_datajud(con, n, hits, completo)
                                        com_dados += 1
                                    elif completo:
                                        db.marcar_datajud(con, n, "sem_dados")
                                        sem_dados += 1
                                    else:  # resposta parcial: não dá para afirmar que não há dados
                                        db.marcar_datajud(con, n, "erro", MSG_PARCIAL)
                                        nao_confirmados += 1
                                    db.recalcular_resumo(con, n)
                            except Exception as e:  # dado estranho de um processo não estraga o lote
                                log.exception("Erro ao gravar %s", n)
                                problemas.append(f"{cnj.formatar(n)}: erro ao gravar ({e})")
                    if nao_confirmados:
                        incertos += nao_confirmados
                        problemas.append(f"{nao_confirmados} processo(s) sem resposta completa (servidor do DataJud "
                                         "sobrecarregado); serão consultados de novo na próxima atualização")
                    for msg in problemas:
                        self._erro("DataJud", sigla, msg)
                feitos += len(nums)
                self._progresso(feitos, f"{sigla}: {len(nums)} processo(s) consultado(s)")
        resumo = f"DataJud: {com_dados} com dados, {sem_dados} sem dados públicos, {movs_novos} movimentos novos"
        return resumo + (f", {incertos} não confirmados" if incertos else "")

    # --- ações pontuais ---------------------------------------------------

    def atualizar_um(self, numero: str) -> dict:
        """Consulta um único processo no DataJud agora (botão no painel lateral)."""
        cfg = config.carregar()
        _, alias = cnj.tribunal(numero)
        with db.conexao() as con:
            if not alias:
                db.marcar_datajud(con, numero, "sem_alias", "Tribunal não publica no DataJud")
                return {"ok": False, "mensagem": "Este tribunal não publica no DataJud."}
            if not cfg["datajud_api_key"]:
                return {"ok": False, "mensagem": "Configure a chave do DataJud primeiro."}
        try:
            with DatajudClient(cfg["datajud_api_key"]) as cli:
                hits, completo = cli.buscar(numero)
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


sincronizador = Sincronizador()
