#!/usr/bin/env bash
# Baixa a versão nova do GitHub e reinicia os serviços.
# Uso (na VM, dentro da pasta do projeto):  bash deploy/atualizar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart radar-magalu postar-shopee
echo "Atualizado e reiniciado."
