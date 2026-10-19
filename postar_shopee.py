"""Posta no canal as ofertas da curadoria da Shopee (curadoria_shopee_baby.csv),
com foto e o SEU link de afiliado.

Uso:
  python postar_shopee.py                     -> posta as 10 primeiras, uma a cada 10 s
  python postar_shopee.py --quantidade 20 --intervalo 30 --inicio 11
  python postar_shopee.py --simular           -> só mostra os posts, não envia
  python postar_shopee.py --agendado          -> fica ligado postando 1 a cada INTERVALO_MIN (uso na VM)
  python postar_shopee.py --rodada            -> posta 1 se estiver no horário e sai (GitHub Actions)
"""
import argparse
import asyncio
import csv
import json
import os
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import fila
import formato
import radar

PLANILHA = radar.PASTA / "listas" / "curadoria_shopee_baby.csv"
PASTA_FOTOS = radar.DADOS / "fotos_shopee"
POSTADOS = radar.DADOS / "postados_shopee.json"
# horário de postagem do modo --agendado (horário de Brasília, mesmo com a VM em UTC)
FUSO = ZoneInfo("America/Sao_Paulo")
POSTAR_DAS = int(os.getenv("POSTAR_DAS", "8"))
POSTAR_ATE = int(os.getenv("POSTAR_ATE", "22"))
INTERVALO_MIN = int(os.getenv("INTERVALO_MIN", "40"))


def _num(txt):
    try:
        return float(str(txt).replace(",", "."))
    except ValueError:
        return 0.0


def titulo_curto(titulo, limite=80):
    return formato.titulo(titulo, limite)[2:]  # sem o "🔥 ", para os logs


def montar_post(linha):
    return formato.juntar(
        formato.titulo(linha["produto"]),
        formato.preco(_num(linha["preco_de"]), _num(linha["preco_por"]), int(_num(linha["desconto_%"])) or None),
        formato.nota(linha.get("nota"), _num(linha.get("curtidas")) or None),
        formato.link("Shopee", linha["meu_link_afiliado"]),
        formato.AVISO,
    )


def id_produto(linha):
    return linha["link_produto"].rstrip("/").split("/")[-1]


def carregar_postados():
    try:
        return set(json.loads(POSTADOS.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def salvar_postados(postados):
    POSTADOS.write_text(json.dumps(sorted(postados)), encoding="utf-8")


def baixar_foto(linha):
    PASTA_FOTOS.mkdir(exist_ok=True)
    destino = PASTA_FOTOS / (linha["link_produto"].rstrip("/").split("/")[-1] + ".jpg")
    if not destino.exists():
        req = urllib.request.Request(linha["foto"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
            f.write(r.read())
    return destino


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quantidade", type=int, default=10)
    ap.add_argument("--intervalo", type=int, default=10, help="segundos entre posts")
    ap.add_argument("--inicio", type=int, default=1, help="posição na planilha (rank) para começar")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--agendado", action="store_true",
                    help="fica ligado e posta 1 oferta a cada INTERVALO_MIN minutos, dentro do horário do .env")
    ap.add_argument("--rodada", action="store_true",
                    help="posta 1 oferta se estiver no horário do .env e sai (GitHub Actions)")
    ap.add_argument("--fila", action="store_true",
                    help="deixa 1 oferta da Shopee esperando na fila do publicar.py (não posta nada)")
    args = ap.parse_args()
    if args.fila:
        abastecer_fila()
        return
    if args.rodada:
        agora = datetime.now(FUSO)
        if not POSTAR_DAS <= agora.hour < POSTAR_ATE:
            print(f"[{agora:%d/%m %H:%M}] fora do horário de postagem ({POSTAR_DAS}h-{POSTAR_ATE}h): nada a fazer.")
            return
        args.quantidade = 1

    if args.simular:
        for l in proximos(args.quantidade, args.inicio):
            print(montar_post(l), "\n")
        return

    client = radar.criar_cliente(copia="shopee")
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Telegram sem login: rode o radar.py uma vez no PC ou gere a TG_SESSION")
    await client.get_dialogs()

    if args.agendado:
        await modo_agendado(client)
        return

    lote = proximos(args.quantidade, args.inicio)
    if not lote:
        print("Nada novo para postar: todos os produtos da planilha já foram postados.")
        return
    for linha in lote:
        await postar(client, linha)
        if linha is not lote[-1]:
            await asyncio.sleep(args.intervalo)
    print(f"Pronto: {len(lote)} posts da Shopee enviados para {radar.DESTINO}.")
    await client.disconnect()


def proximos(quantidade, inicio=1):
    # relê a planilha toda vez: na VM ela pode ter sido atualizada por um git pull
    linhas = list(csv.DictReader(open(PLANILHA, encoding="utf-8-sig"), delimiter=";"))
    postados = carregar_postados()
    linhas = [l for l in linhas[inicio - 1:]
              if l.get("meu_link_afiliado")  # nunca posta sem o link de afiliado
              and id_produto(l) not in postados]  # nem repete o que já foi para o canal
    return linhas[:quantidade]


def abastecer_fila():
    """Mantém 1 oferta da Shopee na fila. Ela não vence: serve de 'reserva' para quando não há
    oferta fresca de Magalu/Amazon, e o publicar.py alterna as lojas."""
    if fila.tem_da_loja("Shopee"):
        print("Fila já tem uma oferta da Shopee esperando.")
        return
    na_fila = {i["id"] for i in fila.carregar()["itens"]}
    for linha in proximos(5):
        item_id = f"shopee:{id_produto(linha)}"
        if item_id in na_fila:
            continue
        de, por = _num(linha["preco_de"]), _num(linha["preco_por"])
        nota = fila.nota_vantagem(linha["produto"], linha["produto"], por, de)
        fila.adicionar({"id": item_id, "loja": "Shopee", "texto": montar_post(linha), "nota": round(nota, 1),
                        "criado": time.time(), "expira": False, "foto": {"tipo": "url", "url": linha["foto"]}})
        print(f"[fila] Shopee nota {nota:.0f}: {titulo_curto(linha['produto'], 60)}")
        return
    print("Lista da Shopee sem ofertas novas para a fila.")


async def postar(client, linha):
    post = montar_post(linha)
    try:
        await client.send_file(radar.DESTINO, str(baixar_foto(linha)), caption=post)
    except Exception as erro:
        print(f"[aviso] sem foto no #{linha['rank']} ({erro}); enviando só texto")
        await client.send_message(radar.DESTINO, post)
    postados = carregar_postados()
    postados.add(id_produto(linha))
    salvar_postados(postados)
    print(f"[{datetime.now(FUSO):%d/%m %H:%M}] [{linha['rank']}] postado: {titulo_curto(linha['produto'], 60)}",
          flush=True)


async def modo_agendado(client):
    print(f"Agendador ligado: 1 oferta a cada {INTERVALO_MIN} min, das {POSTAR_DAS}h às {POSTAR_ATE}h.", flush=True)
    while True:
        agora = datetime.now(FUSO)
        if POSTAR_DAS <= agora.hour < POSTAR_ATE:
            lote = proximos(1)
            if lote:
                await postar(client, lote[0])
            else:
                print(f"[{agora:%d/%m %H:%M}] lista acabou: atualize curadoria_shopee_baby.csv", flush=True)
        await asyncio.sleep(INTERVALO_MIN * 60)


if __name__ == "__main__":
    asyncio.run(main())
