"""
CISA - Alertas con dirección, tipo y empresa
"""
import json, os, requests, threading, time
from config import (TG_TOKEN, TG_CHAT_ID, TG_VALIDADOR_IDS, ID_PUERTA, UNIDADES_INFO,
                    SIN_TELEGRAM, VALIDAR_CON_GEMINI)

TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
_pendientes = {}
_pendientes_desc = {}
_PENDIENTES_FILE = "/tmp/cisa_pendientes.json"

def _guardar_pendientes():
    try:
        import json
        data = {str(k): {**v, "frame_path": str(v["frame_path"])} for k, v in _pendientes.items()}
        open(_PENDIENTES_FILE, "w").write(json.dumps(data))
    except: pass

def _cargar_pendientes():
    try:
        import json, os
        if not os.path.exists(_PENDIENTES_FILE): return
        data = json.loads(open(_PENDIENTES_FILE).read())
        for k, v in data.items():
            _pendientes[int(k)] = v
        print(f"[PENDIENTES] Recuperados {len(data)} del disco")
        os.remove(_PENDIENTES_FILE)
    except Exception as e:
        print(f"[PENDIENTES] Error: {e}")

_cargar_pendientes()
_pendientes_lock = threading.Lock()

_update_offset = 0
_on_validated_callback = None

def set_validation_callback(fn):
    global _on_validated_callback
    _on_validated_callback = fn

def _get_info(numero):
    info = UNIDADES_INFO.get(str(numero), {})
    return info.get("empresa", "CISA"), info.get("tipo", "diesel")

def _fmt_dir(d):   return "🟢 *ENTRADA*" if d == "entrada" else "🔴 *SALIDA*"
def _fmt_tipo(t):  return "⚡ Eléctrica" if t == "electrica" else "🛢️ Diesel"
def _fmt_emp(e):
    return {"CISA": "🏢 CISA", "COPATSA": "🚌 COPATSA", "CCA": "🔵 CCA"}.get(e, f"🚍 {e}")

def _foto(chat_id, frame_path, caption, reply_markup=None):
    if SIN_TELEGRAM:
        print(f"[SIN TELEGRAM] foto: {caption.splitlines()[0][:60]}")
        return None
    try:
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
        if reply_markup:
            data["reply_markup"] = reply_markup
        with open(frame_path, 'rb') as f:
            resp = requests.post(f"{TG_API}/sendPhoto", data=data,
                                 files={"photo": f}, timeout=15)
        r = resp.json()
        return r["result"]["message_id"] if r.get("ok") else None
    except Exception as e:
        print(f"[TG ERROR] {e}"); return None

def _msg(chat_id, texto):
    if SIN_TELEGRAM:
        print(f"[SIN TELEGRAM] mensaje: {texto.splitlines()[0][:60]}")
        return
    try:
        requests.post(f"{TG_API}/sendMessage",
                      data={"chat_id": chat_id, "text": texto,
                            "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"[TG ERROR] {e}")

def _cb(cb_id, texto):
    try:
        requests.post(f"{TG_API}/answerCallbackQuery",
                      data={"callback_query_id": cb_id, "text": texto}, timeout=10)
    except: pass

def enviar_a_validador(frame_path, numero, confianza, ts, estado,
                       no_detectado=None, thumb_name=None,
                       puerta_id=None, camera_label='Cam 1', direccion='entrada'):
    if puerta_id is None:
        puerta_id = ID_PUERTA
    empresa, tipo = _get_info(numero)
    caption = (
        f"🔍 *Validar detección* — {camera_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_fmt_dir(direccion)}\n"
        f"🔢 Número: `{numero}`\n"
        f"{_fmt_emp(empresa)}\n"
        f"{_fmt_tipo(tipo)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Confianza: `{round(confianza*100)}%`\n"
        f"🕐 Hora: `{ts}`\n\n"
        f"_Presiona un botón para validar_"
    )
    keyboard = json.dumps({"inline_keyboard": [[
        {"text": "🟢 Entrada",   "callback_data": f"entrada:{numero}"},
        {"text": "🔴 Salida",    "callback_data": f"salida:{numero}"},
        {"text": "✗ Incorrecto", "callback_data": f"no:{numero}"},
    ]]})
    ids = []
    for vid in TG_VALIDADOR_IDS:
        mid = _foto(vid, frame_path, caption, reply_markup=keyboard)
        if mid:
            ids.append(mid)
            print(f"[VALIDADOR] {numero} {direccion} → {vid}")
    if not ids:
        alerta_unidad_detectada(frame_path, numero, confianza, ts, direccion)
        return None
    datos = {"numero": numero, "no_detectado": no_detectado or numero,
             "confianza": confianza, "ts": ts, "estado": estado,
             "frame_path": frame_path, "duracion": 0, "thumb_name": thumb_name,
             "puerta_id": puerta_id, "camera_label": camera_label,
             "direccion": direccion, "empresa": empresa, "tipo": tipo,
             "siblings": ids}
    with _pendientes_lock:
        for mid in ids:
            _pendientes[mid] = datos
        _guardar_pendientes()
    return ids[0]

def actualizar_pendiente(msg_id, numero_ganador, conf, estado, duracion):
    if msg_id is None: return
    with _pendientes_lock:
        if msg_id in _pendientes:
            d = _pendientes[msg_id]
            d.update({"numero": numero_ganador, "confianza": conf,
                      "estado": estado, "duracion": duracion})
            for sib in d.get("siblings", []):
                if sib in _pendientes:
                    _pendientes[sib] = d

def alerta_unidad_desconocida(frame_path, numero, confianza, ts, camera_label='Cam 1'):
    caption = (
        f"🔍 *¿Número desconocido?* — {camera_label}\n"
        f"🔢 OCR leyó: `{numero}`\n"
        f"📊 Confianza YOLO: `{round(confianza*100)}%`\n"
        f"🕐 Hora: `{ts}`\n\n"
        f"_¿Es una unidad real no registrada?_"
    )
    keyboard = json.dumps({"inline_keyboard": [[
        {"text": "📢 Sí, enviar", "callback_data": f"desc_ok:{numero}"},
        {"text": "🗑 Ignorar",    "callback_data": f"desc_no:{numero}"},
    ]]})
    ids = []
    for vid in TG_VALIDADOR_IDS:
        mid = _foto(vid, frame_path, caption, reply_markup=keyboard)
        if mid: ids.append(mid)
    if ids:
        datos = {"numero": numero, "confianza": confianza, "ts": ts,
                 "frame_path": frame_path, "camera_label": camera_label,
                 "siblings": ids}
        with _pendientes_lock:
            for mid in ids:
                _pendientes_desc[mid] = datos
    print(f"[DESCONOCIDA] '{numero}' → {len(ids)} validador(es)")

def _pop(store, msg_id):
    d = store.pop(msg_id, None)
    if d:
        for sib in d.get("siblings", []):
            store.pop(sib, None)
    return d

def _procesar_callbacks():
    global _update_offset
    while True:
        try:
            resp = requests.get(f"{TG_API}/getUpdates",
                params={"offset": _update_offset, "timeout": 30,
                        "allowed_updates": '["callback_query"]'}, timeout=35)
            for update in resp.json().get("result", []):
                _update_offset = update["update_id"] + 1
                cb = update.get("callback_query")
                if not cb: continue
                cb_id   = cb["id"]
                cb_data = cb.get("data", "")
                msg_id  = cb.get("message", {}).get("message_id")
                user_id = str(cb.get("from", {}).get("id", ""))
                print(f"[CB] user={user_id} data={cb_data} msg_id={msg_id} pendientes={list(_pendientes.keys())}")
                if user_id not in TG_VALIDADOR_IDS:
                    _cb(cb_id, "No autorizado"); continue
                if cb_data.startswith("entrada:") or cb_data.startswith("salida:") or cb_data.startswith("no:"):
                    with _pendientes_lock:
                        datos = _pop(_pendientes, msg_id)
                    if not datos:
                        _cb(cb_id, "⚠️ Ya procesado"); continue
                    if cb_data.startswith("entrada:"):
                        datos["direccion"] = "entrada"
                        _cb(cb_id, f"🟢 {datos['numero']} → Entrada")
                        _on_ok(msg_id, datos)
                    elif cb_data.startswith("salida:"):
                        datos["direccion"] = "salida"
                        _cb(cb_id, f"🔴 {datos['numero']} → Salida")
                        _on_ok(msg_id, datos)
                    else:
                        _cb(cb_id, f"✗ {datos['numero']} descartado")
                        _on_no(msg_id, datos)
                elif cb_data.startswith("desc_ok:") or cb_data.startswith("desc_no:"):
                    with _pendientes_lock:
                        datos = _pop(_pendientes_desc, msg_id)
                    if not datos:
                        _cb(cb_id, "⚠️ Ya procesado"); continue
                    if cb_data.startswith("desc_ok:"):
                        _cb(cb_id, "📢 Enviando...")
                        _on_desc_ok(datos)
                    else:
                        _cb(cb_id, "🗑 Ignorado")
                        print(f"[DESCONOCIDA] '{datos['numero']}' ignorada")
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[CALLBACK ERROR] {e}"); time.sleep(5)

def _on_ok(msg_id, d):
    empresa, tipo = d.get("empresa","CISA"), d.get("tipo","diesel")
    caption = (
        f"✅ *VERIFICADO* — {d.get('camera_label','Cam 1')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_fmt_dir(d.get('direccion','entrada'))}\n"
        f"🔢 Número: `{d['numero']}`\n"
        f"{_fmt_emp(empresa)}\n"
        f"{_fmt_tipo(tipo)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Confianza: `{round(d['confianza']*100)}%`\n"
        f"🕐 Hora: `{d['ts']}`\n"
        f"⏱ Duración: `{d.get('duracion',0)}s`\n"
        f"_Validado manualmente_"
    )
    _foto(TG_CHAT_ID, d["frame_path"], caption)
    print(f"[VERIFICADO] {d['numero']} {d.get('direccion','')} ({empresa}/{tipo}) → grupo")
    if _on_validated_callback:
        try: _on_validated_callback(msg_id, "VERIFICADO")
        except Exception as e: print(f"[CB ERROR] {e}")

def _on_no(msg_id, d):
    import shutil
    print(f"[RECHAZADO] {d['numero']}")
    # Mover frame a carpeta de erróneas
    try:
        src = d.get("frame_path")
        if src:
            dest_dir = "/media/cisa/JETSON_SD/telegram_unidades_erroneas"
            dest = f"{dest_dir}/{src.name if hasattr(src, 'name') else str(src).split('/')[-1]}"
            shutil.move(str(src), dest)
            print(f"[RECHAZADO] Frame movido a {dest}")
    except Exception as e:
        print(f"[RECHAZADO] Error moviendo frame: {e}")
    for vid in TG_VALIDADOR_IDS:
        _msg(vid, f"🗑 `{d['numero']}` descartado manualmente")
    if _on_validated_callback:
        try: _on_validated_callback(msg_id, "RECHAZADO")
        except Exception as e: print(f"[CB ERROR] {e}")

def _on_desc_ok(d):
    caption = (
        f"🚫 *NÚMERO DESCONOCIDO* — {d.get('camera_label','Cam 1')}\n"
        f"🔢 OCR leyó: `{d['numero']}`\n"
        f"❌ No registrado en el sistema\n"
        f"📊 Confianza: `{round(d['confianza']*100)}%`\n"
        f"🕐 Hora: `{d['ts']}`\n"
        f"_Validado manualmente_"
    )
    _foto(TG_CHAT_ID, d["frame_path"], caption)

def alerta_unidad_detectada(frame_path, numero, confianza, ts, direccion='entrada'):
    empresa, tipo = _get_info(numero)
    caption = (
        f"{_fmt_dir(direccion)}\n"
        f"🔢 Número: `{numero}`\n"
        f"{_fmt_emp(empresa)}\n"
        f"{_fmt_tipo(tipo)}\n"
        f"📊 Confianza: `{round(confianza*100)}%`\n"
        f"🕐 Hora: `{ts}`"
    )
    _foto(TG_CHAT_ID, frame_path, caption)

def alerta_pipeline_error():
    _msg(TG_CHAT_ID, "🔴 *PIPELINE CAÍDO*\n_Reintentando conexión..._")


# ─── Validación automática con LLM ───────────────────────────────
from validar_llm import validar_con_llm, APROBADO, NO_CONFIRMADO, FALLBACK
from config import UNIDADES_VALIDAS

LLM_ACTIVO = VALIDAR_CON_GEMINI   # False = todo al flujo humano de siempre (ver config.py)
LLM_SOMBRA = False     # True = LLM solo opina en log; humano sigue validando


def _caption_verificado_llm(d, detalle):
    empresa, tipo = _get_info(d["numero"])
    return (
        f"\u2705 *VERIFICADO* \u2014 {d.get('camera_label','Cam 1')}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"{_fmt_dir(d.get('direccion','entrada'))}\n"
        f"\U0001F522 N\u00famero: `{d['numero']}`\n"
        f"{_fmt_emp(empresa)}\n"
        f"{_fmt_tipo(tipo)}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001F4CA Confianza: `{round(d['confianza']*100)}%`\n"
        f"\U0001F550 Hora: `{d['ts']}`\n"
        f"\U0001F916 _Validado por IA \u2014 {detalle}_"
    )


def _caption_no_confirmado(d, detalle):
    return (
        f"\u26A0\uFE0F *SIN CONFIRMAR* \u2014 {d.get('camera_label','Cam 1')}\n"
        f"{_fmt_dir(d.get('direccion','entrada'))}\n"
        f"\U0001F522 OCR ley\u00f3: `{d.get('no_detectado') or d['numero']}`\n"
        f"\U0001F916 IA: _{detalle}_\n"
        f"\U0001F4CA Confianza: `{round(d['confianza']*100)}%`\n"
        f"\U0001F550 Hora: `{d['ts']}`"
    )


def validar_y_enviar(frame_path, numero, confianza, ts, estado,
                     no_detectado=None, thumb_name=None, puerta_id=None,
                     camera_label='Cam 1', direccion='entrada', crop_path=None):
    """Devuelve (resultado, numero_final, msg_id). Ver PASOS_DESPLIEGUE.md"""
    d = {"numero": numero, "no_detectado": no_detectado or numero,
         "confianza": confianza, "ts": ts, "camera_label": camera_label,
         "direccion": direccion}

    if not LLM_ACTIVO:
        mid = enviar_a_validador(frame_path, numero, confianza, ts, estado,
                                 no_detectado, thumb_name, puerta_id,
                                 camera_label, direccion)
        return FALLBACK, numero, mid

    resultado, numero_llm, detalle = validar_con_llm(
        frame_path, numero, UNIDADES_VALIDAS, ruta_crop=crop_path)

    if LLM_SOMBRA:
        print(f"[LLM-SOMBRA] ocr={numero} llm={numero_llm} "
              f"res={resultado} | {detalle}")
        mid = enviar_a_validador(frame_path, numero, confianza, ts, estado,
                                 no_detectado, thumb_name, puerta_id,
                                 camera_label, direccion)
        return FALLBACK, numero, mid

    if resultado == APROBADO:
        if str(numero_llm) == str(numero):
            d["numero"] = numero_llm
            _foto(TG_CHAT_ID, frame_path, _caption_verificado_llm(d, detalle))
            print(f"[LLM-VERIFICADO] {numero_llm} {direccion} -> grupo | {detalle}")
            return APROBADO, numero_llm, None
        print(f"[LLM-DESACUERDO] ocr={numero} llm={numero_llm} -> humano")
        mid = enviar_a_validador(frame_path, numero, confianza, ts, estado,
                                 no_detectado, thumb_name, puerta_id,
                                 camera_label, direccion)
        return FALLBACK, numero, mid

    if resultado == NO_CONFIRMADO:
        if numero_llm and "sin match" in detalle:
            print(f"[LLM-FUERA-PADRON] llm={numero_llm} -> humano")
            mid = enviar_a_validador(frame_path, numero, confianza, ts, estado,
                                     no_detectado, thumb_name, puerta_id,
                                     camera_label, direccion)
            return FALLBACK, numero, mid
        _foto(TG_CHAT_ID, frame_path, _caption_no_confirmado(d, detalle))
        print(f"[LLM-SIN-CONFIRMAR] ocr={numero} | {detalle}")
        return NO_CONFIRMADO, numero_llm or numero, None

    print(f"[LLM-FALLBACK] {detalle} -> validador humano")
    mid = enviar_a_validador(frame_path, numero, confianza, ts, estado,
                             no_detectado, thumb_name, puerta_id,
                             camera_label, direccion)
    return FALLBACK, numero, mid
# ─────────────────────────────────────────────────────────────────

if not SIN_TELEGRAM:
    threading.Thread(target=_procesar_callbacks, daemon=True).start()
print(f"[VALIDADOR] Listener iniciado — {len(TG_VALIDADOR_IDS)} validadores")
_msg(TG_VALIDADOR_IDS[0], "🟢 *Sistema CISA iniciado*\n_Lista para recibir detecciones._")