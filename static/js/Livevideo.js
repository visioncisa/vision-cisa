'use strict';

/* ── Modal ── */
function openModal(infoStr){
    try{
        var d=JSON.parse(infoStr);
        var imgEl=document.getElementById('modal-img');
        var src=d.frame_url||d.thumb_url||d.captura_url||'';
        imgEl.onerror=function(){var f=d.thumb_url||d.captura_url; if(f&&imgEl.src.indexOf(f)===-1)imgEl.src=f;};
        imgEl.src=src;
        document.getElementById('modal-num').textContent=d.numero||'—';
        document.getElementById('m-leido').textContent=d.leido||d.no_detectado||d.numero||'—';
        document.getElementById('m-estado').textContent=d.estado||'—';
        document.getElementById('m-conf').textContent=d.conf?Math.round(d.conf*100)+'%':'—';
        document.getElementById('m-ts').textContent=d.ts||d.hora_paso||'—';
        document.getElementById('m-cls').textContent=(d.cls||'').replace('numero_','')||'—';
        document.getElementById('modal').classList.add('open');
    }catch(e){console.error(e);}
}

function closeModal(){document.getElementById('modal').classList.remove('open');document.getElementById('modal-img').src='';}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});

/* ── Video en vivo (MJPEG desde Flask, sin ffmpeg) ── */
var video=document.getElementById('video');
var overlay=document.getElementById('vid-overlay');
var isVideoTransitioning=false;
var mjpegRetries=0;

function startPlayer(){
    video.onerror=function(){
        mjpegRetries++;
        overlay.classList.remove('hidden');
        setTimeout(startPlayer,Math.min(mjpegRetries*2000,10000));
    };
    video.src='/api/video.mjpeg?t='+Date.now();
}
setInterval(function(){
    if(video.naturalWidth>0){overlay.classList.add('hidden');mjpegRetries=0;}
},500);
startPlayer();

/* ── Selector de cámara ── */
var _activeCam=1;
function switchCamera(num){
if(num===_activeCam)return;
var btn1=document.getElementById('btn-cam1'),btn2=document.getElementById('btn-cam2');
var activeBtn=num===1?btn1:btn2,inactiveBtn=num===1?btn2:btn1;
activeBtn.classList.add('active');inactiveBtn.classList.remove('active');
_activeCam=num;
if(num===2){
    // Cam 2 → go2rtc (proxy sin CPU/GPU en Jetson)
    // go2rtc WebRTC — funciona con H.265 en todos los navegadores
    var panel=document.getElementById('video-panel');
    var iframe=document.getElementById('go2rtc-frame');
    if(!iframe){
        iframe=document.createElement('iframe');
        iframe.id='go2rtc-frame';
        iframe.style.cssText='width:100%;height:100%;border:none;position:absolute;top:0;left:0;z-index:10;';
        panel.style.position='relative';
        panel.appendChild(iframe);
    }
    iframe.src='http://'+window.location.hostname+':1984/stream.html?src=cam2&media=video';
    iframe.style.display='block';
    video.style.display='none';
}else{
    // Cam 1 → go2rtc main stream 4K (detecciones siguen en subtype=1)
    var panel=document.getElementById('video-panel');
    var iframe=document.getElementById('go2rtc-frame');
    if(!iframe){
        iframe=document.createElement('iframe');
        iframe.id='go2rtc-frame';
        iframe.style.cssText='width:100%;height:100%;border:none;position:absolute;top:0;left:0;z-index:10;';
        panel.style.position='relative';
        panel.appendChild(iframe);
    }
    iframe.src='http://'+window.location.hostname+':1984/stream.html?src=cam1&media=video';
    iframe.style.display='block';
    video.style.display='none';
}
}

/* ── Estado ── */
function setDot(id,ok){document.getElementById(id).className='dot'+(ok?' ok':' err');}
function pollEstado(){
fetch('/api/estado').then(function(r){return r.json();}).then(function(d){
    setDot('dot-yolo',d.yolo_fps>0);
    document.getElementById('txt-yolo').textContent='YOLO '+(d.yolo_fps||0)+' fps';
    setDot('dot-pg',d.pg_conectada);
    document.getElementById('txt-pg').textContent=d.pg_conectada?'PG '+(d.unidades_registradas||0)+'u':'PG ERR';
    setDot('dot-cam',d.pipeline);
    document.getElementById('txt-cam').textContent=d.pipeline?'CAM OK':'CAM ERR';

    var swOverlay=document.getElementById('cam-switching');
    var btn1=document.getElementById('btn-cam1'),btn2=document.getElementById('btn-cam2');
    if(d.switching||isVideoTransitioning){
        swOverlay.classList.add('show');
        document.getElementById('sw-text').textContent='CONECTANDO CAM '+(d.active_camera||'')+'…';
        btn1.disabled=true;btn2.disabled=true;
    }else{
        swOverlay.classList.remove('show');
        btn1.disabled=false;btn2.disabled=false;
    }
    // No resetear cámara activa desde el servidor — el usuario la controla localmente
    btn1.className='cam-btn'+(_activeCam===1?' active':'');
    btn2.className='cam-btn'+(_activeCam===2?' active':'');
    
    var tb=document.getElementById('track-badge');
    if(d.tracking){
        document.getElementById('track-txt').textContent=d.tracking+' · '+Math.round(d.tracking_duracion||0)+'s';
        tb.classList.remove('hidden');
    }else tb.classList.add('hidden');
        document.getElementById('hora').textContent=new Date().toLocaleTimeString('es-MX');
    }).catch(function(){document.getElementById('hora').textContent=new Date().toLocaleTimeString('es-MX');});
}
setInterval(pollEstado,1000);pollEstado();

/* ── Detecciones ── */
var tilesEl=document.getElementById('tiles'),emptyEl=document.getElementById('empty'),countEl=document.getElementById('panel-count');
var seen={},byMsgId={},MAX_TILES=10;
var ESTADOS={
    'pendiente':{tile:'s-pendiente',badge:'b-pendiente',label:'⏳ Pendiente'},
    'VERIFICADO':{tile:'s-VERIFICADO',badge:'b-VERIFICADO',label:'✓ Verificado'},
    'CORREGIDO':{tile:'s-CORREGIDO',badge:'b-CORREGIDO',label:'✎ Corregido'},
    'RECHAZADO':{tile:'s-RECHAZADO',badge:'b-RECHAZADO',label:'✗ Rechazado'}
};

function getE(e){return ESTADOS[e]||ESTADOS['pendiente'];}
function fmtTime(ts){if(!ts)return'';try{return new Date(ts.replace(' ','T')).toLocaleTimeString('es-MX',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}catch(e){return String(ts).slice(-8);}}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function makeTile(data){
    var num=data.numero||data.no_economico||data.no_detectado||'—';
    var estado=data.estado||'VERIFICADO',ts=data.ts||data.hora_paso||'';
    var thumbUrl=data.thumb_url||data.captura_url||null,info=getE(estado);
    var div=document.createElement('div');div.className='tile '+info.tile;
    div.setAttribute('data-info',JSON.stringify(data));
    div.onclick=function(){openModal(this.getAttribute('data-info'));};
    var imgHtml;
    if(thumbUrl){imgHtml='<img class="tile-img" src="'+esc(thumbUrl)+'" alt="'+esc(num)+'" onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'"><div class="tile-ph" style="display:none">🚌</div>';}
    else imgHtml='<div class="tile-ph">🚌</div>';
    div.innerHTML=imgHtml+'<div class="tile-body"><div class="tile-num">'+esc(num)+'</div><div class="tile-meta"><span class="badge '+info.badge+'" data-badge>'+info.label+'</span><span class="tile-time">'+fmtTime(ts)+'</span></div></div>';
    if(data.msg_id)byMsgId[data.msg_id]=div;
    return div;
}

function updateTile(tile,estado){var info=getE(estado);tile.className='tile '+info.tile;var b=tile.querySelector('[data-badge]');if(b){b.className='badge '+info.badge;b.textContent=info.label;}try{var d=JSON.parse(tile.getAttribute('data-info'));d.estado=estado;tile.setAttribute('data-info',JSON.stringify(d));}catch(e){}}
function insertTile(tile){if(tilesEl.contains(emptyEl))tilesEl.removeChild(emptyEl);tilesEl.insertBefore(tile,tilesEl.firstChild);}
function tileKey(item,kind){var ts=item.ts||item.hora_paso||'';var num=item.numero||item.no_economico||item.no_detectado||'';return kind+':'+ts+':'+num;}
function pollDetecciones(){
    fetch('/api/detecciones-recent').then(function(r){return r.json();}).then(function(data){
        var pending=data.pending||[],approved=data.approved||[];
        for(var i=pending.length-1;i>=0;i--){var p=pending[i],mid=p.msg_id;
        if(mid&&byMsgId[mid]){var cur=byMsgId[mid].className,exp='tile '+getE(p.estado).tile;if(cur!==exp)updateTile(byMsgId[mid],p.estado);continue;}
        var key=tileKey(p,'p');if(seen[key])continue;seen[key]=true;insertTile(makeTile(p));}
        for(var j=approved.length-1;j>=0;j--){var a=approved[j],key2=tileKey(a,'a');if(seen[key2])continue;seen[key2]=true;insertTile(makeTile(a));}
        var all=tilesEl.querySelectorAll('.tile');
        while(all.length>MAX_TILES){var last=tilesEl.lastElementChild;if(last&&last!==emptyEl){if(last.dataset&&last.dataset.mid)delete byMsgId[last.dataset.mid];tilesEl.removeChild(last);all=tilesEl.querySelectorAll('.tile');}else break;}
        if(seen&&Object.keys(seen).length>300){seen={};pending.concat(approved).forEach(function(x){seen[tileKey(x,'p')]=seen[tileKey(x,'a')]=true;});}
        var n=tilesEl.querySelectorAll('.tile').length;countEl.textContent=n;
        if(n===0&&!tilesEl.contains(emptyEl))tilesEl.appendChild(emptyEl);
    }).catch(function(){});
}
setInterval(pollDetecciones,3000);pollDetecciones();

/* ── Modo prueba: controles tipo YouTube sobre el video (solo con video grabado) ── */
(function () {
  var estilo = document.createElement('style');
  estilo.textContent = [
    '.vp{position:absolute;left:0;right:0;bottom:0;z-index:5;display:none;flex-direction:column;gap:6px;',
    '  padding:28px 14px 10px;color:#fff;font:600 13px/1.2 system-ui,sans-serif;',
    '  background:linear-gradient(to top,rgba(0,0,0,.78),rgba(0,0,0,0))}',
    '.vp.vp-fijo{position:fixed;left:12px;right:12px;bottom:12px;border-radius:12px;padding:10px 14px;background:rgba(15,23,42,.92)}',
    '.vp-fila{display:flex;align-items:center;gap:8px}',
    '.vp-btn{border:0;border-radius:6px;padding:5px 10px;background:rgba(255,255,255,.14);color:#fff;font:inherit;cursor:pointer;white-space:nowrap}',
    '.vp-btn:hover{background:rgba(255,255,255,.28)}',
    '.vp-tiempo{font-variant-numeric:tabular-nums;margin-left:6px}',
    '.vp-nombre{margin-left:auto;margin-right:6px;opacity:.7;font-weight:500;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.vp-barra{-webkit-appearance:none;appearance:none;width:100%;height:4px;margin:0;border-radius:2px;outline:none;cursor:pointer;',
    '  background:linear-gradient(to right,#e11d2e var(--p,0%),rgba(255,255,255,.35) var(--p,0%))}',
    '.vp-barra:hover{height:6px}',
    '.vp-barra::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:#e11d2e;border:0}',
    '.vp-barra::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:#e11d2e;border:0}',
    '.vp-barra::-moz-range-track{background:transparent}'
  ].join('\n');
  document.head.appendChild(estilo);

  var caja = document.createElement('div');
  caja.className = 'vp';
  caja.innerHTML =
    '<input class="vp-barra" type="range" min="0" max="100" step="0.1" value="0">' +
    '<div class="vp-fila">' +
      '<button class="vp-btn" data-s="-10">\u221210 s</button>' +
      '<button class="vp-btn" data-s="10">+10 s</button>' +
      '<span class="vp-tiempo">0:00 / 0:00</span>' +
      '<span class="vp-nombre"></span>' +
      '<button class="vp-btn" data-sig="1">Siguiente \u203a</button>' +
    '</div>';
  var barra = caja.querySelector('.vp-barra');
  var tiempo = caja.querySelector('.vp-tiempo');
  var nombre = caja.querySelector('.vp-nombre');

  var base = {pos: 0, t: Date.now()};   // posición conocida y el momento en que se supo
  var dur = 0, activo = false, arrastrando = false, ignorarHasta = 0, ultimoEnvio = 0;

  function fmt(s) {
    s = Math.max(0, Math.floor(s));
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (x < 10 ? '0' : '') + x;
  }
  function pintar(pos) {
    pos = Math.min(Math.max(0, pos), dur || 0);
    tiempo.textContent = fmt(pos) + ' / ' + fmt(dur);
    barra.style.setProperty('--p', (dur ? pos / dur * 100 : 0) + '%');
    return pos;
  }
  function posActual() { return Math.min(base.pos + (Date.now() - base.t) / 1000, dur); }
  function mandar(ruta, cuerpo) {
    return fetch(ruta, {method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(cuerpo || {})})
      .then(function (r) { return r.json(); }).catch(function () { return {ok: false}; });
  }
  function ir(seg) {   // se ve al instante; el servidor lo confirma después
    seg = Math.min(Math.max(0, seg), dur);
    base = {pos: seg, t: Date.now()};
    ignorarHasta = Date.now() + 800;
    barra.value = pintar(seg);
    return mandar('/api/prueba/ir', {seg: seg});
  }
  function ubicar() {   // debajo del video, como YouTube; si no lo encuentra, abajo de la página
    var img = document.querySelector('img[src*="video.mjpeg"]');
    var sitio = img ? img.parentElement : null;
    if (sitio) {
      if (getComputedStyle(sitio).position === 'static') sitio.style.position = 'relative';
      caja.classList.remove('vp-fijo');
      if (caja.parentElement !== sitio) sitio.appendChild(caja);
    } else {
      caja.classList.add('vp-fijo');
      if (caja.parentElement !== document.body) document.body.appendChild(caja);
    }
  }

  caja.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.getAttribute('data-sig')) {
      base = {pos: 0, t: Date.now()};
      ignorarHasta = Date.now() + 800;
      mandar('/api/prueba/siguiente');
    } else {
      ir(posActual() + Number(b.getAttribute('data-s')));
    }
  });
  barra.addEventListener('input', function () {   // mientras arrastras, el video te sigue
    arrastrando = true;
    var s = Number(barra.value);
    base = {pos: s, t: Date.now()};
    ignorarHasta = Date.now() + 800;
    pintar(s);
    if (Date.now() - ultimoEnvio > 250) {
      ultimoEnvio = Date.now();
      mandar('/api/prueba/ir', {seg: s});
    }
  });
  barra.addEventListener('change', function () {
    ir(Number(barra.value));
    arrastrando = false;
  });

  setInterval(function () {   // avanza solo, suave, entre una consulta y otra
    if (!activo || arrastrando) return;
    barra.value = pintar(posActual());
  }, 200);

  function revisar() {
    fetch('/api/prueba/estado').then(function (r) { return r.json(); }).then(function (d) {
      activo = !!d.prueba;
      caja.style.display = activo ? 'flex' : 'none';
      if (!activo) return;
      ubicar();
      dur = d.dur;
      barra.max = Math.max(1, d.dur);
      nombre.textContent = d.video;
      if (!arrastrando && Date.now() > ignorarHasta) base = {pos: d.pos, t: Date.now()};
    }).catch(function () {});
  }
  revisar();
  setInterval(revisar, 1000);
})();
