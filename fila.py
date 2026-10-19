"""Fila de ofertas: as fontes (Magalu, Amazon, Shopee) colocam ofertas aqui, cada uma com
uma NOTA DE VANTAGEM para o cliente, e o publicar.py posta a melhor a cada 5 minutos.

Nota de vantagem (0 a 100):
  - Fralda e lenço: preço por unidade comparado com um preço de referência por tamanho
    (ex.: fralda G a R$ 0,80/un quando o normal é ~R$ 1,05 = muito vantajoso)
  - Outros produtos: desconto (preço "de" x "por"), cupom e nota/curtidas da Shopee
  - Ofertas de Magalu e Amazon perdem pontos com o tempo (promoção acaba rápido)
    e são descartadas depois de VALIDADE_MIN minutos
"""
import json
import os
import re
import time
import unicodedata
from pathlib import Path

PASTA = Path(__file__).parent
DADOS = Path(os.getenv("DADOS_DIR") or PASTA / "dados")
DADOS.mkdir(parents=True, exist_ok=True)
ARQ = DADOS / "fila.json"
VALIDADE_MIN = int(os.getenv("VALIDADE_MIN", "180"))  # ofertas com mais de 3 h saem da fila

# preço "normal" por unidade (R$) por tamanho; abaixo disso é vantagem para o cliente
REF_FRALDA = {"rn": 0.80, "p": 0.85, "m": 0.95, "g": 1.05, "xg": 1.15, "xxg": 1.25, "xxxg": 1.35}
REF_FRALDA_PADRAO = 1.05
REF_LENCO = 0.25  # lenço umedecido, R$ por folha (pacote de 48 a ~R$ 12)

UNID_RE = re.compile(r"(?:leve\s+)?(\d{2,4})\s*(?:unidades|unid|und|un\b|fraldas|tiras|pads|folhas|lencos)",
                     re.IGNORECASE)
PRECO_UN_RE = re.compile(r"\(\s*(?:r\$\s*)?(\d+,\d{2})\s*(?:/|a|por)\s*unidade", re.IGNORECASE)
TAMANHO_RE = re.compile(r"\b(rn|p|m|g|xg|xxg|xxxg)\b")


def _norm(t):
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def preco_por_unidade(texto, preco):
    """Usa o 'R$ X / unidade' da fonte quando houver; senão divide o preço pelas unidades."""
    m = PRECO_UN_RE.search(texto or "")
    if m:
        return float(m.group(1).replace(",", "."))
    m = UNID_RE.search(_norm(texto))
    if m and preco:
        return preco / int(m.group(1))
    return None


def nota_vantagem(titulo, texto="", preco=None, preco_de=None, cupom=None, extra=0.0):
    t = _norm(titulo)
    nota = 50.0
    eh_fralda, eh_lenco = "fralda" in t, ("lenco" in t or "toalhinha" in t)
    if (eh_fralda or eh_lenco) and preco:
        un = preco_por_unidade(texto or titulo, preco)
        if un:
            if eh_fralda:
                tam = TAMANHO_RE.search(t)
                ref = REF_FRALDA.get(tam.group(1) if tam else "", REF_FRALDA_PADRAO)
            else:
                ref = REF_LENCO
            # 30% abaixo da referência = nota ~95; no preço normal = 50; bem acima = no mínimo 20
            nota = max(20.0, 50 + (ref - un) / ref * 150)
        nota += 5  # item de compra recorrente: interessa a quase todo seguidor
    elif preco_de and preco and preco_de > preco:
        desconto = (1 - preco / preco_de) * 100
        # "de/por" vale menos que preço por unidade: lojas costumam inflar o preço "de".
        # 60% ou mais de desconto = 74 (teto); 30% = 56
        nota = 38 + min(desconto, 60) * 0.6
    if cupom:
        nota += 5
    return max(0.0, min(100.0, nota + extra))


def carregar():
    try:
        return json.loads(ARQ.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"itens": [], "ultima_loja": ""}


def salvar(fila):
    ARQ.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")


def adicionar(item):
    """item: id, loja, texto, nota, criado (timestamp da oferta na fonte), expira (bool),
    foto: {"tipo": "telegram", "chat", "msg"} | {"tipo": "url", "url"} | {"tipo": "previa"}"""
    fila = carregar()
    if any(i["id"] == item["id"] for i in fila["itens"]):
        return False
    fila["itens"].append(item)
    salvar(fila)
    return True


def tem_da_loja(loja):
    return any(i["loja"] == loja for i in carregar()["itens"])


def escolher(fila, agora=None):
    """Tira da fila as vencidas e devolve a de maior nota (com penalidade de tempo
    e um empurrão para variar de loja)."""
    agora = agora or time.time()
    validos = []
    for i in fila["itens"]:
        idade = (agora - i["criado"]) / 60
        if i.get("expira") and idade > VALIDADE_MIN:
            continue
        validos.append(i)
    fila["itens"] = validos
    if not validos:
        return None

    def pontos(i):
        p = i["nota"]
        if i.get("expira"):
            p -= (agora - i["criado"]) / 60 / 6  # -10 pontos por hora
        if i["loja"] == fila.get("ultima_loja"):
            p -= 15  # evita duas da mesma loja seguidas
        return p

    return max(validos, key=pontos)
