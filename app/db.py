"""Banco SQLite local: processos, publicações (DJEN), movimentos (DataJud), advogadas e metadados."""
import hashlib
import json
import logging
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime

from . import cnj, config, texto as txt
from .config import DB_DIR, DB_PATH

log = logging.getLogger("db")
SCHEMA_VERSAO = 3  # 2 = várias advogadas; 3 = agenda/prazos

SCHEMA = """
CREATE TABLE IF NOT EXISTS processos (
    numero            TEXT PRIMARY KEY,      -- 20 dígitos
    tribunal          TEXT,
    alias             TEXT,                  -- índice do DataJud (ex.: tjpr)
    origem            TEXT,                  -- 'djen' ou 'manual'
    orgao             TEXT,
    classe            TEXT,
    assuntos          TEXT,                  -- JSON (lista de nomes)
    grau              TEXT,
    data_ajuizamento  TEXT,
    sistema           TEXT,
    instancias        TEXT,                  -- JSON com um resumo por grau retornado pelo DataJud
    partes            TEXT,                  -- JSON {"ativo": [...], "passivo": [...], "outros": [...]}
    datajud_status    TEXT,                  -- NULL, ok, sem_dados, erro, sem_alias
    datajud_msg       TEXT,
    datajud_em        TEXT,
    ult_mov_data      TEXT,
    ult_mov_texto     TEXT,
    ult_pub_data      TEXT,
    ult_pub_texto     TEXT,
    ult_atividade     TEXT,
    novidade_em       TEXT,                  -- quando algo novo foi capturado
    visto_em          TEXT,                  -- quando a advogada marcou como visto
    busca             TEXT,                  -- texto normalizado para busca
    criado_em         TEXT
);
CREATE TABLE IF NOT EXISTS comunicacoes (
    hash              TEXT PRIMARY KEY,
    djen_id           INTEGER,
    numero            TEXT NOT NULL,
    tribunal          TEXT,
    orgao             TEXT,
    tipo              TEXT,
    tipo_documento    TEXT,
    classe            TEXT,
    data_disp         TEXT,                  -- YYYY-MM-DD
    texto             TEXT,                  -- texto limpo (sem HTML)
    texto_original    TEXT,                  -- original do DJEN, só quando era diferente
    link              TEXT,
    destinatarios     TEXT,                  -- JSON
    advogados         TEXT,                  -- JSON
    busca             TEXT,
    capturado_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_com_numero ON comunicacoes(numero, data_disp);
CREATE TABLE IF NOT EXISTS movimentos (
    chave             TEXT PRIMARY KEY,
    numero            TEXT NOT NULL,
    grau              TEXT,
    codigo            INTEGER,
    data_hora         TEXT,
    nome              TEXT,
    complementos      TEXT,
    orgao             TEXT,
    capturado_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_mov_numero ON movimentos(numero, data_hora);
CREATE TABLE IF NOT EXISTS meta (
    chave             TEXT PRIMARY KEY,
    valor             TEXT
);
CREATE TABLE IF NOT EXISTS sync_erros (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id           TEXT,
    quando            TEXT,
    fonte             TEXT,
    tribunal          TEXT,
    mensagem          TEXT
);
CREATE TABLE IF NOT EXISTS advogadas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    oab_numero        TEXT NOT NULL,
    oab_uf            TEXT NOT NULL,
    nome              TEXT,
    cor               TEXT,
    UNIQUE(oab_numero, oab_uf)
);
CREATE TABLE IF NOT EXISTS processo_advogada (     -- N:N: um processo pode ser de mais de uma advogada
    numero            TEXT NOT NULL,
    advogada_id       INTEGER NOT NULL,
    origem            TEXT,                  -- 'djen', 'manual' ou 'migracao'
    criado_em         TEXT,
    PRIMARY KEY (numero, advogada_id)
);
CREATE INDEX IF NOT EXISTS ix_pa_advogada ON processo_advogada(advogada_id);
CREATE TABLE IF NOT EXISTS comunicacao_advogada (  -- qual busca por OAB trouxe cada publicação
    hash              TEXT NOT NULL,
    advogada_id       INTEGER NOT NULL,
    PRIMARY KEY (hash, advogada_id)
);
CREATE TABLE IF NOT EXISTS feriados (            -- calendário forense editável (feriados, suspensões, recesso)
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio            TEXT NOT NULL,         -- YYYY-MM-DD (ou MM-DD se recorrente)
    fim               TEXT,                  -- idem; NULL = um dia só
    descricao         TEXT NOT NULL,
    tipo              TEXT NOT NULL,         -- feriado | suspensao | recesso | expediente_reduzido
    tribunais         TEXT,                  -- siglas separadas por vírgula; vazio = todos
    comarca           TEXT,                  -- vazio = todas; senão casa com o nome do órgão do processo
    recorrente        INTEGER DEFAULT 0,     -- 1 = repete todo ano (datas em MM-DD)
    origem            TEXT,                  -- 'padrao' (pré-preenchido, conferir) ou 'manual'
    ativo             INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_feriados_inicio ON feriados(inicio);
CREATE TABLE IF NOT EXISTS tipos_ato (           -- tabela editável: palavras-chave -> nome do ato e prazo padrão
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem             INTEGER,
    nome              TEXT NOT NULL,
    palavras          TEXT NOT NULL,         -- separadas por ';' (comparadas sem acento e em minúsculas)
    dias              INTEGER,
    contagem          TEXT,                  -- uteis | corridos
    justica           TEXT,                  -- vazio = qualquer; 'trabalho' = só TRT/TST
    ativo             INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tarefas (             -- cartões da agenda/kanban
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo            TEXT NOT NULL,
    tipo              TEXT DEFAULT 'tarefa', -- prazo | tarefa | audiencia
    status            TEXT DEFAULT 'a_fazer',-- sugerido | a_fazer | andamento | aguardando | concluido | descartado
    numero            TEXT,                  -- processo vinculado (opcional)
    advogada_id       INTEGER,               -- responsável (NULL = as duas / a definir)
    prazo_fatal       TEXT,
    data_interna      TEXT,
    hora              TEXT,                  -- audiências
    prioridade        TEXT DEFAULT 'media',  -- alta | media | baixa
    observacoes       TEXT,
    checklist         TEXT,                  -- JSON [{"texto", "feito"}]
    origem            TEXT DEFAULT 'manual', -- manual | djen
    comunicacao_hash  TEXT,
    trecho            TEXT,                  -- trecho da publicação que gerou a sugestão
    calculo           TEXT,                  -- JSON: memória de cálculo
    conferir          INTEGER DEFAULT 0,     -- 1 = detecção incerta, conferir manualmente
    aviso             TEXT,
    criado_em         TEXT,
    atualizado_em     TEXT,
    concluido_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_tarefas_status ON tarefas(status, prazo_fatal);
CREATE TABLE IF NOT EXISTS comunicacao_analise ( -- publicações já varridas por "Verificar prazos" (não duplica)
    hash              TEXT PRIMARY KEY,
    analisado_em      TEXT,
    resultado         TEXT,                  -- prazo | sem_prazo | ja_vencido | erro
    detalhe           TEXT
);
"""


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para busca tolerante ('citacao' acha 'Citação')."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def iniciar():
    DB_DIR.mkdir(exist_ok=True)
    _backup_antes_de_migrar()
    with conexao() as con:
        con.executescript(SCHEMA)
        _migrar(con)


def _versao(con) -> int:
    """Versão da estrutura do banco. Bancos de antes das advogadas não têm a chave: são v1."""
    tem_meta = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not tem_meta:
        return SCHEMA_VERSAO  # banco recém-criado
    return int(meta_get(con, "schema_versao", 1))


def _backup_antes_de_migrar():
    """Copia o banco (processos.sqlite3.bak-AAAAMMDD) antes de mudar a estrutura. Nunca sobrescreve um backup."""
    if not DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        tem_processos = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='processos'").fetchone()
        if not tem_processos or _versao(con) >= SCHEMA_VERSAO:
            return
        destino = DB_PATH.with_name(f"{DB_PATH.name}.bak-{datetime.now():%Y%m%d}")
        if destino.exists():
            destino = destino.with_name(f"{destino.name}-{datetime.now():%H%M%S}")
        bak = sqlite3.connect(destino)
        try:
            con.backup(bak)  # API de backup do SQLite: cópia consistente, inclui o que ainda está no WAL
        finally:
            bak.close()
        log.info("Backup do banco antes da migração: %s", destino)
    finally:
        con.close()


def _migrar(con):
    versao = _versao(con)
    if versao < 2:
        _migrar_v2(con)
    if versao < 3:
        # v2 -> v3 (agenda): contagem de prazo por processo (NULL = padrão) e tabela de tipos de ato
        colunas = [r["name"] for r in con.execute("PRAGMA table_info(processos)")]
        if "contagem" not in colunas:
            con.execute("ALTER TABLE processos ADD COLUMN contagem TEXT")
        from .extrair import TIPOS_PADRAO
        if not con.execute("SELECT 1 FROM tipos_ato LIMIT 1").fetchone():
            con.executemany("INSERT INTO tipos_ato(ordem, nome, palavras, dias, contagem, justica) VALUES(?,?,?,?,?,?)",
                            [(i, *t) for i, t in enumerate(TIPOS_PADRAO, start=1)])
        log.info("Migração do banco: agenda e prazos")
    if versao < SCHEMA_VERSAO:
        meta_set(con, "schema_versao", str(SCHEMA_VERSAO))
    semear_feriados(con)


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
               VALUES(:inicio, :fim, :descricao, :tipo, :tribunais, :comarca, :recorrente, :origem)""",
            feriados_padrao(a))
        meta_set(con, chave, agora())


def _migrar_v2(con):
    """v1 -> v2: tudo o que já existia passa a ser da primeira advogada (a OAB que estava configurada)."""
    lista = advogadas(con)
    if lista:
        dona = lista[0]
        con.execute("""INSERT OR IGNORE INTO processo_advogada(numero, advogada_id, origem, criado_em)
                       SELECT numero, ?, 'migracao', criado_em FROM processos""", (dona["id"],))
        con.execute("INSERT OR IGNORE INTO comunicacao_advogada(hash, advogada_id) SELECT hash, ? FROM comunicacoes",
                    (dona["id"],))
        # O marco do DJEN era único; agora é por advogada (as novas começam do zero, com o backfill)
        ultima = meta_get(con, "djen_ultima_data")
        if ultima and not meta_get(con, chave_marco(dona)):
            meta_set(con, chave_marco(dona), ultima)
        qtd = con.execute("SELECT COUNT(*) FROM processo_advogada WHERE advogada_id=?", (dona["id"],)).fetchone()[0]
        log.info("Migração do banco: %d processos vinculados a %s", qtd, dona["nome"])


@contextmanager
def savepoint(con):
    """Isola a gravação de um item: se der erro, desfaz só ele e o resto da transação segue."""
    con.execute("SAVEPOINT item")
    try:
        yield
    except Exception:
        con.execute("ROLLBACK TO item")
        con.execute("RELEASE item")
        raise
    con.execute("RELEASE item")


@contextmanager
def conexao():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# --- meta ------------------------------------------------------------------

def meta_get(con, chave, padrao=None):
    row = con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
    return row["valor"] if row else padrao


def meta_set(con, chave, valor):
    con.execute("INSERT INTO meta(chave, valor) VALUES(?, ?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (chave, valor))


# --- advogadas -------------------------------------------------------------

def advogadas(con) -> list[dict]:
    """Advogadas do config.json com o id do banco (cria ou atualiza nome/cor, casando pelo número da OAB)."""
    saida = []
    for a in config.carregar(com_env=False)["advogadas"]:
        con.execute("""INSERT INTO advogadas(oab_numero, oab_uf, nome, cor) VALUES(?,?,?,?)
                       ON CONFLICT(oab_numero, oab_uf) DO UPDATE SET nome=excluded.nome, cor=excluded.cor
                       WHERE nome IS NOT excluded.nome OR cor IS NOT excluded.cor""",
                    (a["oab_numero"], a["oab_uf"], a["nome"], a["cor"]))
        r = con.execute("SELECT id FROM advogadas WHERE oab_numero=? AND oab_uf=?",
                        (a["oab_numero"], a["oab_uf"])).fetchone()
        saida.append({**a, "id": r["id"]})
    return saida


def chave_marco(adv: dict) -> str:
    """Até que data o DJEN já foi lido para esta advogada (cada uma tem o seu marco)."""
    return f"djen_ultima_data:{adv['oab_numero']}/{adv['oab_uf']}"


def vincular(con, numero: str, advogada_id: int, origem: str):
    con.execute("INSERT OR IGNORE INTO processo_advogada(numero, advogada_id, origem, criado_em) VALUES(?,?,?,?)",
                (numero, advogada_id, origem, agora()))


# --- processos -------------------------------------------------------------

def garantir_processo(con, numero: str, origem: str) -> bool:
    """Cria o processo se não existir. Retorna True se foi criado agora."""
    sigla, alias = cnj.tribunal(numero)
    cur = con.execute(
        "INSERT OR IGNORE INTO processos(numero, tribunal, alias, origem, criado_em, novidade_em) VALUES(?,?,?,?,?,?)",
        (numero, sigla, alias, origem, agora(), agora()),
    )
    return cur.rowcount > 0


def remover_processo(con, numero: str):
    con.execute("DELETE FROM comunicacao_advogada WHERE hash IN (SELECT hash FROM comunicacoes WHERE numero=?)",
                (numero,))
    for tabela in ("comunicacoes", "movimentos", "processo_advogada", "processos"):
        con.execute(f"DELETE FROM {tabela} WHERE numero=?", (numero,))


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
    cur = con.execute(
        """INSERT OR IGNORE INTO comunicacoes
           (hash, djen_id, numero, tribunal, orgao, tipo, tipo_documento, classe, data_disp, texto, texto_original,
            link, destinatarios, advogados, busca, capturado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            chave, item.get("id"), numero, item.get("siglaTribunal"), item.get("nomeOrgao"),
            item.get("tipoComunicacao"), item.get("tipoDocumento"), item.get("nomeClasse"),
            item.get("data_disponibilizacao"), texto, bruto if bruto != texto else None, item.get("link"),
            json.dumps(destinatarios, ensure_ascii=False), json.dumps(advogados, ensure_ascii=False),
            busca, agora(),
        ),
    )
    nova = cur.rowcount > 0
    garantir_processo(con, numero, "djen")
    if advogada_id is not None:
        con.execute("INSERT OR IGNORE INTO comunicacao_advogada(hash, advogada_id) VALUES(?,?)", (chave, advogada_id))
        vincular(con, numero, advogada_id, "djen")
    if nova:
        _mesclar_partes(con, numero, _partes_de(destinatarios))
        con.execute("UPDATE processos SET novidade_em=? WHERE numero=?", (agora(), numero))
    return nova


def _mesclar_partes(con, numero, novas: dict):
    row = con.execute("SELECT partes FROM processos WHERE numero=?", (numero,)).fetchone()
    atuais = json.loads(row["partes"]) if row and row["partes"] else {"ativo": [], "passivo": [], "outros": []}
    for polo, nomes in novas.items():
        for n in nomes:
            if n not in atuais.setdefault(polo, []):
                atuais[polo].append(n)
    con.execute("UPDATE processos SET partes=? WHERE numero=?", (json.dumps(atuais, ensure_ascii=False), numero))


# --- DataJud ---------------------------------------------------------------

def _data_ajuizamento(valor: str | None) -> str | None:
    """DataJud mistura '20260513163404' e ISO; devolve 'YYYY-MM-DD'."""
    if not valor:
        return None
    v = str(valor)
    if v[:8].isdigit() and (len(v) == 8 or v[8:9].isdigit()):
        return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"
    return v[:10]


def _data_hora_mov(valor: str | None) -> str:
    """Datas dos movimentos vêm como ISO com 'Z', mas na prática estão no horário local do tribunal."""
    v = str(valor or "")
    if v[:14].isdigit():
        return f"{v[0:4]}-{v[4:6]}-{v[6:8]}T{v[8:10]}:{v[10:12]}:{v[12:14]}"
    return v.replace("Z", "")[:19]


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
        row = con.execute("SELECT instancias FROM processos WHERE numero=?", (numero,)).fetchone()
        anteriores = json.loads(row["instancias"]) if row and row["instancias"] else []
        instancias += [i for i in anteriores if i.get("grau") not in graus]

    antigos = {r["chave"]: r["capturado_em"]
               for r in con.execute("SELECT chave, capturado_em FROM movimentos WHERE numero=?", (numero,))}
    novos_movs = []
    for s in fontes:
        grau = s.get("grau")
        for m in s.get("movimentos") or []:
            data_hora = _data_hora_mov(m.get("dataHora"))
            comp = _complementos_texto(m)
            chave = hashlib.sha1(f"{numero}|{grau}|{m.get('codigo')}|{data_hora}|{m.get('nome')}|{comp}".encode()).hexdigest()
            nome = m.get("nome") or f"Movimento {m.get('codigo') or ''}".strip()
            novos_movs.append((chave, numero, grau, m.get("codigo"), data_hora, nome, comp,
                               (m.get("orgaoJulgador") or {}).get("nome"), antigos.get(chave) or agora()))
    qtd_novos = len({m[0] for m in novos_movs} - set(antigos))

    # Substitui os movimentos pelo retrato atual do DataJud (evita lixo se o tribunal corrigir algo)
    if completo:
        con.execute("DELETE FROM movimentos WHERE numero=?", (numero,))
    else:
        marcas = ",".join("?" * len(graus))
        con.execute(f"DELETE FROM movimentos WHERE numero=? AND grau IN ({marcas})", (numero, *graus))
    con.executemany("INSERT OR IGNORE INTO movimentos VALUES (?,?,?,?,?,?,?,?,?)", novos_movs)

    con.execute(
        """UPDATE processos SET orgao=?, classe=?, assuntos=?, grau=?, data_ajuizamento=?, sistema=?, instancias=?,
           datajud_status='ok', datajud_msg=NULL, datajud_em=? WHERE numero=?""",
        (
            (principal.get("orgaoJulgador") or {}).get("nome"), (principal.get("classe") or {}).get("nome"),
            json.dumps(assuntos, ensure_ascii=False), principal.get("grau"),
            _data_ajuizamento(principal.get("dataAjuizamento")), (principal.get("sistema") or {}).get("nome"),
            json.dumps(instancias, ensure_ascii=False), agora(), numero,
        ),
    )
    if qtd_novos:
        con.execute("UPDATE processos SET novidade_em=? WHERE numero=?", (agora(), numero))
    return qtd_novos


def marcar_datajud(con, numero: str, status: str, msg: str | None = None):
    if status == "erro":
        # Falha temporária não apaga dados já obtidos: mantém 'ok' e só guarda a mensagem
        con.execute("""UPDATE processos SET datajud_msg=?,
                       datajud_status=CASE WHEN datajud_status='ok' THEN 'ok' ELSE 'erro' END WHERE numero=?""",
                    (f"Última consulta falhou: {msg}", numero))
        return
    con.execute("UPDATE processos SET datajud_status=?, datajud_msg=?, datajud_em=? WHERE numero=?",
                (status, msg, agora(), numero))


# --- resumo por processo ---------------------------------------------------

def recalcular_resumo(con, numero: str):
    """Atualiza colunas de 'última movimentação/publicação', órgão/classe de reserva e texto de busca."""
    p = con.execute("SELECT * FROM processos WHERE numero=?", (numero,)).fetchone()
    if not p:
        return
    mov = con.execute(
        "SELECT data_hora, nome, complementos FROM movimentos WHERE numero=? ORDER BY data_hora DESC LIMIT 1",
        (numero,)).fetchone()
    pub = con.execute(
        "SELECT data_disp, tipo, orgao, classe, texto FROM comunicacoes WHERE numero=? ORDER BY data_disp DESC, djen_id DESC LIMIT 1",
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
        """UPDATE processos SET ult_mov_data=?, ult_mov_texto=?, ult_pub_data=?, ult_pub_texto=?, ult_atividade=?,
           orgao=?, classe=?, busca=? WHERE numero=?""",
        (ult_mov_data, ult_mov_texto, ult_pub_data, ult_pub_texto, ult_atividade, orgao, classe, busca, numero),
    )


# --- consultas para a interface --------------------------------------------

def listar(con, tribunal="", orgao="", q="", de="", ate="", so_novidades=False) -> list[dict]:
    sql = ["SELECT * FROM processos WHERE 1=1"]
    args: list = []
    if tribunal:
        sql.append("AND tribunal=?")
        args.append(tribunal)
    if orgao:
        sql.append("AND orgao=?")
        args.append(orgao)
    if q:
        termo = normalizar(q).strip()
        digitos = cnj.so_digitos(q)
        cond = ["busca LIKE ?", "numero IN (SELECT numero FROM comunicacoes WHERE busca LIKE ?)"]
        args += [f"%{termo}%", f"%{termo}%"]
        if len(digitos) >= 4 and len(digitos) >= len(q.strip()) * 0.6:
            cond.append("numero LIKE ?")
            args.append(f"%{digitos}%")
        sql.append("AND (" + " OR ".join(cond) + ")")
    if de or ate:
        de_, ate_ = de or "0000-00-00", (ate or "9999-12-31") + "T99"
        sql.append("""AND (numero IN (SELECT numero FROM comunicacoes WHERE data_disp BETWEEN ? AND ?)
                      OR numero IN (SELECT numero FROM movimentos WHERE data_hora BETWEEN ? AND ?))""")
        args += [de_, ate_, de_, ate_]
    if so_novidades:
        sql.append("AND novidade_em IS NOT NULL AND (visto_em IS NULL OR novidade_em > visto_em)")
    sql.append("ORDER BY ult_atividade IS NULL, ult_atividade DESC, criado_em DESC")
    donas = _advogadas_por_processo(con)
    return [_processo_dict(r, donas) for r in con.execute(" ".join(sql), args)]


def _advogadas_por_processo(con, numero: str | None = None) -> dict[str, list[int]]:
    sql = "SELECT numero, advogada_id FROM processo_advogada"
    linhas = con.execute(sql + " WHERE numero=?", (numero,)) if numero else con.execute(sql)
    donas: dict[str, list[int]] = {}
    for r in linhas:
        donas.setdefault(r["numero"], []).append(r["advogada_id"])
    return donas


def _processo_dict(r: sqlite3.Row, donas: dict | None = None) -> dict:
    d = dict(r)
    d["advogadas"] = sorted((donas or {}).get(d["numero"], []))
    d.pop("busca", None)
    d["numero_fmt"] = cnj.formatar(d["numero"])
    d["partes"] = json.loads(d["partes"]) if d.get("partes") else {}
    d["assuntos"] = json.loads(d["assuntos"]) if d.get("assuntos") else []
    d["instancias"] = json.loads(d["instancias"]) if d.get("instancias") else []
    d["novo"] = bool(d.get("novidade_em") and (not d.get("visto_em") or d["novidade_em"] > d["visto_em"]))
    return d


def detalhe(con, numero: str) -> dict | None:
    r = con.execute("SELECT * FROM processos WHERE numero=?", (numero,)).fetchone()
    if not r:
        return None
    p = _processo_dict(r, _advogadas_por_processo(con, numero))
    visto = p["visto_em"]

    def novo(capturado):  # só destaca eventos depois da última vez que marcou como visto
        return bool(visto and capturado and capturado > visto)

    eventos = []
    for c in con.execute("SELECT * FROM comunicacoes WHERE numero=? ORDER BY data_disp DESC", (numero,)):
        eventos.append({
            "fonte": "djen", "data": c["data_disp"], "titulo": c["tipo"] or "Publicação",
            "orgao": c["orgao"], "texto": c["texto"], "link": c["link"], "documento": c["tipo_documento"],
            "resumo": txt.resumo(c["texto"], 360), "novo": novo(c["capturado_em"]),
            "destinatarios": [d.get("nome") for d in json.loads(c["destinatarios"] or "[]") if d.get("nome")],
        })
    for m in con.execute("SELECT * FROM movimentos WHERE numero=? ORDER BY data_hora DESC", (numero,)):
        eventos.append({
            "fonte": "datajud", "data": m["data_hora"], "titulo": m["nome"], "complementos": m["complementos"],
            "orgao": m["orgao"], "grau": m["grau"], "novo": novo(m["capturado_em"]),
        })
    eventos.sort(key=lambda e: e["data"] or "", reverse=True)
    p["eventos"] = eventos
    return p


def opcoes_filtros(con) -> dict:
    tribunais = [r[0] for r in con.execute("SELECT DISTINCT tribunal FROM processos WHERE tribunal IS NOT NULL ORDER BY tribunal")]
    orgaos = [{"tribunal": r[0], "orgao": r[1]} for r in con.execute(
        "SELECT DISTINCT tribunal, orgao FROM processos WHERE orgao IS NOT NULL ORDER BY orgao COLLATE NOCASE")]
    return {"tribunais": tribunais, "orgaos": orgaos}
