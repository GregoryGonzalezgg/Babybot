"""Decide se uma oferta é do nicho Baby.

O site da Magalu bloqueia consulta automática pelo código, então a decisão usa
o texto do post (nome do produto ou chamada do cupom):
  "sim"       -> é do nicho, pode postar
  "nao"       -> não é do nicho, descarta
  "verificar" -> post só com códigos e sem pista no texto; vai para você conferir

As palavras ficam em palavras_baby.txt (uma por linha) para você ajustar.
Códigos que você confirmar como baby podem ir em codigos_baby.txt.
"""
import re
import unicodedata
from pathlib import Path

PASTA = Path(__file__).parent


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _ler_lista(nome):
    try:
        linhas = (PASTA / nome).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [normalizar(l.strip()) for l in linhas if l.strip() and not l.startswith("#")]


def _regex(palavras):
    if not palavras:
        return None
    # \b evita falso positivo como "bebe" dentro de "bebedouro"
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in palavras) + r")\b")


INCLUIR = _regex([l for l in _ler_lista("palavras_baby.txt") if not l.startswith("-")])
EXCLUIR = _regex([l[1:].strip() for l in _ler_lista("palavras_baby.txt") if l.startswith("-")])
CODIGOS_BABY = set(_ler_lista("codigos_baby.txt"))


def classificar(oferta):
    if CODIGOS_BABY & set(oferta.ids):
        return "sim"
    texto = normalizar(oferta.texto_original)
    if EXCLUIR and EXCLUIR.search(texto):
        return "nao"
    if INCLUIR and INCLUIR.search(texto):
        return "sim"
    # post com nome de produto ou chamada de categoria sem palavra de bebê: não é do nicho
    if oferta.preco_por or oferta.chamada or not oferta.ids:
        return "nao"
    return "verificar"
