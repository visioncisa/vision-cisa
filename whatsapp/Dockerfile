# CISA — puente de WhatsApp (servicio cisa-whatsapp). Node 22 en ARM64 (Jetson).
FROM node:22-bookworm-slim

# git: una dependencia de la librería (libsignal) se descarga de GitHub
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY puente.js ./

ENV TZ=America/Mexico_City
CMD ["node", "puente.js"]
