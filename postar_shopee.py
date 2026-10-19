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
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

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
    # títulos da Shopee vêm cheios de palavras-chave; corta no fim de uma palavra
    titulo = " ".join(titulo.split())
    if len(titulo) <= limite:
        return titulo
    return titulo[:limite].rsplit(" ", 1)[0] + "…"


def curtidas(n):
    n = int(_num(n))
    return f"{n / 1000:.1f} mil".replace(".", ",").replace(",0 mil", " mil") if n >= 1000 else str(n)


def montar_post(linha):
    de, por = _num(linha["preco_de"]), _num(linha["preco_por"])
    linhas = [f"🔥 {titulo_curto(linha['produto'])}"]
    if de > por:
        linhas.append(f"💰 de {radar.brl(de)} por {radar.brl(por)} (-{linha['desconto_%']}%)")
    else:
        linhas.append(f"💰 por {radar.brl(por)}")
    nota = linha["nota"].replace(".", ",")
    linhas.append(f"⭐ Nota {nota} | ❤️ {curtidas(linha['curtidas'])} curtidas")
    link = linha["meu_link_afiliado"]
    if "an_redir" in link:
        # link montado é longo: vira texto clicável (o Telegram usa markdown por padrão)
        linhas.append(f"🛍️ [👉 Ver oferta na Shopee]({link})")
    else:
        linhas.append(f"🛍️ Shopee 👉 {link}")
    linhas.append("⚠️ Preço e estoque podem mudar a qualquer momento")
    return "\n".join(linhas)


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
    args = ap.parse_args()
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
