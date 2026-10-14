"""Configuração: variáveis de ambiente (.env no computador; painel da Vercel no site), padrões do config.json
(só leitura: no servidor da Vercel não dá para gravar arquivo) e ajustes feitos na tela (guardados no banco).

Variáveis (ver .env.example):
  DATABASE_URL        conexão do backend com o Postgres do Supabase (segredo do servidor; nunca vai para a tela)
  SUPABASE_URL        https://<projeto>.supabase.co
  SUPABASE_ANON_KEY   chave pública "anon": a única que a tela recebe (para o login)
  DATAJUD_API_KEY     opcional; tem precedência sobre a do config.json e a salva na tela

Processos em cooperação: os advogados de cooperação ficam na tabela advogados_cooperacao (editável em ⚙) e
"ocultar processos em cooperação" é um ajuste da tela (padrão: ligado).
"""
import json
import logging
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
CHECKLIST_PATH = BASE_DIR / "checklists_padrao.txt"
MODELOS_CHECKLIST = ("processo", "preventivo")
ENV_PATH = BASE_DIR / ".env"
DB_DIR = BASE_DIR / "db"                      # banco SQLite antigo (origem do script de migração)
DB_PATH = DB_DIR / "processos.sqlite3"
LOG_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"

CORES = ["#7c3aed", "#0f766e", "#c2410c", "#be185d", "#4d7c0f", "#0369a1"]
# Advogados de fora do escritório: processo em que algum deles consta é "em cooperação" (dá para ocultar)
COOPERACAO_PADRAO = [{"nome": "Jessica Delmoni", "oab_numero": "13043", "oab_uf": "AL"}]

DEFAULTS = {
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
    "advogados_cooperacao": COOPERACAO_PADRAO,  # só o valor inicial: depois vale a tabela advogados_cooperacao
    "porta": 8000,
}
AJUSTAVEIS = ("datajud_api_key", "backfill_dias", "ocultar_cooperacao")  # mudados na tela (ficam no banco)


def carregar_env() -> None:
    """Lê o .env (CHAVE=valor) para o ambiente, sem sobrescrever o que já veio do sistema/Vercel."""
    if not ENV_PATH.exists():
        return
    for linha in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


carregar_env()


def ambiente(nome: str, obrigatoria: bool = True) -> str:
    valor = os.environ.get(nome, "").strip()
    if obrigatoria and not valor:
        raise RuntimeError(f"Falta a variável {nome} (veja o .env.example e o README).")
    return valor


def na_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def normalizar_chave(chave: str) -> str:
    """Aceita a chave colada com ou sem 'Authorization:' / 'APIKey'."""
    chave = (chave or "").strip()
    chave = re.sub(r"^authorization\s*:\s*", "", chave, flags=re.I)
    chave = re.sub(r"^apikey\s+", "", chave, flags=re.I)
    return chave.strip()


def _arquivo() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    except (OSError, json.JSONDecodeError) as e:
        logging.getLogger(__name__).error("config.json inválido (%s); usando padrões", e)
        return {}


def carregar() -> dict:
    """Padrões + config.json (sem os ajustes da tela, que estão no banco: use efetiva())."""
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _arquivo().items() if k in DEFAULTS})
    cfg["advogados_cooperacao"] = _cooperacao(cfg)
    return cfg


def efetiva(con) -> dict:
    """Configuração em uso: padrões, config.json, ajustes salvos na tela e, por último, DATAJUD_API_KEY do ambiente."""
    cfg = carregar()
    for r in con.execute("SELECT chave, valor FROM meta WHERE chave LIKE 'ajuste:%%'"):
        k = r["chave"].split(":", 1)[1]
        if k in AJUSTAVEIS:
            cfg[k] = json.loads(r["valor"])
    if os.environ.get("DATAJUD_API_KEY"):
        cfg["datajud_api_key"] = os.environ["DATAJUD_API_KEY"]
    cfg["datajud_api_key"] = normalizar_chave(cfg.get("datajud_api_key", ""))
    cfg["ocultar_cooperacao"] = bool(cfg.get("ocultar_cooperacao"))
    cfg["advogados_cooperacao"] = cooperacao(con)
    return cfg


def ajustar(con, **valores) -> None:
    for k, v in valores.items():
        if k in AJUSTAVEIS:
            con.execute("INSERT INTO meta(chave, valor) VALUES(%s, %s) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                        (f"ajuste:{k}", json.dumps(v)))


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


def cooperacao(con) -> list[dict]:
    """Advogados de cooperação cadastrados (tabela advogados_cooperacao)."""
    return [{"nome": r["nome"], "oab_numero": r["oab_numero"], "oab_uf": r["oab_uf"]}
            for r in con.execute("SELECT nome, oab_numero, oab_uf FROM advogados_cooperacao ORDER BY id")]


def salvar_cooperacao(con, lista: list[dict]) -> list[dict]:
    """Troca a lista inteira (vinda da tela). Devolve a lista normalizada."""
    lista = _cooperacao({"advogados_cooperacao": lista})
    con.execute("DELETE FROM advogados_cooperacao")
    if lista:
        con.executemany("INSERT INTO advogados_cooperacao(nome, oab_numero, oab_uf) VALUES(%s, %s, %s)",
                        [(a["nome"], a["oab_numero"], a["oab_uf"]) for a in lista])
    return lista


def cooperacao_do_arquivo() -> list[dict]:
    """Lista inicial: a do config.json (versões antigas gravavam lá) ou a padrão."""
    cfg = _arquivo()
    return _cooperacao(cfg if "advogados_cooperacao" in cfg else {"advogados_cooperacao": COOPERACAO_PADRAO})


def advogadas_do_arquivo() -> list[dict]:
    """Advogadas do config.json antigo (só para o script de migração, se o banco antigo não tiver a tabela)."""
    cfg = _arquivo()
    lista = cfg.get("advogadas")
    if not isinstance(lista, list):
        lista = [{"nome": cfg.get("nome_advogado", ""), "oab_numero": cfg.get("oab_numero", ""), "oab_uf": cfg.get("oab_uf", "")}]
    saida = []
    for i, a in enumerate(x for x in lista if isinstance(x, dict)):
        oab, uf = str(a.get("oab_numero") or "").strip(), str(a.get("oab_uf") or "").strip().upper()
        if oab and uf:
            saida.append({"nome": str(a.get("nome") or "").strip() or f"OAB {oab}/{uf}", "oab_numero": oab, "oab_uf": uf,
                          "cor": str(a.get("cor") or CORES[i % len(CORES)])})
    return saida


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
    """Na tela (stderr) sempre; em logs/app.log só no computador (na Vercel o disco é somente leitura)."""
    raiz = logging.getLogger()
    if getattr(raiz, "_configurado_app", False):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    tela = logging.StreamHandler()
    tela.setFormatter(fmt)
    raiz.addHandler(tela)
    if not na_vercel():
        try:
            from logging.handlers import RotatingFileHandler
            LOG_DIR.mkdir(exist_ok=True)
            arq = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            arq.setFormatter(fmt)
            raiz.addHandler(arq)
        except OSError:
            pass
    raiz.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raiz._configurado_app = True
