/*
 * CISA — Puente de WhatsApp (servicio cisa-whatsapp)
 * ================================================================
 * Mantiene abierta una sesión de WhatsApp Web (librería Baileys) y
 * recibe los avisos del sistema por HTTP para mandarlos por WhatsApp.
 *
 *   Primera vez: docker compose logs -f cisa-whatsapp  → aparece un QR
 *   (o un código de 8 letras si WHATSAPP_EMISOR está en el .env).
 *   En el teléfono que va a MANDAR los avisos: WhatsApp → Dispositivos
 *   vinculados → Vincular un dispositivo → escanear el QR, o
 *   "Vincular con el número de teléfono" y escribir el código.
 *   La sesión se guarda en whatsapp/sesion/ y no se vuelve a pedir el QR.
 *
 * HTTP (solo desde la misma Jetson, 127.0.0.1):
 *   GET  /estado   → {"conectado": true|false}
 *   POST /enviar   → JSON {"numero": "5215512345678", "texto": "...",
 *                          "foto_b64": "<jpg en base64, opcional>"}
 *
 * No es la API oficial de WhatsApp: el número que manda puede ser
 * bloqueado si WhatsApp lo considera spam. Usar un número dedicado.
 * ================================================================
 */
import http from 'node:http'
import makeWASocket, {
    useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, Browsers,
} from '@whiskeysockets/baileys'
import fs from 'node:fs/promises'
import path from 'node:path'
import pino from 'pino'
import qrcode from 'qrcode-terminal'

const PUERTO      = Number(process.env.WHATSAPP_PUERTO || 5002)
const HOST        = process.env.WHATSAPP_HOST || '127.0.0.1'   // solo la propia Jetson
const SESION_DIR  = process.env.WHATSAPP_SESION || './sesion'
const MAX_CUERPO  = 15 * 1024 * 1024                          // 15 MB por aviso
// Número del teléfono que MANDA los avisos. Si está, se vincula con código de 8 letras en vez de QR.
const EMISOR      = (process.env.WHATSAPP_EMISOR || '').replace(/\D/g, '')

const log = (...a) => console.log(new Date().toLocaleString('es-MX'), '[WHATSAPP]', ...a)

let sock = null
let conectado = false
const jids = new Map()          // número → jid de WhatsApp (se consulta una vez)

// ── Sesión de WhatsApp Web ───────────────────────────────────────────────────
// Vinculado = WhatsApp ya confirmó la cuenta (pasa igual con QR y con código).
// Ojo: creds.registered solo se marca con código, no con QR.
const vinculado = (state) => Boolean(state.creds.account)

async function limpiarSesion() {
    // Se borra el contenido (no la carpeta: en Docker es un volumen montado)
    try {
        for (const f of await fs.readdir(SESION_DIR)) {
            await fs.rm(path.join(SESION_DIR, f), { recursive: true, force: true })
        }
    } catch { /* la carpeta aún no existe */ }
}

async function conectar() {
    const { state, saveCreds } = await useMultiFileAuthState(SESION_DIR)
    let version
    try {
        ({ version } = await fetchLatestBaileysVersion())
    } catch {
        version = undefined                  // sin internet: usa la que trae la librería
    }
    sock = makeWASocket({
        version,
        auth: state,
        browser: Browsers.ubuntu('CISA'),
        logger: pino({ level: 'warn' }),
        qrTimeout: 60_000,                   // 1 min por QR (antes 20 s): más tiempo para vincular
        markOnlineOnConnect: false,          // que el teléfono siga recibiendo notificaciones
    })
    sock.ev.on('creds.update', saveCreds)
    let codigoPedido = false
    sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
        if (qr && EMISOR && !vinculado(state)) {
            // Vincular con código de 8 letras en vez de QR (WHATSAPP_EMISOR en el .env)
            if (!codigoPedido) {
                codigoPedido = true
                try {
                    const c = await sock.requestPairingCode(EMISOR)
                    log(`CÓDIGO PARA VINCULAR: ${c.slice(0, 4)}-${c.slice(4)}`)
                    log(`En el teléfono ${EMISOR}: WhatsApp → Dispositivos vinculados → Vincular un dispositivo →`)
                    log('"Vincular con el número de teléfono" (abajo) → escribe el código. Si vence, sale uno nuevo aquí.')
                } catch (e) {
                    log('No se pudo pedir el código:', e.message)
                }
            }
        } else if (qr) {
            log('Escanea este QR con WhatsApp → Dispositivos vinculados → Vincular un dispositivo:')
            qrcode.generate(qr, { small: true })
        }
        if (connection === 'open') {
            conectado = true
            log(`Conectado como ${sock.user?.id?.split(':')[0] ?? '?'}`)
        }
        if (connection === 'close') {
            conectado = false
            const codigo = lastDisconnect?.error?.output?.statusCode
            if (codigo === DisconnectReason.restartRequired) {
                // Normal justo después de vincular: WhatsApp pide reconectar. Nunca se borra nada.
                log('Vinculado; reconectando...')
                setTimeout(() => conectar().catch(e => log('Error al reconectar:', e.message)), 1000)
                return
            }
            if (!vinculado(state)) {
                // Todavía no se vincula (venció el QR/código o WhatsApp rechazó el intento):
                // se borra el intento a medias y se empieza limpio, con QR/código nuevo.
                log(`El QR/código venció o no se aceptó (código ${codigo ?? '?'}); generando uno nuevo...`)
                await limpiarSesion()
                setTimeout(() => conectar().catch(e => log('Error al reconectar:', e.message)), 2000)
                return
            }
            if (codigo === DisconnectReason.loggedOut) {
                log('La sesión se cerró desde el teléfono. Borra la carpeta whatsapp/sesion y reinicia para escanear un QR nuevo.')
                return
            }
            log(`Conexión cerrada (código ${codigo ?? '?'}); reconectando en 5 s`)
            setTimeout(() => conectar().catch(e => log('Error al reconectar:', e.message)), 5000)
        }
    })
}

async function jidDe(numero) {
    if (jids.has(numero)) return jids.get(numero)
    const [r] = await sock.onWhatsApp(numero)
    if (!r?.exists) throw new Error(`el número ${numero} no tiene WhatsApp`)
    jids.set(numero, r.jid)
    return r.jid
}

export async function enviar({ numero, texto, foto_b64 }) {
    if (!conectado) throw Object.assign(new Error('WhatsApp no está conectado'), { http: 503 })
    numero = String(numero || '').replace(/\D/g, '')
    if (!numero) throw Object.assign(new Error('falta "numero"'), { http: 400 })
    const jid = await jidDe(numero)
    const mensaje = foto_b64
        ? { image: Buffer.from(foto_b64, 'base64'), caption: texto || '' }
        : { text: texto || '' }
    await sock.sendMessage(jid, mensaje)
    log(`Enviado a ${numero}: ${(texto || '').split('\n')[0].slice(0, 60)}`)
}

// ── Servidor HTTP local ──────────────────────────────────────────────────────
function responder(res, codigo, datos) {
    res.writeHead(codigo, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(datos))
}

export const servidor = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/estado') {
        return responder(res, 200, { conectado })
    }
    if (req.method !== 'POST' || req.url !== '/enviar') {
        return responder(res, 404, { ok: false, error: 'ruta no existe' })
    }
    const partes = []
    let tam = 0
    req.on('data', c => {
        tam += c.length
        if (tam > MAX_CUERPO) { responder(res, 413, { ok: false, error: 'aviso demasiado grande' }); req.destroy() }
        else partes.push(c)
    })
    req.on('end', async () => {
        if (res.writableEnded) return
        try {
            await enviar(JSON.parse(Buffer.concat(partes).toString('utf-8')))
            responder(res, 200, { ok: true })
        } catch (e) {
            log('No se envió:', e.message)
            responder(res, e.http || (e instanceof SyntaxError ? 400 : 500), { ok: false, error: e.message })
        }
    })
})

if (process.env.WHATSAPP_NO_INICIAR !== '1') {      // las pruebas lo cargan sin conectarse
    servidor.listen(PUERTO, HOST, () => log(`Escuchando en http://${HOST}:${PUERTO}`))
    conectar().catch(e => { log('No se pudo iniciar:', e.message); process.exit(1) })
}

// Permite a las pruebas simular una sesión conectada
export function _simular(sockFalso) { sock = sockFalso; conectado = true }
