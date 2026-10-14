"""Meus processos. O app trabalha no horário de Brasília (datas de prazo, "hoje", "vence amanhã"), também quando
roda num servidor em UTC (Vercel): no Linux/Mac, fixa o fuso do processo antes de qualquer data ser calculada."""
import os
import time

FUSO = "America/Sao_Paulo"

if hasattr(time, "tzset"):  # Windows não tem tzset; lá o app roda no computador dela, já no fuso certo
    os.environ["TZ"] = FUSO
    time.tzset()
