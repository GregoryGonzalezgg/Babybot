"""Radar de ofertas da Amazon a partir de comunidades de ofertas no Telegram.

Lê o Promobit e o Baby Promo Kids (o Pelando bloqueia acesso automático), separa as ofertas da Amazon que são de
bebê (0 a 5 anos), descobre o código do produto (ASIN) pelo link da comunidade
e posta com o SEU link de afiliado. Não acessa o site da Amazon: o ASIN vem da
página de redirecionamento da comunidade.

Uso:
  python radar_amazon.py --rodada            -> posts novos desde a última rodada (GitHub Actions)
  python radar_amazon.py --teste 150         -> mostra o que faria com os últimos 150 posts, sem enviar
"""
import argparse
import asyncio
import json
import os
import re
import urllib.request

import radar
from curadoria_shopee import para_ate_5_anos
from nicho import classificar
from parser_magalu import CUPOM_RE, PRECO_RE, Oferta, brl

FONTES = [f.strip().lstrip("@") for f in os.getenv("FONTES_AMAZON", "cupons_desconto,babypromokids").split(",")
          if f.strip()]
# canais que só postam coisas de bebê: dispensam a palavra "bebê" no título, mas o filtro
# de idade (0 a 5 anos) continua. Deles não reaproveitamos a foto: ela vem da prévia do nosso link.
FONTES_SO_BEBE = {f.strip().lstrip("@") for f in os.getenv("FONTES_SO_BEBE", "babypromokids").split(",") if f.strip()}
CONDICAO_RE = re.compile(r"recorr[eê]ncia|comprando \d|cada em \d|leve \d|a partir de \d unidades", re.IGNORECASE)
AMAZON_TAG = os.getenv("AMAZON_TAG", "").strip()
VISTOS_ARQ = radar.DADOS / "vistos_amazon.json"
ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
LINK_RE = re.compile(r"https?://\S+")
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}


def eh_amazon(texto):
    return bool(re.search(r"\bamazon\b|amzn\.to|amzlink\.to", texto or "", re.IGNORECASE))


def montar_oferta(texto):
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    titulo = re.sub(r"[^\w\s\-\+/,\.%()|]", "", linhas[0]).strip() if linhas else ""
    precos = [p for p in PRECO_RE.findall(texto)]
    oferta = Oferta(ids=["amazon"], titulo=titulo, texto_original=texto)
    if precos:
        oferta.preco_por = float(precos[0].replace(".", "").replace(",", "."))
    m = CUPOM_RE.search(texto)
    if m:
        oferta.cupom = m.group(1).upper()
    return oferta


def eh_de_bebe(oferta, canal=""):
    if canal in FONTES_SO_BEBE:
        # "Baby Clothes" = subcategoria que já conta como bebê; só valem as exclusões de idade
        return para_ate_5_anos({"title": oferta.titulo, "global_category2": "Baby Clothes"})
    return classificar(oferta) == "sim" and para_ate_5_anos({"title": oferta.titulo, "global_category2": ""})


def descobrir_asin(link_comunidade):
    """Segue o link da comunidade até a página dela que aponta para a Amazon e tira o ASIN.
    Nunca abre páginas da Amazon."""
    url = link_comunidade
    for _ in range(6):
        if re.search(r"amazon\.com(\.br)?/", url):  # chegou na Amazon: o ASIN está no próprio endereço
            m = ASIN_RE.search(url)
            return m.group(1) if m else None

        class SemSeguir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        try:
            resp = urllib.request.build_opener(SemSeguir).open(urllib.request.Request(url, headers=NAVEGADOR), timeout=20)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            return None
        html = resp.read(2_000_000).decode("utf-8", "ignore")
        m = ASIN_RE.search(html)
        return m.group(1) if m else None
    return None


def link_amazon(asin):
    return f"https://www.amazon.com.br/dp/{asin}?tag={AMAZON_TAG}"


def montar_post(oferta, asin):
    linhas = [f"🔥 {oferta.titulo}"]
    if oferta.preco_por:
        linhas.append(f"💰 por {brl(oferta.preco_por)} (preço no momento da postagem)")
        if CONDICAO_RE.search(oferta.texto_original):
            linhas.append("ℹ️ Preço com condição (recorrência, parcelas ou quantidade): confira na página")
    if oferta.cupom:
        linhas.append(f"🎟️ Cupom: {oferta.cupom}")
    linhas.append(f"🛒 Amazon 👉 {link_amazon(asin)}")
    linhas.append("⚠️ Preço e estoque podem mudar a qualquer momento")
    return "\n".join(linhas)


def carregar_vistos():
    try:
        return set(json.loads(VISTOS_ARQ.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


async def processar(client, canal, msg, vistos, enviar):
    texto = msg.message or ""
    if not eh_amazon(texto):
        return
    oferta = montar_oferta(texto)
    if not eh_de_bebe(oferta, canal):
        return
    links = LINK_RE.findall(texto) + [e.url for e in (msg.entities or []) if getattr(e, "url", None)]
    asin = next((a for a in (descobrir_asin(l) for l in links[:2]) if a), None)
    if not asin:
        print(f"[@{canal}] bebê, mas sem ASIN: {oferta.titulo[:60]}")
        return
    if asin in vistos:
        return
    post = montar_post(oferta, asin)
    if not enviar:
        print(f"[@{canal}] {asin} -> {post.splitlines()[0][:70]}")
        return
    if msg.photo and canal not in FONTES_SO_BEBE:
        await radar.enviar_com_foto(client, radar.DESTINO, msg, post)
    else:
        await client.send_message(radar.DESTINO, post, link_preview=True)  # foto vem da prévia do link
    vistos.add(asin)
    VISTOS_ARQ.write_text(json.dumps(sorted(vistos)), encoding="utf-8")
    print(f"[@{canal}] postado {asin}: {oferta.titulo[:60]}", flush=True)


async def rodada(client, enviar):
    vistos = carregar_vistos()
    for canal in FONTES:
        arq = radar.DADOS / f"ultimo_id_{canal}.txt"
        try:
            ultimo = int(arq.read_text().strip())
        except (FileNotFoundError, ValueError):
            recente = await client.get_messages(canal, limit=1)
            if recente and enviar:
                arq.write_text(str(recente[0].id))
            print(f"[@{canal}] primeira rodada: ponto de partida marcado.")
            continue
        novos = 0
        async for msg in client.iter_messages(canal, min_id=ultimo, reverse=True):
            novos += 1
            await processar(client, canal, msg, vistos, enviar)
            if enviar:
                arq.write_text(str(msg.id))
        print(f"[@{canal}] {novos} posts novos lidos.", flush=True)


async def demo(client, quantidade):
    """Teste de envio: posta N ofertas recentes da Amazon de QUALQUER categoria.
    Não marca nada como visto. Use com DESTINO apontando para o canal de teste."""
    enviados = 0
    for canal in FONTES:
        async for msg in client.iter_messages(canal, limit=60):
            texto = msg.message or ""
            if not eh_amazon(texto):
                continue
            links = LINK_RE.findall(texto) + [e.url for e in (msg.entities or []) if getattr(e, "url", None)]
            asin = next((a for a in (descobrir_asin(l) for l in links[:2]) if a), None)
            if not asin:
                continue
            post = montar_post(montar_oferta(texto), asin)
            if msg.photo:
                await radar.enviar_com_foto(client, radar.DESTINO, msg, post)
            else:
                await client.send_message(radar.DESTINO, post, link_preview=True)
            enviados += 1
            print(f"[{enviados}] @{canal} {asin}: {post.splitlines()[0][:70]}", flush=True)
            if enviados >= quantidade:
                return
            await asyncio.sleep(5)


async def teste(client, quantidade):
    vistos = set()
    for canal in FONTES:
        print(f"== @{canal}")
        async for msg in client.iter_messages(canal, limit=quantidade):
            await processar(client, canal, msg, vistos, enviar=False)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rodada", action="store_true")
    ap.add_argument("--teste", type=int, metavar="N")
    ap.add_argument("--demo", type=int, metavar="N", help="envia N ofertas de qualquer categoria (teste de envio)")
    args = ap.parse_args()
    if args.demo and not AMAZON_TAG:
        raise SystemExit("Preencha AMAZON_TAG antes do teste de envio.")

    enviar = bool(args.rodada and AMAZON_TAG)
    if args.rodada and not AMAZON_TAG:
        print("AMAZON_TAG vazia: rodando só em simulação (nada é postado).")

    client = radar.criar_cliente(copia="amazon")
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Telegram sem login: gere a TG_SESSION")
    await client.get_dialogs()
    if args.demo:
        await demo(client, args.demo)
    elif args.teste:
        await teste(client, args.teste)
    else:
        await rodada(client, enviar)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
