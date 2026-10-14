"""Configuração local: config.json (editável) + variável DATAJUD_API_KEY opcional (.env ou ambiente).

Advogadas ficam em "advogadas": [{"nome", "oab_numero", "oab_uf", "cor"}]. Um config.json antigo, com
oab_numero/oab_uf/nome_advogado soltos, continua funcionando: vira uma lista de uma advogada só.
Processos em cooperação: "advogados_cooperacao" ([{"nome", "oab_numero", "oab_uf"}]) e "ocultar_cooperacao".
"""
import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
CHECKLIST_PATH = BASE_DIR / "checklists_padrao.txt"
MODELOS_CHECKLIST = ("processo", "preventivo")
ENV_PATH = BASE_DIR / ".env"
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "processos.sqlite3"
LOG_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"

ADVOGADAS_PADRAO = [
    {"nome": "Beatriz Daffara", "oab_numero": "130678", "oab_uf": "PR", "cor": "#7c3aed"},
]
# Advogados de fora do escritório: processo em que algum deles consta é "em cooperação" (dá para ocultar)
COOPERACAO_PADRAO = [{"nome": "Jessica Delmoni", "oab_numero": "13043", "oab_uf": "AL"}]
CORES = ["#7c3aed", "#0f766e", "#c2410c", "#be185d", "#4d7c0f", "#0369a1"]
LEGADO = ("oab_numero", "oab_uf", "nome_advogado")  # formato antigo (uma advogada só)

DEFAULTS = {
    "advogadas": ADVOGADAS_PADRAO,
    "datajud_api_key": "",
    "backfill_dias": 180,
    "janela_dias": 30,
    "buscar_tambem_por_nome": False,
    # Prazos (ver app/prazos.py). regra_publicacao: "djen" = publicação no 1º dia útil após a disponibilização;
    # "disponibilizacao" = publicação no próprio dia. dias_internos: data interna = N dias úteis antes do fatal.
    "prazos_regra_publicacao": "djen",
    "prazos_dias_internos": 2,
    "prazos_contagem_padrao": "uteis",
    "ocultar_cooperacao": True,
    "advogados_cooperacao": COOPERACAO_PADRAO,
    "porta": 8000,
}


def _ler_env_arquivo() -> dict:
    """Lê um .env simples (CHAVE=valor), sem dependências extras."""
    valores = {}
    if ENV_PATH.exists():
        for linha in ENV_PATH.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                valores[k.strip()] = v.strip().strip('"').strip("'")
    return valores


def normalizar_chave(chave: str) -> str:
    """Aceita a chave colada com ou sem 'Authorization:' / 'APIKey'."""
    chave = (chave or "").strip()
    chave = re.sub(r"^authorization\s*:\s*", "", chave, flags=re.I)
    chave = re.sub(r"^apikey\s+", "", chave, flags=re.I)
    return chave.strip()


def _advogadas(cfg: dict) -> list[dict]:
    """Normaliza a lista de advogadas; converte o formato antigo (OAB única) se for o caso."""
    lista = cfg.get("advogadas")
    if not isinstance(lista, list) or not lista:
        if any(cfg.get(k) for k in LEGADO):
            lista = [{"nome": cfg.get("nome_advogado", ""), "oab_numero": cfg.get("oab_numero", ""),
                      "oab_uf": cfg.get("oab_uf", "")}]
        else:
            lista = ADVOGADAS_PADRAO
    saida = []
    for i, a in enumerate(x for x in lista if isinstance(x, dict)):
        oab, uf = str(a.get("oab_numero") or "").strip(), str(a.get("oab_uf") or "").strip().upper()
        nome = str(a.get("nome") or "").strip()
        if not (oab and uf) and not nome:
            continue
        saida.append({"nome": nome or f"OAB {oab}/{uf}", "oab_numero": oab, "oab_uf": uf,
                      "cor": str(a.get("cor") or CORES[i % len(CORES)])})
    return saida


def _cooperacao(cfg: dict) -> list[dict]:
    """Normaliza a lista de advogados de cooperação. Aceita a OAB junto com a UF ("13043AL", "13043/AL")."""
    lista = cfg.get("advogados_cooperacao")
    saida = []
    for a in (x for x in (lista if isinstance(lista, list) else []) if isinstance(x, dict)):
        oab, uf = str(a.get("oab_numero") or "").strip().upper(), str(a.get("oab_uf") or "").strip().upper()
        junto = re.fullmatch(r"(\d+)\s*/?\s*([A-Z]{2})", oab)
        if junto:
            oab, uf = junto.group(1), uf or junto.group(2)
        nome = re.sub(r"\s+", " ", str(a.get("nome") or "")).strip()
        if oab or nome:
            saida.append({"nome": nome, "oab_numero": oab, "oab_uf": uf[:2]})
    return saida


def carregar(com_env: bool = True) -> dict:
    """Lê o config.json. Com com_env=True, DATAJUD_API_KEY do ambiente/.env tem precedência."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            lido = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if "advogadas" not in lido:  # config antigo: não deixa o padrão mascarar a OAB que estava lá
                cfg.pop("advogadas")
            cfg.update(lido)
        except (OSError, json.JSONDecodeError) as e:
            logging.getLogger(__name__).error("config.json inválido (%s); usando padrões", e)
    else:
        salvar(cfg)
    cfg["advogadas"] = _advogadas(cfg)
    cfg["advogados_cooperacao"] = _cooperacao(cfg)
    cfg["ocultar_cooperacao"] = bool(cfg.get("ocultar_cooperacao"))
    # O código antigo lia estes campos; continuam valendo para a primeira advogada
    primeira = cfg["advogadas"][0] if cfg["advogadas"] else {"nome": "", "oab_numero": "", "oab_uf": ""}
    cfg.setdefault("nome_advogado", primeira["nome"])
    cfg.setdefault("oab_numero", primeira["oab_numero"])
    cfg.setdefault("oab_uf", primeira["oab_uf"])
    env_key = os.environ.get("DATAJUD_API_KEY") or _ler_env_arquivo().get("DATAJUD_API_KEY")
    if com_env and env_key:
        cfg["datajud_api_key"] = env_key
    cfg["datajud_api_key"] = normalizar_chave(cfg.get("datajud_api_key", ""))
    return cfg


def salvar(cfg: dict) -> None:
    dados = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    dados["advogadas"] = _advogadas(cfg)
    dados["advogados_cooperacao"] = _cooperacao(cfg)
    CONFIG_PATH.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def checklists_padrao() -> dict[str, list[str]]:
    """Checklists com que as demandas novas nascem, por modelo (checklists_padrao.txt: seções [processo] e
    [preventivo], um item por linha, # = comentário). Lido a cada uso: editar o arquivo vale na hora."""
    modelos = {m: [] for m in MODELOS_CHECKLIST}
    try:
        linhas = CHECKLIST_PATH.read_text(encoding="utf-8-sig").splitlines()  # -sig: aceita o BOM do Bloco de Notas
    except OSError:
        return modelos
    atual = "processo"  # itens antes de qualquer seção valem para processo
    for linha in (x.strip() for x in linhas):
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("[") and linha.endswith("]"):
            atual = linha[1:-1].strip().lower()
            modelos.setdefault(atual, [])
        else:
            modelos[atual].append(linha)
    return modelos


def checklist_padrao(modelo: str = "processo") -> list[str]:
    return checklists_padrao().get(modelo) or []


def configurar_log() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    raiz = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in raiz.handlers):
        return
    arq = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    arq.setFormatter(fmt)
    tela = logging.StreamHandler()
    tela.setFormatter(fmt)
    raiz.addHandler(arq)
    raiz.addHandler(tela)
    raiz.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
