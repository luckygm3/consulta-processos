"""Banco: Postgres do Supabase (schema em supabase/schema.sql).

Cada requisição usa uma transação que assume o papel "authenticated" com os dados (claims) da usuária logada,
então as políticas de RLS valem também para o backend: sem usuária logada não há acesso (conexao() recusa).
Datas, horas e JSON voltam do banco como texto ("AAAA-MM-DD", "HH:MM", "AAAA-MM-DDTHH:MM:SS", JSON cru), no
mesmo formato que o resto do código sempre usou.
"""
import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime

import psycopg
from psycopg.adapt import Loader
from psycopg_pool import ConnectionPool

from . import FUSO, cnj, config, texto as txt

log = logging.getLogger("db")

# --- conexão ---------------------------------------------------------------------

_usuaria: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usuaria", default=None)


def definir_usuaria(claims: dict | None):
    """Quem está fazendo a requisição (claims do token do Supabase). Devolve o token para resetar o contexto."""
    return _usuaria.set(claims)


def esquecer_usuaria(ctx) -> None:
    _usuaria.reset(ctx)


def usuaria_atual() -> dict | None:
    return _usuaria.get()


class _Texto(Loader):
    def load(self, data):
        return bytes(data).decode()


class _Hora(Loader):
    def load(self, data):
        return bytes(data).decode()[:5]  # "13:55:00" -> "13:55"


class _Momento(Loader):
    """timestamp/timestamptz -> "AAAA-MM-DDTHH:MM:SS" no horário de Brasília (o fuso da sessão), sem fração nem fuso."""
    def load(self, data):
        s = bytes(data).decode().replace(" ", "T", 1)
        return re.sub(r"(\.\d+)?([+-]\d{2}(:\d{2})?)?$", "", s)


class Linha(dict):
    """Linha do resultado: por nome (linha["numero"]) e por posição (linha[0])."""
    __slots__ = ("_valores",)

    def __getitem__(self, chave):
        return self._valores[chave] if isinstance(chave, int) else dict.__getitem__(self, chave)


def _linhas(cursor):
    nomes = [c.name for c in cursor.description] if cursor.description else []

    def fazer(valores):
        linha = Linha(zip(nomes, valores))
        linha._valores = valores
        return linha
    return fazer


def preparar(con: psycopg.Connection) -> None:
    """Ajustes de leitura de tipos (vale para conexões do app, dos testes e do script de migração)."""
    for tipo in ("date", "json", "jsonb"):
        con.adapters.register_loader(tipo, _Texto)
    con.adapters.register_loader("time", _Hora)
    for tipo in ("timestamp", "timestamptz"):
        con.adapters.register_loader(tipo, _Momento)
    con.row_factory = _linhas


class Conexao:
    """Fina camada sobre a conexão do psycopg: execute/executemany com placeholders %s."""
    def __init__(self, con: psycopg.Connection):
        self.bruta = con

    def execute(self, sql, params=None):
        return self.bruta.execute(sql, params)

    def executemany(self, sql, seq):
        cur = self.bruta.cursor()
        cur.executemany(sql, list(seq))
        return cur


_pool: ConnectionPool | None = None
_pool_trava = threading.Lock()


def _pool_aberto() -> ConnectionPool:
    """Pool aberto na primeira consulta. prepare_threshold=None: o pooler do Supabase (modo transação) não aceita
    prepared statements."""
    global _pool
    with _pool_trava:
        if _pool is None:
            _pool = ConnectionPool(
                config.ambiente("DATABASE_URL"), min_size=1, max_size=int(config.ambiente("DB_POOL_MAX", False) or 4),
                kwargs={"prepare_threshold": None, "autocommit": False}, configure=preparar, open=True, timeout=30,
                name="processos")
        return _pool


def entrar(con: psycopg.Connection, claims: dict) -> None:
    """Início de cada transação: papel "authenticated" + claims da usuária (RLS) + fuso de Brasília.
    set_config(..., true) vale só até o fim da transação, o que é seguro com o pooler em modo transação."""
    con.execute("SELECT set_config('role', 'authenticated', true), set_config('request.jwt.claims', %s, true),"
                " set_config('TimeZone', %s, true)", (json.dumps(claims), os.environ.get("FUSO_BANCO") or FUSO))


@contextmanager
def conexao():
    claims = _usuaria.get()
    if not claims:
        raise PermissionError("Acesso ao banco sem usuária logada")
    with _pool_aberto().connection() as bruta:
        try:
            entrar(bruta, claims)
            yield Conexao(bruta)
            bruta.commit()
        except BaseException:
            bruta.rollback()
            raise


@contextmanager
def savepoint(con):
    """Isola a gravação de um item: se der erro, desfaz só ele e o resto da transação segue."""
    con.execute("SAVEPOINT item")
    try:
        yield
    except Exception:
        con.execute("ROLLBACK TO SAVEPOINT item")
        con.execute("RELEASE SAVEPOINT item")
        raise
    con.execute("RELEASE SAVEPOINT item")


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para busca tolerante ('citacao' acha 'Citação')."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def autorizada(con) -> bool:
    return bool(con.execute("SELECT public.e_autorizada()").fetchone()[0])


# --- padrões que o app cria sozinho (tipos de ato, feriados dos próximos anos) -----------

def garantir_padroes(con, hoje: date | None = None):
    if not con.execute("SELECT 1 FROM tipos_ato LIMIT 1").fetchone():
        from .extrair import TIPOS_PADRAO
        con.executemany("INSERT INTO tipos_ato(ordem, nome, palavras, dias, contagem, justica) VALUES(%s,%s,%s,%s,%s,%s)",
                        [(i, *t) for i, t in enumerate(TIPOS_PADRAO, start=1)])
    if not meta_get(con, "cooperacao_semeada"):  # lista inicial de cooperação, uma vez só (o que ela tirar não volta)
        if not con.execute("SELECT 1 FROM advogados_cooperacao LIMIT 1").fetchone():
            config.salvar_cooperacao(con, config.cooperacao_do_arquivo())
        meta_set(con, "cooperacao_semeada", agora())
    semear_feriados(con, hoje)


def semear_feriados(con, hoje: date | None = None):
    """Pré-preenche o calendário do ano passado até daqui a 2 anos. Cada ano só uma vez: o que ela apagar ou
    editar não volta."""
    from .prazos import feriados_padrao
    ano = (hoje or date.today()).year
    for a in range(ano - 1, ano + 3):
        chave = f"feriados_padrao:{a}"
        if meta_get(con, chave):
            continue
        con.executemany(
            """INSERT INTO feriados(inicio, fim, descricao, tipo, tribunais, comarca, recorrente, origem)
               VALUES(%(inicio)s, %(fim)s, %(descricao)s, %(tipo)s, %(tribunais)s, %(comarca)s, %(recorrente)s, %(origem)s)""",
            [{**f, "recorrente": bool(f["recorrente"])} for f in feriados_padrao(a)])
        meta_set(con, chave, agora())


# --- meta ------------------------------------------------------------------

def meta_get(con, chave, padrao=None):
    row = con.execute("SELECT valor FROM meta WHERE chave=%s", (chave,)).fetchone()
    return row["valor"] if row else padrao


def meta_set(con, chave, valor):
    con.execute("INSERT INTO meta(chave, valor) VALUES(%s, %s) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (chave, valor))


# --- advogadas -------------------------------------------------------------

def advogadas(con) -> list[dict]:
    """Advogadas cadastradas (tabela advogadas; quem entra no app e de quem são os processos)."""
    return [dict(r) for r in con.execute("SELECT id, nome, oab_numero, oab_uf, cor FROM advogadas ORDER BY id")]


def chave_marco(adv: dict) -> str:
    """Até que data o DJEN já foi lido para esta advogada (cada uma tem o seu marco)."""
    return f"djen_ultima_data:{adv['oab_numero']}/{adv['oab_uf']}"


def vincular(con, numero: str, advogada_id: int, origem: str):
    con.execute("""INSERT INTO processo_advogada(numero, advogada_id, origem, criado_em) VALUES(%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""", (numero, advogada_id, origem, agora()))


# --- processos em cooperação ------------------------------------------------
# Processo em que consta um dos advogados de cooperação (tabela advogados_cooperacao, de fora do escritório).
# A marcação automática (processos.cooperacao) é refeita a cada sincronização; cooperacao_manual vale por cima dela.

COOPERACAO_SQL = "COALESCE(cooperacao_manual, cooperacao)"  # true = em cooperação (manual ou automática)


def _oab(numero) -> str:
    return cnj.so_digitos(str(numero or "")).lstrip("0")


def _mesmo_nome(nome_api: str, nome_cadastrado: str) -> bool:
    """Todas as palavras do nome cadastrado aparecem no nome da API, sem acento/maiúscula
    ("Jessica Delmoni" casa com "JESSICA FERREIRA DELMONI")."""
    alvo = normalizar(nome_cadastrado).split()
    return bool(alvo) and set(alvo) <= set(normalizar(nome_api).split())


def _casa_advogado(adv: dict, coop: dict) -> bool:
    """Pela OAB quando os dois lados têm; senão, pelo nome."""
    oab_api, oab_coop = _oab(adv.get("numero_oab")), _oab(coop["oab_numero"])
    if oab_api and oab_coop:
        uf_api = str(adv.get("uf_oab") or "").strip().upper()
        return oab_api == oab_coop and (not uf_api or not coop["oab_uf"] or uf_api == coop["oab_uf"])
    return bool(coop["nome"]) and _mesmo_nome(adv.get("nome") or "", coop["nome"])


def cooperacao_de(con, numero: str, lista: list[dict]) -> dict | None:
    """O advogado de cooperação que consta no processo (advogados das publicações do DJEN ou partes), ou None."""
    if not lista:
        return None
    for r in con.execute("SELECT advogados FROM comunicacoes WHERE numero=%s", (numero,)):
        for adv in json.loads(r["advogados"] or "[]"):
            achado = next((c for c in lista if isinstance(adv, dict) and _casa_advogado(adv, c)), None)
            if achado:
                return achado
    p = con.execute("SELECT partes FROM processos WHERE numero=%s", (numero,)).fetchone()
    nomes = [n for ns in json.loads(p["partes"]).values() for n in ns] if p and p["partes"] else []
    return next((c for c in lista if c["nome"] and any(_mesmo_nome(n, c["nome"]) for n in nomes)), None)


def atualizar_cooperacao(con, numero: str | None = None, lista: list[dict] | None = None) -> int:
    """Refaz a marcação automática de um processo (ou de todos). Retorna quantos ficaram marcados."""
    if lista is None:
        lista = config.cooperacao(con)
    numeros = [numero] if numero else [r[0] for r in con.execute("SELECT numero FROM processos")]
    marcados = 0
    for n in numeros:
        sim = cooperacao_de(con, n, lista) is not None
        marcados += sim
        con.execute("UPDATE processos SET cooperacao=%s WHERE numero=%s", (sim, n))
    return marcados


def marcar_cooperacao(con, numero: str, valor: bool | None) -> bool:
    """Marcação à mão. Igual à automática (ou None) volta a seguir a automática."""
    r = con.execute("SELECT cooperacao FROM processos WHERE numero=%s", (numero,)).fetchone()
    if not r:
        return False
    manual = None if valor is None or bool(valor) == bool(r["cooperacao"]) else bool(valor)
    con.execute("UPDATE processos SET cooperacao_manual=%s WHERE numero=%s", (manual, numero))
    return True


# --- processos -------------------------------------------------------------

def garantir_processo(con, numero: str, origem: str) -> bool:
    """Cria o processo se não existir. Retorna True se foi criado agora."""
    sigla, alias = cnj.tribunal(numero)
    cur = con.execute(
        """INSERT INTO processos(numero, tribunal, alias, origem, criado_em, novidade_em) VALUES(%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        (numero, sigla, alias, origem, agora(), agora()),
    )
    return cur.rowcount > 0


def remover_processo(con, numero: str):
    """Publicações, movimentos e vínculos com advogadas saem junto (on delete cascade)."""
    con.execute("DELETE FROM processos WHERE numero=%s", (numero,))


# --- DJEN ------------------------------------------------------------------

def _hash_comunicacao(item: dict) -> str:
    if item.get("hash"):
        return str(item["hash"])
    base = f'{item.get("id")}|{item.get("numero_processo")}|{item.get("data_disponibilizacao")}|{item.get("texto", "")[:500]}'
    return "sha1:" + hashlib.sha1(base.encode("utf-8")).hexdigest()


def _partes_de(destinatarios: list) -> dict:
    partes = {"ativo": [], "passivo": [], "outros": []}
    for d in destinatarios or []:
        nome = (d.get("nome") or "").strip()
        polo = {"A": "ativo", "P": "passivo"}.get(d.get("polo"), "outros")
        if nome and nome not in partes[polo]:
            partes[polo].append(nome)
    return partes


def salvar_comunicacao(con, item: dict, advogada_id: int | None = None) -> bool:
    """Grava uma comunicação do DJEN (sem duplicar) e a vincula a quem originou a busca. Retorna True se for nova."""
    numero = cnj.so_digitos(item.get("numero_processo") or item.get("numeroprocessocommascara") or "")
    if not numero:
        return False
    destinatarios = item.get("destinatarios") or []
    advogados = [a.get("advogado", {}) for a in item.get("destinatarioadvogados") or []]
    bruto = item.get("texto") or ""
    texto = txt.limpar(bruto)
    busca = normalizar(" ".join([texto, " ".join(d.get("nome", "") for d in destinatarios)]))
    chave = _hash_comunicacao(item)
    garantir_processo(con, numero, "djen")
    cur = con.execute(
        """INSERT INTO comunicacoes
           (hash, djen_id, numero, tribunal, orgao, tipo, tipo_documento, classe, data_disp, texto, texto_original,
            link, destinatarios, advogados, busca, capturado_em)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (
            chave, item.get("id"), numero, item.get("siglaTribunal"), item.get("nomeOrgao"),
            item.get("tipoComunicacao"), item.get("tipoDocumento"), item.get("nomeClasse"),
            item.get("data_disponibilizacao"), texto, bruto if bruto != texto else None, item.get("link"),
            json.dumps(destinatarios, ensure_ascii=False), json.dumps(advogados, ensure_ascii=False),
            busca, agora(),
        ),
    )
    nova = cur.rowcount > 0
    if advogada_id is not None:
        con.execute("INSERT INTO comunicacao_advogada(hash, advogada_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (chave, advogada_id))
        vincular(con, numero, advogada_id, "djen")
    if nova:
        _mesclar_partes(con, numero, _partes_de(destinatarios))
        con.execute("UPDATE processos SET novidade_em=%s WHERE numero=%s", (agora(), numero))
    return nova


def resumo_partes(partes_json: str | None) -> str:
    """'Fulano e outros × Beltrano' a partir do JSON de partes do processo (vazio se não houver)."""
    partes = json.loads(partes_json) if partes_json else {}
    nome = lambda xs: (xs[0] + (" e outros" if len(xs) > 1 else "")) if xs else ""  # noqa: E731
    a, b = nome(partes.get("ativo") or []), nome(partes.get("passivo") or [])
    return f"{a} × {b}" if a and b else (a or b)


def _mesclar_partes(con, numero, novas: dict):
    row = con.execute("SELECT partes FROM processos WHERE numero=%s", (numero,)).fetchone()
    atuais = json.loads(row["partes"]) if row and row["partes"] else {"ativo": [], "passivo": [], "outros": []}
    for polo, nomes in novas.items():
        for n in nomes:
            if n not in atuais.setdefault(polo, []):
                atuais[polo].append(n)
    con.execute("UPDATE processos SET partes=%s WHERE numero=%s", (json.dumps(atuais, ensure_ascii=False), numero))


# --- DataJud ---------------------------------------------------------------

def _data_ajuizamento(valor: str | None) -> str | None:
    """DataJud mistura '20260513163404' e ISO; devolve 'YYYY-MM-DD' (ou None se vier algo que não é data)."""
    if not valor:
        return None
    v = str(valor)
    if v[:8].isdigit() and (len(v) == 8 or v[8:9].isdigit()):
        v = f"{v[0:4]}-{v[4:6]}-{v[6:8]}"
    try:
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        return None


def _data_hora_mov(valor: str | None) -> str | None:
    """Datas dos movimentos vêm como ISO com 'Z', mas na prática estão no horário local do tribunal."""
    v = str(valor or "")
    if v[:14].isdigit():
        v = f"{v[0:4]}-{v[4:6]}-{v[6:8]}T{v[8:10]}:{v[10:12]}:{v[12:14]}"
    v = v.replace("Z", "")[:19]
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return None
    return v


def _complementos_texto(mov: dict) -> str:
    partes = []
    for c in mov.get("complementosTabelados") or []:
        nome = c.get("nome") or c.get("valor")
        if nome:
            partes.append(str(nome))
    return "; ".join(partes)


def salvar_datajud(con, numero: str, hits: list[dict], completo: bool = True) -> int:
    """Grava metadados e movimentos de todos os graus. Retorna quantos movimentos são novos.

    completo=False (resposta parcial do DataJud): preserva o que já existe dos graus que não vieram.
    """
    fontes = [h.get("_source", h) for h in hits]
    fontes.sort(key=lambda s: s.get("dataHoraUltimaAtualizacao") or "", reverse=True)
    principal = fontes[0]

    assuntos = []
    for s in fontes:
        for a in s.get("assuntos") or []:
            # assuntos às vezes vêm aninhados em listas
            for item in (a if isinstance(a, list) else [a]):
                nome = (item or {}).get("nome")
                if nome and nome not in assuntos:
                    assuntos.append(nome)
    instancias = [
        {
            "grau": s.get("grau"),
            "orgao": (s.get("orgaoJulgador") or {}).get("nome"),
            "classe": (s.get("classe") or {}).get("nome"),
            "sistema": (s.get("sistema") or {}).get("nome"),
            "ajuizamento": _data_ajuizamento(s.get("dataAjuizamento")),
            "atualizado": s.get("dataHoraUltimaAtualizacao"),
            "sigilo": s.get("nivelSigilo"),
        }
        for s in fontes
    ]
    graus = [s.get("grau") for s in fontes]
    if not completo:
        row = con.execute("SELECT instancias FROM processos WHERE numero=%s", (numero,)).fetchone()
        anteriores = json.loads(row["instancias"]) if row and row["instancias"] else []
        instancias += [i for i in anteriores if i.get("grau") not in graus]

    antigos = {r["chave"]: r["capturado_em"]
               for r in con.execute("SELECT chave, capturado_em FROM movimentos WHERE numero=%s", (numero,))}
    novos_movs = {}
    for s in fontes:
        grau = s.get("grau")
        for m in s.get("movimentos") or []:
            data_hora = _data_hora_mov(m.get("dataHora"))
            comp = _complementos_texto(m)
            chave = hashlib.sha1(f"{numero}|{grau}|{m.get('codigo')}|{data_hora}|{m.get('nome')}|{comp}".encode()).hexdigest()
            nome = m.get("nome") or f"Movimento {m.get('codigo') or ''}".strip()
            novos_movs.setdefault(chave, (chave, numero, grau, m.get("codigo"), data_hora, nome, comp,
                                          (m.get("orgaoJulgador") or {}).get("nome"), antigos.get(chave) or agora()))
    qtd_novos = len(set(novos_movs) - set(antigos))

    # Substitui os movimentos pelo retrato atual do DataJud (evita lixo se o tribunal corrigir algo)
    if completo:
        con.execute("DELETE FROM movimentos WHERE numero=%s", (numero,))
    else:
        con.execute("DELETE FROM movimentos WHERE numero=%s AND grau = ANY(%s)", (numero, graus))
    con.executemany("""INSERT INTO movimentos(chave, numero, grau, codigo, data_hora, nome, complementos, orgao, capturado_em)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", novos_movs.values())

    con.execute(
        """UPDATE processos SET orgao=%s, classe=%s, assuntos=%s, grau=%s, data_ajuizamento=%s, sistema=%s, instancias=%s,
           datajud_status='ok', datajud_msg=NULL, datajud_em=%s WHERE numero=%s""",
        (
            (principal.get("orgaoJulgador") or {}).get("nome"), (principal.get("classe") or {}).get("nome"),
            json.dumps(assuntos, ensure_ascii=False), principal.get("grau"),
            _data_ajuizamento(principal.get("dataAjuizamento")), (principal.get("sistema") or {}).get("nome"),
            json.dumps(instancias, ensure_ascii=False), agora(), numero,
        ),
    )
    if qtd_novos:
        con.execute("UPDATE processos SET novidade_em=%s WHERE numero=%s", (agora(), numero))
    return qtd_novos


def marcar_datajud(con, numero: str, status: str, msg: str | None = None):
    if status == "erro":
        # Falha temporária não apaga dados já obtidos: mantém 'ok' e só guarda a mensagem
        con.execute("""UPDATE processos SET datajud_msg=%s,
                       datajud_status=CASE WHEN datajud_status='ok' THEN 'ok' ELSE 'erro' END WHERE numero=%s""",
                    (f"Última consulta falhou: {msg}", numero))
        return
    con.execute("UPDATE processos SET datajud_status=%s, datajud_msg=%s, datajud_em=%s WHERE numero=%s",
                (status, msg, agora(), numero))


# --- resumo por processo ---------------------------------------------------

def recalcular_resumo(con, numero: str):
    """Atualiza colunas de 'última movimentação/publicação', órgão/classe de reserva e texto de busca."""
    p = con.execute("SELECT * FROM processos WHERE numero=%s", (numero,)).fetchone()
    if not p:
        return
    mov = con.execute(
        "SELECT data_hora, nome, complementos FROM movimentos WHERE numero=%s ORDER BY data_hora DESC NULLS LAST LIMIT 1",
        (numero,)).fetchone()
    pub = con.execute(
        """SELECT data_disp, tipo, orgao, classe, texto FROM comunicacoes WHERE numero=%s
           ORDER BY data_disp DESC NULLS LAST, djen_id DESC NULLS LAST LIMIT 1""",
        (numero,)).fetchone()

    ult_mov_data = mov["data_hora"] if mov else None
    ult_mov_texto = None
    if mov:
        ult_mov_texto = (mov["nome"] or "Movimento") + (f" ({mov['complementos']})" if mov["complementos"] else "")
    ult_pub_data = pub["data_disp"] if pub else None
    ult_pub_texto = f"{pub['tipo'] or 'Publicação'}: {txt.resumo(pub['texto'])}" if pub else None
    ult_atividade = max(filter(None, [ult_mov_data, ult_pub_data]), default=None)

    # Sem DataJud, usa órgão e classe da publicação mais recente
    orgao = p["orgao"] or (pub["orgao"] if pub else None)
    classe = p["classe"] or (pub["classe"].lower().capitalize() if pub and pub["classe"] else None)

    partes = json.loads(p["partes"]) if p["partes"] else {}
    assuntos = json.loads(p["assuntos"]) if p["assuntos"] else []
    busca = normalizar(" ".join(filter(None, [
        numero, cnj.formatar(numero), p["tribunal"], orgao, classe, " ".join(assuntos),
        " ".join(n for nomes in partes.values() for n in nomes),
    ])))
    con.execute(
        """UPDATE processos SET ult_mov_data=%s, ult_mov_texto=%s, ult_pub_data=%s, ult_pub_texto=%s, ult_atividade=%s,
           orgao=%s, classe=%s, busca=%s WHERE numero=%s""",
        (ult_mov_data, ult_mov_texto, ult_pub_data, ult_pub_texto, ult_atividade, orgao, classe, busca, numero),
    )
    atualizar_cooperacao(con, numero)


# --- consultas para a interface --------------------------------------------

def listar(con, tribunal="", q="", so_novidades=False) -> list[dict]:
    sql = ["SELECT * FROM processos WHERE true"]
    args: list = []
    if tribunal:
        sql.append("AND tribunal=%s")
        args.append(tribunal)
    if q:
        termo = normalizar(q).strip()
        digitos = cnj.so_digitos(q)
        cond = ["busca LIKE %s", "numero IN (SELECT numero FROM comunicacoes WHERE busca LIKE %s)"]
        args += [f"%{termo}%", f"%{termo}%"]
        if len(digitos) >= 4 and len(digitos) >= len(q.strip()) * 0.6:
            cond.append("numero LIKE %s")
            args.append(f"%{digitos}%")
        sql.append("AND (" + " OR ".join(cond) + ")")
    if so_novidades:
        sql.append("AND novidade_em IS NOT NULL AND (visto_em IS NULL OR novidade_em > visto_em)")
    sql.append("ORDER BY ult_atividade DESC NULLS LAST, criado_em DESC")
    donas = _advogadas_por_processo(con)
    return [_processo_dict(r, donas) for r in con.execute(" ".join(sql), args)]


def _advogadas_por_processo(con, numero: str | None = None) -> dict[str, list[int]]:
    sql = "SELECT numero, advogada_id FROM processo_advogada"
    linhas = con.execute(sql + " WHERE numero=%s", (numero,)) if numero else con.execute(sql)
    donas: dict[str, list[int]] = {}
    for r in linhas:
        donas.setdefault(r["numero"], []).append(r["advogada_id"])
    return donas


def _processo_dict(r, donas: dict | None = None) -> dict:
    d = dict(r)
    d["advogadas"] = sorted((donas or {}).get(d["numero"], []))
    d.pop("busca", None)
    d["numero_fmt"] = cnj.formatar(d["numero"])
    d["partes"] = json.loads(d["partes"]) if d.get("partes") else {}
    d["assuntos"] = json.loads(d["assuntos"]) if d.get("assuntos") else []
    d["instancias"] = json.loads(d["instancias"]) if d.get("instancias") else []
    d["novo"] = bool(d.get("novidade_em") and (not d.get("visto_em") or d["novidade_em"] > d["visto_em"]))
    d["cooperacao_auto"] = bool(d.get("cooperacao"))
    d["cooperacao"] = bool(d["cooperacao_auto"] if d.get("cooperacao_manual") is None else d["cooperacao_manual"])
    return d


def detalhe(con, numero: str) -> dict | None:
    r = con.execute("SELECT * FROM processos WHERE numero=%s", (numero,)).fetchone()
    if not r:
        return None
    p = _processo_dict(r, _advogadas_por_processo(con, numero))
    visto = p["visto_em"]

    def novo(capturado):  # só destaca eventos depois da última vez que marcou como visto
        return bool(visto and capturado and capturado > visto)

    eventos = []
    for c in con.execute("SELECT * FROM comunicacoes WHERE numero=%s ORDER BY data_disp DESC", (numero,)):
        eventos.append({
            "fonte": "djen", "data": c["data_disp"], "titulo": c["tipo"] or "Publicação",
            "orgao": c["orgao"], "texto": c["texto"], "link": c["link"], "documento": c["tipo_documento"],
            "resumo": txt.resumo(c["texto"], 360), "novo": novo(c["capturado_em"]),
            "destinatarios": [d.get("nome") for d in json.loads(c["destinatarios"] or "[]") if d.get("nome")],
        })
    for m in con.execute("SELECT * FROM movimentos WHERE numero=%s ORDER BY data_hora DESC", (numero,)):
        eventos.append({
            "fonte": "datajud", "data": m["data_hora"], "titulo": m["nome"], "complementos": m["complementos"],
            "orgao": m["orgao"], "grau": m["grau"], "novo": novo(m["capturado_em"]),
        })
    eventos.sort(key=lambda e: e["data"] or "", reverse=True)
    p["eventos"] = eventos
    p["cooperacao_por"] = cooperacao_de(con, numero, config.cooperacao(con))
    return p


def opcoes_filtros(con) -> dict:
    tribunais = [r[0] for r in con.execute("SELECT DISTINCT tribunal FROM processos WHERE tribunal IS NOT NULL ORDER BY tribunal")]
    return {"tribunais": tribunais}
