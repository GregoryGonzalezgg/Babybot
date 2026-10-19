"""Curadoria das ofertas de bebê do feed de produtos da Shopee.

Lê o CSV do feed, filtra Mãe & Bebê e Moda Infantil, pontua por desconto,
nota e curtidas, REMOVE PRODUTOS REPETIDOS (mesmo produto anunciado mais de
uma vez) e grava curadoria_shopee_baby.csv. Links de afiliado já gerados
numa curadoria anterior são mantidos.

Uso: python curadoria_shopee.py caminho/do/feed.csv [--total 100]
"""
import argparse
import csv
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

PASTA = Path(__file__).parent
SAIDA = PASTA / "listas" / "curadoria_shopee_baby.csv"

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


def carregar_candidatos(caminho_feed):
    csv.field_size_limit(10**8)
    candidatos = []
    with open(caminho_feed, encoding="utf-8-sig", errors="surrogateescape", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["global_category1"] not in CATEGORIAS:
                continue
            r = {k: corrigir(v) for k, v in r.items()}
            d, nota, likes = num(r["discount_percentage"]), num(r["item_rating"]), num(r["like"])
            if d < 25 or nota < 4.7 or likes < 30 or num(r["shop_rating"]) < 4.6 or num(r["sale_price"]) < 8:
                continue
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
    candidatos.sort(key=lambda r: -r["_nota"])
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--total", type=int, default=100)
    args = ap.parse_args()

    candidatos = carregar_candidatos(args.feed)
    escolhidos, repetidos = selecionar(candidatos, args.total)
    links = links_existentes()

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
