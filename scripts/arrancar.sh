#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

if ! nvidia-smi >/dev/null 2>&1; then
  echo "La GPU no inicio. Apaga con 'sudo shutdown now', desconecta 1 minuto y vuelve a encender."
  exit 1
fi

echo "Regenerando la definicion de la GPU..."
if ! sudo nvidia-ctk cdi generate --output=/var/run/cdi/nvidia.yaml >/dev/null 2>&1; then
  echo "No se pudo generar el archivo de la GPU. Corre el comando a mano para ver el error."
  exit 1
fi

docker compose down >/dev/null 2>&1
docker compose up -d
docker compose ps
echo
python3 scripts/fuente.py
