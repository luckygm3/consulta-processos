"""Configuração local: config.json (editável) + variável DATAJUD_API_KEY opcional (.env ou ambiente)."""
import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "processos.sqlite3"
LOG_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"

DEFAULTS = {
    "oab_numero": "130678",
    "oab_uf": "PR",
    "nome_advogado": "Beatriz Daffara",
    "datajud_api_key": "",
    "backfill_dias": 180,
    "janela_dias": 30,
    "buscar_tambem_por_nome": False,
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


def carregar(com_env: bool = True) -> dict:
    """Lê o config.json. Com com_env=True, DATAJUD_API_KEY do ambiente/.env tem precedência."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            logging.getLogger(__name__).error("config.json inválido (%s); usando padrões", e)
    else:
        salvar(cfg)
    env_key = os.environ.get("DATAJUD_API_KEY") or _ler_env_arquivo().get("DATAJUD_API_KEY")
    if com_env and env_key:
        cfg["datajud_api_key"] = env_key
    cfg["datajud_api_key"] = normalizar_chave(cfg.get("datajud_api_key", ""))
    return cfg


def salvar(cfg: dict) -> None:
    dados = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    CONFIG_PATH.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
