#!/usr/bin/env bash
# Instala o radar numa VM Ubuntu/Debian e deixa os dois programas ligados 24h:
#   radar-magalu  -> ouve o canal da Magalu e posta as ofertas de bebê
#   postar-shopee -> posta 1 oferta da curadoria da Shopee a cada INTERVALO_MIN
# Eles reiniciam sozinhos se cair e voltam quando a VM reinicia.
#
# Uso (dentro da pasta do projeto, já com o .env copiado):  bash deploy/instalar.sh
set -euo pipefail

PROJETO="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="$(whoami)"
cd "$PROJETO"

if [ ! -f .env ]; then
  echo "Falta o arquivo .env nesta pasta. Copie o .env do seu PC (com TG_SESSION) para $PROJETO/.env"
  exit 1
fi
if ! grep -q '^TG_SESSION=.\+' .env; then
  echo "O .env não tem TG_SESSION. No PC, rode 'python gerar_sessao.py' e copie o .env de novo."
  exit 1
fi
chmod 600 .env  # só o seu usuário lê os segredos

echo ">> Instalando Python..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git

echo ">> Criando ambiente Python e instalando dependências..."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

criar_servico() {
  local nome="$1" comando="$2" descricao="$3"
  sudo tee "/etc/systemd/system/${nome}.service" > /dev/null <<EOF
[Unit]
Description=${descricao}
After=network-online.target
Wants=network-online.target

[Service]
User=${USUARIO}
WorkingDirectory=${PROJETO}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PROJETO}/.venv/bin/python ${comando}
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
}

echo ">> Criando os serviços..."
criar_servico radar-magalu "radar.py" "Radar de ofertas Magalu (nicho Baby)"
criar_servico postar-shopee "postar_shopee.py --agendado" "Postagem agendada das ofertas da Shopee"
sudo systemctl daemon-reload
sudo systemctl enable --now radar-magalu postar-shopee

sleep 5
systemctl --no-pager --lines=0 status radar-magalu postar-shopee || true
echo
echo "Pronto! Para ver o que está acontecendo:"
echo "  journalctl -u radar-magalu -f"
echo "  journalctl -u postar-shopee -f"
