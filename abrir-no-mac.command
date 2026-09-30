#!/bin/sh
# Mac: dois cliques aqui abrem o app no navegador. Deixe a janela do Terminal aberta enquanto usa.
cd "$(dirname "$0")" || exit 1
sh ./run.sh "$@"
if [ $? -ne 0 ]; then
  echo
  printf "Veja a mensagem acima. Pressione Enter para fechar esta janela..."
  read -r _
fi
