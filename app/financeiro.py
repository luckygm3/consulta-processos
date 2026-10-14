"""Financeiro: lançamentos de honorários (entrada + parcelas mensais), pagamentos e o painel de visão geral.

Valores sempre em centavos (inteiros). A entrada é guardada como a parcela de número 0, com vencimento na data de
pagamento da entrada; as parcelas 1..n vencem uma por mês a partir do 1º vencimento (editáveis uma a uma).
Cada parcela tem um histórico de pagamentos (tabela pagamentos): pendente (nada pago), parcial (pagou uma parte) ou
paga (pago >= valor). A parcial continua aberta pelo que falta, no vencimento e no calendário.
No calendário, o lembrete de cada parcela cai 1 dia depois do vencimento, para conferir se foi paga.
Lançamento de cliente inadimplente não entra na renda do mês (a receber no mês e previsto), mas continua no cadastro,
no total a receber e no bloco "Inadimplentes" do painel.
"""
import calendar
import re
from datetime import date, timedelta

from . import cnj, db

LEMBRETE_DIAS_DEPOIS = 1
MAX_PARCELAS = 360


def somar_meses(d: date, n: int) -> date:
    """Mesmo dia n meses depois; se o mês não tem esse dia (31/02), usa o último dia do mês."""
    m = d.month - 1 + n
    ano, mes = d.year + m // 12, m % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def gerar_vencimentos(primeiro: date, qtd: int) -> list[date]:
    """Sempre contado a partir do 1º vencimento: 31/01 -> 28/02 -> 31/03 (não "escorrega" para o dia 28)."""
    return [somar_meses(primeiro, i) for i in range(max(0, qtd))]


def diferenca(total: int, entrada: int, valores_parcelas: list[int]) -> int:
    """Quanto falta (+) ou sobra (-) para entrada + parcelas fecharem o total."""
    return total - entrada - sum(valores_parcelas)


def quitacao(valor: int, pagamentos: list[dict]) -> tuple[int, str | None]:
    """(total pago, data do pagamento que quitou a parcela ou None). Pagamentos em ordem de data."""
    soma, quitou = 0, None
    for g in pagamentos:
        soma += g["valor"]
        if quitou is None and soma >= valor:
            quitou = g["data"]
    return soma, quitou


def chave_cliente(nome: str) -> str:
    """Nome para comparar clientes: sem acento, minúsculo e com espaços simples."""
    return " ".join(db.normalizar(nome).split())


# --- validação e gravação ---------------------------------------------------------

def _centavos(valor, campo: str, minimo: int = 0) -> int:
    try:
        v = int(valor or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{campo}: valor inválido")
    if v < minimo:
        raise ValueError(f"{campo}: valor inválido")
    return v


def _data(valor, campo: str, obrigatoria: bool = True) -> str | None:
    v = str(valor or "")[:10]
    if not v:
        if obrigatoria:
            raise ValueError(f"Informe {campo}")
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"{campo}: data inválida")
    return v


def _pagamento(dados: dict, rotulo: str = "") -> dict:
    de = f" ({rotulo})" if rotulo else ""
    return {"valor": _centavos(dados.get("valor"), f"Valor pago{de}", 1),
            "data": _data(dados.get("data"), f"a data do pagamento{de}")}


def _pagamentos_da_tela(p: dict, valor: int, rotulo: str, hoje: date) -> list[dict]:
    """Histórico da parcela vindo do formulário. Sem a lista (chamada antiga), "pago" vira um pagamento do valor cheio."""
    if p.get("pagamentos") is not None:
        return sorted((_pagamento(g, rotulo) for g in p["pagamentos"]), key=lambda g: g["data"])
    if p.get("pago") and valor:
        return [{"valor": valor, "data": _data(p.get("pago_em"), f"a data do pagamento ({rotulo})", obrigatoria=False)
                 or hoje.isoformat()}]
    return []


def _valores(dados: dict, hoje: date | None = None) -> tuple[dict, list[dict]]:
    hoje = hoje or date.today()
    cliente = re.sub(r"\s+", " ", str(dados.get("cliente") or "")).strip()[:120]
    if not cliente:
        raise ValueError("Informe o nome do cliente")
    numero = cnj.so_digitos(dados.get("numero") or "") or None
    if numero and (len(numero) != 20 or not cnj.digito_valido(numero)):
        raise ValueError("Número de processo inválido")
    total = _centavos(dados.get("valor_total"), "Valor total", 1)
    entrada = _centavos(dados.get("entrada"), "Valor da entrada")
    valor_parcela = _centavos(dados.get("valor_parcela"), "Valor das parcelas")
    qtd = _centavos(dados.get("qtd_parcelas"), "Quantidade de parcelas")
    if qtd > MAX_PARCELAS:
        raise ValueError(f"No máximo {MAX_PARCELAS} parcelas")
    entrada_data = _data(dados.get("entrada_data"), "a data de pagamento da entrada", obrigatoria=entrada > 0)
    lanc = {"cliente": cliente, "numero": numero, "valor_total": total, "entrada": entrada, "entrada_data": entrada_data,
            "valor_parcela": valor_parcela, "qtd_parcelas": qtd,
            "observacoes": (str(dados.get("observacoes") or "").strip()[:2000] or None),
            "inadimplente": 1 if dados.get("inadimplente") else 0}

    # Parcelas: as da tela (datas e valores editados um a um) ou, se não vierem, geradas a partir do 1º vencimento
    recebidas = dados.get("parcelas")
    if recebidas is None:
        if qtd:
            primeiro = date.fromisoformat(_data(dados.get("primeiro_vencimento"), "o 1º vencimento"))
            recebidas = [{"numero": i + 1, "vencimento": d.isoformat(), "valor": valor_parcela}
                         for i, d in enumerate(gerar_vencimentos(primeiro, qtd))]
        else:
            recebidas = []
        if entrada:
            recebidas = [{"numero": 0, "vencimento": entrada_data, "valor": entrada,
                          "pago": dados.get("entrada_paga", False)}] + recebidas
    parcelas, numeros = [], set()
    for p in recebidas:
        n = _centavos(p.get("numero"), "Número da parcela")
        if n == 0 and not entrada:
            continue  # sem valor de entrada, não há linha de entrada
        if n in numeros or n > qtd:
            raise ValueError("Parcelas repetidas ou fora da quantidade informada")
        numeros.add(n)
        rotulo = "Entrada" if n == 0 else f"Parcela {n}"
        valor = entrada if n == 0 else _centavos(p.get("valor"), rotulo)
        parcelas.append({
            # a entrada vence na "data de pagamento da entrada" (campo próprio do formulário)
            "numero": n, "vencimento": entrada_data if n == 0 else _data(p.get("vencimento"), f"o vencimento ({rotulo})"),
            "valor": valor, "pagamentos": _pagamentos_da_tela(p, valor, rotulo, hoje),
        })
    if entrada and 0 not in numeros:  # tela antiga/sem a linha: cria a entrada a partir dos campos
        parcelas.append({"numero": 0, "vencimento": entrada_data, "valor": entrada, "pagamentos": []})
    if len(numeros - {0}) != qtd:
        raise ValueError(f"São {qtd} parcelas: falta o vencimento de alguma")
    parcelas.sort(key=lambda p: p["numero"])
    return lanc, parcelas


def salvar(con, dados: dict, lid: int | None = None) -> int:
    lanc, parcelas = _valores(dados)
    lanc["atualizado_em"] = db.agora()
    if lid:
        if not con.execute("SELECT 1 FROM lancamentos WHERE id=?", (lid,)).fetchone():
            raise LookupError("Lançamento não encontrado")
        con.execute(f"UPDATE lancamentos SET {','.join(f'{k}=?' for k in lanc)} WHERE id=?", [*lanc.values(), lid])
        _apagar_parcelas(con, lid)
    else:
        lanc["criado_em"] = lanc["atualizado_em"]
        lid = con.execute(f"INSERT INTO lancamentos({','.join(lanc)}) VALUES({','.join('?' * len(lanc))})",
                          list(lanc.values())).lastrowid
    for p in parcelas:
        _, quitou = quitacao(p["valor"], p["pagamentos"])
        pid = con.execute("INSERT INTO parcelas(lancamento_id, numero, vencimento, valor, pago, pago_em) VALUES(?,?,?,?,?,?)",
                          (lid, p["numero"], p["vencimento"], p["valor"], 1 if quitou else 0, quitou)).lastrowid
        con.executemany("INSERT INTO pagamentos(parcela_id, valor, data, criado_em) VALUES(?,?,?,?)",
                        [(pid, g["valor"], g["data"], lanc["atualizado_em"]) for g in p["pagamentos"]])
    return lid


def _apagar_parcelas(con, lid: int):
    con.execute("DELETE FROM pagamentos WHERE parcela_id IN (SELECT id FROM parcelas WHERE lancamento_id=?)", (lid,))
    con.execute("DELETE FROM parcelas WHERE lancamento_id=?", (lid,))


def excluir(con, lid: int):
    _apagar_parcelas(con, lid)
    con.execute("DELETE FROM lancamentos WHERE id=?", (lid,))


# --- pagamentos de uma parcela ------------------------------------------------------

def _pagamentos(con, pid: int) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT id, valor, data FROM pagamentos WHERE parcela_id=? ORDER BY data, id",
                                         (pid,))]


def _mudou(con, pid: int):
    """Depois de mexer no histórico: refaz o resumo da parcela (pago = quitada, pago_em) e a data do lançamento."""
    valor = con.execute("SELECT valor FROM parcelas WHERE id=?", (pid,)).fetchone()[0]
    _, quitou = quitacao(valor, _pagamentos(con, pid))
    con.execute("UPDATE parcelas SET pago=?, pago_em=? WHERE id=?", (1 if quitou else 0, quitou, pid))
    con.execute("UPDATE lancamentos SET atualizado_em=? WHERE id=(SELECT lancamento_id FROM parcelas WHERE id=?)",
                (db.agora(), pid))


def adicionar_pagamento(con, pid: int, dados: dict) -> int:
    """Lança um pagamento (parcial ou não) na parcela, sem mexer nos que já existem."""
    if not con.execute("SELECT 1 FROM parcelas WHERE id=?", (pid,)).fetchone():
        raise LookupError("Parcela não encontrada")
    g = _pagamento(dados)
    gid = con.execute("INSERT INTO pagamentos(parcela_id, valor, data, criado_em) VALUES(?,?,?,?)",
                      (pid, g["valor"], g["data"], db.agora())).lastrowid
    _mudou(con, pid)
    return gid


def _parcela_do_pagamento(con, gid: int) -> int:
    r = con.execute("SELECT parcela_id FROM pagamentos WHERE id=?", (gid,)).fetchone()
    if not r:
        raise LookupError("Pagamento não encontrado")
    return r[0]


def editar_pagamento(con, gid: int, dados: dict):
    pid = _parcela_do_pagamento(con, gid)
    g = _pagamento(dados)
    con.execute("UPDATE pagamentos SET valor=?, data=? WHERE id=?", (g["valor"], g["data"], gid))
    _mudou(con, pid)


def excluir_pagamento(con, gid: int):
    pid = _parcela_do_pagamento(con, gid)
    con.execute("DELETE FROM pagamentos WHERE id=?", (gid,))
    _mudou(con, pid)


def marcar_paga(con, pid: int, pago: bool, pago_em: str | None = None, hoje: date | None = None) -> bool:
    """Atalho da caixinha "paga": marcar lança um pagamento do que falta (na data informada ou hoje);
    desmarcar apaga o histórico da parcela."""
    r = con.execute("SELECT valor FROM parcelas WHERE id=?", (pid,)).fetchone()
    if not r:
        return False
    if pago:
        data = _data(pago_em, "a data do pagamento", obrigatoria=False) or (hoje or date.today()).isoformat()
        falta = r["valor"] - sum(g["valor"] for g in _pagamentos(con, pid))
        if falta > 0:
            con.execute("INSERT INTO pagamentos(parcela_id, valor, data, criado_em) VALUES(?,?,?,?)",
                        (pid, falta, data, db.agora()))
    else:
        con.execute("DELETE FROM pagamentos WHERE parcela_id=?", (pid,))
    _mudou(con, pid)
    return True


# --- leitura ---------------------------------------------------------------------------

def _situacao(p: dict, hoje: date) -> tuple[str, int]:
    if p["pago"]:
        return "paga", 0
    atraso = (hoje - date.fromisoformat(p["vencimento"])).days
    return ("atrasada", atraso) if atraso > 0 else ("pendente", 0)


def listar(con, hoje: date | None = None) -> list[dict]:
    """Lançamentos com as parcelas (e o histórico de pagamentos de cada uma) e os saldos."""
    hoje = hoje or date.today()
    pagamentos: dict[int, list[dict]] = {}
    for r in con.execute("SELECT id, parcela_id, valor, data FROM pagamentos ORDER BY data, id"):
        pagamentos.setdefault(r["parcela_id"], []).append({"id": r["id"], "valor": r["valor"], "data": r["data"]})
    parcelas: dict[int, list[dict]] = {}
    for r in con.execute("SELECT * FROM parcelas ORDER BY lancamento_id, numero"):
        p = dict(r)
        p["pagamentos"] = pagamentos.get(p["id"], [])
        p["pago_valor"], quitou = quitacao(p["valor"], p["pagamentos"])
        p["falta"] = max(0, p["valor"] - p["pago_valor"])
        p["pago"], p["pago_em"] = (1, quitou) if quitou else (0, None)
        p["status"] = "paga" if quitou else "parcial" if p["pago_valor"] > 0 else "pendente"
        p["situacao"], p["dias_atraso"] = _situacao(p, hoje)
        parcelas.setdefault(p["lancamento_id"], []).append(p)
    saida = []
    for r in con.execute("""SELECT l.*, pr.partes AS p_partes FROM lancamentos l
                            LEFT JOIN processos pr ON pr.numero = l.numero
                            ORDER BY l.cliente COLLATE NOCASE, l.id"""):
        d = dict(r)
        d["numero_fmt"] = cnj.formatar(d["numero"]) if d["numero"] else ""
        d["partes"] = db.resumo_partes(d.pop("p_partes"))
        d["inadimplente"] = bool(d["inadimplente"])
        ps = parcelas.get(d["id"], [])
        for p in ps:
            p["rotulo"] = "Entrada" if p["numero"] == 0 else f"{p['numero']}/{d['qtd_parcelas']}"
        d["parcelas"] = ps
        d["recebido"] = sum(p["pago_valor"] for p in ps)
        d["falta"] = sum(p["falta"] for p in ps)
        d["atrasado"] = sum(p["falta"] for p in ps if p["situacao"] == "atrasada")
        d["diferenca"] = diferenca(d["valor_total"], d["entrada"], [p["valor"] for p in ps if p["numero"] > 0])
        abertas = [p for p in ps if not p["pago"]]
        d["proximo_vencimento"] = min((p["vencimento"] for p in abertas), default=None)
        saida.append(d)
    return saida


def _atraso_por_cliente(parcelas: list[dict]) -> list[dict]:
    """O que falta das parcelas em atraso, por cliente (todo cliente das parcelas recebidas aparece, mesmo sem
    atraso), dos mais atrasados para os menos."""
    grupos: dict[str, dict] = {}
    for p in parcelas:
        g = grupos.setdefault(chave_cliente(p["cliente"]), {
            "cliente": p["cliente"], "valor": 0, "parcelas": 0, "dias_atraso": 0, "desde": None, "lancamentos": []})
        if p["lancamento_id"] not in g["lancamentos"]:
            g["lancamentos"].append(p["lancamento_id"])
        if p["situacao"] != "atrasada":
            continue
        g["valor"] += p["falta"]
        g["parcelas"] += 1
        g["dias_atraso"] = max(g["dias_atraso"], p["dias_atraso"])
        g["desde"] = min(g["desde"] or p["vencimento"], p["vencimento"])
    return sorted(grupos.values(), key=lambda g: (-g["dias_atraso"], -g["valor"], g["cliente"]))


def resumo(lancamentos: list[dict], mes: str, hoje: date | None = None) -> dict:
    """Números do painel. mes = 'AAAA-MM' (o mês navegado nos cards; 'recebido no ano' usa o ano desse mês).
    Parcela parcial conta pelo que falta; recebido conta pela data de cada pagamento. Inadimplente fica fora da renda
    do mês e do "em atraso" (tem bloco próprio), mas entra no total a receber."""
    hoje = hoje or date.today()
    ano = mes[:4]
    todas = [{**p, "cliente": l["cliente"], "numero_fmt": l["numero_fmt"], "inadimplente": l["inadimplente"]}
             for l in lancamentos for p in l["parcelas"]]
    do_mes = [p for p in todas if p["vencimento"][:7] == mes]
    renda = [p for p in do_mes if not p["inadimplente"]]
    pagamentos = [g for p in todas for g in p["pagamentos"]]
    atrasados = _atraso_por_cliente([p for p in todas if p["situacao"] == "atrasada" and not p["inadimplente"]])
    inadimplentes = _atraso_por_cliente([p for p in todas if p["inadimplente"]])
    proximas = sorted((p for p in todas if not p["pago"] and p["vencimento"] >= hoje.isoformat()),
                      key=lambda p: (p["vencimento"], p["cliente"]))
    return {
        "mes": mes,
        "a_receber_mes": {"pendente": sum(p["falta"] for p in renda),
                          "pago": sum(min(p["pago_valor"], p["valor"]) for p in renda),
                          "previsto": sum(p["valor"] for p in renda),
                          "qtd_pendente": sum(1 for p in renda if not p["pago"]),
                          "inadimplentes": sum(p["falta"] for p in do_mes if p["inadimplente"])},
        "recebido_mes": sum(g["valor"] for g in pagamentos if g["data"][:7] == mes),
        "recebido_ano": sum(g["valor"] for g in pagamentos if g["data"][:4] == ano),
        "total_a_receber": sum(p["falta"] for p in todas),
        "em_atraso": {"valor": sum(g["valor"] for g in atrasados), "clientes": len(atrasados),
                      "parcelas": sum(g["parcelas"] for g in atrasados)},
        "atrasados": atrasados,
        "inadimplentes": {"valor": sum(g["valor"] for g in inadimplentes), "clientes": len(inadimplentes),
                          "parcelas": sum(g["parcelas"] for g in inadimplentes), "lista": inadimplentes},
        "proximas": proximas[:8],
    }


def clientes_inadimplentes(con) -> set[str]:
    """Chaves (chave_cliente) dos clientes com algum lançamento marcado como inadimplente."""
    return {chave_cliente(r[0]) for r in con.execute("SELECT cliente FROM lancamentos WHERE inadimplente=1")}


def lembretes(lancamentos: list[dict], de: str, ate: str) -> list[dict]:
    """Lembretes do calendário: 1 dia depois de cada vencimento, para conferir se a parcela foi paga."""
    saida = []
    for l in lancamentos:
        for p in l["parcelas"]:
            dia = (date.fromisoformat(p["vencimento"]) + timedelta(days=LEMBRETE_DIAS_DEPOIS)).isoformat()
            if de <= dia <= ate:
                saida.append({**p, "data": dia, "cliente": l["cliente"], "numero_fmt": l["numero_fmt"],
                              "qtd_parcelas": l["qtd_parcelas"], "inadimplente": l["inadimplente"]})
    return sorted(saida, key=lambda p: (p["data"], p["cliente"]))
