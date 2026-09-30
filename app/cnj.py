"""Número CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO): validação, formatação e mapeamento para o alias do DataJud."""
import re

# Código TR -> UF (Resolução CNJ 65/2008), usado na Justiça Estadual (J=8) e Eleitoral (J=6)
UF_POR_TR = {
    1: "AC", 2: "AL", 3: "AP", 4: "AM", 5: "BA", 6: "CE", 7: "DF", 8: "ES", 9: "GO",
    10: "MA", 11: "MT", 12: "MS", 13: "MG", 14: "PA", 15: "PB", 16: "PR", 17: "PE",
    18: "PI", 19: "RJ", 20: "RN", 21: "RS", 22: "RO", 23: "RR", 24: "SC", 25: "SE",
    26: "SP", 27: "TO",
}

# Justiça Militar Estadual (J=9): só MG, RS e SP têm tribunal próprio
TJM_POR_TR = {13: "tjmmg", 21: "tjmrs", 26: "tjmsp"}

_RE_CNJ = re.compile(r"(?<!\d)(\d{7})[-.\s]?(\d{2})[.\s]?(\d{4})[.\s]?(\d)[.\s]?(\d{2})[.\s]?(\d{4})(?!\d)")


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def formatar(numero: str) -> str:
    n = so_digitos(numero)
    if len(n) != 20:
        return numero or ""
    return f"{n[0:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:20]}"


def digito_valido(numero: str) -> bool:
    """Confere o dígito verificador (módulo 97, ISO 7064)."""
    n = so_digitos(numero)
    if len(n) != 20:
        return False
    base = n[0:7] + n[9:20]
    return 98 - (int(base + "00") % 97) == int(n[7:9])


def extrair_numeros(texto: str) -> list[str]:
    """Acha números CNJ (com ou sem máscara) num texto livre, CSV ou TXT. Mantém a ordem, sem repetir."""
    vistos, saida = set(), []
    for m in _RE_CNJ.finditer(texto or ""):
        n = "".join(m.groups())
        if n not in vistos:
            vistos.add(n)
            saida.append(n)
    return saida


def tribunal(numero: str) -> tuple[str, str | None]:
    """Retorna (sigla do tribunal, alias do DataJud ou None se o DataJud não publica)."""
    n = so_digitos(numero)
    if len(n) != 20:
        return ("?", None)
    j, tr = n[13], int(n[14:16])
    if j == "1":
        return ("STF", None)
    if j == "2":
        return ("CNJ", None)
    if j == "3":
        return ("STJ", "stj")
    if j == "4":
        if 1 <= tr <= 6:
            return (f"TRF{tr}", f"trf{tr}")
        return ("CJF", None)
    if j == "5":
        if tr == 0:
            return ("TST", "tst")
        if 1 <= tr <= 24:
            return (f"TRT{tr}", f"trt{tr}")
        return ("CSJT", None)
    if j == "6":
        if tr == 0:
            return ("TSE", "tse")
        uf = UF_POR_TR.get(tr)
        if uf:
            return (f"TRE-{uf}", "tre-dft" if uf == "DF" else f"tre-{uf.lower()}")
        return ("TRE-?", None)
    if j == "7":
        # Justiça Militar da União: STM e auditorias ficam no índice do STM
        return ("STM" if tr == 0 else "JMU", "stm")
    if j == "8":
        uf = UF_POR_TR.get(tr)
        if uf == "DF":
            return ("TJDFT", "tjdft")
        if uf:
            return (f"TJ{uf}", f"tj{uf.lower()}")
        return ("TJ?", None)
    if j == "9":
        alias = TJM_POR_TR.get(tr)
        return ((alias.upper(), alias) if alias else ("TJM?", None))
    return ("?", None)
