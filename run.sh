#!/usr/bin/env sh
# Cria o ambiente (na primeira vez), instala as dependências e abre o app no navegador.
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1

vpy() {
  if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo .venv/Scripts/python.exe; fi
}

if [ ! -x .venv/bin/python ] && [ ! -x .venv/Scripts/python.exe ]; then
  PY=""
  for c in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.11+ não encontrado. Instale em https://www.python.org/downloads/"
    exit 1
  fi
  echo "Criando ambiente virtual com $PY ..."
  "$PY" -m venv .venv
fi

if ! cmp -s requirements.txt .venv/requirements.instalado; then
  echo "Instalando dependências..."
  "$(vpy)" -m pip install -q --disable-pip-version-check -r requirements.txt
  cp requirements.txt .venv/requirements.instalado
fi

exec "$(vpy)" run.py "$@"
