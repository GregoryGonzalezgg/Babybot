"""Radar de ofertas da Magalu.

Lê o canal oficial da Magalu no Telegram (com a SUA conta), troca o ID do
produto pelo link da SUA loja Parceiro Magalu e monta o post no seu padrão.

Uso:
  python radar.py              -> fica ouvindo o canal e processa cada post novo
  python radar.py --teste 10   -> só mostra o que extraiu dos últimos 10 posts (não envia nada)
"""
import argparse
import asyncio
import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from nicho import classificar
from parser_magalu import brl, extrair

PASTA = Path(__file__).parent
load_dotenv(PASTA / ".env")

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
CANAL_ORIGEM = os.getenv("CANAL_ORIGEM", "")
if CANAL_ORIGEM.lstrip("-").isdigit():  # canal sem @ vem como ID numérico
    CANAL_ORIGEM = int(CANAL_ORIGEM)
LOJA = os.getenv("LOJA_MAGALU", "")
LINK_TEMPLATE = os.getenv(
    "LINK_TEMPLATE", "https://www.magazinevoce.com.br/magazine{loja}/p/{id}/"
)
DESTINO = os.getenv("DESTINO", "me")  # "me" = suas Mensagens Salvas (modo aprovação)
if DESTINO.lstrip("-").isdigit():  # canal privado vem como ID numérico (-100...)
    DESTINO = int(DESTINO)
DESCONTO_MINIMO = int(os.getenv("DESCONTO_MINIMO", "0"))
NICHO = os.getenv("NICHO", "baby").strip().lower()  # "baby" ou vazio para todas as ofertas
ID_REGEX = os.getenv("ID_REGEX") or None
MAX_LINKS = 3

# tudo que o radar grava fica em dados/ (fora do Git); na VM pode apontar para outro lugar
DADOS = Path(os.getenv("DADOS_DIR") or PASTA / "dados")
DADOS.mkdir(parents=True, exist_ok=True)
VISTOS_ARQ = DADOS / "vistos.json"
FILA_WHATSAPP = DADOS / "fila_whatsapp.csv"
PASTA_FOTOS = DADOS / "fotos"
# login do Telegram: na nuvem vem da variável TG_SESSION (gerada com gerar_sessao.py);
# no PC, do arquivo sessao_radar.session
TG_SESSION = os.getenv("TG_SESSION", "").strip()
ARQ_SESSAO = PASTA / "sessao_radar"


def criar_cliente(copia=None):
    """Cliente do Telegram. `copia` cria uma cópia do arquivo de sessão para um segundo
    programa rodar junto com o radar sem travar o arquivo (não precisa com TG_SESSION)."""
    if TG_SESSION:
        return TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
    sessao = ARQ_SESSAO
    if copia:
        shutil.copyfile(f"{ARQ_SESSAO}.session", f"{ARQ_SESSAO}_{copia}.session")
        sessao = Path(f"{ARQ_SESSAO}_{copia}")
    return TelegramClient(str(sessao), API_ID, API_HASH)


def link_parceiro(item_id):
    return LINK_TEMPLATE.format(loja=LOJA, id=item_id)


def filtrar(oferta):
    """Retorna "sim", "nao" ou "verificar" (ver nicho.py)."""
    if oferta.tipo == "outro":
        return "nao"
    if DESCONTO_MINIMO and oferta.preco_por and (oferta.desconto or 0) < DESCONTO_MINIMO:
        return "nao"
    if NICHO != "baby":
        return "sim"
    return classificar(oferta)


def montar_verificacao(oferta):
    """Post só com códigos: vai para você abrir os links e decidir."""
    linhas = ["❓ CONFIRA SE É DE BEBÊ (post só com códigos, sem nome do produto)",
              f"Cupom: {oferta.cupom}" if oferta.cupom else "",
              (oferta.chamada or oferta.titulo or "")]
    linhas += [f"• {item_id}: {link_parceiro(item_id)}" for item_id in oferta.ids[:20]]
    if len(oferta.ids) > 20:
        linhas.append(f"... e mais {len(oferta.ids) - 20} códigos")
    linhas.append("Se algum for de bebê, coloque o código em codigos_baby.txt")
    return "\n".join(l for l in linhas if l)


def loja_home():
    return LINK_TEMPLATE.split("/p/")[0].format(loja=LOJA)


def montar_post_cupom(oferta):
    """Post de campanha: cupom + lista de códigos, sem nome de produto nem preço."""
    n = len(oferta.ids)
    linhas = [f"🎟️ CUPOM: {oferta.cupom}"]
    if oferta.chamada:
        linhas.append(f"🔥 {oferta.chamada}")
    else:
        # a frase do post costuma ser só empolgação ("E BORA APROVEITAR"), então descrevemos
        linhas.append(f"🔥 Desconto em {n} produto{'s' if n > 1 else ''} selecionado{'s' if n > 1 else ''}")
    for item_id in oferta.ids[:MAX_LINKS]:
        linhas.append(f"👉 {link_parceiro(item_id)}")
    if n > MAX_LINKS:
        linhas.append(f"➕ e mais {n - MAX_LINKS} produtos participantes")
        linhas.append(f"🛒 Veja tudo na minha loja: {loja_home()}")
    linhas.append("⚠️ Cupom por tempo limitado, aplique no carrinho")
    return "\n".join(linhas)


def montar_post(oferta):
    linhas = []
    if oferta.ids and oferta.cupom and not oferta.preco_por:
        return montar_post_cupom(oferta)
    if oferta.tipo == "cupom" and not oferta.ids:
        linhas.append("🎟️ CUPOM MAGALU")
        linhas.append(f"Código: {oferta.cupom}")
        if oferta.titulo:
            linhas.append(oferta.titulo)
        if LOJA:
            linhas.append(f"👉 Use na minha loja: {LINK_TEMPLATE.split('/p/')[0].format(loja=LOJA)}")
    else:
        titulo = oferta.chamada or oferta.titulo or "Oferta Magalu"
        if oferta.preco_de and oferta.preco_por and oferta.preco_de > oferta.preco_por:
            preco = f"de {brl(oferta.preco_de)} por {brl(oferta.preco_por)}"
            if oferta.desconto:
                preco += f" (-{oferta.desconto}%)"
        elif oferta.preco_por:
            preco = f"por {brl(oferta.preco_por)}"
        else:
            preco = ""
        if preco and oferta.pix:
            preco += " no Pix"
        linhas.append(f"🔥 {titulo}")
        if preco:
            linhas.append(f"💰 {preco}")
        if oferta.parcelas:
            linhas.append(f"💳 ou {oferta.parcelas}")
        if "frete grátis" in oferta.texto_original.lower():
            linhas.append("🚚 Frete grátis (consulte seu CEP)")
        if oferta.cupom:
            linhas.append(f"🎟️ Cupom: {oferta.cupom}")
        # campanhas trazem dezenas de modelos; post com muitos links espanta o leitor
        for item_id in oferta.ids[:MAX_LINKS]:
            linhas.append(f"👉 {link_parceiro(item_id)}")
        if len(oferta.ids) > MAX_LINKS:
            linhas.append(f"➕ e mais {len(oferta.ids) - MAX_LINKS} modelos com o mesmo desconto")
    linhas.append("⚠️ Preço e estoque podem mudar a qualquer momento")
    return "\n".join(linhas)


def carregar_vistos():
    try:
        return set(json.loads(VISTOS_ARQ.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def salvar_vistos(vistos):
    VISTOS_ARQ.write_text(json.dumps(sorted(vistos)[-5000:]), encoding="utf-8")


def anotar_fila(post, oferta, foto=""):
    novo = not FILA_WHATSAPP.exists()
    with FILA_WHATSAPP.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["data", "tipo", "ids", "cupom", "foto", "post"])
        w.writerow([datetime.now().strftime("%d/%m %H:%M"), oferta.tipo,
                    " ".join(oferta.ids), oferta.cupom or "", foto, post])


LIMITE_LEGENDA = 1024  # o Telegram corta legendas de foto maiores que isso


async def enviar_com_foto(client, destino, msg, texto):
    try:
        if msg.photo and len(texto) <= LIMITE_LEGENDA:
            await client.send_file(destino, msg.photo, caption=texto)
            return
        if msg.photo:  # texto longo: foto primeiro, texto em seguida
            await client.send_file(destino, msg.photo)
    except Exception as erro:  # canal com cópia bloqueada, etc.: envia só o texto
        print(f"[aviso] não consegui reenviar a imagem ({erro}); enviando só texto")
    await client.send_message(destino, texto, link_preview=not msg.photo)


async def baixar_foto(msg, chave):
    """Salva a foto em fotos/ para você anexar no WhatsApp."""
    if not msg.photo:
        return ""
    PASTA_FOTOS.mkdir(exist_ok=True)
    nome = f"{datetime.now():%Y%m%d_%H%M}_{chave.split()[0] if chave else msg.id}.jpg"
    try:
        caminho = await msg.download_media(file=str(PASTA_FOTOS / nome))
        return Path(caminho).name
    except Exception as erro:
        print(f"[aviso] não consegui salvar a foto ({erro})")
        return ""


async def processar(client, msg, vistos):
    oferta = extrair(msg.message or "", ID_REGEX)
    chave = " ".join(oferta.ids) or oferta.cupom or ""
    decisao = filtrar(oferta)
    if decisao == "nao" or chave in vistos:
        return
    if decisao == "verificar":
        # sempre só para você (Mensagens Salvas), nunca direto no canal;
        # a foto ajuda a decidir se é de bebê
        await enviar_com_foto(client, "me", msg, montar_verificacao(oferta))
        vistos.add(chave)
        salvar_vistos(vistos)
        print(f"[{datetime.now():%H:%M:%S}] para conferir: {len(oferta.ids)} códigos")
        return
    post = montar_post(oferta)
    await enviar_com_foto(client, DESTINO, msg, post)
    foto = await baixar_foto(msg, chave)
    anotar_fila(post, oferta, foto)
    vistos.add(chave)
    salvar_vistos(vistos)
    print(f"[{datetime.now():%H:%M:%S}] enviado: {oferta.titulo or chave}")


async def modo_demo(client, quantidade, enviar=True):
    """Demonstração: varre os posts recentes e envia os N primeiros válidos,
    de QUALQUER nicho. Não muda o .env, não marca como visto e não entra na fila."""
    lidos = validos = 0
    async for msg in client.iter_messages(CANAL_ORIGEM, limit=50):
        lidos += 1
        oferta = extrair(msg.message or "", ID_REGEX)
        if oferta.tipo == "outro" or (oferta.ids and not oferta.preco_por and not oferta.cupom):
            continue
        validos += 1
        print(f"[varredura] post {lidos}: {(oferta.chamada or oferta.titulo)[:70]}")
        if enviar:
            await enviar_com_foto(client, DESTINO, msg, montar_post(oferta))
            await asyncio.sleep(3)  # intervalo entre envios
        if validos >= quantidade:
            break
    print(f"Demo concluída: {lidos} posts lidos, {validos} {'enviados' if enviar else 'seriam enviados'} para {DESTINO}.")


async def modo_teste(client, quantidade):
    async for msg in client.iter_messages(CANAL_ORIGEM, limit=quantidade):
        oferta = extrair(msg.message or "", ID_REGEX)
        print("=" * 60)
        print(f"POST ORIGINAL ({msg.date:%d/%m %H:%M}):\n{(msg.message or '')[:400]}")
        print("-" * 60)
        print(f"tipo={oferta.tipo} ids={oferta.ids} de={oferta.preco_de} "
              f"por={oferta.preco_por} desc={oferta.desconto} cupom={oferta.cupom}")
        decisao = filtrar(oferta)
        print(f"nicho {NICHO or 'todos'}: {decisao}")
        if decisao != "nao":
            print("-" * 60)
            print(montar_verificacao(oferta) if decisao == "verificar" else montar_post(oferta))


def pedir_telefone():
    while True:
        tel = "".join(c for c in input("Seu telefone com +55 e DDD (ex.: +5511999998888): ") if c.isdigit() or c == "+")
        if tel.startswith("+55") and len(tel) >= 13:
            return tel
        print("Formato inválido: comece com +55, depois DDD e número.")


def pedir_codigo():
    print("O código (5 números) chegou no APP do Telegram, numa mensagem da conta oficial 'Telegram'.")
    return input("Código: ").strip()


async def procurar_canal(client, nome):
    """Procura entre os canais/grupos em que você está inscrito e mostra os últimos posts."""
    achados = [d async for d in client.iter_dialogs() if nome.lower() in (d.name or "").lower()]
    if not achados:
        print(f"Nenhum canal com '{nome}' no nome. Confira se sua conta está inscrita nele.")
        return
    for d in achados:
        usuario = getattr(d.entity, "username", None)
        print("=" * 60)
        print(f"Canal: {d.name}")
        print(f"Para o .env -> CANAL_ORIGEM={'@' + usuario if usuario else d.id}")
        async for msg in client.iter_messages(d.entity, limit=3):
            print("-" * 60)
            print(f"({msg.date:%d/%m %H:%M}) {(msg.message or '[sem texto / só mídia]')[:300]}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", type=int, metavar="N", help="mostra a extração dos últimos N posts")
    ap.add_argument("--procurar", metavar="NOME", help="acha um canal pelo nome e mostra os últimos posts")
    ap.add_argument("--demo", type=int, metavar="N", help="demonstração: envia N ofertas recentes de qualquer nicho")
    ap.add_argument("--simular", action="store_true", help="com --demo: mostra o que faria, sem enviar")
    args = ap.parse_args()

    if not API_ID or not API_HASH or not (CANAL_ORIGEM or args.procurar):
        raise SystemExit("Preencha API_ID, API_HASH e CANAL_ORIGEM no arquivo .env (veja LEIA-ME.md)")

    client = criar_cliente(copia="demo" if args.demo else None)
    if TG_SESSION:
        await client.connect()  # na nuvem não tem como digitar código: a sessão já vem pronta
        if not await client.is_user_authorized():
            raise SystemExit("TG_SESSION inválida ou expirada: gere de novo com gerar_sessao.py")
    else:
        # na 1ª vez pede seu telefone e o código do Telegram
        await client.start(phone=pedir_telefone, code_callback=pedir_codigo)

    if args.procurar:
        await procurar_canal(client, args.procurar)
        return

    await client.get_dialogs()  # carrega os canais para aceitar CANAL_ORIGEM numérico

    if args.demo:
        await modo_demo(client, args.demo, enviar=not args.simular)
        return

    if args.teste:
        await modo_teste(client, args.teste)
        return

    if not LOJA:
        print("[aviso] LOJA_MAGALU vazio no .env: os links não terão sua loja!")

    vistos = carregar_vistos()

    @client.on(events.NewMessage(chats=CANAL_ORIGEM))
    async def novo_post(event):
        await processar(client, event.message, vistos)

    print(f"Radar ligado. Ouvindo {CANAL_ORIGEM} -> enviando para {DESTINO}. Ctrl+C para parar.", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
