"""Ciclo contínuo para o GitHub Actions: repete a rodada (coletar ofertas + publicar a melhor)
a cada INTERVALO segundos durante MINUTOS e sai. O workflow então dispara a próxima execução,
formando uma corrente que não depende do agendamento do GitHub (que atrasa e pula).

Cada rodada salva a fila e o que foi postado no repositório (git commit + push), para a
próxima execução continuar de onde parou.

Uso: python ciclo.py --minutos 55 --intervalo 300
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# horário de funcionamento (Brasília); depois de DESLIGA_AS o ciclo para e não dispara o próximo
LIGA_AS = os.getenv("LIGA_AS", "08:00")
DESLIGA_AS = os.getenv("DESLIGA_AS", "21:30")

PASSOS = [
    ("Magalu", ["radar.py", "--rodada"]),
    ("Amazon", ["radar_amazon.py", "--rodada"]),
    ("Lista Shopee", ["curadoria_shopee.py", "--se-faltar", "15"]),
    ("Shopee na fila", ["postar_shopee.py", "--fila"]),
    ("Publicar", ["publicar.py"]),
]


def rodar(nome, args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    saida = (r.stdout + r.stderr).strip()
    print(f"--- {nome} (saída {r.returncode})")
    if saida:
        print(saida[-1500:])


def salvar_estado(n):
    git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True)
    git("add", "estado/", "listas/")
    # só os .json/.txt de estado e a lista vão para o Git (fotos ficam de fora pelo .gitignore)
    if git("diff", "--cached", "--quiet").returncode != 0:
        git("commit", "-m", f"estado: ciclo {n}")
        for _ in range(3):  # se alguém mexeu no repositório nesse meio-tempo, junta e tenta de novo
            if git("pull", "--rebase", "--quiet").returncode == 0 and git("push", "--quiet").returncode == 0:
                return
            time.sleep(5)
        print("[aviso] não consegui salvar o estado no GitHub nesta rodada")


def agora_brasilia():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")


def no_horario():
    """O ciclo só funciona entre LIGA_AS e DESLIGA_AS (horário de Brasília)."""
    return LIGA_AS <= agora_brasilia() < DESLIGA_AS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=int, default=55)
    ap.add_argument("--intervalo", type=int, default=300)
    args = ap.parse_args()

    fim = time.time() + args.minutos * 60
    if not no_horario():
        print(f"Fora do horário de funcionamento ({LIGA_AS}-{DESLIGA_AS}, Brasília): nada a fazer.", flush=True)
        return
    n = 0
    while True:
        inicio = time.time()
        if not no_horario():
            print(f"Deu {DESLIGA_AS}: encerrando o dia.", flush=True)
            break
        n += 1
        print(f"===== rodada {n} ({agora_brasilia()} Brasília)", flush=True)
        for nome, cmd in PASSOS:
            try:
                rodar(nome, cmd)
            except Exception as erro:  # um passo com problema não derruba o ciclo
                print(f"--- {nome}: erro {erro}")
        salvar_estado(n)
        proxima = inicio + args.intervalo
        if proxima + 60 > fim:  # não começa uma rodada que não termina antes do fim
            break
        time.sleep(max(0, proxima - time.time()))
    print(f"Ciclo encerrado após {n} rodadas.", flush=True)


if __name__ == "__main__":
    main()
