"""Quadro de clientes (aba Clientes; o nome fica em static/quadro.js): 5 colunas que ela nomeia, cards de cliente
(tabela clientes) ligados a um processo ou marcados como petição inicial (o processo ainda não existe) ou
preventivo/consultoria. Criado à mão, o card nasce com a checklist padrão; cada processo também ganha um card sozinho
(interligar.py), e as tarefas aprovadas no Monitoramento entram no checklist dele. Na tela e na API o nome do cliente
se chama "titulo"."""
import calendar
import re
from datetime import date

from . import agenda, checklist, cnj, db, financeiro, prazos

TIPOS = {"processo": "Com processo", "inicial": "Petição inicial", "preventivo": "Preventivo / consultoria"}
MODELO = {"processo": "processo", "inicial": "processo", "preventivo": "preventivo"}  # tipo -> checklist padrão


def prazos_processuais(con, hoje: date | None = None) -> dict[str, dict]:
    """Prazo fatal processual de cada processo = o próximo prazo dele: item ainda não feito, no checklist do cliente,
    que veio de um prazo aprovado no Monitoramento (com a data do item, que ela pode ter mudado), ou sugestão ainda
    aguardando aprovação. Sem prazo futuro, o último vencido ainda em aberto. Sugestões já vencidas não contam."""
    hoje = (hoje or date.today()).isoformat()
    melhor: dict[str, dict] = {}
    for r in con.execute("""SELECT t.numero, t.titulo AS descricao, t.prazo_fatal AS data, t.hora, t.id AS tarefa_id,
                                   true AS sugerido
                              FROM tarefas t
                             WHERE t.status='sugerido' AND t.tipo='prazo' AND t.numero IS NOT NULL AND t.prazo_fatal >= %s
                            UNION ALL
                            SELECT c.numero, i.texto, i.data, i.hora, t.id, false
                              FROM checklist_itens i JOIN tarefas t ON t.id = i.origem_id
                              JOIN clientes c ON c.id = i.cliente_id
                             WHERE t.tipo='prazo' AND NOT i.feito AND i.data IS NOT NULL AND c.numero IS NOT NULL
                            ORDER BY data, sugerido""", (hoje,)):
        atual = melhor.get(r["numero"])
        # em ordem de data: troca enquanto o escolhido estiver vencido (fica o 1º futuro, ou o vencido mais recente)
        if atual is None or atual["data"] < hoje:
            melhor[r["numero"]] = {"tipo": "processual", "descricao": r["descricao"], "data": r["data"],
                                   "hora": r["hora"], "tarefa_id": r["tarefa_id"], "sugerido": r["sugerido"]}
    return melhor


def carregar(con, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    cals = agenda.Calendarios(con)
    processuais = prazos_processuais(con, hoje)
    inadimplentes = financeiro.clientes_inadimplentes(con)  # selo no card: mesmo nome de um lançamento inadimplente
    colunas = [dict(r) for r in con.execute("SELECT id, posicao, nome FROM clientes_colunas ORDER BY posicao")]
    itens = checklist.ler(con, "card")
    sugestoes = {r[0]: r[1] for r in con.execute(  # aguardando aprovação no Monitoramento, por processo
        "SELECT numero, COUNT(*) FROM tarefas WHERE status='sugerido' AND numero IS NOT NULL GROUP BY numero")}
    cards = []
    for r in con.execute("""SELECT q.*, p.partes AS p_partes, p.numero AS p_numero, p.tribunal AS p_tribunal,
                                   p.orgao AS p_orgao,
                                   (SELECT string_agg(advogada_id::text, ',') FROM processo_advogada pa
                                     WHERE pa.numero=q.numero) AS p_advs
                            FROM clientes q LEFT JOIN processos p ON p.numero = q.numero
                            ORDER BY q.coluna_id, q.posicao, q.id"""):
        d = dict(r)
        d["titulo"] = d.pop("nome")
        d["checklist"] = itens.get(d["id"], [])
        d["numero_fmt"] = cnj.formatar(d["numero"]) if d["numero"] else ""
        d["partes"] = db.resumo_partes(d.pop("p_partes"))
        d["cadastrado"] = d.pop("p_numero") is not None  # o painel do processo só abre se ele está na lista
        d["advogadas_processo"] = [int(x) for x in (d.pop("p_advs") or "").split(",") if x]
        d["inadimplente"] = financeiro.chave_cliente(d["titulo"]) in inadimplentes
        d["sugestoes"] = sugestoes.get(d["numero"], 0) if d["numero"] else 0
        cal = cals.de(d.pop("p_tribunal") or "", d.pop("p_orgao") or "")
        for c in d["checklist"]:  # tarefa aprovada (prazo, audiência…) com data: cor da urgência na Agenda e no alerta
            if c.get("tipo") and c["data"] and not c["feito"]:
                c["urgencia"], c["dias_restantes"] = prazos.urgencia(c["data"], cal, hoje)
        if d["tipo"] == "processo":
            prazo = dict(processuais[d["numero"]]) if d["numero"] in processuais else None
        elif d["prazo_data"]:
            prazo = {"tipo": "interno", "descricao": d["prazo_descricao"] or "Prazo fatal", "data": d["prazo_data"],
                     "hora": d["prazo_hora"]}
        else:
            prazo = None
        if prazo:
            prazo["urgencia"], prazo["dias_restantes"] = prazos.urgencia(prazo["data"], cal, hoje)
        d["prazo"] = prazo
        cards.append(d)
    return {"colunas": colunas, "cards": cards, "tipos": TIPOS}


def _valores(dados: dict, tipo_atual: str | None = None) -> dict:
    v = {}
    if "titulo" in dados:
        v["nome"] = (dados["titulo"] or "").strip()
        if not v["nome"]:
            raise ValueError("Informe o nome do cliente")
    if "tipo" in dados or "numero" in dados:
        tipo = dados.get("tipo") or tipo_atual or "processo"
        if tipo not in TIPOS:
            raise ValueError("Tipo inválido")
        numero = cnj.so_digitos(dados.get("numero") or "") or None
        if tipo != "processo":
            numero = None  # petição inicial / preventivo: sem processo (vincula depois, mudando o tipo)
        elif not numero:
            raise ValueError("Escolha o processo, ou mude o tipo para petição inicial ou preventivo")
        elif len(numero) != 20 or not cnj.digito_valido(numero):
            raise ValueError("Número de processo inválido (confira os dígitos)")
        v["tipo"], v["numero"] = tipo, numero
    if "prazo_data" in dados or "prazo_descricao" in dados or "prazo_hora" in dados:
        data = str(dados.get("prazo_data") or "")[:10] or None
        if data:
            date.fromisoformat(data)  # ValueError -> 400
        hora = str(dados.get("prazo_hora") or "")[:5] or None
        if not data or (hora and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora)):
            hora = None
        v["prazo_descricao"] = (dados.get("prazo_descricao") or "").strip()[:120] or None
        v["prazo_data"], v["prazo_hora"] = data, hora
    if "aniversario" in dados:
        aniv = str(dados.get("aniversario") or "")[:10] or None
        if aniv:
            date.fromisoformat(aniv)  # ValueError -> 400
        v["aniversario"] = aniv
    if v.get("tipo") == "processo":  # com processo, o prazo fatal é o processual (vem da agenda)
        v["prazo_descricao"] = v["prazo_data"] = v["prazo_hora"] = None
    return v


def criar(con, dados: dict) -> int:
    coluna = int(dados.get("coluna_id") or 0)
    if not con.execute("SELECT 1 FROM clientes_colunas WHERE id=%s", (coluna,)).fetchone():
        raise ValueError("Coluna inválida")
    dados = {"tipo": "processo", **dados}
    if "checklist" not in dados:  # nasce com a checklist padrão do tipo (petição inicial usa a de processo)
        dados["checklist"] = checklist.padrao(MODELO.get(dados["tipo"], "processo"))
    v = _valores(dados)
    v["coluna_id"] = coluna
    v["posicao"] = con.execute("SELECT COALESCE(MAX(posicao), 0) + 1 FROM clientes WHERE coluna_id=%s",
                               (coluna,)).fetchone()[0]  # entra no fim da coluna
    v["criado_em"] = v["atualizado_em"] = db.agora()
    cid = con.execute(f"INSERT INTO clientes({','.join(v)}) VALUES({','.join(['%s'] * len(v))}) RETURNING id",
                      list(v.values())).fetchone()[0]
    checklist.gravar(con, "card", cid, dados["checklist"])
    return cid


def atualizar(con, cid: int, dados: dict) -> bool:
    atual = db.travar(con, "clientes", cid, dados)
    if not atual:
        return False
    v = _valores(dados, atual["tipo"])
    if "titulo" in dados:  # salvo pelo diálogo do card: ela já conferiu o que foi criado sozinho
        v["completar"] = False
    if "checklist" in dados:
        checklist.gravar(con, "card", cid, dados["checklist"])
    if v or "checklist" in dados:
        v["atualizado_em"] = db.agora()
        con.execute(f"UPDATE clientes SET {','.join(f'{k}=%s' for k in v)} WHERE id=%s", [*v.values(), cid])
    return True


def ordenar(con, coluna_id: int, ids: list[int]):
    """Grava a ordem de uma coluna depois de arrastar (o card arrastado pode ter vindo de outra coluna)."""
    if not con.execute("SELECT 1 FROM clientes_colunas WHERE id=%s", (coluna_id,)).fetchone():
        raise ValueError("Coluna inválida")
    con.executemany("UPDATE clientes SET coluna_id=%s, posicao=%s WHERE id=%s",
                    [(coluna_id, i, cid) for i, cid in enumerate(ids, start=1)])


def renomear_coluna(con, coluna_id: int, nome: str) -> bool:
    cur = con.execute("UPDATE clientes_colunas SET nome=%s WHERE id=%s", ((nome or "").strip()[:60], coluna_id))
    return cur.rowcount > 0


# --- aniversários: "Parabenizar <cliente>" todo ano, calculado na hora (nada é copiado para a agenda) -----------

def dia_do_aniversario(aniversario: str, ano: int) -> date:
    """Data do aniversário naquele ano; quem nasceu em 29/02 é lembrado em 28/02 nos anos comuns."""
    mes, dia = int(aniversario[5:7]), int(aniversario[8:10])
    if mes == 2 and dia == 29 and not calendar.isleap(ano):
        dia = 28
    return date(ano, mes, dia)


def aniversarios(con, de: str, ate: str) -> list[dict]:
    """Ocorrências entre de e ate (AAAA-MM-DD). Feito vale por ano (tabela lembretes_feitos, chave aniv:<card>:<ano>)."""
    a, b = date.fromisoformat(de), date.fromisoformat(ate)
    feitos = {r[0] for r in con.execute("SELECT chave FROM lembretes_feitos WHERE chave LIKE 'aniv:%'")}
    saida = []
    for r in con.execute("SELECT id, nome, aniversario FROM clientes WHERE aniversario IS NOT NULL"):
        for ano in range(a.year, b.year + 1):
            try:
                dia = dia_do_aniversario(r["aniversario"], ano)
            except ValueError:
                break  # data gravada com defeito: ignora este card
            if a <= dia <= b:
                chave = f"aniv:{r['id']}:{ano}"
                saida.append({"chave": chave, "card_id": r["id"], "cliente": r["nome"], "data": dia.isoformat(),
                              "feito": chave in feitos})
    return sorted(saida, key=lambda x: (x["data"], x["cliente"]))


def marcar_lembrete(con, chave: str, feito: bool):
    if not re.fullmatch(r"aniv:\d+:\d{4}", chave or ""):
        raise ValueError("Lembrete inválido")
    if feito:
        con.execute("""INSERT INTO lembretes_feitos(chave, feito_em) VALUES(%s, %s)
                       ON CONFLICT(chave) DO UPDATE SET feito_em=excluded.feito_em""", (chave, db.agora()))
    else:
        con.execute("DELETE FROM lembretes_feitos WHERE chave=%s", (chave,))
