"""Financeiro: lançamentos de honorários (entrada + parcelas mensais), pagamentos e o painel de visão geral.

Valores sempre em centavos (inteiros). A entrada é guardada como a parcela de número 0, com vencimento na data de
pagamento da entrada; as parcelas 1..n vencem uma por mês a partir do 1º vencimento (editáveis uma a uma).
No calendário, o lembrete de cada parcela cai 1 dia depois do vencimento, para conferir se foi paga.
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
            "observacoes": (str(dados.get("observacoes") or "").strip()[:2000] or None)}

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
        pago = bool(p.get("pago"))
        parcelas.append({
            # a entrada vence na "data de pagamento da entrada" (campo próprio do formulário)
            "numero": n, "vencimento": entrada_data if n == 0 else _data(p.get("vencimento"), f"o vencimento ({rotulo})"),
            "valor": entrada if n == 0 else _centavos(p.get("valor"), rotulo),
            "pago": 1 if pago else 0,
            "pago_em": (_data(p.get("pago_em"), f"a data do pagamento ({rotulo})", obrigatoria=False) or hoje.isoformat())
            if pago else None,
        })
    if entrada and 0 not in numeros:  # tela antiga/sem a linha: cria a entrada a partir dos campos
        parcelas.append({"numero": 0, "vencimento": entrada_data, "valor": entrada, "pago": 0, "pago_em": None})
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
        con.execute("DELETE FROM parcelas WHERE lancamento_id=?", (lid,))
    else:
        lanc["criado_em"] = lanc["atualizado_em"]
        lid = con.execute(f"INSERT INTO lancamentos({','.join(lanc)}) VALUES({','.join('?' * len(lanc))})",
                          list(lanc.values())).lastrowid
    con.executemany("INSERT INTO parcelas(lancamento_id, numero, vencimento, valor, pago, pago_em) VALUES(?,?,?,?,?,?)",
                     [(lid, p["numero"], p["vencimento"], p["valor"], p["pago"], p["pago_em"]) for p in parcelas])
    return lid


def excluir(con, lid: int):
    con.execute("DELETE FROM parcelas WHERE lancamento_id=?", (lid,))
    con.execute("DELETE FROM lancamentos WHERE id=?", (lid,))


def marcar_paga(con, pid: int, pago: bool, pago_em: str | None = None, hoje: date | None = None) -> bool:
    data = (_data(pago_em, "a data do pagamento", obrigatoria=False) or (hoje or date.today()).isoformat()) if pago else None
    cur = con.execute("UPDATE parcelas SET pago=?, pago_em=? WHERE id=?", (1 if pago else 0, data, pid))
    if cur.rowcount:
        con.execute("UPDATE lancamentos SET atualizado_em=? WHERE id=(SELECT lancamento_id FROM parcelas WHERE id=?)",
                    (db.agora(), pid))
    return cur.rowcount > 0


# --- leitura ---------------------------------------------------------------------------

def _situacao(p: dict, hoje: date) -> tuple[str, int]:
    if p["pago"]:
        return "paga", 0
    atraso = (hoje - date.fromisoformat(p["vencimento"])).days
    return ("atrasada", atraso) if atraso > 0 else ("pendente", 0)


def listar(con, hoje: date | None = None) -> list[dict]:
    """Lançamentos com as parcelas e os saldos (recebido, falta receber, em atraso)."""
    hoje = hoje or date.today()
    parcelas: dict[int, list[dict]] = {}
    for r in con.execute("SELECT * FROM parcelas ORDER BY lancamento_id, numero"):
        p = dict(r)
        p["situacao"], p["dias_atraso"] = _situacao(p, hoje)
        parcelas.setdefault(p["lancamento_id"], []).append(p)
    saida = []
    for r in con.execute("""SELECT l.*, pr.partes AS p_partes FROM lancamentos l
                            LEFT JOIN processos pr ON pr.numero = l.numero
                            ORDER BY l.cliente COLLATE NOCASE, l.id"""):
        d = dict(r)
        d["numero_fmt"] = cnj.formatar(d["numero"]) if d["numero"] else ""
        d["partes"] = db.resumo_partes(d.pop("p_partes"))
        ps = parcelas.get(d["id"], [])
        for p in ps:
            p["rotulo"] = "Entrada" if p["numero"] == 0 else f"{p['numero']}/{d['qtd_parcelas']}"
        d["parcelas"] = ps
        d["recebido"] = sum(p["valor"] for p in ps if p["pago"])
        d["falta"] = sum(p["valor"] for p in ps if not p["pago"])
        d["atrasado"] = sum(p["valor"] for p in ps if p["situacao"] == "atrasada")
        d["diferenca"] = diferenca(d["valor_total"], d["entrada"], [p["valor"] for p in ps if p["numero"] > 0])
        abertas = [p for p in ps if not p["pago"]]
        d["proximo_vencimento"] = min((p["vencimento"] for p in abertas), default=None)
        saida.append(d)
    return saida


def resumo(lancamentos: list[dict], mes: str, hoje: date | None = None) -> dict:
    """Números do painel. mes = 'AAAA-MM' (o mês navegado nos cards; 'recebido no ano' usa o ano desse mês)."""
    hoje = hoje or date.today()
    ano = mes[:4]
    todas = [{**p, "cliente": l["cliente"], "numero_fmt": l["numero_fmt"]} for l in lancamentos for p in l["parcelas"]]
    do_mes = [p for p in todas if p["vencimento"][:7] == mes]
    inad: dict[str, dict] = {}
    for p in todas:
        if p["situacao"] != "atrasada":
            continue
        g = inad.setdefault(db.normalizar(p["cliente"]).strip(), {
            "cliente": p["cliente"], "valor": 0, "parcelas": 0, "dias_atraso": 0, "desde": p["vencimento"],
            "lancamentos": []})
        g["valor"] += p["valor"]
        g["parcelas"] += 1
        g["dias_atraso"] = max(g["dias_atraso"], p["dias_atraso"])
        g["desde"] = min(g["desde"], p["vencimento"])
        if p["lancamento_id"] not in g["lancamentos"]:
            g["lancamentos"].append(p["lancamento_id"])
    proximas = sorted((p for p in todas if not p["pago"] and p["vencimento"] >= hoje.isoformat()),
                      key=lambda p: (p["vencimento"], p["cliente"]))
    return {
        "mes": mes,
        "a_receber_mes": {"pendente": sum(p["valor"] for p in do_mes if not p["pago"]),
                          "pago": sum(p["valor"] for p in do_mes if p["pago"]),
                          "previsto": sum(p["valor"] for p in do_mes),
                          "qtd_pendente": sum(1 for p in do_mes if not p["pago"])},
        "recebido_mes": sum(p["valor"] for p in todas if p["pago"] and (p["pago_em"] or "")[:7] == mes),
        "recebido_ano": sum(p["valor"] for p in todas if p["pago"] and (p["pago_em"] or "")[:4] == ano),
        "total_a_receber": sum(p["valor"] for p in todas if not p["pago"]),
        "em_atraso": {"valor": sum(g["valor"] for g in inad.values()), "clientes": len(inad),
                      "parcelas": sum(g["parcelas"] for g in inad.values())},
        "inadimplentes": sorted(inad.values(), key=lambda g: (-g["dias_atraso"], -g["valor"])),
        "proximas": proximas[:8],
    }


def lembretes(lancamentos: list[dict], de: str, ate: str) -> list[dict]:
    """Lembretes do calendário: 1 dia depois de cada vencimento, para conferir se a parcela foi paga."""
    saida = []
    for l in lancamentos:
        for p in l["parcelas"]:
            dia = (date.fromisoformat(p["vencimento"]) + timedelta(days=LEMBRETE_DIAS_DEPOIS)).isoformat()
            if de <= dia <= ate:
                saida.append({**p, "data": dia, "cliente": l["cliente"], "numero_fmt": l["numero_fmt"],
                              "qtd_parcelas": l["qtd_parcelas"]})
    return sorted(saida, key=lambda p: (p["data"], p["cliente"]))
