"""Quadro de clientes (aba com nome provisório, definido em static/quadro.js): 5 colunas que ela nomeia, cards de
cliente criados à mão, com a checklist padrão, ligados a um processo ou marcados como petição inicial (o processo
ainda não existe) ou preventivo/consultoria."""
import json
import re
from datetime import date

from . import agenda, checklist, cnj, db, prazos

TIPOS = {"processo": "Com processo", "inicial": "Petição inicial", "preventivo": "Preventivo / consultoria"}
MODELO = {"processo": "processo", "inicial": "processo", "preventivo": "preventivo"}  # tipo -> checklist padrão


def prazos_processuais(con, hoje: date | None = None) -> dict[str, dict]:
    """Prazo fatal processual de cada processo = o próximo prazo dele na agenda (vindo do DJEN / "Verificar prazos"
    ou calculado). Sem prazo futuro, o último vencido ainda em aberto. Sugestões já vencidas não contam."""
    hoje = (hoje or date.today()).isoformat()
    melhor: dict[str, dict] = {}
    for r in con.execute("""SELECT id, numero, titulo, prazo_fatal, hora, status FROM tarefas
                            WHERE numero IS NOT NULL AND prazo_fatal IS NOT NULL AND tipo='prazo'
                              AND status NOT IN ('concluido', 'descartado')
                              AND (status != 'sugerido' OR prazo_fatal >= ?)
                            ORDER BY prazo_fatal""", (hoje,)):
        atual = melhor.get(r["numero"])
        # em ordem de data: troca enquanto o escolhido estiver vencido (fica o 1º futuro, ou o vencido mais recente)
        if atual is None or atual["data"] < hoje:
            melhor[r["numero"]] = {"tipo": "processual", "descricao": r["titulo"], "data": r["prazo_fatal"],
                                   "hora": r["hora"], "tarefa_id": r["id"], "sugerido": r["status"] == "sugerido"}
    return melhor


def carregar(con, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    cals = agenda.Calendarios(con)
    processuais = prazos_processuais(con, hoje)
    colunas = [dict(r) for r in con.execute("SELECT id, posicao, nome FROM quadro_colunas ORDER BY posicao")]
    cards = []
    for r in con.execute("""SELECT q.*, p.partes AS p_partes, p.numero AS p_numero, p.tribunal AS p_tribunal,
                                   p.orgao AS p_orgao,
                                   (SELECT GROUP_CONCAT(advogada_id) FROM processo_advogada pa WHERE pa.numero=q.numero) AS p_advs
                            FROM quadro_cards q LEFT JOIN processos p ON p.numero = q.numero
                            ORDER BY q.coluna_id, q.posicao, q.id"""):
        d = dict(r)
        d["checklist"] = checklist.ler(d["checklist"])
        d["numero_fmt"] = cnj.formatar(d["numero"]) if d["numero"] else ""
        d["partes"] = db.resumo_partes(d.pop("p_partes"))
        d["cadastrado"] = d.pop("p_numero") is not None  # o painel do processo só abre se ele está na lista
        d["advogadas_processo"] = [int(x) for x in (d.pop("p_advs") or "").split(",") if x]
        if d["tipo"] == "processo":
            prazo = dict(processuais[d["numero"]]) if d["numero"] in processuais else None
        elif d["prazo_data"]:
            prazo = {"tipo": "interno", "descricao": d["prazo_descricao"] or "Prazo fatal", "data": d["prazo_data"],
                     "hora": d["prazo_hora"]}
        else:
            prazo = None
        if prazo:
            cal = cals.de(d.pop("p_tribunal") or "", d.pop("p_orgao") or "")
            prazo["urgencia"], prazo["dias_restantes"] = prazos.urgencia(prazo["data"], cal, hoje)
        d.pop("p_tribunal", None)
        d.pop("p_orgao", None)
        d["prazo"] = prazo
        cards.append(d)
    return {"colunas": colunas, "cards": cards, "tipos": TIPOS}


def _valores(dados: dict, tipo_atual: str | None = None) -> dict:
    v = {}
    if "titulo" in dados:
        v["titulo"] = (dados["titulo"] or "").strip()
        if not v["titulo"]:
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
    if "checklist" in dados:
        v["checklist"] = json.dumps(checklist.normalizar(dados["checklist"]), ensure_ascii=False)
    if "prazo_data" in dados or "prazo_descricao" in dados or "prazo_hora" in dados:
        data = str(dados.get("prazo_data") or "")[:10] or None
        if data:
            date.fromisoformat(data)  # ValueError -> 400
        hora = str(dados.get("prazo_hora") or "")[:5] or None
        if not data or (hora and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora)):
            hora = None
        v["prazo_descricao"] = (dados.get("prazo_descricao") or "").strip()[:120] or None
        v["prazo_data"], v["prazo_hora"] = data, hora
    if v.get("tipo") == "processo":  # com processo, o prazo fatal é o processual (vem da agenda)
        v["prazo_descricao"] = v["prazo_data"] = v["prazo_hora"] = None
    return v


def criar(con, dados: dict) -> int:
    coluna = int(dados.get("coluna_id") or 0)
    if not con.execute("SELECT 1 FROM quadro_colunas WHERE id=?", (coluna,)).fetchone():
        raise ValueError("Coluna inválida")
    dados = {"tipo": "processo", **dados}
    if "checklist" not in dados:  # nasce com a checklist padrão do tipo (petição inicial usa a de processo)
        dados["checklist"] = checklist.padrao(MODELO.get(dados["tipo"], "processo"))
    v = _valores(dados)
    v["coluna_id"] = coluna
    v["posicao"] = con.execute("SELECT COALESCE(MAX(posicao), 0) + 1 FROM quadro_cards WHERE coluna_id=?",
                               (coluna,)).fetchone()[0]  # entra no fim da coluna
    v["criado_em"] = v["atualizado_em"] = db.agora()
    cur = con.execute(f"INSERT INTO quadro_cards({','.join(v)}) VALUES({','.join('?' * len(v))})", list(v.values()))
    return cur.lastrowid


def atualizar(con, cid: int, dados: dict) -> bool:
    atual = con.execute("SELECT tipo FROM quadro_cards WHERE id=?", (cid,)).fetchone()
    if not atual:
        return False
    v = _valores(dados, atual["tipo"])
    if v:
        v["atualizado_em"] = db.agora()
        con.execute(f"UPDATE quadro_cards SET {','.join(f'{k}=?' for k in v)} WHERE id=?", [*v.values(), cid])
    return True


def ordenar(con, coluna_id: int, ids: list[int]):
    """Grava a ordem de uma coluna depois de arrastar (o card arrastado pode ter vindo de outra coluna)."""
    if not con.execute("SELECT 1 FROM quadro_colunas WHERE id=?", (coluna_id,)).fetchone():
        raise ValueError("Coluna inválida")
    con.executemany("UPDATE quadro_cards SET coluna_id=?, posicao=? WHERE id=?",
                    [(coluna_id, i, cid) for i, cid in enumerate(ids, start=1)])


def renomear_coluna(con, coluna_id: int, nome: str) -> bool:
    cur = con.execute("UPDATE quadro_colunas SET nome=? WHERE id=?", ((nome or "").strip()[:60], coluna_id))
    return cur.rowcount > 0
