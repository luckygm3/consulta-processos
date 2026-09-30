"""Limpeza dos textos das publicações do DJEN (vêm como HTML, texto com <br> ou texto puro)."""
import html
import re

_TAGS_BLOCO = r"br|p|div|section|article|header|footer|tr|li|ul|ol|table|h[1-6]|blockquote|center"
_TAGS_CONHECIDAS = (_TAGS_BLOCO + r"|html|head|body|meta|style|script|span|b|i|u|em|strong|a|td|th|tbody|"
                    r"thead|font|small|sup|sub|img|hr|link|title|col|colgroup|caption|label|o:p")

_RE_DOC_HTML = re.compile(r"<(html|body|p|section|table|div)\b", re.I)
_RE_REMOVER = re.compile(r"<\?xml.*?\?>|<!DOCTYPE[^>]*>|<!--.*?-->|<(head|style|script)\b.*?</\1\s*>", re.I | re.S)
_RE_BLOCO = re.compile(rf"<\s*(/\s*)?({_TAGS_BLOCO})\b[^>]*>", re.I)
_RE_CELULA = re.compile(r"<\s*/\s*t[dh]\s*>", re.I)
_RE_TAG = re.compile(rf"<\s*/?\s*({_TAGS_CONHECIDAS})\b[^>]*>", re.I)


def limpar(texto: str) -> str:
    """Devolve texto legível com quebras de linha reais."""
    if not texto:
        return ""
    t = _RE_REMOVER.sub(" ", texto)
    if _RE_DOC_HTML.search(t):
        t = re.sub(r"\s+", " ", t)  # em HTML, espaços e quebras do código-fonte não contam
    t = _RE_CELULA.sub(" ", t)
    t = _RE_BLOCO.sub("\n", t)
    t = _RE_TAG.sub("", t)
    t = html.unescape(t).replace(" ", " ").replace("\r", "")
    t = re.sub(r"[ \t]{2,}", "\n", t)  # no DJEN, dois ou mais espaços seguidos marcam quebra de linha
    linhas = [ln.strip() for ln in t.split("\n")]
    t = "\n".join(linhas)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


_RE_ROTULO = re.compile(r"^(poder judici|justi[cç]a |tribunal |processo|autos|reclamante|reclamad|autor|r[ée]u|"
                        r"requerente|requerid|exequente|executad|advogad|destinat|intimado|parte|assunto|classe|"
                        r"[óo]rg[ãa]o|juiz|relator|documento|data|n[ºo°]|atord|atsum|atalc)", re.I)


def resumo(texto: str, limite: int = 220) -> str:
    """Trecho útil da publicação para a tabela: pula cabeçalhos em caixa alta e rótulos de partes."""
    linhas = [ln for ln in (texto or "").split("\n") if ln.strip()]
    inicio = 0
    for i, ln in enumerate(linhas):
        letras = [c for c in ln if c.isalpha()]
        maiusculas = sum(c.isupper() for c in letras) / len(letras) if letras else 1
        if len(ln) >= 25 and maiusculas < 0.6 and not _RE_ROTULO.match(ln):
            inicio = i
            break
    trecho = " ".join(linhas[inicio:])
    return trecho[:limite].rstrip() + ("…" if len(trecho) > limite else "")
