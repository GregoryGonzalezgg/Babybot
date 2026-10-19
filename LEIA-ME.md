# Radar de Ofertas – nicho Baby

Posta ofertas de bebê no Telegram com **foto** e o **seu link de afiliado**:
- **Magalu:** lê o canal oficial *[Oficial] Influenciador Magalu*, filtra o que é de bebê
  e troca o código do produto pelo link da sua loja Parceiro Magalu.
- **Shopee:** posta a curadoria de `listas/curadoria_shopee_baby.csv`
  (feita a partir do feed oficial de produtos, já com os seus links de afiliado).

Para rodar 24h na nuvem de graça, veja **[DEPLOY.md](DEPLOY.md)**.

## Pastas e arquivos
| | |
|---|---|
| `radar.py` | radar da Magalu (fica ouvindo o canal) |
| `postar_shopee.py` | posta as ofertas da Shopee (lote ou `--agendado`) |
| `curadoria_shopee.py` | gera a curadoria a partir do feed CSV da Shopee (tira repetidos) |
| `parser_magalu.py`, `nicho.py` | leitura dos posts e filtro de bebê |
| `palavras_baby.txt`, `codigos_baby.txt` | palavras e códigos que contam como bebê (pode editar) |
| `listas/` | listas prontas para postar (vão para o Git) |
| `dados/` | o que os programas gravam: já postados, fotos, fila do WhatsApp (fora do Git) |
| `deploy/` | instalação e atualização na VM |
| `.env` | suas configurações e segredos (fora do Git; modelo em `.env.exemplo`) |

## No PC
```
pip install -r requirements.txt
python radar.py --teste 10          # mostra o que leria dos últimos 10 posts, sem enviar
python radar.py                     # liga o radar da Magalu
python radar.py --demo 3            # demonstração: envia 3 ofertas de qualquer nicho
python postar_shopee.py --simular   # mostra os próximos posts da Shopee
python postar_shopee.py --quantidade 10 --intervalo 10
python curadoria_shopee.py caminho/do/feed.csv
```
Na primeira vez, o Telegram pede seu telefone (com +55) e o código que chega no app.

## Segurança
- **Nunca** compartilhe `.env`, `sessao_radar.session` nem a `TG_SESSION`: dão acesso à sua conta.
- Mantenha o repositório do GitHub **privado**.
