"""Cria um canal PRIVADO no seu Telegram para receber os posts do radar
e grava o ID dele como DESTINO no .env.

Uso: python criar_canal.py "Nome do canal" "Descrição"
"""
import asyncio
import re
import sys

from telethon.tl.functions.channels import CreateChannelRequest

import radar


async def main():
    titulo = sys.argv[1] if len(sys.argv) > 1 else "Radar Baby (teste)"
    descricao = sys.argv[2] if len(sys.argv) > 2 else "Canal de teste dos posts do radar de ofertas"

    client = radar.criar_cliente()
    await client.start(phone=radar.pedir_telefone, code_callback=radar.pedir_codigo)
    resultado = await client(CreateChannelRequest(title=titulo, about=descricao, broadcast=True))
    canal = resultado.chats[0]
    destino = f"-100{canal.id}"  # formato de ID que o Telegram usa para canais

    env = radar.PASTA / ".env"
    texto = env.read_text(encoding="utf-8")
    texto = re.sub(r"^DESTINO=.*$", f"DESTINO={destino}", texto, flags=re.MULTILINE)
    env.write_text(texto, encoding="utf-8")

    print(f"Canal criado: {titulo} (privado)")
    print(f"DESTINO={destino} gravado no .env")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
