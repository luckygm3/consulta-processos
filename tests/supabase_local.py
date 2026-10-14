"""Postgres local que imita o Supabase, para testar o schema (supabase/schema.sql), a RLS e o código do banco
sem projeto na nuvem: papéis anon/authenticated, schema auth com auth.users e auth.uid() iguais aos do Supabase.

Usa o pacote pgserver (requirements-dev.txt), que traz o Postgres junto. Sem ele, os testes de banco são pulados.
Cada teste roda numa transação desfeita no final (não sobra nada entre testes).
"""
import atexit
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from app import db

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA = RAIZ / "supabase" / "schema.sql"

# Duas advogadas com login, como no escritório; ids 1 e 2
BEATRIZ = {"id": 1, "email": "beatriz@exemplo.com", "nome": "Beatriz Daffara", "oab": "130678"}
KAZUZA = {"id": 2, "email": "kazuza@exemplo.com", "nome": "Kazuza", "oab": "130152"}

IMITA_SUPABASE = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN NOINHERIT; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN NOINHERIT; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text UNIQUE, email_confirmed_at timestamptz);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
GRANT USAGE ON SCHEMA auth TO anon, authenticated;
-- sem as permissões padrão do schema public (como num projeto criado com a Data API desligada):
-- o supabase/schema.sql tem de dar sozinho tudo o que o app usa
REVOKE ALL ON SCHEMA public FROM PUBLIC;
"""

_estado: dict = {}


def disponivel() -> bool:
    import importlib.util
    return importlib.util.find_spec("pgserver") is not None


def criar_banco(prefixo: str = "teste", apagar_no_fim: bool = True) -> str:
    """Sobe (uma vez) o Postgres local e cria um banco novo, vazio, com o schema do Supabase. Devolve a URL."""
    import pgserver
    import psycopg
    servidor = pgserver.get_server(Path(tempfile.gettempdir()) / "processos-pg-teste", cleanup_mode=None)
    base = servidor.get_uri()
    nome = f"{prefixo}_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome}")
    url = base.rsplit("/", 1)[0] + "/" + nome
    with psycopg.connect(url, autocommit=True) as c:
        try:
            c.execute("SET TIME ZONE 'America/Sao_Paulo'")
        except psycopg.errors.InvalidParameterValue:
            # o Postgres do pgserver no Windows vem sem a base de fusos; Brasília sem horário de verão = UTC-3
            os.environ["FUSO_BANCO"] = "<-03>+03"
        c.execute(IMITA_SUPABASE)
        c.execute(SCHEMA.read_text(encoding="utf-8"))

    def apagar():
        try:
            with psycopg.connect(base, autocommit=True) as c:
                c.execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)")
        except Exception:
            pass
    if apagar_no_fim:
        atexit.register(apagar)
    return url


def url_do_banco() -> str:
    """Banco dos testes: schema do Supabase + as duas advogadas com login confirmado (criado uma vez por execução)."""
    if "url" in _estado:
        return _estado["url"]
    import psycopg
    url = criar_banco()
    with psycopg.connect(url, autocommit=True) as c:
        for a in (BEATRIZ, KAZUZA):
            a["uid"] = str(uuid.uuid4())
            c.execute("INSERT INTO advogadas(id, nome, oab_numero, oab_uf, email) VALUES(%s, %s, %s, 'PR', %s)",
                      (a["id"], a["nome"], a["oab"], a["email"]))
            # login confirmado: o trigger vincula sozinho a advogada (user_id)
            c.execute("INSERT INTO auth.users(id, email, email_confirmed_at) VALUES(%s, %s, now())", (a["uid"], a["email"]))
        c.execute("SELECT setval(pg_get_serial_sequence('advogadas', 'id'), 2)")
    _estado["url"] = url
    return url


def claims(advogada: dict | None = None, email: str | None = None, uid: str | None = None) -> dict:
    a = advogada or BEATRIZ
    return {"sub": uid or a["uid"], "email": email or a["email"], "role": "authenticated", "aud": "authenticated"}


@unittest.skipUnless(disponivel(), "pgserver não instalado (pip install -r requirements-dev.txt)")
class TesteComBanco(unittest.TestCase):
    """Base dos testes de banco: self.conexao() devolve uma db.Conexao já como usuária logada (RLS valendo),
    numa transação que é desfeita no fim do teste."""

    @classmethod
    def setUpClass(cls):
        cls.url = url_do_banco()

    def conexao(self, quem: dict | None = None):
        import psycopg
        bruta = psycopg.connect(self.url, prepare_threshold=None)
        db.preparar(bruta)
        db.entrar(bruta, quem or claims())

        def fechar():
            bruta.rollback()
            bruta.close()
        self.addCleanup(fechar)
        return db.Conexao(bruta)

    def processo(self, con, numero: str, **campos):
        cols = {"numero": numero, **campos}
        for k in ("partes", "instancias", "assuntos"):
            if k in cols and not isinstance(cols[k], str) and cols[k] is not None:
                cols[k] = json.dumps(cols[k], ensure_ascii=False)
        con.execute(f"INSERT INTO processos({','.join(cols)}) VALUES({','.join(['%s'] * len(cols))})", list(cols.values()))
