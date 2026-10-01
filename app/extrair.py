"""Detecção de prazos no texto das publicações, só com regras (regex + palavras-chave), sem IA.

Para cada publicação devolve no máximo um prazo sugerido (o mais provável), o trecho original que o gerou, o nome
do ato quando reconhecido e um nível de confiança. Na dúvida, marca "conferir manualmente".
"""
import re
import unicodedata

# (nome, palavras-chave separadas por ';', dias padrão, contagem, justiça). A ordem importa: o primeiro que casar
# vence, então os mais específicos vêm antes (ex.: "contrarrazões" antes de "apelação"). Editável na tela.
TIPOS_PADRAO = [
    ("Embargos de declaração", "embargos de declaracao;embargos declaratorios;aclaratorios", 5, "uteis", ""),
    ("Contrarrazões", "contrarrazoes;contrarrazoar;contraminuta", 8, "uteis", "trabalho"),
    ("Contrarrazões", "contrarrazoes;contrarrazoar;contraminuta", 15, "uteis", ""),
    ("Agravo de instrumento", "agravo de instrumento", 15, "uteis", ""),
    ("Agravo de petição", "agravo de peticao", 8, "uteis", "trabalho"),
    ("Agravo interno", "agravo interno;agravo regimental", 15, "uteis", ""),
    ("Recurso ordinário", "recurso ordinario", 8, "uteis", "trabalho"),
    ("Recurso de revista", "recurso de revista", 8, "uteis", "trabalho"),
    ("Recurso inominado", "recurso inominado", 10, "uteis", ""),
    ("Apelação", "apelacao;apelar", 15, "uteis", ""),
    ("Réplica", "replica;impugnacao a contestacao;sobre a contestacao;impugnar a contestacao", 15, "uteis", ""),
    ("Contestação", "contestar;contestacao;apresentar defesa;oferecer defesa;apresente defesa", 15, "uteis", ""),
    ("Emenda à inicial", "emendar a inicial;emende a inicial;emenda a inicial;emenda da inicial;emendar a peticao inicial",
     15, "uteis", ""),
    ("Embargos à execução", "embargos a execucao;embargos do devedor", 15, "uteis", ""),
    ("Impugnação ao cumprimento de sentença", "impugnacao ao cumprimento;impugnar o cumprimento", 15, "uteis", ""),
    ("Pagamento", "pagar;efetuar o pagamento;pagamento voluntario;art. 523;artigo 523;recolher as custas;"
     "recolhimento das custas", 15, "uteis", ""),
    ("Especificação de provas", "especificar provas;especifiquem as provas;especificacao de provas;"
     "provas que pretendem produzir", 5, "uteis", ""),
    ("Quesitos / assistente técnico", "quesitos;assistente tecnico", 15, "uteis", ""),
    ("Recurso ordinário (sentença)", "julgo procedente;julgo improcedente;julgo parcialmente procedente;"
     "julgo extinto;julgo extinta;extingo o processo", 8, "uteis", "trabalho"),
    ("Recurso contra sentença (apelação)", "julgo procedente;julgo improcedente;julgo parcialmente procedente;"
     "julgo extinto;julgo extinta;extingo o processo", 15, "uteis", ""),
    ("Manifestação", "manifeste-se;manifestem-se;manifestar-se;manifestacao;dar vista;vista as partes;"
     "vista a parte;ciencia as partes;digam as partes;diga a parte", 5, "uteis", ""),
    ("Cumprimento de determinação", "cumprir;cumpra;juntar;junte;juntada de;apresentar;apresente;comprovar;"
     "comprove;regularizar;regularize;informar;informe;esclarecer;esclareca;indicar;indique", 5, "uteis", ""),
    ("Ato da parte", "intime-se para;intimem-se para;intime-se a parte;intimem-se as partes para;fica intimad;"
     "ficam intimad;intimacao para", 5, "uteis", ""),
]

# Verbos/expressões de ato a cargo da parte: aumentam a confiança de um número de dias próximo
_ACOES = re.compile(
    r"intim|manifest|contest|recorr|recurso|emend|pag|cumpr|junt|apresent|comprov|regulariz|especific|"
    r"impugn|contrarraz|replica|embarg|apel|agrav|recolh|deposit|indic|inform|esclarec|diga|digam|vista|"
    r"querendo|sob pena|prazo")
# Contextos em que "N dias" não é prazo da parte
_NAO_PRAZO_ANTES = re.compile(r"\b(ha|faz|apos|desde|ultimos?|cerca de|aproximadamente|por mais|suspend\w*|"
                              r"sobrest\w*|aguarde-se|aguardem-se|arquiv\w*|pena de|condeno a|pena|"
                              r"antecedencia(\s+minima)?)\s*(o|a|os|as|de|por|pelo prazo de|pelo periodo de|\s)*$")
_NAO_PRAZO_DEPOIS = re.compile(r"^\s*(-|de\s+)?(multa|reclusao|detencao|prisao|atraso|ferias|internacao|afastamento|"
                               r"trabalho|servico|salario|aviso|antes|de antecedencia|apos)")
# Sem número de dias, a palavra-chave só vale se o texto estiver mandando a parte agir (não basta citar o ato)
_ORDEM = re.compile(r"(intim\w*|querendo|para\s+que\b|prazo|sob pena|devera|deverao|"
                    r"\b(manifeste|manifestem|cumpra|junte|diga|digam|especifique|especifiquem|comprove|regularize|"
                    r"recolha|deposite|apresente|emende|indique|providencie|esclareca|informe)m?-se\b)[^.;]{0,90}$")
_DISPOSITIVO = re.compile(r"^(julgo|extingo|homologo)")  # dispositivo de sentença: prazo é o do recurso

_UNIDADES = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
    "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
    "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100,
}
_PALAVRA = "(?:" + "|".join(sorted(_UNIDADES, key=len, reverse=True)) + ")"
_EXTENSO = rf"{_PALAVRA}(?:\s+e\s+{_PALAVRA})*"
_NUM = rf"(?:\d{{1,3}}|{_EXTENSO})"
_RE_PRAZO = re.compile(
    rf"(?<![\w/.,-])(?P<n1>{_NUM})(?:\s*\(\s*(?P<n2>{_NUM})\s*\))?\s*(?P<unid>dias?|horas?)\b"
    rf"(?:\s+(?P<cont>uteis|corridos|util|corrido))?")
_RE_AUDIENCIA = re.compile(
    r"audiencia\b[^.;]{0,160}?\b(?:design\w*|redesign\w*|marcad\w*|agendad\w*|realizar\w*|para|dia|em)\s+"
    r"(?:o\s+|a\s+)?(?:dia\s+|data\s+de\s+)?(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<a>\d{4}|\d{2})\b"
    r"(?:[^.;\d]{0,25}?(?P<h>\d{1,2})\s*(?:h|:|horas)\s*(?P<min>\d{2})?)?")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento, preservando o tamanho (posição i no normalizado = posição i no original)."""
    saida = []
    for c in texto or "":
        b = unicodedata.normalize("NFKD", c)[:1].lower()
        saida.append(b if len(b) == 1 else c)
    return "".join(saida)


def numero(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    partes = [p for p in re.split(r"\s+e\s+|\s+", token) if p]
    if not partes or any(p not in _UNIDADES for p in partes):
        return None
    return sum(_UNIDADES[p] for p in partes)


def _trecho(original: str, ini: int, fim: int, folga: int = 220) -> str:
    """Frase(s) em volta da posição, do texto original, para ela conferir."""
    a = max(0, ini - folga)
    corte = max(original.rfind(". ", a, ini), original.rfind("\n", a, ini))
    a = corte + 1 if corte >= 0 else a
    b = min(len(original), fim + folga)
    fims = [i for i in (original.find(". ", fim, b), original.find("\n", fim, b)) if i >= 0]
    b = min(fims) + 1 if fims else b
    t = re.sub(r"\s+", " ", original[a:b]).strip()
    return ("…" if a > 0 and not corte >= 0 else "") + t + ("…" if b < len(original) and not fims else "")


def tipo_do_ato(norm: str, tipos: list[dict], justica_trabalho: bool, exigir_ordem: bool = True) -> dict | None:
    for t in tipos:
        if not t.get("ativo", 1):
            continue
        if t.get("justica") == "trabalho" and not justica_trabalho:
            continue
        for p in (t.get("palavras") or "").split(";"):
            p = normalizar(p.strip())
            if not p:
                continue
            for m in re.finditer(r"(?<!\w)" + re.escape(p), norm):
                ordem = _DISPOSITIVO.match(p) or re.search(r"(?<!\w)(manifest|intim)\w*-se$", p) or _ORDEM.search(norm[max(0, m.start() - 120):m.start()])
                if ordem or not exigir_ordem:
                    return {**t, "palavra": p, "pos": m.start(), "sentenca": bool(_DISPOSITIVO.match(p))}
    return None


def analisar(texto: str, tipos: list[dict], tribunal: str = "") -> dict | None:
    """Devolve a sugestão de prazo (ou None se a publicação não indica ato a praticar)."""
    original = texto or ""
    norm = normalizar(original)
    trabalho = (tribunal or "").upper().startswith(("TRT", "TST"))
    tipo = tipo_do_ato(norm, tipos, trabalho)

    candidatos = []
    for m in _RE_PRAZO.finditer(norm):
        n = numero(m.group("n1"))
        n2 = numero(m.group("n2")) if m.group("n2") else None
        if not n or n > 365:
            continue
        antes, depois = norm[max(0, m.start() - 160):m.start()], norm[m.end():m.end() + 40]
        if _NAO_PRAZO_DEPOIS.search(depois) or _NAO_PRAZO_ANTES.search(antes[-40:]):
            continue
        pontos = 1
        if re.search(r"prazo\s*(legal|comum|improrrogavel|sucessivo)?\s*(de|em)?\s*$", antes[-40:]) \
                or re.search(r"(no|em|dentro do|pelo)\s*$", antes[-12:]):
            pontos += 3
        if _ACOES.search(antes[-160:]) or _ACOES.search(depois):
            pontos += 2
        if n2 is not None and n2 != n:
            pontos -= 2  # "15 (dez) dias": número e extenso não batem
        candidatos.append((pontos, m, n, n2))

    aud = _audiencia(norm, original)
    if aud and not candidatos and tipo and not tipo["sentenca"]:
        tipo = None  # intimação de audiência: as instruções ("deverão comparecer...") não são um prazo à parte
    if not candidatos and not tipo and not aud:
        return None

    avisos, outros = [], []
    usar_tipo = tipo and tipo["sentenca"]  # sentença: os "N dias" do texto costumam ser obrigações da condenação
    if candidatos and usar_tipo:
        avisos.append("Sentença: sugerido o prazo do recurso. O texto também cita: "
                      + ", ".join(sorted({f"{c[2]} {c[1].group('unid')}" for c in candidatos})) + ".")
    if candidatos and not usar_tipo:
        candidatos.sort(key=lambda c: (-c[0], c[1].start()))
        pontos, m, n, n2 = candidatos[0]
        unid = m.group("unid")
        cont = m.group("cont") or ""
        contagem = "corridos" if cont.startswith("corrido") else ("uteis" if cont.startswith("ut") else None)
        dias, horas = n, None
        if unid.startswith("hora"):
            horas, dias, contagem = n, max(1, -(-n // 24)), "corridos"
            avisos.append(f"Prazo em horas ({n} h): convertido em {dias} dia(s) corrido(s). Conferir a contagem "
                          "hora a hora a partir da intimação.")
        if n2 is not None and n2 != n:
            avisos.append(f"O número ({m.group('n1')}) e o extenso ({m.group('n2')}) não batem no texto.")
        confianca = "alta" if pontos >= 6 else ("media" if pontos >= 3 else "baixa")
        trecho = _trecho(original, m.start(), m.end())
        fonte = f"“{original[m.start():m.end()]}” no texto"
        outros = sorted({c[2] for c in candidatos[1:] if c[2] != n})
        if outros:
            avisos.append("O texto cita outros prazos: " + ", ".join(f"{x} dias" for x in outros) + ".")
        # Nome do ato: palavra-chave perto do número (ou a ordem principal do texto)
        perto = tipo_do_ato(norm[max(0, m.start() - 250):m.end() + 120], tipos, trabalho, exigir_ordem=False)
        tipo = perto or tipo
    else:
        horas = None
        if tipo:
            dias, contagem = tipo.get("dias") or 5, tipo.get("contagem")
            confianca = "media" if usar_tipo else "baixa"
            pos = tipo["pos"]
            trecho = _trecho(original, pos, pos + len(tipo["palavra"]))
            fonte = f"padrão da tabela para “{tipo['nome']}”"
            if not usar_tipo:
                avisos.append(f"O texto não diz o número de dias: usado o padrão de {dias} dias para “{tipo['nome']}”"
                              + (" (CPC art. 218 §3º)" if dias == 5 else "") + ".")
        else:
            dias = contagem = confianca = trecho = fonte = None

    if re.search(r"prazo\s+comum", norm):
        avisos.append("Prazo comum às partes.")
    if re.search(r"em dobro|prazo dobrado|art\.?\s*(183|186|229)\b", norm):
        avisos.append("O texto menciona prazo em dobro: conferir se se aplica.")
    if dias is not None and confianca != "alta":
        avisos.insert(0, "Conferir manualmente: prazo não detectado com certeza.")

    return {
        "dias": dias, "horas": horas, "contagem": contagem, "confianca": confianca, "trecho": trecho,
        "fonte": fonte, "tipo": tipo["nome"] if tipo else None, "tipo_dias": tipo.get("dias") if tipo else None,
        "tipo_contagem": tipo.get("contagem") if tipo else None, "avisos": avisos, "audiencia": aud,
    }


def _audiencia(norm: str, original: str) -> dict | None:
    m = _RE_AUDIENCIA.search(norm)
    if not m:
        return None
    ano = int(m.group("a"))
    ano += 2000 if ano < 100 else 0
    try:
        from datetime import date
        dia = date(ano, int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None
    hora = f"{int(m.group('h')):02d}:{m.group('min') or '00'}" if m.group("h") and int(m.group("h")) < 24 else None
    return {"data": dia.isoformat(), "hora": hora, "trecho": _trecho(original, m.start(), m.end())}
