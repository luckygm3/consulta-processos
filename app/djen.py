"""Cliente do DJEN (comunicaapi.pje.jus.br) — descobre processos pelas publicações da advogada.

Comportamento real observado (set/2026):
- GET /api/v1/comunicacao aceita numeroOab+ufOab ou nomeAdvogado, dataDisponibilizacaoInicio/Fim
  (YYYY-MM-DD), pagina, itensPorPagina. Resposta: {"status","message","count","items":[...]}.
- Janela de 180 dias funciona numa consulta só; itens vêm do mais recente para o mais antigo.
- Headers X-RateLimit-Limit (20) e X-RateLimit-Remaining; sem header de reset.
- HTTP 500 "O sistema está muito ocupado" é frequente e transitório: resolve com retry.
"""
import logging
import time
from datetime import date
from typing import Iterator

import httpx

log = logging.getLogger("djen")

BASE_URL = "https://comunicaapi.pje.jus.br/api/v1"
ESPERAS = [3, 6, 12, 24, 45, 60]  # backoff (segundos) entre tentativas
INTERVALO_MINIMO = 1.0            # pausa mínima entre requisições, por educação com a API
MAX_PAGINAS = 200                 # trava de segurança contra laço infinito


class DjenErro(Exception):
    pass


class DjenClient:
    def __init__(self, timeout: float = 90.0):
        self.http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "processos-beatriz/1.0 (uso pessoal local)"},
        )
        self._ultima_req = 0.0
        self._pausa_extra = 0.0

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- infraestrutura -------------------------------------------------

    def _aguardar_vez(self):
        espera = max(INTERVALO_MINIMO - (time.monotonic() - self._ultima_req), self._pausa_extra)
        if espera > 0:
            time.sleep(espera)
        self._pausa_extra = 0.0
        self._ultima_req = time.monotonic()

    def _ler_ratelimit(self, headers: httpx.Headers):
        try:
            restante = int(headers.get("x-ratelimit-remaining", "-1"))
        except ValueError:
            return
        if 0 <= restante <= 2:
            log.info("Rate limit quase no fim (restam %s); pausando 20s", restante)
            self._pausa_extra = 20.0
        elif 0 <= restante <= 5:
            self._pausa_extra = 5.0

    def _get(self, caminho: str, params: dict | None = None):
        ultimo_erro = ""
        for tentativa, espera in enumerate(ESPERAS, start=1):
            self._aguardar_vez()
            try:
                r = self.http.get(caminho, params=params)
            except httpx.HTTPError as e:
                ultimo_erro = f"falha de rede: {e.__class__.__name__}"
                log.warning("DJEN %s (tentativa %d): %s; nova tentativa em %ss", caminho, tentativa, ultimo_erro, espera)
                time.sleep(espera)
                continue

            self._ler_ratelimit(r.headers)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    ultimo_erro = "resposta não é JSON"
            elif r.status_code == 429:
                retry_after = r.headers.get("retry-after", "")
                espera = int(retry_after) if retry_after.isdigit() else 60
                ultimo_erro = "limite de requisições (429)"
            elif r.status_code >= 500:
                ultimo_erro = f"HTTP {r.status_code}: {_mensagem(r)}"
            else:
                raise DjenErro(f"HTTP {r.status_code}: {_mensagem(r)}")
            log.warning("DJEN %s (tentativa %d): %s; nova tentativa em %ss", caminho, tentativa, ultimo_erro, espera)
            time.sleep(espera)
        raise DjenErro(f"DJEN indisponível após {len(ESPERAS)} tentativas ({ultimo_erro})")

    # --- API ------------------------------------------------------------

    def comunicacoes(
        self,
        data_inicio: date,
        data_fim: date,
        numero_oab: str = "",
        uf_oab: str = "",
        nome_advogado: str = "",
        itens_por_pagina: int = 100,
    ) -> Iterator[dict]:
        """Itera todas as comunicações da janela, paginando até esgotar o 'count'."""
        params = {
            "dataDisponibilizacaoInicio": data_inicio.isoformat(),
            "dataDisponibilizacaoFim": data_fim.isoformat(),
            "itensPorPagina": itens_por_pagina,
        }
        if numero_oab:
            params.update(numeroOab=numero_oab, ufOab=uf_oab)
        elif nome_advogado:
            params["nomeAdvogado"] = nome_advogado
        else:
            raise DjenErro("Informe OAB/UF ou nome da advogada")

        recebidos = 0
        for pagina in range(1, MAX_PAGINAS + 1):
            dados = self._get("/comunicacao", {**params, "pagina": pagina})
            if not isinstance(dados, dict) or dados.get("status") not in (None, "success"):
                raise DjenErro(f"Resposta inesperada: {str(dados)[:200]}")
            itens = dados.get("items") or []
            total = int(dados.get("count") or 0)
            yield from itens
            recebidos += len(itens)
            if not itens or recebidos >= total or len(itens) < itens_por_pagina:
                return

    def tribunais(self) -> list[dict]:
        """Lista de tribunais que publicam no DJEN, agrupada por UF."""
        return self._get("/comunicacao/tribunal")


def _mensagem(r: httpx.Response) -> str:
    try:
        return str(r.json().get("message", ""))[:200]
    except Exception:
        return r.text[:200]
