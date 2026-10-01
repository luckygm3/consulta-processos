"""Cálculo de prazos processuais, sem IA: calendário forense (feriados/suspensões/recesso) + regras do CPC.

Regras implementadas (todas determinísticas e mostradas na "memória de cálculo"):
- Contagem em dias úteis por padrão (CPC art. 219); "corridos" pode ser escolhido por tipo de ato ou por processo.
- Comunicação pelo DJEN (Lei 11.419/2006 art. 4º §3º; Res. CNJ 455/2022): considera-se publicada no 1º dia útil
  seguinte ao da disponibilização. Regra configurável: "djen" (padrão) ou "disponibilizacao" (publicação = o próprio dia).
- Exclui o dia do começo e inclui o do vencimento (CPC art. 224): a contagem começa no 1º dia útil após a publicação.
- Começo/vencimento em dia sem expediente ou com expediente reduzido são prorrogados ao próximo dia útil (art. 224 §1º).
- Recesso forense (20/12 a 20/01, CPC art. 220) suspende a contagem. A data de publicação não é empurrada pelo
  recesso (o DJEN publica nesse período); só a contagem fica parada e recomeça em 21/01.
- Dias corridos: conta todos os dias (exceto o recesso) e, se o último cair em dia não útil, prorroga.
"""
from datetime import date, timedelta

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# tipos de registro do calendário
FERIADO, SUSPENSAO, RECESSO, REDUZIDO = "feriado", "suspensao", "recesso", "expediente_reduzido"
TIPOS = {FERIADO: "Feriado", SUSPENSAO: "Suspensão de expediente", RECESSO: "Recesso forense",
         REDUZIDO: "Expediente reduzido (só prorroga começo/vencimento)"}

TRIBUNAIS_FEDERAIS = "TRF1,TRF2,TRF3,TRF4,TRF5,TRF6"
TRIBUNAIS_PR = "TJPR,TRT9"


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriados_padrao(ano: int) -> list[dict]:
    """Calendário pré-preenchido para um ano. É um ponto de partida de bom senso: precisa ser conferido com os
    atos de cada tribunal (que todo ano publicam suas suspensões e às vezes mudam datas, como o 28/10)."""
    p = pascoa(ano)

    def item(dia: date, descricao: str, tipo: str = FERIADO, tribunais: str = "", fim: date | None = None):
        return {"inicio": dia.isoformat(), "fim": fim.isoformat() if fim else None, "descricao": descricao,
                "tipo": tipo, "tribunais": tribunais, "comarca": "", "recorrente": 0, "origem": "padrao"}

    return [
        item(date(ano, 1, 1), "Confraternização Universal"),
        item(p - timedelta(days=48), "Carnaval (segunda-feira)", SUSPENSAO),
        item(p - timedelta(days=47), "Carnaval (terça-feira)", SUSPENSAO),
        item(p - timedelta(days=46), "Quarta-feira de Cinzas (expediente a partir das 12h/14h)", REDUZIDO),
        item(p - timedelta(days=4), "Quarta-feira Santa (Justiça Federal, Lei 5.010/66)", FERIADO, TRIBUNAIS_FEDERAIS),
        item(p - timedelta(days=3), "Quinta-feira Santa", SUSPENSAO),
        item(p - timedelta(days=2), "Sexta-feira Santa (Paixão de Cristo)"),
        item(date(ano, 4, 21), "Tiradentes"),
        item(date(ano, 5, 1), "Dia do Trabalho"),
        item(p + timedelta(days=60), "Corpus Christi", SUSPENSAO),
        item(date(ano, 8, 11), "Dia do Advogado / criação dos cursos jurídicos (Justiça Federal)", FERIADO,
             TRIBUNAIS_FEDERAIS),
        item(date(ano, 9, 7), "Independência do Brasil"),
        item(date(ano, 10, 12), "Nossa Senhora Aparecida"),
        item(date(ano, 10, 28), "Dia do Servidor Público (suspensão usual; conferir se o tribunal mudou a data)",
             SUSPENSAO),
        item(date(ano, 11, 1), "Todos os Santos (Justiça Federal)", FERIADO, TRIBUNAIS_FEDERAIS),
        item(date(ano, 11, 2), "Finados"),
        item(date(ano, 11, 15), "Proclamação da República"),
        item(date(ano, 11, 20), "Dia Nacional de Zumbi e da Consciência Negra (Lei 14.759/2023)"),
        item(date(ano, 12, 8), "Dia da Justiça (Lei 1.408/51)", SUSPENSAO),
        item(date(ano, 12, 19), "Emancipação Política do Paraná", FERIADO, TRIBUNAIS_PR),
        item(date(ano, 12, 20), "Recesso forense (CPC art. 220)", RECESSO, fim=date(ano + 1, 1, 20)),
        item(date(ano, 12, 25), "Natal"),
    ]


def _norm(s: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


class Calendario:
    """Responde se um dia conta no prazo, a partir dos registros da tabela de feriados (editável)."""

    def __init__(self, registros: list[dict], tribunal: str = "", orgao: str = "", todos: bool = False):
        """todos=True ignora tribunal/comarca (só para exibir o calendário completo)."""
        self.tribunal = (tribunal or "").upper()
        self.orgao = _norm(orgao)
        self._fixos: dict[date, list[dict]] = {}
        self._anuais: list[dict] = []
        for r in registros:
            if not r.get("ativo", 1) or not (todos or self._vale_aqui(r)):
                continue
            if r.get("recorrente"):
                self._anuais.append(r)
                continue
            ini = date.fromisoformat(r["inicio"])
            fim = date.fromisoformat(r["fim"]) if r.get("fim") else ini
            d = ini
            while d <= fim and (d - ini).days < 400:
                self._fixos.setdefault(d, []).append(r)
                d += timedelta(days=1)

    def _vale_aqui(self, r: dict) -> bool:
        tribs = [t.strip().upper() for t in (r.get("tribunais") or "").split(",") if t.strip()]
        if tribs and self.tribunal not in tribs:
            return False
        comarca = _norm(r.get("comarca") or "")
        return not comarca or comarca in self.orgao  # comarca: casa com o nome do órgão/vara do processo

    def registros(self, d: date) -> list[dict]:
        saida = list(self._fixos.get(d, []))
        md = d.strftime("%m-%d")
        for r in self._anuais:  # recorrentes guardam MM-DD (podem atravessar a virada do ano)
            ini, fim = r["inicio"][-5:], (r.get("fim") or r["inicio"])[-5:]
            if (ini <= md <= fim) if ini <= fim else (md >= ini or md <= fim):
                saida.append(r)
        return saida

    def motivo(self, d: date, considerar_recesso: bool = True) -> str | None:
        """Por que o dia não é útil (None = é útil). Expediente reduzido não tira o dia da contagem."""
        if d.weekday() >= 5:
            return "fim de semana"
        for r in self.registros(d):
            if r["tipo"] == RECESSO and not considerar_recesso:
                continue
            if r["tipo"] != REDUZIDO:
                return r["descricao"]
        return None

    def reduzido(self, d: date) -> str | None:
        return next((r["descricao"] for r in self.registros(d) if r["tipo"] == REDUZIDO), None)

    def util(self, d: date, considerar_recesso: bool = True) -> bool:
        return self.motivo(d, considerar_recesso) is None

    def proximo_util(self, d: date, considerar_recesso: bool = True, aceita_reduzido: bool = True) -> date:
        """Primeiro dia útil estritamente depois de d."""
        d += timedelta(days=1)
        while not self.util(d, considerar_recesso) or (not aceita_reduzido and self.reduzido(d)):
            d += timedelta(days=1)
        return d

    def uteis_entre(self, a: date, b: date) -> int:
        """Quantos dias úteis em (a, b]. Negativo se b < a."""
        if b < a:
            return -self.uteis_entre(b, a)
        n, d = 0, a
        while d < b:
            d += timedelta(days=1)
            if self.util(d):
                n += 1
        return n

    def voltar_uteis(self, d: date, n: int) -> date:
        while n > 0:
            d -= timedelta(days=1)
            if self.util(d):
                n -= 1
        return d


def fmt(d: date) -> str:
    return f"{d:%d/%m/%Y} ({DIAS_SEMANA[d.weekday()]})"


def calcular(disponibilizacao: date, dias: int, cal: Calendario, contagem: str = "uteis",
             regra_publicacao: str = "djen", dias_internos: int = 2) -> dict:
    """Prazo fatal a partir da data de disponibilização. Devolve datas ISO e a memória de cálculo."""
    dias = max(1, int(dias))
    passos, pulados = [], []

    def anotar_pulos(de: date, ate: date):
        d = de + timedelta(days=1)
        while d < ate:
            m = cal.motivo(d)
            if m and m != "fim de semana":
                pulados.append({"data": d.isoformat(), "motivo": m})
            d += timedelta(days=1)

    passos.append(f"Disponibilização no DJEN: {fmt(disponibilizacao)}")
    if regra_publicacao == "disponibilizacao":
        publicacao = disponibilizacao
        passos.append("Publicação: considerada no próprio dia da disponibilização (regra configurada)")
    else:
        publicacao = cal.proximo_util(disponibilizacao, considerar_recesso=False)
        anotar_pulos(disponibilizacao, publicacao)
        passos.append(f"Publicação: {fmt(publicacao)} — 1º dia útil seguinte à disponibilização")

    # Começo: 1º dia útil depois da publicação (art. 224 §3º); não pode ser dia de expediente reduzido (§1º)
    inicio = cal.proximo_util(publicacao, aceita_reduzido=False)
    anotar_pulos(publicacao, inicio)
    passos.append(f"Início da contagem: {fmt(inicio)} — exclui o dia da publicação (CPC art. 224)")

    if contagem == "corridos":
        d, n = inicio, 1
        while n < dias:
            d += timedelta(days=1)
            if cal.motivo(d) and any(r["tipo"] == RECESSO for r in cal.registros(d)):
                pulados.append({"data": d.isoformat(), "motivo": "recesso forense (suspende)"})
                continue
            n += 1
        passos.append(f"{dias} dias corridos: último dia {fmt(d)}")
        vencimento = d
        if not cal.util(vencimento):
            anterior = vencimento
            vencimento = cal.proximo_util(vencimento - timedelta(days=1))
            passos.append(f"{fmt(anterior)} não é dia útil ({cal.motivo(anterior)}): prorrogado")
    else:
        d, n = inicio, 1
        while n < dias:
            d += timedelta(days=1)
            m = cal.motivo(d)
            if m:
                if m != "fim de semana":
                    pulados.append({"data": d.isoformat(), "motivo": m})
                continue
            n += 1
        vencimento = d
        passos.append(f"{dias} dias úteis contados a partir do início: {fmt(vencimento)}")

    while cal.reduzido(vencimento):
        motivo = cal.reduzido(vencimento)
        vencimento = cal.proximo_util(vencimento)
        passos.append(f"Vencimento em dia de {motivo}: prorrogado (CPC art. 224 §1º)")
    passos.append(f"Prazo fatal: {fmt(vencimento)}")

    # Recesso aparece como um único item na memória (são ~30 dias)
    resumo_pulos, recesso_visto = [], False
    for p in pulados:
        if "ecesso" in p["motivo"]:
            if recesso_visto:
                continue
            recesso_visto = True
            p = {"data": p["data"], "motivo": "Recesso forense 20/12 a 20/01 (contagem suspensa)"}
        resumo_pulos.append(p)

    interno = cal.voltar_uteis(vencimento, dias_internos) if dias_internos > 0 else vencimento
    return {
        "disponibilizacao": disponibilizacao.isoformat(), "publicacao": publicacao.isoformat(),
        "inicio": inicio.isoformat(), "dias": dias, "contagem": contagem, "regra_publicacao": regra_publicacao,
        "vencimento": vencimento.isoformat(), "interno": interno.isoformat(), "dias_internos": dias_internos,
        "pulados": resumo_pulos, "passos": passos,
    }


def urgencia(vencimento: str | None, cal: Calendario, hoje: date | None = None) -> tuple[str, int | None]:
    """Faixa de urgência e dias úteis restantes: vencido | hoje | amanha | ate5 | folgado | sem_data."""
    if not vencimento:
        return "sem_data", None
    hoje = hoje or date.today()
    v = date.fromisoformat(vencimento[:10])
    if v < hoje:
        return "vencido", -cal.uteis_entre(v, hoje)
    if v == hoje:
        return "hoje", 0
    restantes = cal.uteis_entre(hoje, v)
    if v <= cal.proximo_util(hoje):  # amanhã, ou o próximo dia útil (sexta -> segunda)
        return "amanha", restantes
    return ("ate5" if restantes <= 5 else "folgado"), restantes
