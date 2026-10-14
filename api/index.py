"""Entrada da Vercel: a função Python serve o app inteiro (API + telas). Ver vercel.json."""
from app.main import app

__all__ = ["app"]
