#!/bin/bash
# =====================================================================
# CISA - Grabación de la cámara 1, un archivo por hora (72 h guardadas)
#   bash scripts/grabar.sh iniciar    empieza a grabar (sigue aunque cierres la terminal)
#   bash scripts/grabar.sh detener    deja de grabar
#   bash scripts/grabar.sh estado     dice si está grabando y cuánto ocupa
# Con Docker: "docker compose up -d" también arranca la grabación (servicio cisa-grabacion)
# y "docker compose down" la detiene. iniciar/detener son para usarlo sin Docker.
# La dirección de la cámara sale del .env (RTSP_URL_CAMARA); no se escribe aquí.
# =====================================================================
cd "$(dirname "$0")/.." || exit 1
ENV=.env
leer() {   # primero la variable de entorno (Docker), si no, el .env
    if [ -n "${!1}" ]; then printf '%s\n' "${!1}"; return; fi
    grep -m1 "^$1=" "$ENV" 2>/dev/null | cut -d= -f2- | tr -d '\r'
}

URL=$(leer RTSP_URL_CAMARA); [ -z "$URL" ] && URL=$(leer RTSP_URL)
BASE=$(leer GRABACIONES_DIR); BASE=${BASE:-/home/jetson/Documents/Jetson8/grabaciones}
DIR="$BASE/cam1_grabacion"
RETENCION_MIN=4320          # 72 horas
SEGMENTO_SEG=3600           # 1 hora
PIDF=/tmp/cisa_grabacion.pid
LOG=logs/grabacion.log

corriendo() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
en_docker() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx cisa-grabacion; }

limpiar() {
    find "$DIR" -maxdepth 1 -name 'cam1_*.mp4' -mmin +$RETENCION_MIN -print -delete 2>/dev/null \
        | sed 's/^/[LIMPIEZA] borrado (más de 72 h): /'
}

case "$1" in
  iniciar)
    if corriendo; then echo "Ya está grabando (PID $(cat "$PIDF"))."; exit 0; fi
    if en_docker; then echo "Ya está grabando con Docker (cisa-grabacion). No se inicia otra vez."; exit 0; fi
    case "$URL" in rtsp://*) ;; *) echo "ERROR: no hay dirección de cámara (RTSP_URL_CAMARA en el .env). Corre antes: python3 scripts/fuente.py camara"; exit 1;; esac
    command -v ffmpeg >/dev/null || { echo "ERROR: no está instalado ffmpeg."; exit 1; }
    mkdir -p "$DIR" logs
    setsid nohup bash "$0" _bucle >> "$LOG" 2>&1 < /dev/null &
    sleep 3
    if corriendo; then echo "GRABANDO en $DIR (un archivo por hora). Mensajes: tail -f $LOG"
    else echo "No arrancó. Revisa: tail -20 $LOG"; exit 1; fi
    ;;
  detener)
    if corriendo; then kill -TERM -- -"$(cat "$PIDF")" 2>/dev/null; sleep 2; rm -f "$PIDF"; echo "Grabación detenida."
    else rm -f "$PIDF"; echo "No estaba grabando."; fi
    ;;
  estado)
    if en_docker; then echo "GRABANDO con Docker (cisa-grabacion)"
    elif corriendo; then echo "GRABANDO sin Docker (PID $(cat "$PIDF"))"
    else echo "NO está grabando"; fi
    if en_docker || corriendo; then
        ult=$(ls -1t "$DIR"/cam1_*.mp4 2>/dev/null | head -1)
        if [ -z "$ult" ] || [ $(( $(date +%s) - $(stat -c %Y "$ult") )) -gt 120 ]; then
            echo "  ATENCIÓN: no se ha guardado nada en los últimos 2 minutos."
            echo "  Revisa: docker compose logs --tail 20 cisa-grabacion   (o: tail -20 $LOG)"
        fi
    fi
    echo "Carpeta: $DIR"
    ls -1t "$DIR"/cam1_*.mp4 2>/dev/null | head -3 | while read -r f; do echo "  $(basename "$f")  $(du -h "$f" | cut -f1)"; done
    echo "Total grabado: $(du -sh "$DIR" 2>/dev/null | cut -f1)   |   Libre en disco: $(df -h "$BASE" 2>/dev/null | awk 'NR==2{print $4}')"
    ;;
  _bucle)
    echo $$ > "$PIDF"
    FF=""
    # Al detener: se le pide a ffmpeg que cierre bien el archivo en curso
    trap '[ -n "$FF" ] && kill -TERM "$FF" 2>/dev/null && wait "$FF"; echo "[GRABACION] detenida"; exit 0' TERM INT
    case "$URL" in rtsp://*) ;; *) echo "[GRABACION] ERROR: falta RTSP_URL_CAMARA"; sleep 60; exit 1;; esac
    mkdir -p "$DIR"
    limpiar
    ( while sleep 1800; do limpiar; done ) &
    while true; do
        echo "[GRABACION] $(date '+%F %T') iniciando ffmpeg -> $DIR"
        ffmpeg -nostdin -loglevel warning -rtsp_transport tcp -i "$URL" \
            -an -c:v copy -tag:v hvc1 \
            -f segment -segment_time $SEGMENTO_SEG -segment_atclocktime 1 \
            -segment_format mp4 -segment_format_options movflags=+faststart \
            -strftime 1 -reset_timestamps 1 \
            "$DIR/cam1_%Y%m%d_%H%M%S.mp4" &
        FF=$!
        wait "$FF"; CODIGO=$?; FF=""
        echo "[GRABACION] $(date '+%F %T') ffmpeg terminó (código $CODIGO); reintento en 5 s"
        sleep 5
    done
    ;;
  *)
    echo "Uso: bash scripts/grabar.sh iniciar | detener | estado"; exit 1;;
esac
