"""Banco antigo (SQLite, de antes do Supabase): leitura segura e "impressão digital" do conteúdo.

- copia(): abre uma cópia temporária do arquivo junto com o -wal/-shm. O app antigo usava WAL: com a janela
  fechada à força, o que foi registrado por último pode estar só no -wal. O original nunca é alterado.
- impressao(): hash do conteúdo inteiro (todas as tabelas, linha a linha). A migração guarda a do banco que copiou
  (meta "migracao_origem"). Num computador que ainda tem db/processos.sqlite3, o app compara com a do arquivo
  local e avisa se ele tem dados que não estão no Supabase (outro banco, cópia sem o -wal, ou a versão antiga
  usada depois da migração).
"""
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config, db

log = logging.getLogger("banco_antigo")

SUFIXOS = ("", "-wal", "-shm")
CHAVE_META = "migracao_origem"


def arquivos(caminho: Path) -> list[Path]:
    """O banco e, se existirem, os arquivos -wal e -shm ao lado dele."""
    return [f for f in (caminho.with_name(caminho.name + s) for s in SUFIXOS) if f.exists()]


@contextmanager
def copia(caminho: Path):
    """Conexão (sqlite3.Row) com uma cópia temporária do banco; apagada ao sair."""
    pasta = Path(tempfile.mkdtemp(prefix="banco-antigo-"))
    try:
        for f in arquivos(caminho):
            shutil.copy2(f, pasta / f.name)
        con = sqlite3.connect(pasta / caminho.name)
        try:
            con.row_factory = sqlite3.Row
            yield con
        finally:
            con.close()
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def impressao(con: sqlite3.Connection) -> str:
    """sha256 do dump completo (estrutura + todas as linhas): muda se qualquer registro mudar."""
    h = hashlib.sha256()
    fabrica, con.row_factory = con.row_factory, None
    try:
        for linha in con.iterdump():
            h.update(linha.encode("utf-8") + b"\n")
    finally:
        con.row_factory = fabrica
    return h.hexdigest()


_trava = threading.Lock()
_calculada: dict = {}


def situacao(con) -> str | None:
    """Há banco antigo neste computador? None = não (ou na Vercel); "migrado" = o conteúdo dele é o que foi para
    o Supabase; "pendente" = ele tem dados que não estão lá."""
    if config.na_vercel() or not config.DB_PATH.exists():
        return None
    try:
        with _trava:  # o hash só é refeito se o arquivo mudar
            chave = tuple((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in arquivos(config.DB_PATH))
            if _calculada.get("chave") != chave:
                with copia(config.DB_PATH) as o:
                    _calculada.update(chave=chave, impressao=impressao(o))
            local = _calculada["impressao"]
    except (OSError, sqlite3.Error) as e:
        log.warning("Não deu para ler o banco antigo %s: %s", config.DB_PATH, e)
        return None
    try:
        origem = json.loads(db.meta_get(con, CHAVE_META) or "{}")
    except ValueError:
        origem = {}
    return "migrado" if origem.get("impressao") == local else "pendente"
