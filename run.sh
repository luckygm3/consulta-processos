#!/usr/bin/env sh
# Cria o ambiente (na primeira vez), instala as dependências e abre o app no navegador.
# No Mac, basta dar dois cliques em "abrir-no-mac.command", que chama este script.
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1

vpy() {
  if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo .venv/Scripts/python.exe; fi
}

# Procura um Python 3.11+. No Mac, ignora o /usr/bin/python3 do sistema (é 3.9 e pode abrir
# um pedido de instalação das ferramentas do Xcode).
achar_python() {
  for c in python3.13 python3.12 python3.11 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 python3 python; do
    caminho=$(command -v "$c" 2>/dev/null) || continue
    if [ "$caminho" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ]; then continue; fi
    if "$caminho" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
      echo "$caminho"
      return 0
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ] && [ ! -x .venv/Scripts/python.exe ]; then
  echo "Procurando Python 3.11 ou mais novo..."
  if ! PY=$(achar_python); then
    echo
    echo "O Python 3.11+ não foi encontrado neste computador. Ele é necessário para rodar o app."
    echo "Baixe em https://www.python.org/downloads/ (botão amarelo \"Download Python\"), instale"
    echo "e depois abra o app de novo."
    if [ "$(uname)" = Darwin ]; then open "https://www.python.org/downloads/" 2>/dev/null || true; fi
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
