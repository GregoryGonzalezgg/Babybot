"""Lê o texto de um post do canal da Magalu e extrai os dados da oferta.

Como ainda não vimos posts reais, as regras são tolerantes e ajustáveis
pelo .env (ID_REGEX). Rode `python radar.py --teste 10` para ver o que
está sendo extraído dos últimos posts e ajustar se precisar.
"""
import re
from dataclasses import dataclass, field

PRECO_RE = re.compile(r"R\$\s*([\d\.]+,\d{2}|\d+)")
CUPOM_RE = re.compile(
    r"(?:cupom|c[óo]digo promocional|use o c[óo]digo)\s*[:\-–]?\s*\*?`?([A-Z0-9]{4,20})`?",
    re.IGNORECASE,
)
DESCONTO_RE = re.compile(r"(\d{1,2})\s*%\s*(?:off|de desconto|desc)", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")
# Formato do canal oficial da Magalu: "Código: 241921400 241921700" (um ou mais IDs na linha)
LINHA_CODIGO_RE = re.compile(
    r"^\W*(?:c[óo]digos?|top itens|itens|produtos)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
TOKEN_ID_RE = re.compile(r"\b[a-z0-9]{6,12}\b", re.IGNORECASE)
PARCELA_RE = re.compile(r"\d+\s*x\s*(?:de\s*)?R\$", re.IGNORECASE)
POR_RE = re.compile(r"\bpor\s*(?:apenas|s[óo])?\s*R\$\s*([\d\.]+,\d{2}|\d+)", re.IGNORECASE)
DE_RE = re.compile(r"\bde\s*R\$\s*([\d\.]+,\d{2}|\d+)", re.IGNORECASE)
LINHA_INFO_RE = re.compile(r"frete|cep|disponibilidade|parcel|sem juros", re.IGNORECASE)
# Post de campanha: "R$ 20 OFF em Pelúcia Plush Chaves" (o valor é desconto, não preço)
OFF_RE = re.compile(r"R\$\s*[\d\.,]+\s*(?:de\s*)?off\b", re.IGNORECASE)
# Chamada de campanha com porcentagem: "GANHE 10% OFF EM TODA A CATEGORIA..."
OFF_PCT_RE = re.compile(r"\d{1,2}\s*%\s*(?:de\s*)?(?:off|desconto)\b", re.IGNORECASE)

# Ordem de tentativa para achar o ID do produto
ID_PADROES = [
    # "ID: 237184700", "Código: kd5f2hb1j7", "SKU 123456"
    re.compile(r"\b(?:id|c[óo]d(?:igo)?|sku)\b\s*(?:do (?:produto|item))?\s*[:#\-–]?\s*`?([a-z0-9]{6,12})`?", re.IGNORECASE),
    # link da Magalu: .../p/237184700/...
    re.compile(r"magazine(?:luiza|voce)\.com\.br/(?:[^\s]*/)?p/([a-z0-9]{6,12})", re.IGNORECASE),
    # número solto de 9 dígitos (formato comum dos IDs da Magalu)
    re.compile(r"(?<![\d,\.])(\d{9})(?![\d,])"),
]


@dataclass
class Oferta:
    ids: list = field(default_factory=list)
    titulo: str = ""
    preco_de: float | None = None
    preco_por: float | None = None
    desconto: int | None = None
    cupom: str | None = None
    parcelas: str | None = None
    chamada: str | None = None  # ex.: "R$ 20 OFF em Pelúcia Plush Chaves"
    pix: bool = False
    texto_original: str = ""

    @property
    def tipo(self):
        if self.ids:
            return "produto"
        if self.cupom:
            return "cupom"
        return "outro"


def _valor(txt):
    txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _titulo(texto):
    candidatas = []
    for linha in texto.splitlines():
        limpa = re.sub(r"[^\w\s\-\+/,\.%()]", "", linha).strip()
        if len(limpa) < 6:
            continue
        if URL_RE.search(linha) or PRECO_RE.search(linha) or CUPOM_RE.search(linha):
            continue
        if re.match(r"^(id|c[óo]d|sku)", limpa, re.IGNORECASE) or LINHA_INFO_RE.search(linha):
            continue
        candidatas.append(limpa)
    # chamadas tipo "ISSO AQUI TÁ BOM DEMAIS" são curtas; o nome do produto é a linha mais longa
    return max(candidatas, key=len, default="")


def extrair(texto, id_regex=None):
    oferta = Oferta(texto_original=texto or "")
    if not texto:
        return oferta

    padroes = [re.compile(id_regex, re.IGNORECASE)] if id_regex else ID_PADROES
    vistos = []
    if not id_regex:
        for linha in LINHA_CODIGO_RE.findall(texto):
            for item in TOKEN_ID_RE.findall(linha):
                if item.lower() not in vistos:
                    vistos.append(item.lower())
    for padrao in ([] if vistos else padroes):
        for m in padrao.finditer(texto):
            item = m.group(1).lower()
            if item not in vistos:
                vistos.append(item)
        if vistos:
            break
    oferta.ids = vistos

    linha_off = next((l for l in texto.splitlines() if OFF_RE.search(l)), None) or next(
        (l for l in texto.splitlines() if OFF_PCT_RE.search(l) and not CUPOM_RE.search(l)), None
    )
    if linha_off:
        oferta.chamada = re.sub(r"[^\w\s\-\+/,\.%()$]", "", linha_off).strip()
    linhas_preco = [l for l in texto.splitlines()
                    if PRECO_RE.search(l) and not PARCELA_RE.search(l) and not OFF_RE.search(l)]
    parcela = next((l.strip() for l in texto.splitlines() if PARCELA_RE.search(l)), None)
    if parcela:
        oferta.parcelas = re.sub(r"^\W*ou\s+", "", parcela, flags=re.IGNORECASE)
    oferta.pix = any("pix" in l.lower() for l in linhas_preco)
    corpo = "\n".join(linhas_preco)
    m_por, m_de = POR_RE.search(corpo), DE_RE.search(corpo)
    if m_por:
        oferta.preco_por = _valor(m_por.group(1))
        if m_de and m_de.start() < m_por.start():
            oferta.preco_de = _valor(m_de.group(1))
    else:
        precos = [v for v in (_valor(p) for p in PRECO_RE.findall(corpo)) if v]
        if len(precos) >= 2:
            oferta.preco_de, oferta.preco_por = max(precos[:2]), min(precos[:2])
        elif precos:
            oferta.preco_por = precos[0]

    m = DESCONTO_RE.search(texto)
    if m:
        oferta.desconto = int(m.group(1))
    elif oferta.preco_de and oferta.preco_por and oferta.preco_de > oferta.preco_por:
        oferta.desconto = round((1 - oferta.preco_por / oferta.preco_de) * 100)

    m = CUPOM_RE.search(texto)
    if m:
        oferta.cupom = m.group(1).upper()

    oferta.titulo = _titulo(texto)
    if oferta.tipo == "cupom":
        # Em post de cupom, os valores são regra do cupom (ex.: R$ 50 off acima de R$ 300),
        # não preço de produto; e a 1ª linha costuma ser a própria chamada do cupom.
        oferta.preco_de = oferta.preco_por = oferta.desconto = None
        primeira = next((l for l in texto.splitlines() if l.strip()), "")
        oferta.titulo = re.sub(r"[^\w\s\-\+/,\.%()$]", "", primeira).strip()
    return oferta


def brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
