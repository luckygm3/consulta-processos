"""Agenda/Kanban de prazos: tarefas, verificação de prazos nas publicações do DJEN, feriados e tipos de ato."""
import json
import logging
from datetime import date, timedelta

from . import cnj, config, db, extrair, prazos

log = logging.getLogger("agenda")

STATUS = ["sugerido", "a_fazer", "andamento", "aguardando", "concluido"]
CAMPOS = ["titulo", "tipo", "status", "numero", "advogada_id", "prazo_fatal", "data_interna", "hora", "prioridade",
          "observacoes", "checklist", "trecho", "calculo", "conferir", "aviso"]


# --- calendário -------------------------------------------------------------

class Calendarios:
    """Um Calendario por tribunal/órgão, montado a partir da tabela de feriados (lida uma vez por requisição)."""

    def __init__(self, con):
        self.registros = [dict(r) for r in con.execute("SELECT * FROM feriados WHERE ativo=1")]
        self._cache = {}

    def de(self, tribunal: str | None = "", orgao: str | None = "") -> prazos.Calendario:
        chave = (tribunal or "", orgao or "")
        if chave not in self._cache:
            self._cache[chave] = prazos.Calendario(self.registros, *chave)
        return self._cache[chave]


def regras(cfg: dict | None = None) -> dict:
    cfg = cfg or config.carregar()
    return {"regra_publicacao": cfg.get("prazos_regra_publicacao", "djen"),
            "dias_internos": int(cfg.get("prazos_dias_internos", 2)),
            "contagem_padrao": cfg.get("prazos_contagem_padrao", "uteis")}


def calcular_para(con, numero: str | None, disponibilizacao: str, dias: int, contagem: str | None = None,
                  cals: Calendarios | None = None) -> dict:
    """Prazo fatal para um processo (usa o calendário do tribunal/comarca e a contagem definida no processo)."""
    p = con.execute("SELECT tribunal, orgao, contagem FROM processos WHERE numero=?", (numero or "",)).fetchone()
    tribunal = p["tribunal"] if p else (cnj.tribunal(numero)[0] if numero else "")
    r = regras()
    contagem = contagem or (p["contagem"] if p else None) or r["contagem_padrao"]
    cal = (cals or Calendarios(con)).de(tribunal, p["orgao"] if p else "")
    calc = prazos.calcular(date.fromisoformat(disponibilizacao[:10]), dias, cal, contagem,
                           r["regra_publicacao"], r["dias_internos"])
    calc["tribunal"] = tribunal
    return calc


# --- tarefas ----------------------------------------------------------------

def _tarefa_dict(r, cals: Calendarios, hoje: date) -> dict:
    d = dict(r)
    for campo, vazio in (("checklist", []), ("calculo", None)):
        try:
            d[campo] = json.loads(d[campo]) if d.get(campo) else vazio
        except ValueError:
            d[campo] = vazio
    d["numero_fmt"] = cnj.formatar(d["numero"]) if d.get("numero") else ""
    cal = cals.de(d.get("p_tribunal") or (cnj.tribunal(d["numero"])[0] if d.get("numero") else ""), d.get("p_orgao"))
    if d["status"] == "concluido":
        d["urgencia"], d["dias_restantes"] = "concluido", None
    else:
        d["urgencia"], d["dias_restantes"] = prazos.urgencia(d.get("prazo_fatal"), cal, hoje)
    partes = json.loads(d.pop("p_partes") or "{}") if d.get("p_partes") else {}
    nome = lambda xs: (xs[0] + (" e outros" if len(xs) > 1 else "")) if xs else ""  # noqa: E731
    a, b = nome(partes.get("ativo") or []), nome(partes.get("passivo") or [])
    d["partes"] = f"{a} × {b}" if a and b else (a or b)
    d["tribunal"] = d.pop("p_tribunal", None)
    d.pop("p_orgao", None)
    d["advogadas_processo"] = [int(x) for x in (d.pop("p_advs") or "").split(",") if x]
    return d


_SELECT = """SELECT t.*, p.tribunal AS p_tribunal, p.orgao AS p_orgao, p.partes AS p_partes, c.link AS link,
                    c.data_disp AS data_disp,
                    (SELECT GROUP_CONCAT(advogada_id) FROM processo_advogada pa WHERE pa.numero=t.numero) AS p_advs
             FROM tarefas t LEFT JOIN processos p ON p.numero=t.numero
             LEFT JOIN comunicacoes c ON c.hash=t.comunicacao_hash"""


def listar(con, hoje: date | None = None) -> list[dict]:
    cals, hoje = Calendarios(con), hoje or date.today()
    rows = con.execute(_SELECT + " WHERE t.status != 'descartado' ORDER BY t.prazo_fatal IS NULL, t.prazo_fatal, t.id")
    return [_tarefa_dict(r, cals, hoje) for r in rows]


def obter(con, tid: int) -> dict | None:
    r = con.execute(_SELECT + " WHERE t.id=?", (tid,)).fetchone()
    return _tarefa_dict(r, Calendarios(con), date.today()) if r else None


def _valores(dados: dict) -> dict:
    v = {k: dados[k] for k in CAMPOS if k in dados}
    for k in ("checklist", "calculo"):
        if k in v and not isinstance(v[k], str) and v[k] is not None:
            v[k] = json.dumps(v[k], ensure_ascii=False)
    if "numero" in v:
        v["numero"] = cnj.so_digitos(v["numero"] or "") or None
    if v.get("status") and v["status"] not in STATUS + ["descartado"]:
        raise ValueError("status inválido")
    for k in ("prazo_fatal", "data_interna"):
        if k in v:
            v[k] = (v[k] or "")[:10] or None
            if v[k]:
                date.fromisoformat(v[k])
    return v


def criar(con, dados: dict) -> int:
    v = _valores(dados)
    v.setdefault("status", "a_fazer")
    v["origem"] = dados.get("origem", "manual")
    v["comunicacao_hash"] = dados.get("comunicacao_hash")
    v["criado_em"] = v["atualizado_em"] = db.agora()
    if v["status"] == "concluido":
        v["concluido_em"] = db.agora()
    cols = ",".join(v)
    cur = con.execute(f"INSERT INTO tarefas({cols}) VALUES({','.join('?' * len(v))})", list(v.values()))
    return cur.lastrowid


def atualizar(con, tid: int, dados: dict):
    v = _valores(dados)
    if not v:
        return
    v["atualizado_em"] = db.agora()
    if "status" in v:
        v["concluido_em"] = db.agora() if v["status"] == "concluido" else None
    sets = ",".join(f"{k}=?" for k in v)
    con.execute(f"UPDATE tarefas SET {sets} WHERE id=?", [*v.values(), tid])


def lote(con, ids: list[int], acao: str) -> int:
    marcas = ",".join("?" * len(ids))
    if acao == "confirmar":
        cur = con.execute(f"UPDATE tarefas SET status='a_fazer', atualizado_em=? WHERE status='sugerido' AND id IN ({marcas})",
                          [db.agora(), *ids])
    elif acao == "descartar":  # fica guardado como descartado: a mesma publicação não volta a sugerir
        cur = con.execute(f"UPDATE tarefas SET status='descartado', atualizado_em=? WHERE id IN ({marcas})",
                          [db.agora(), *ids])
    else:
        raise ValueError("ação inválida")
    return cur.rowcount


def alertas(con) -> dict:
    hoje = date.today()
    cont = {"vencidos": 0, "hoje": 0, "amanha": 0, "sugeridos": 0}
    for t in listar(con, hoje):
        if t["status"] == "concluido":
            continue
        if t["status"] == "sugerido":
            cont["sugeridos"] += 1
        if t["urgencia"] == "vencido":
            cont["vencidos"] += 1
        elif t["urgencia"] in ("hoje", "amanha"):
            cont[t["urgencia"]] += 1
    return cont


# --- verificar prazos ---------------------------------------------------------

def tipos(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM tipos_ato ORDER BY ordem, id")]


def verificar(con, incluir_vencidos: bool = False, hoje: date | None = None) -> dict:
    """Varre as publicações ainda não analisadas e cria cartões 'Sugeridos'. Cada publicação é analisada uma vez
    (tabela comunicacao_analise); as que só tinham prazo já vencido podem ser revistas com incluir_vencidos."""
    hoje = hoje or date.today()
    cals, lista_tipos, cfg = Calendarios(con), tipos(con), regras()
    rows = list(con.execute(
        """SELECT c.hash, c.numero, c.data_disp, c.texto, p.tribunal, p.orgao, p.contagem
           FROM comunicacoes c LEFT JOIN processos p ON p.numero=c.numero
           LEFT JOIN comunicacao_analise a ON a.hash=c.hash
           WHERE a.hash IS NULL OR (? AND a.resultado='ja_vencido')
           ORDER BY c.data_disp""", (1 if incluir_vencidos else 0,)))
    res = {"analisadas": len(rows), "sugeridos": 0, "audiencias": 0, "sem_prazo": 0, "ja_vencidos": 0,
           "repetidos": 0, "erros": 0, "conferir": 0}
    for r in rows:
        try:
            with db.savepoint(con):
                resultado = _analisar_uma(con, r, cals, lista_tipos, cfg, incluir_vencidos, hoje, res)
        except Exception as e:  # uma publicação estranha não interrompe a varredura
            log.exception("Erro ao analisar %s", r["hash"])
            resultado, res["erros"] = f"erro: {e}", res["erros"] + 1
        con.execute("""INSERT INTO comunicacao_analise(hash, analisado_em, resultado) VALUES(?,?,?)
                       ON CONFLICT(hash) DO UPDATE SET analisado_em=excluded.analisado_em, resultado=excluded.resultado""",
                    (r["hash"], db.agora(), resultado.split(":")[0]))
    log.info("Verificar prazos: %s", res)
    return res


def _analisar_uma(con, r, cals, lista_tipos, cfg, incluir_vencidos, hoje, res) -> str:
    a = extrair.analisar(r["texto"], lista_tipos, r["tribunal"] or "")
    if not a:
        res["sem_prazo"] += 1
        return "sem_prazo"
    advs = [x[0] for x in con.execute("SELECT advogada_id FROM comunicacao_advogada WHERE hash=?", (r["hash"],))]
    responsavel = advs[0] if len(advs) == 1 else None
    cards, vencidos = [], 0

    if a["dias"]:
        contagem = r["contagem"] or a["contagem"] or a["tipo_contagem"] or cfg["contagem_padrao"]
        cal = cals.de(r["tribunal"], r["orgao"])
        calc = prazos.calcular(date.fromisoformat(r["data_disp"]), a["dias"], cal, contagem,
                               cfg["regra_publicacao"], cfg["dias_internos"])
        calc.update(fonte=a["fonte"], confianca=a["confianca"], tipo=a["tipo"], horas=a["horas"],
                    tribunal=r["tribunal"])
        if date.fromisoformat(calc["vencimento"]) < hoje and not incluir_vencidos:
            vencidos += 1
        else:
            unidade = f"{a['horas']} horas" if a["horas"] else \
                f"{a['dias']} dias {'úteis' if contagem == 'uteis' else 'corridos'}"
            cards.append({
                "titulo": f"{a['tipo'] or 'Prazo'} ({unidade})", "tipo": "prazo",
                "prazo_fatal": calc["vencimento"], "data_interna": calc["interno"],
                "prioridade": "alta" if a["dias"] <= 5 else "media", "trecho": a["trecho"], "calculo": calc,
                "conferir": 1 if a["confianca"] != "alta" else 0, "aviso": "\n".join(a["avisos"]) or None,
            })

    aud = a.get("audiencia")
    if aud and aud["data"] >= r["data_disp"]:
        if aud["data"] < hoje.isoformat() and not incluir_vencidos:
            vencidos += 1
        else:
            cards.append({
                "titulo": "Audiência" + (f" às {aud['hora']}" if aud["hora"] else ""), "tipo": "audiencia",
                "prazo_fatal": aud["data"], "hora": aud["hora"], "prioridade": "alta", "trecho": aud["trecho"],
                "conferir": 1, "aviso": "Data de audiência lida do texto: conferir no processo.",
                "calculo": {"passos": [f"Data e hora lidas do texto da publicação ({r['data_disp']})."]},
            })

    criados = 0
    for c in cards:
        # Publicações repetidas (uma por parte intimada) não geram cartões repetidos
        igual = con.execute("SELECT id FROM tarefas WHERE origem='djen' AND numero IS ? AND prazo_fatal=? AND titulo=?",
                            (r["numero"], c["prazo_fatal"], c["titulo"])).fetchone()
        if igual:
            res["repetidos"] += 1
            continue
        criar(con, {**c, "status": "sugerido", "numero": r["numero"], "advogada_id": responsavel,
                    "origem": "djen", "comunicacao_hash": r["hash"]})
        criados += 1
        res["audiencias" if c["tipo"] == "audiencia" else "sugeridos"] += 1
        res["conferir"] += c["conferir"]
    res["ja_vencidos"] += vencidos
    if criados:
        return "prazo"
    return "ja_vencido" if vencidos else "prazo"  # só repetidos: já está coberto por outro cartão


# --- feriados -----------------------------------------------------------------

def listar_feriados(con, ano: int | None = None) -> list[dict]:
    if ano:
        rows = con.execute("""SELECT * FROM feriados WHERE recorrente=1 OR inicio LIKE ? OR fim LIKE ?
                              ORDER BY recorrente, inicio""", (f"{ano}-%", f"{ano}-%"))
    else:
        rows = con.execute("SELECT * FROM feriados ORDER BY recorrente, inicio")
    return [dict(r) for r in rows]


def salvar_feriado(con, dados: dict, fid: int | None = None) -> int:
    rec = 1 if dados.get("recorrente") else 0
    ini, fim = (dados.get("inicio") or "").strip(), (dados.get("fim") or "").strip() or None
    for x in filter(None, (ini, fim)):
        date.fromisoformat(x)  # datas sempre completas na tela; recorrente guarda só MM-DD
    if not ini or not (dados.get("descricao") or "").strip():
        raise ValueError("Informe a data e a descrição")
    if rec:
        ini, fim = ini[-5:], fim[-5:] if fim else None
    if dados.get("tipo") not in prazos.TIPOS:
        raise ValueError("tipo inválido")
    valores = (ini, fim, dados["descricao"].strip(), dados["tipo"], (dados.get("tribunais") or "").upper().replace(" ", ""),
               (dados.get("comarca") or "").strip(), rec, 1 if dados.get("ativo", True) else 0)
    if fid:
        con.execute("""UPDATE feriados SET inicio=?, fim=?, descricao=?, tipo=?, tribunais=?, comarca=?, recorrente=?,
                       ativo=?, origem='manual' WHERE id=?""", (*valores, fid))
        return fid
    cur = con.execute("""INSERT INTO feriados(inicio, fim, descricao, tipo, tribunais, comarca, recorrente, ativo, origem)
                         VALUES(?,?,?,?,?,?,?,?,'manual')""", valores)
    return cur.lastrowid


def dias_nao_uteis(con, de: str, ate: str) -> list[dict]:
    """Feriados/suspensões expandidos dia a dia, para mostrar no calendário da agenda."""
    a, b = date.fromisoformat(de), date.fromisoformat(ate)
    cal = prazos.Calendario([dict(r) for r in con.execute("SELECT * FROM feriados WHERE ativo=1")], todos=True)
    saida, d = [], a
    while d <= b and (d - a).days < 120:
        for r in cal.registros(d):
            saida.append({"data": d.isoformat(), "descricao": r["descricao"], "tipo": r["tipo"],
                          "tribunais": r["tribunais"] or "", "comarca": r["comarca"] or ""})
        d += timedelta(days=1)
    return saida


# --- tipos de ato -------------------------------------------------------------

def salvar_tipos(con, lista: list[dict]):
    con.execute("DELETE FROM tipos_ato")
    for i, t in enumerate(lista, start=1):
        if not (t.get("nome") or "").strip() or not (t.get("palavras") or "").strip():
            continue
        con.execute("INSERT INTO tipos_ato(ordem, nome, palavras, dias, contagem, justica, ativo) VALUES(?,?,?,?,?,?,?)",
                    (i, t["nome"].strip(), t["palavras"].strip(), int(t.get("dias") or 5),
                     "corridos" if t.get("contagem") == "corridos" else "uteis",
                     "trabalho" if t.get("justica") == "trabalho" else "", 1 if t.get("ativo", True) else 0))
