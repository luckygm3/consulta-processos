"""Limite de tempo dos passos da sincronização (na Vercel cada requisição tem duração máxima)."""
import time


class TempoEsgotado(Exception):
    """O passo chegou ao limite de tempo: o que faltou é retomado no próximo passo (não é erro)."""


def restante(prazo: float | None) -> float | None:
    """Segundos até o prazo (time.monotonic()); None = sem limite."""
    return None if prazo is None else prazo - time.monotonic()


def cabe(prazo: float | None, segundos: float) -> bool:
    r = restante(prazo)
    return r is None or r > segundos


def timeout_ate(prazo: float | None, padrao: float, folga: float = 2.0) -> float:
    """Timeout de uma chamada de rede que não passa do prazo; TempoEsgotado se não sobra tempo útil."""
    r = restante(prazo)
    if r is None:
        return padrao
    if r - folga < 3:
        raise TempoEsgotado("sem tempo para mais uma consulta neste passo")
    return min(padrao, r - folga)
