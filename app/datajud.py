"""Cliente da API Pública do DataJud (CNJ) — enriquece processos com classe, assuntos, órgão e movimentos.

Comportamento real observado (set/2026):
- POST /api_publica_{alias}/_search com "Authorization: APIKey <chave>"; 401 se a chave for inválida.
- Processo inexistente ou sigiloso: 200 com hits vazio.
- Um processo pode ter vários hits (um por grau: G1, G2, JE...), _id = "TRT9_G1_<numero>".
- 429 "es_rejected_execution_exception" = fila do servidor cheia (sobrecarga); resolve com retry.
- ATENÇÃO: sob carga, também responde 200 com parte dos shards falhando (_shards.failed > 0) e hits
  faltando. Por isso "sem dados" só é concluído com uma resposta completa; parciais são repetidas.
- Consultas levam de 5 a 40s. Por isso buscamos em lote ("terms") por tribunal.
"""
import logging
import time

import httpx

from . import cnj

log = logging.getLogger("datajud")

BASE_URL = "https://api-publica.datajud.cnj.jus.br"
ESPERAS = [5, 10, 20, 40, 60]
TAMANHO_LOTE = 20


class DatajudErro(Exception):
    pass


class DatajudChaveInvalida(DatajudErro):
    pass


class DatajudClient:
    def __init__(self, api_key: str, timeout: float = 120.0):
        if not api_key:
            raise DatajudChaveInvalida("Chave do DataJud não configurada")
        self.http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"Authorization": f"APIKey {api_key}", "Content-Type": "application/json",
                     "User-Agent": "processos-beatriz/1.0 (uso pessoal local)"},
        )

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _search(self, alias: str, corpo: dict) -> tuple[list[dict], bool]:
        """Retorna (hits, completo). completo=False: nenhuma tentativa veio com todos os shards."""
        ultimo_erro = ""
        acumulado: dict[str, dict] = {}
        teve_parcial = False
        for tentativa, espera in enumerate(ESPERAS, start=1):
            try:
                r = self.http.post(f"/api_publica_{alias}/_search", json=corpo)
            except httpx.HTTPError as e:
                ultimo_erro = f"falha de rede: {e.__class__.__name__}"
            else:
                if r.status_code == 200:
                    try:
                        dados = r.json()
                        hits = dados["hits"]["hits"]
                    except (ValueError, KeyError):
                        ultimo_erro = "resposta inesperada"
                    else:
                        for h in hits:  # junta o que cada tentativa parcial encontrou
                            acumulado[h.get("_id") or str(len(acumulado))] = h
                        shards = dados.get("_shards") or {}
                        if not shards.get("failed") and not dados.get("timed_out"):
                            return list(acumulado.values()), True
                        teve_parcial = True
                        ultimo_erro = f"resposta parcial ({shards.get('failed')} de {shards.get('total')} shards falharam)"
                elif r.status_code in (401, 403):
                    raise DatajudChaveInvalida("Chave do DataJud recusada (401). Pegue a chave atual na wiki do CNJ.")
                elif r.status_code == 404:
                    raise DatajudErro(f"Tribunal '{alias}' não existe no DataJud")
                elif r.status_code == 429 or r.status_code >= 500:
                    ultimo_erro = f"HTTP {r.status_code} (servidor do DataJud sobrecarregado)"
                else:
                    raise DatajudErro(f"HTTP {r.status_code}: {r.text[:200]}")
            log.warning("DataJud %s (tentativa %d): %s; nova tentativa em %ss", alias, tentativa, ultimo_erro, espera)
            time.sleep(espera)
        if teve_parcial:
            return list(acumulado.values()), False
        raise DatajudErro(f"DataJud indisponível após {len(ESPERAS)} tentativas ({ultimo_erro})")

    def buscar(self, numero: str) -> tuple[list[dict], bool]:
        """Busca um processo pelo número (match). Retorna (hits, completo); hits vazio e completo = sem dados públicos."""
        numero = cnj.so_digitos(numero)
        _, alias = cnj.tribunal(numero)
        if not alias:
            raise DatajudErro("Tribunal não publicado no DataJud")
        return self._search(alias, {"query": {"match": {"numeroProcesso": numero}}, "size": 20})

    def buscar_lote(self, alias: str, numeros: list[str]) -> tuple[dict[str, list[dict]], bool]:
        """Busca vários processos do mesmo tribunal numa consulta. Retorna ({numero: [hits]}, completo)."""
        numeros = [cnj.so_digitos(n) for n in numeros]
        hits, completo = self._search(alias, {"query": {"terms": {"numeroProcesso": numeros}}, "size": len(numeros) * 8})
        resultado: dict[str, list[dict]] = {n: [] for n in numeros}
        for h in hits:
            n = cnj.so_digitos(h.get("_source", {}).get("numeroProcesso", ""))
            if n in resultado:
                resultado[n].append(h)
        return resultado, completo
