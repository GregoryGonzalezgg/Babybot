"""Formato padrão dos posts do Totuxa Baby, igual para Shopee, Magalu e Amazon:

🔥 Nome do produto
💰 de R$ 179,90 por R$ 79,90 (-56%)
⭐ Nota 4,88 | ❤️ 7,4 mil curtidas        (só quando a loja informa)
🛍️ 👉 Ver oferta na Shopee               (texto clicável com o link de afiliado)
⚠️ Preço e estoque podem mudar a qualquer momento
"""
AVISO = "⚠️ Preço e estoque podem mudar a qualquer momento"
AVISO_CUPOM = "⚠️ Cupom por tempo limitado, aplique no carrinho"


def brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def titulo(texto, limite=80):
    # títulos de marketplace vêm cheios de palavras-chave; corta no fim de uma palavra
    texto = " ".join((texto or "").split())
    if len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0] + "…"
    return f"🔥 {texto}"


def preco(de=None, por=None, desconto=None, sufixo=""):
    if not por:
        return None
    if de and de > por:
        desconto = desconto or round((1 - por / de) * 100)
        linha = f"💰 de {brl(de)} por {brl(por)} (-{desconto}%)"
    else:
        linha = f"💰 por {brl(por)}"
    return linha + (f" {sufixo}" if sufixo else "")


def nota(valor=None, curtidas=None):
    partes = []
    if valor:
        partes.append(f"⭐ Nota {str(valor).replace('.', ',')}")
    if curtidas:
        n = int(float(curtidas))
        texto = f"{n / 1000:.1f} mil".replace(".", ",").replace(",0 mil", " mil") if n >= 1000 else str(n)
        partes.append(f"❤️ {texto} curtidas")
    return " | ".join(partes) or None


def link(loja, url, rotulo="Ver oferta"):
    return f"🛍️ [👉 {rotulo} na {loja}]({url})"


def juntar(*linhas):
    return "\n".join(l for l in linhas if l)
