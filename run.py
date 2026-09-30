"""Inicia o app em http://127.0.0.1:<porta> (só nesta máquina) e abre o navegador.

Uso: python run.py [--sem-navegador]
"""
import socket
import sys
import threading
import time
import webbrowser

import httpx
import uvicorn

from app import config


def porta_ocupada(porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main():
    porta = int(config.carregar().get("porta") or 8000)
    url = f"http://127.0.0.1:{porta}"
    abrir = "--sem-navegador" not in sys.argv

    if porta_ocupada(porta):
        try:
            ja_aberto = httpx.get(f"{url}/api/ping", timeout=3).json().get("app") == "processos-beatriz"
        except Exception:
            ja_aberto = False
        if ja_aberto:
            print(f"O app já está rodando em {url}. Abrindo no navegador.")
            if abrir:
                webbrowser.open(url)
        else:
            print(f"A porta {porta} está ocupada por outro programa. Mude 'porta' no config.json.")
        return

    def abrir_quando_pronto():
        for _ in range(100):
            time.sleep(0.2)
            if porta_ocupada(porta):
                webbrowser.open(url)
                return

    if abrir:
        threading.Thread(target=abrir_quando_pronto, daemon=True).start()
    print(f"\n  Processos rodando em {url}\n  Deixe esta janela aberta. Para encerrar, feche-a (ou Ctrl+C).\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=porta, log_level="warning")


if __name__ == "__main__":
    main()
