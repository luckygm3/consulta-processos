"""Login: a tela entra pelo Supabase Auth (e-mail e senha, com a chave pública anon) e manda o token de acesso em
cada chamada (Authorization: Bearer ...). Aqui o token é conferido no próprio Supabase e vira o "contexto" da
requisição: db.conexao() assume o papel authenticated com esses dados, e a RLS decide o que ela pode ver.

Só passa quem é uma das advogadas cadastradas (public.e_autorizada()): outras contas recebem 403.
"""
import json
import logging
import threading
import time

import anyio
import httpx

from . import config, db

log = logging.getLogger("auth")

ABERTAS = {"/api/ping", "/api/publico"}  # rotas da API que funcionam sem login
CACHE_SEGUNDOS = 120                      # token conferido vale por até 2 min (ou até expirar, o que vier antes)

_cache: dict[str, tuple[float, dict]] = {}
_cache_trava = threading.Lock()


class NaoAutorizada(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status, self.mensagem = status, mensagem


async def _usuario_do_token(token: str) -> dict:
    """GET /auth/v1/user no Supabase: a forma oficial de saber se o token é válido (funciona com qualquer tipo de
    chave de assinatura do projeto, sem guardar segredo de JWT aqui)."""
    url = config.ambiente("SUPABASE_URL").rstrip("/") + "/auth/v1/user"
    async with httpx.AsyncClient(timeout=10) as cli:
        r = await cli.get(url, headers={"apikey": config.ambiente("SUPABASE_ANON_KEY"), "Authorization": f"Bearer {token}"})
    if r.status_code in (401, 403):
        raise NaoAutorizada(401, "Sessão expirada. Entre de novo.")
    if r.status_code != 200:
        raise NaoAutorizada(503, f"Não foi possível conferir o login no Supabase (HTTP {r.status_code}).")
    return r.json()


def _autorizada(claims: dict) -> bool:
    ctx = db.definir_usuaria(claims)
    try:
        with db.conexao() as con:
            return db.autorizada(con)
    finally:
        db.esquecer_usuaria(ctx)


async def conferir(token: str) -> dict:
    """Claims da usuária (sub, email, role) se o token for válido e ela for uma das advogadas; senão NaoAutorizada."""
    agora = time.monotonic()
    with _cache_trava:
        guardado = _cache.get(token)
    if guardado and guardado[0] > agora:
        return guardado[1]
    try:
        usuario = await _usuario_do_token(token)
    except httpx.HTTPError as e:
        raise NaoAutorizada(503, f"Sem conexão com o Supabase ({e.__class__.__name__}).")
    claims = {"sub": usuario["id"], "email": usuario.get("email"), "role": "authenticated", "aud": "authenticated"}
    if not await anyio.to_thread.run_sync(_autorizada, claims):
        log.warning("Login sem acesso: %s", usuario.get("email"))
        raise NaoAutorizada(403, "Esta conta não tem acesso. Peça para cadastrarem seu e-mail entre as advogadas.")
    with _cache_trava:
        if len(_cache) > 200:
            _cache.clear()
        _cache[token] = (agora + CACHE_SEGUNDOS, claims)
    return claims


class ExigirLogin:
    """Middleware ASGI: toda rota /api/* (menos as abertas) precisa de token válido de uma advogada.
    O contexto (db.definir_usuaria) vale para a rota inteira, inclusive quando ela roda numa thread."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        caminho = scope.get("path", "") if scope["type"] == "http" else ""
        if not caminho.startswith("/api/") or caminho in ABERTAS:
            await self.app(scope, receive, send)
            return
        cabecalhos = dict(scope.get("headers") or [])
        valor = cabecalhos.get(b"authorization", b"").decode()
        token = valor[7:].strip() if valor.lower().startswith("bearer ") else ""
        try:
            if not token:
                raise NaoAutorizada(401, "Entre com seu e-mail e senha.")
            claims = await conferir(token)
        except NaoAutorizada as e:
            await _responder(send, e.status, e.mensagem)
            return
        ctx = db.definir_usuaria(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            db.esquecer_usuaria(ctx)


async def _responder(send, status: int, mensagem: str):
    corpo = json.dumps({"detail": mensagem}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(corpo)).encode())]})
    await send({"type": "http.response.body", "body": corpo})
