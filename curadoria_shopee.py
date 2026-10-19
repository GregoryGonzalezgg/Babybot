"""Curadoria das ofertas de bebê do feed de produtos da Shopee.

Lê o CSV do feed, filtra Mãe & Bebê e Moda Infantil, pontua por desconto,
nota e curtidas, REMOVE PRODUTOS REPETIDOS (mesmo produto anunciado mais de
uma vez) e grava curadoria_shopee_baby.csv. Links de afiliado já gerados
numa curadoria anterior são mantidos.

Produtos que já foram postados ficam de fora; produtos sem link do portal
ganham o link de afiliado montado com SHOPEE_AFILIADO_ID.

Uso:
  python curadoria_shopee.py                    -> baixa os feeds (SHOPEE_FEED_URLS) e refaz a lista
  python curadoria_shopee.py --se-faltar 15     -> só refaz se restarem menos de 15 ofertas (uso diário)
  python curadoria_shopee.py feed1.csv feed2.csv -> usa CSVs já baixados
"""
import argparse
import csv
import json
import math
import os
import re
import shutil
import tempfile
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

PASTA = Path(__file__).parent
load_dotenv(PASTA / ".env")
SAIDA = PASTA / "listas" / "curadoria_shopee_baby.csv"
ARQ_POSTADOS = Path(os.getenv("DADOS_DIR") or PASTA / "dados") / "postados_shopee.json"
# links fixos dos CSVs em Criativo > Feed de produto, separados por vírgula
FEED_URLS = os.getenv("SHOPEE_FEED_URLS", "")
# seu ID de afiliado (aparece como utm_source=an_<ID> nos seus links) e a etiqueta de rastreio
AFILIADO_ID = os.getenv("SHOPEE_AFILIADO_ID", "").strip()
SUB_ID = os.getenv("SHOPEE_SUB_ID", "totuxababy").strip()

PT = {"Toys": "Brinquedos", "Girl Shoes": "Calçados menina", "Girl Clothes": "Roupas menina",
      "Boy Shoes": "Calçados menino", "Boy Clothes": "Roupas menino", "Nursery": "Quarto do bebê",
      "Bath & Body Care": "Banho e cuidados", "Baby & Kids Accessories": "Acessórios infantis",
      "Feeding Essentials": "Alimentação", "Diapering & Potty": "Fraldas e penico",
      "Baby Clothes": "Roupas de bebê", "Baby Travel Essentials": "Passeio (carrinho, bebê conforto)",
      "Baby Healthcare": "Saúde do bebê", "Milk Formula & Baby Food": "Leite e papinha",
      "Baby Safety": "Segurança do bebê", "Others": "Outros", "Baby Mittens & Footwear": "Luvas e sapatinhos",
      "Maternity Accessories": "Maternidade", "Maternity Healthcare": "Saúde da gestante"}
CATEGORIAS = ("Mom & Baby", "Baby & Kids Fashion")
SEMPRE_INFANTIS = ("Toys", "Nursery", "Feeding Essentials", "Diapering & Potty",
                   "Baby Travel Essentials", "Bath & Body Care")
KIDS = re.compile(r"\b(infantil|infantis|bebe|bebes|baby|kids|crianca|criancas|menino|menina|juvenil|"
                  r"recem|maternidade|toddler|kid|nenem)\b")
ADULTO = re.compile(r"\b(masculino|feminino|adulto)\b")
# palavras que não ajudam a diferenciar um produto de outro
VAZIAS = {"de", "da", "do", "com", "para", "e", "o", "a", "em", "infantil", "menino", "menina", "masculino",
          "feminino", "bebe", "kit", "tenis", "unissex", "original", "promocao", "novo", "nova", "ou"}
MAX_POR_SUBCATEGORIA = 12

# ---- faixa etária: só bebê e criança pequena (0 a 5 anos) ----
IDADE_MAXIMA = 5
# subcategorias que já são de bebê por natureza
SUB_BEBE = {"Baby Clothes", "Feeding Essentials", "Diapering & Potty", "Bath & Body Care", "Nursery",
            "Baby Travel Essentials", "Baby Healthcare", "Baby Safety", "Baby Mittens & Footwear",
            "Milk Formula & Baby Food", "Maternity Accessories", "Maternity Healthcare"}
# nas outras (brinquedos, roupas e calçados infantis), o título precisa indicar bebê/criança pequena
BEBE = re.compile(r"\b(bebe|bebes|baby|recem nascido|recem-nascido|rn|meses|newborn|toddler|primeiros passos|"
                  r"maternidade|nenem|berco|mordedor|chocalho|montessori|primeira infancia|infancia)\b")
# produtos de criança maior ou que não combinam com o nicho
CRIANCA_MAIOR = re.compile(r"\b(juvenil|teen|adolescente|escolar|reborn|patinete|bicicleta|skate|patins|"
                           r"cama elastica|trampolim|pula pula|slime|micangas?|maquiagem|parque aquatico|"
                           r"videogame|celular|lol surprise|barbie|hot wheels|pistola|arma|"
                           r"adulto|adulta|women|men|mulher|mulheres|homem)\b")
FAIXA_ANOS = re.compile(r"(\d{1,2})\s*(?:a|ao|-|ate)\s*(\d{1,2})\s*anos")
IDADE_MINIMA = re.compile(r"(?:\+|acima de |a partir de )(\d{1,2})\s*anos|(\d{1,2})\+\s*anos")
NUMERACAO = re.compile(r"\b(\d{2})\s*(?:a|ao|-|/)\s*(\d{2})\b")


def para_ate_5_anos(r):
    """True se o produto é para bebê ou criança de até 5 anos."""
    t = normalizar(r["title"])
    if CRIANCA_MAIOR.search(t):
        return False
    for ini, fim in FAIXA_ANOS.findall(t):
        ini, fim = int(ini), int(fim)
        if ini > IDADE_MAXIMA or fim >= 8:  # "6 a 10 anos", "1 a 12 anos" (patinete)
            return False
    for a, b in IDADE_MINIMA.findall(t):
        if int(a or b) > IDADE_MAXIMA:
            return False
    sub = r["global_category2"]
    if "Shoes" in sub:
        # numeração brasileira: até ~27 é bebê/criança pequena; "20 ao 36" ou "28 a 35" é criança maior
        for ini, fim in NUMERACAO.findall(t):
            ini, fim = int(ini), int(fim)
            if 14 <= ini <= 40 and (ini >= 26 or fim >= 32):
                return False
    if sub in SUB_BEBE:
        return True
    return bool(BEBE.search(t) or any(int(f) <= IDADE_MAXIMA for _, f in FAIXA_ANOS.findall(t)))


def corrigir(texto):
    # o feed mistura UTF-8 com textos em Latin-1; esses viram "surrogates" na leitura
    try:
        texto.encode("utf-8")
        return texto
    except UnicodeEncodeError:
        return texto.encode("utf-8", "surrogateescape").decode("cp1252", "replace")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def normalizar(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def palavras_chave(titulo):
    return {p for p in re.findall(r"[a-z0-9]+", normalizar(titulo)) if len(p) > 2 and p not in VAZIAS}


def mesmo_produto(a, b):
    """Dois anúncios são o mesmo produto se quase todas as palavras do título mais
    curto aparecem no outro. Na mesma loja a régua é mais baixa: lojas repetem o
    anúncio com outro título (ex.: "Tênis LED Aranha" duas vezes na Club Happy)."""
    pa, pb = a["_chave"], b["_chave"]
    if a["shop_name"] == b["shop_name"]:
        loja = palavras_chave(a["shop_name"])
        pa, pb = pa - loja, pb - loja
    if len(pa) < 2 or len(pb) < 2:
        return False
    contidas = len(pa & pb) / min(len(pa), len(pb))
    return contidas >= (0.75 if a["shop_name"] == b["shop_name"] else 0.9)


def carregar_candidatos(caminhos_feed, ignorar=()):
    """Lê um ou mais CSVs do feed. `ignorar` = IDs de produtos que não devem entrar
    (os que já foram postados), para a lista nova trazer só ofertas inéditas."""
    csv.field_size_limit(10**8)
    candidatos, vistos = [], set(ignorar)
    for caminho_feed in caminhos_feed:
        candidatos += _ler_feed(caminho_feed, vistos)
    candidatos.sort(key=lambda r: -r["_nota"])
    return candidatos


def _ler_feed(caminho_feed, vistos):
    candidatos = []
    with open(caminho_feed, encoding="utf-8-sig", errors="surrogateescape", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["global_category1"] not in CATEGORIAS or r["itemid"] in vistos:
                continue
            vistos.add(r["itemid"])  # o mesmo produto pode vir nos dois feeds
            r = {k: corrigir(v or "") for k, v in r.items()}
            # o feed menor ("Shopee Brasil") não traz curtidas nem dados da loja
            tem_popularidade = "like" in r
            r.setdefault("shop_name", "")
            r.setdefault("shop_rating", "")
            r.setdefault("like", "")
            if not para_ate_5_anos(r):
                continue
            d, nota, likes = num(r["discount_percentage"]), num(r["item_rating"]), num(r["like"])
            if d < 25 or nota < 4.7 or num(r["sale_price"]) < 8:
                continue
            if tem_popularidade and (likes < 30 or num(r["shop_rating"]) < 4.6):
                continue
            if not tem_popularidade:
                likes = 100  # sem o dado, conta como popularidade média (não ganha nem perde)
            t = normalizar(r["title"])
            alerta = []
            if not KIDS.search(t) and r["global_category2"] not in SEMPRE_INFANTIS:
                alerta.append("conferir se é infantil")
            if ADULTO.search(t) and not KIDS.search(t):
                alerta.append("parece produto adulto")
            if d >= 70:
                alerta.append("desconto alto: conferir preço 'de'")
            # desconto conta até 60% para não premiar preço "de" inflado
            nota_final = min(d, 60) / 60 * 0.45 + min(math.log10(likes + 1) / 4, 1) * 0.35 + (nota - 4.7) / 0.3 * 0.2
            if alerta:
                nota_final -= 0.25
            r["_nota"], r["_alerta"], r["_chave"] = nota_final, alerta, palavras_chave(r["title"])
            candidatos.append(r)
    return candidatos


def selecionar(candidatos, total):
    escolhidos, repetidos = [], 0
    por_sub = defaultdict(int)
    for r in candidatos:
        if por_sub[r["global_category2"]] >= MAX_POR_SUBCATEGORIA:
            continue
        if any(mesmo_produto(r, e) for e in escolhidos):
            repetidos += 1
            continue
        por_sub[r["global_category2"]] += 1
        escolhidos.append(r)
        if len(escolhidos) >= total:
            break
    return escolhidos, repetidos


def links_existentes():
    if not SAIDA.exists():
        return {}
    with open(SAIDA, encoding="utf-8-sig") as f:
        return {l["link_produto"]: l.get("meu_link_afiliado", "") for l in csv.DictReader(f, delimiter=";")}


def link_afiliado(link_produto):
    """Monta o link de afiliado direto, sem passar pelo portal (mesmo rastreio dos links
    gerados em "Link personalizado": utm_medium=affiliates + seu ID + Sub_id)."""
    if not AFILIADO_ID:
        return ""
    return ("https://s.shopee.com.br/an_redir?origin_link=" + quote(link_produto, safe="")
            + f"&affiliate_id={AFILIADO_ID}&sub_id={SUB_ID}")


def carregar_postados():
    try:
        return set(json.loads(ARQ_POSTADOS.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def restantes_na_lista(postados):
    if not SAIDA.exists():
        return 0
    with open(SAIDA, encoding="utf-8-sig") as f:
        return sum(1 for l in csv.DictReader(f, delimiter=";")
                   if l["link_produto"].rstrip("/").split("/")[-1] not in postados)


def baixar_feeds(pasta):
    """Baixa os CSVs do feed oficial (links fixos de Criativo > Feed de produto)."""
    caminhos = []
    for i, url in enumerate(u.strip() for u in FEED_URLS.split(",") if u.strip()):
        destino = Path(pasta) / f"feed_{i + 1}.csv"
        print(f"baixando feed {i + 1}...", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=600) as r, open(destino, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 1024)
        caminhos.append(destino)
    return caminhos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feeds", nargs="*", help="CSVs já baixados; sem isso, baixa de SHOPEE_FEED_URLS")
    ap.add_argument("--total", type=int, default=100)
    ap.add_argument("--se-faltar", type=int, metavar="N",
                    help="só refaz a lista se restarem menos de N ofertas ainda não postadas")
    args = ap.parse_args()

    postados = carregar_postados()
    if args.se_faltar is not None:
        restam = restantes_na_lista(postados)
        if restam >= args.se_faltar:
            print(f"Lista da Shopee ok: {restam} ofertas ainda não postadas (mínimo {args.se_faltar}).")
            return
        print(f"Restam só {restam} ofertas: renovando a lista.", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        feeds = args.feeds or baixar_feeds(tmp)
        if not feeds:
            raise SystemExit("Nenhum feed: passe o CSV ou preencha SHOPEE_FEED_URLS no .env")
        candidatos = carregar_candidatos(feeds, ignorar=postados)
    escolhidos, repetidos = selecionar(candidatos, args.total)
    links = links_existentes()
    for r in escolhidos:  # sem link do portal: monta o link de afiliado
        links[r["product_link"]] = links.get(r["product_link"]) or link_afiliado(r["product_link"])

    campos = ["rank", "nota_curadoria", "subcategoria", "produto", "preco_de", "preco_por", "desconto_%", "nota",
              "curtidas", "loja", "nota_loja", "alerta", "meu_link_afiliado", "foto", "link_produto"]
    with open(SAIDA, "w", encoding="utf-8-sig", newline="") as out:
        w = csv.writer(out, delimiter=";")
        w.writerow(campos)
        for i, r in enumerate(escolhidos, 1):
            w.writerow([i, round(r["_nota"] * 100), PT.get(r["global_category2"], r["global_category2"]), r["title"],
                        r["price"].replace(".", ","), r["sale_price"].replace(".", ","),
                        int(num(r["discount_percentage"])), r["item_rating"], int(num(r["like"])), r["shop_name"],
                        r["shop_rating"], "; ".join(r["_alerta"]), links.get(r["product_link"], ""),
                        r["image_link"], r["product_link"]])
    sem_link = sum(1 for r in escolhidos if not links.get(r["product_link"]))
    print(f"{len(candidatos)} candidatos | {repetidos} repetidos descartados | {len(escolhidos)} na planilha "
          f"| {sem_link} ainda sem link de afiliado")


if __name__ == "__main__":
    main()
