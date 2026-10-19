"""Transforma o login do Telegram deste PC (sessao_radar.session) em um texto
TG_SESSION, para a VM conseguir entrar sem pedir código.

Uso: python gerar_sessao.py
Grava TG_SESSION no arquivo .env deste PC. Depois copie esse .env para a VM.

ATENÇÃO: TG_SESSION dá acesso total à sua conta do Telegram. Não coloque no Git,
não mande em chat e não mostre na tela. Se vazar, encerre a sessão no app do
Telegram (Configurações > Dispositivos) e gere outra.
"""
import re
import sys

from telethon.sessions import SQLiteSession, StringSession

import radar


def main():
    arquivo = radar.ARQ_SESSAO.with_suffix(".session")
    if not arquivo.exists():
        sys.exit("Não achei sessao_radar.session: rode 'python radar.py --teste 1' e faça o login primeiro.")
    texto_sessao = StringSession.save(SQLiteSession(str(radar.ARQ_SESSAO)))
    if not texto_sessao:
        sys.exit("A sessão está vazia: faça o login de novo com 'python radar.py --teste 1'.")

    env = radar.PASTA / ".env"
    conteudo = env.read_text(encoding="utf-8") if env.exists() else ""
    linha = f"TG_SESSION={texto_sessao}"
    if re.search(r"^TG_SESSION=.*$", conteudo, flags=re.MULTILINE):
        conteudo = re.sub(r"^TG_SESSION=.*$", lambda _: linha, conteudo, flags=re.MULTILINE)
    else:
        conteudo = conteudo.rstrip("\n") + "\n\n# login do Telegram para a nuvem (SEGREDO: não compartilhe)\n" + linha + "\n"
    env.write_text(conteudo, encoding="utf-8")
    print("TG_SESSION gravada no .env (o valor não é mostrado por segurança).")


if __name__ == "__main__":
    main()
