/**
 * CISA - Lógica del visor minimalista
 * ======================================
 * Usado por: templates/html/home.html
 *
 * Responsabilidad:
 *   Hacer polling a /api/estado cada segundo y actualizar el número
 *   en pantalla con animación de destello cuando cambia.
 *
 * API consumida (pipe_stream_v2.py):
 *   GET /api/estado → { numero, conf, ts, pipeline }
 */

'use strict';

var prev = null;

async function poll() {
  try {
    var d = await fetch('/api/estado').then(function(r) { return r.json(); });

    // Indicador de conexión (punto rojo arriba a la derecha)
    document.getElementById('dot').className = 'dot ' + (d.pipeline ? 'ok' : '');

    if (d.numero) {
      var el = document.getElementById('numero');

      if (d.numero !== prev) {
        // Número nuevo — animar destello
        el.classList.remove('flash', 'vacio');
        void el.offsetWidth;   // forzar reflow para reiniciar animación
        el.classList.add('flash');
        prev = d.numero;
      } else {
        el.classList.remove('vacio');
      }

      el.textContent = d.numero;

      var pct  = Math.round((d.conf || 0) * 100);
      var cEl  = document.getElementById('conf');
      cEl.textContent = 'confianza  ' + pct + '%';
      cEl.className   = 'conf visible';

      document.getElementById('ts').textContent = d.ts || '';
    }
  } catch(e) {
    // Silencioso — el punto rojo ya indica la pérdida de conexión
  }
}

poll();
setInterval(poll, 1000);