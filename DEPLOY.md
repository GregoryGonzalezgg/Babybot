# Colocar o radar na nuvem (grátis, 24h)

## Por que VM e não Vercel / GitHub Actions
O radar precisa ficar **conectado o tempo todo** ao Telegram, esperando posts novos.
- **Vercel** só roda funções curtas (segundos) e desliga: não serve.
- **GitHub Actions** é para tarefas que começam e terminam; manter ligado 24h vai contra as regras.
- **VM grátis** (um computador na nuvem que fica sempre ligado) é o caminho certo.
  O **GitHub** entra para guardar o código e levar as atualizações até a VM.

## Opções de VM grátis
| Provedor | O que é grátis | Observação |
|---|---|---|
| **Oracle Cloud – Always Free** (recomendado) | VM Ampere A1 (até 4 núcleos / 24 GB) ou 2 VMs micro | Grátis para sempre; pede cartão só para verificar |
| **Google Cloud – e2-micro** | 1 VM pequena nas regiões us-west1, us-central1 ou us-east1 | Grátis para sempre dentro do limite; pede cartão |

Escolha **Ubuntu 22.04 ou 24.04** como sistema da VM. Os dois programas usam pouca memória.

---

## Passo a passo

### 1. No seu PC: gerar o login do Telegram para a nuvem
```
python gerar_sessao.py
```
Isso grava `TG_SESSION` no seu `.env`. É o login da sua conta: **não mostre, não mande em chat,
não suba para o GitHub** (o `.gitignore` já impede).

### 2. Subir o código para o GitHub (repositório PRIVADO)
1. Crie um repositório **privado** em github.com (já criado: `Babybot`).
2. Nesta pasta:
```
git remote add origin https://github.com/GregoryGonzalezgg/Babybot.git
git push -u origin main
```
O `.env`, as sessões e a pasta `dados/` **não** sobem.

### 3. Criar a VM (Oracle Cloud)
1. Crie a conta em cloud.oracle.com (plano Always Free).
2. Compute → Instances → Create instance → imagem **Ubuntu**, shape **Always Free** (Ampere A1 ou E2.1.Micro).
3. Baixe a chave SSH que ele oferece e crie.
4. Anote o **IP público** da VM.

### 4. Entrar na VM e baixar o código
No PowerShell do seu PC:
```
ssh -i caminho\da\chave.key ubuntu@IP_DA_VM
```
Na VM:
```
git clone https://github.com/GregoryGonzalezgg/Babybot.git
cd Babybot
```
(Repositório privado: o GitHub vai pedir login; use um *Personal Access Token* no lugar da senha.)

### 5. Levar o .env para a VM
No PowerShell do seu PC (outra janela):
```
scp -i caminho\da\chave.key .env ubuntu@IP_DA_VM:~/Babybot/.env
```

### 6. Instalar e ligar
Na VM:
```
bash deploy/instalar.sh
```
Pronto: o radar da Magalu e a postagem agendada da Shopee ficam ligados 24h,
reiniciam sozinhos se cair e voltam quando a VM reinicia.

**Importante:** depois que a VM estiver postando, **desligue o radar do seu PC**,
senão os dois postam a mesma oferta.

---

## Dia a dia
| Quero... | Comando (na VM) |
|---|---|
| Ver o radar da Magalu ao vivo | `journalctl -u radar-magalu -f` |
| Ver a postagem da Shopee | `journalctl -u postar-shopee -f` |
| Pausar / voltar a Shopee | `sudo systemctl stop postar-shopee` / `start` |
| Atualizar depois de um `git push` | `bash deploy/atualizar.sh` |

**Lista nova da Shopee:** gere a curadoria e os links no PC, faça `git add listas/ && git commit && git push`
e rode `bash deploy/atualizar.sh` na VM. O que já foi postado fica registrado na VM e não se repete.

**Mudar horário ou intervalo da Shopee:** edite `POSTAR_DAS`, `POSTAR_ATE` e `INTERVALO_MIN`
no `.env` da VM (`nano .env`) e rode `sudo systemctl restart postar-shopee`.

## Se der problema
- `TG_SESSION inválida ou expirada`: no PC, rode `python radar.py --teste 1` (faz login de novo),
  depois `python gerar_sessao.py` e copie o `.env` para a VM outra vez (passo 5).
- Se a `TG_SESSION` vazar: no app do Telegram, Configurações → Dispositivos → encerre a sessão
  do radar, e gere outra.
