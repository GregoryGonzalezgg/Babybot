"""Posta a oferta mais vantajosa da fila (fila.py). Roda a cada 5 minutos no GitHub Actions,
então sai no máximo 1 post a cada 5 minutos, sempre o melhor que estiver esperando.

Uso:
  python publicar.py             -> posta 1 (se estiver no horário de postagem)
  python publicar.py --simular   -> mostra a fila em ordem de prioridade, sem postar
"""
import argparse
import asyncio
import time
from datetime import datetime

import fila
import radar
from postar_shopee import FUSO, POSTAR_ATE, POSTAR_DAS, baixar_foto, carregar_postados, salvar_postados


async def enviar(client, item):
    foto = item.get("foto") or {}
    try:
        if foto.get("tipo") == "telegram":
            msg = await client.get_messages(foto["chat"], ids=foto["msg"])
            if msg and msg.photo:
                await client.send_file(radar.DESTINO, msg.photo, caption=item["texto"])
                return
        elif foto.get("tipo") == "url":
            caminho = baixar_foto({"link_produto": item["id"].replace(":", "_"), "foto": foto["url"]})
            await client.send_file(radar.DESTINO, str(caminho), caption=item["texto"])
            return
    except Exception as erro:
        print(f"[aviso] não consegui usar a foto ({erro}); vai com a prévia do link")
    # sem foto da fonte: o Telegram monta a prévia (foto e nome) a partir do link da oferta
    await client.send_message(radar.DESTINO, item["texto"], link_preview=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true")
    args = ap.parse_args()

    f = fila.carregar()
    escolhido = fila.escolher(f)
    if args.simular:
        agora = time.time()
        for i in sorted(f["itens"], key=lambda i: -i["nota"]):
            idade = (agora - i["criado"]) / 60
            print(f"{'>>' if i is escolhido else '  '} {i['loja']:7} nota {i['nota']:5.1f} | {idade:5.0f} min | "
                  f"{i['texto'].splitlines()[0][:60]}")
        return

    agora = datetime.now(FUSO)
    if not POSTAR_DAS <= agora.hour < POSTAR_ATE:
        fila.salvar(f)  # só limpa as vencidas
        print(f"[{agora:%H:%M}] fora do horário ({POSTAR_DAS}h-{POSTAR_ATE}h): nada postado.")
        return
    if not escolhido:
        fila.salvar(f)
        print("Fila vazia: nada para postar agora.")
        return

    client = radar.criar_cliente(copia="publicar")
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Telegram sem login: gere a TG_SESSION")
    await client.get_dialogs()
    await enviar(client, escolhido)
    await client.disconnect()

    f["itens"] = [i for i in f["itens"] if i["id"] != escolhido["id"]]
    f["ultima_loja"] = escolhido["loja"]
    fila.salvar(f)
    if escolhido["loja"] == "Shopee":  # a Shopee controla o que já foi pela lista de postados
        postados = carregar_postados()
        postados.add(escolhido["id"].split(":", 1)[1])
        salvar_postados(postados)
    print(f"[{agora:%d/%m %H:%M}] postado ({escolhido['loja']}, nota {escolhido['nota']:.0f}): "
          f"{escolhido['texto'].splitlines()[0][:70]} | restam {len(f['itens'])} na fila", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
