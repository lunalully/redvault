#!/usr/bin/env bash
# Sobe o REDVAULT em modo LAN: o painel fica em 127.0.0.1, os labs aceitam
# conexões da rede local para você atacar de outro computador.
#
#   ./scripts/start-lan.sh            # detecta o IP e sobe
#   ./scripts/start-lan.sh --stop     # derruba a plataforma e todos os labs
#   REDVAULT_LAN_IP=192.168.0.10 ./scripts/start-lan.sh   # força o IP
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${REDVAULT_PORT:-8000}"
LOG="${REDVAULT_LOG:-/tmp/redvault.log}"

stop_all() {
  echo "==> Parando plataforma e labs…"
  pkill -f "run\.py" 2>/dev/null || true
  pkill -f "/lab/app.py" 2>/dev/null || true
  sleep 1
  echo "==> Parado. Portas 42000–42999 liberadas."
}

if [[ "${1:-}" == "--stop" ]]; then
  stop_all
  exit 0
fi

# --- 1. IP da rede local -----------------------------------------------------
IP="${REDVAULT_LAN_IP:-}"
if [[ -z "$IP" ]]; then
  IP="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -v '^127\.' | head -1 || true)"
fi
if [[ -z "$IP" ]]; then
  echo "ERRO: não encontrei um IP de rede local. Conecte-se ao Wi-Fi/cabo ou use REDVAULT_LAN_IP=..." >&2
  exit 1
fi

# --- 2. Já existe algo rodando? ---------------------------------------------
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${PORT}\b"; then
  echo "ERRO: a porta ${PORT} já está em uso. Rode '$0 --stop' primeiro." >&2
  exit 1
fi

# --- 3. Sobe a plataforma ----------------------------------------------------
# O tutorial instala as dependências no `.venv`; usar o mesmo interpretador
# aqui evita "No module named fastapi" quando o script roda fora do venv.
if [ -x ".venv/bin/python3" ]; then
  PY=".venv/bin/python3"
else
  PY="python3"
fi

echo "==> IP detectado: ${IP}"
echo "==> Subindo REDVAULT (painel em 127.0.0.1:${PORT}, labs em 0.0.0.0:42000-42999)…"
REDVAULT_LAB_BIND=0.0.0.0 \
REDVAULT_LAB_PUBLIC_HOST="$IP" \
  nohup "$PY" run.py > "$LOG" 2>&1 &

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "ERRO: a plataforma não respondeu. Últimas linhas de ${LOG}:" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

echo
echo "Pronto."
echo "  Painel (só este PC):   http://127.0.0.1:${PORT}"
echo "  Labs (outro PC):       http://${IP}:42000   (a porta aparece no card do lab)"
echo
echo "Subir uma máquina: abra MÁQUINAS → INICIAR LAB → copie a URL mostrada."
echo "Parar tudo:        $0 --stop"