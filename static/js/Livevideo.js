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
        var empEl=document.getElementById('m-emp');
        var dirEl=document.getElementById('m-dir');
        if(empEl)empEl.textContent=d.empresa||'—';
        if(dirEl)dirEl.textContent=d.direccion==='entrada'?'↑ Entrada':(d.direccion==='salida'?'↓ Salida':'—');
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

/* ── Detecciones: búsqueda, filtros y paginación fija de 10 ── */
var detTilesEl   = document.getElementById('tiles');
var detEmptyEl   = document.getElementById('empty');
var detEmptyTxt  = document.getElementById('empty-txt');
var detCountEl   = document.getElementById('panel-count');
var detShownEl   = document.getElementById('det-shown');
var detPagerEl   = document.getElementById('det-pager');
var detPageInfoEl= document.getElementById('det-page-info');
var detPrevEl    = document.getElementById('det-prev');
var detNextEl    = document.getElementById('det-next');
var detRefreshEl = document.getElementById('det-refresh');
var detQEl       = document.getElementById('det-q');
var detQClearEl  = document.getElementById('det-q-clear');
var detEmpresaEl = document.getElementById('det-empresa');
var detFiltersClearEl = document.getElementById('det-filters-clear');
var detDateBtn   = document.getElementById('det-date-btn');
var detDateLabel = document.getElementById('det-date-label');
var detDatePop   = document.getElementById('det-date-pop');
var detDesdeEl   = document.getElementById('det-desde');
var detHastaEl   = document.getElementById('det-hasta');
var detDateApply = document.getElementById('det-date-apply');
var detDateClear = document.getElementById('det-date-clear');
var detDateHint  = document.getElementById('det-date-hint');

var ESTADOS={
    'pendiente':{tile:'s-pendiente',badge:'b-pendiente',label:'⏳ Pendiente'},
    'VERIFICADO':{tile:'s-VERIFICADO',badge:'b-VERIFICADO',label:'✓ Verificado'},
    'CORREGIDO':{tile:'s-CORREGIDO',badge:'b-CORREGIDO',label:'✎ Corregido'},
    'RECHAZADO':{tile:'s-RECHAZADO',badge:'b-RECHAZADO',label:'✗ Rechazado'}
};

function getE(e){return ESTADOS[e]||ESTADOS['VERIFICADO'];}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtNum(n){return Number(n||0).toLocaleString('es-MX');}
function fmtTime(ts){
    if(!ts) return '';
    var d=new Date(String(ts).replace(' ','T'));
    if(isNaN(d.getTime())) return String(ts).slice(-8);
    var ahora=new Date();
    var hora=d.toLocaleTimeString('es-MX',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
    if(d.toDateString()===ahora.toDateString()) return hora;
    var dia=d.toLocaleDateString('es-MX',{day:'2-digit',month:'short'});
    return dia+' '+hora.slice(0,5);
}
function makeTile(data){
    var num=data.numero||data.no_economico||data.no_detectado||'—';
    var emp=data.empresa||'';
    var estado=data.estado||'VERIFICADO',ts=data.ts||data.hora_paso||'';
    var dir=data.direccion==='entrada'?'entrada':(data.direccion==='salida'?'salida':'');
    var dirTxt=dir==='entrada'?'↑ Entrada':(dir==='salida'?'↓ Salida':'');
    var fuera=data.en_padron===false;
    var thumbUrl=data.thumb_url||data.captura_url||null,info=getE(estado);
    var div=document.createElement('div');div.className='tile '+info.tile;
    if(data.id!=null)div.dataset.id=String(data.id);
    div.setAttribute('data-info',JSON.stringify(data));
    div.onclick=function(){openModal(this.getAttribute('data-info'));};
    var imgHtml;
    if(thumbUrl){imgHtml='<img class="tile-img" src="'+esc(thumbUrl)+'" alt="'+esc(num)+'" onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'"><div class="tile-ph" style="display:none">🚌</div>';}
    else imgHtml='<div class="tile-ph">🚌</div>';
    var empHtml=emp?'<div class="tile-emp'+(fuera?' fuera':'')+'">'+esc(emp)+(fuera?' · fuera de padrón':'')+'</div>':'';
    var dirHtml=dirTxt?'<span class="tile-dir '+dir+'">'+dirTxt+'</span>':'';
    div.innerHTML=imgHtml+'<div class="tile-body"><div class="tile-num">'+esc(num)+'</div>'+empHtml+
        '<div class="tile-meta"><span class="badge '+info.badge+'" data-badge>'+info.label+'</span>'+
        dirHtml+'<span class="tile-time">'+fmtTime(ts)+'</span></div></div>';
    return div;
}

var detState={
    pageSize:10, page:1, totalPages:1, cursors:{1:null},
    total:0, loading:false,
    q:'', empresa:'', desde:'', hasta:'', seq:0, horaCorte:3
};

function hayFiltros(){return !!(detState.q||detState.empresa||detState.desde||detState.hasta);}

function isoLocal(d){
    var m=String(d.getMonth()+1).padStart(2,'0'),dia=String(d.getDate()).padStart(2,'0');
    return d.getFullYear()+'-'+m+'-'+dia;
}
function fechaOperativa(d){
    var x=new Date(d.getTime());
    x.setHours(x.getHours()-detState.horaCorte);
    return isoLocal(x);
}
function sumarDias(iso,dias){
    var p=iso.split('-');
    var d=new Date(Number(p[0]),Number(p[1])-1,Number(p[2]));
    d.setDate(d.getDate()+dias);
    return isoLocal(d);
}
function fechaCorta(iso){
    if(!iso) return '';
    var p=iso.split('-');
    var d=new Date(Number(p[0]),Number(p[1])-1,Number(p[2]));
    return d.toLocaleDateString('es-MX',{day:'2-digit',month:'short'});
}
function textoFecha(){
    if(detState.desde&&detState.hasta){
        if(detState.desde===detState.hasta)return fechaCorta(detState.desde);
        return fechaCorta(detState.desde)+' – '+fechaCorta(detState.hasta);
    }
    if(detState.desde)return 'Desde '+fechaCorta(detState.desde);
    if(detState.hasta)return 'Hasta '+fechaCorta(detState.hasta);
    return 'Fechas';
}

function clearDetTiles(){
    var tiles=detTilesEl.querySelectorAll('.tile');
    for(var i=0;i<tiles.length;i++)tiles[i].remove();
}
function showDetEmpty(msg){
    detEmptyTxt.textContent=msg;
    detEmptyEl.hidden=false;
}
function updateDetUI(){
    detCountEl.textContent=fmtNum(detState.total);
    detFiltersClearEl.hidden=!hayFiltros();
    detDateBtn.classList.toggle('active',!!(detState.desde||detState.hasta));
    detDateLabel.textContent=textoFecha();

    detPagerEl.hidden=detState.total===0;
    detPrevEl.disabled=detState.loading||detState.page<=1;
    detNextEl.disabled=detState.loading||detState.page>=detState.totalPages||
        !(detState.page+1 in detState.cursors);
    detRefreshEl.disabled=detState.loading;
    detPageInfoEl.textContent=detState.page+' / '+Math.max(1,detState.totalPages);

    if(detState.loading){
        detShownEl.textContent='Cargando…';
    }else if(detState.total>0){
        var inicio=(detState.page-1)*detState.pageSize+1;
        var fin=Math.min(detState.page*detState.pageSize,detState.total);
        detShownEl.textContent='Mostrando '+inicio+'–'+fin+' de '+fmtNum(detState.total);
    }else{
        detShownEl.textContent='';
    }
}
function detUrl(cursor){
    var p=new URLSearchParams();
    p.set('limit',String(detState.pageSize));
    if(detState.q)p.set('q',detState.q);
    if(detState.empresa)p.set('empresa',detState.empresa);
    if(detState.desde)p.set('desde',detState.desde);
    if(detState.hasta)p.set('hasta',detState.hasta);
    if(cursor){p.set('cursor_hora',cursor.hora);p.set('cursor_id',String(cursor.id));}
    return '/api/detecciones?'+p.toString();
}
function cargarPagina(pagina){
    if(detState.loading)return;
    if(!(pagina in detState.cursors))return;
    var seq=++detState.seq;
    var cursor=detState.cursors[pagina];
    detState.loading=true;
    updateDetUI();
    fetch(detUrl(cursor))
        .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
        .then(function(data){
            if(seq!==detState.seq)return;
            if(data.error)throw new Error(data.error);
            if(typeof data.hora_corte==='number'){
                detState.horaCorte=data.hora_corte;
                detDateHint.textContent='Se filtra por día operativo (corte '+
                    String(data.hora_corte).padStart(2,'0')+':00).';
            }
            detState.total=data.total||0;
            detState.page=pagina;
            detState.totalPages=Math.max(1,Math.ceil(detState.total/detState.pageSize));

            for(var k in detState.cursors){
                if(Number(k)>pagina)delete detState.cursors[k];
            }
            if(data.next_cursor)detState.cursors[pagina+1]=data.next_cursor;
            else delete detState.cursors[pagina+1];

            clearDetTiles();
            var items=data.items||[];
            for(var i=0;i<items.length;i++)detTilesEl.appendChild(makeTile(items[i]));
            detEmptyEl.hidden=items.length>0;
            if(items.length===0){
                showDetEmpty(hayFiltros()?'No hay detecciones con esos filtros.':'Esperando detecciones…');
            }
            detTilesEl.scrollTop=0;
            detState.loading=false;
            updateDetUI();
        })
        .catch(function(){
            if(seq!==detState.seq)return;
            detState.loading=false;
            if(detState.total===0){
                detState.totalPages=1;
                showDetEmpty('No se pudieron cargar las detecciones.');
            }
            updateDetUI();
        });
}

function resetAndLoad(){
    detState.loading=false;
    detState.page=1;
    detState.total=0;
    detState.totalPages=1;
    detState.cursors={1:null};
    detTilesEl.scrollTop=0;
    clearDetTiles();
    detEmptyEl.hidden=true;
    cargarPagina(1);
}

/* Búsqueda por número económico o empresa */
var detQTimer=null;
detQEl.addEventListener('input',function(){
    detQClearEl.hidden=!detQEl.value;
    clearTimeout(detQTimer);
    detQTimer=setTimeout(function(){
        detState.q=detQEl.value.trim();
        resetAndLoad();
    },350);
});
detQEl.addEventListener('keydown',function(e){
    if(e.key==='Enter'){
        clearTimeout(detQTimer);
        detState.q=detQEl.value.trim();
        resetAndLoad();
    }
});
detQClearEl.addEventListener('click',function(){
    detQEl.value='';
    detQClearEl.hidden=true;
    detState.q='';
    resetAndLoad();
    detQEl.focus();
});

/* Filtro por empresa */
detEmpresaEl.addEventListener('change',function(){
    detState.empresa=detEmpresaEl.value;
    resetAndLoad();
});
function cargarEmpresas(){
    fetch('/api/detecciones/empresas')
        .then(function(r){return r.ok?r.json():null;})
        .then(function(data){
            var empresas=(data&&data.empresas)||[];
            for(var i=0;i<empresas.length;i++){
                var o=document.createElement('option');
                o.value=empresas[i];o.textContent=empresas[i];
                detEmpresaEl.appendChild(o);
            }
        }).catch(function(){});
}

/* Filtro por fechas */
function abrirPop(abrir){
    detDatePop.hidden=!abrir;
    detDateBtn.setAttribute('aria-expanded',abrir?'true':'false');
    if(abrir){
        detDesdeEl.value=detState.desde;
        detHastaEl.value=detState.hasta;
    }
}
detDateBtn.addEventListener('click',function(e){
    e.stopPropagation();
    abrirPop(detDatePop.hidden);
});
document.addEventListener('click',function(e){
    if(!detDatePop.hidden&&!detDatePop.contains(e.target)&&e.target!==detDateBtn&&!detDateBtn.contains(e.target)){
        abrirPop(false);
    }
});
document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!detDatePop.hidden)abrirPop(false);
});
var detPresets=detDatePop.querySelectorAll('[data-preset]');
for(var dp=0;dp<detPresets.length;dp++){
    detPresets[dp].addEventListener('click',function(){
        var hoyOp=fechaOperativa(new Date()),desde,hasta;
        if(this.getAttribute('data-preset')==='hoy'){
            desde=hasta=hoyOp;
        }else if(this.getAttribute('data-preset')==='ayer'){
            desde=hasta=sumarDias(hoyOp,-1);
        }else{
            desde=sumarDias(hoyOp,-6);hasta=hoyOp;
        }
        detDesdeEl.value=desde;
        detHastaEl.value=hasta;
    });
}
detDateApply.addEventListener('click',function(){
    var desde=detDesdeEl.value||'',hasta=detHastaEl.value||'';
    if(desde&&hasta&&desde>hasta){var t=desde;desde=hasta;hasta=t;}
    detState.desde=desde;
    detState.hasta=hasta;
    abrirPop(false);
    resetAndLoad();
});
detDateClear.addEventListener('click',function(){
    detDesdeEl.value='';
    detHastaEl.value='';
    detState.desde='';
    detState.hasta='';
    abrirPop(false);
    resetAndLoad();
});
detFiltersClearEl.addEventListener('click',function(){
    detQEl.value='';
    detQClearEl.hidden=true;
    detEmpresaEl.value='';
    detDesdeEl.value='';
    detHastaEl.value='';
    detState.q='';
    detState.empresa='';
    detState.desde='';
    detState.hasta='';
    abrirPop(false);
    resetAndLoad();
});

/* Paginación fija de 10 */
function irPagina(delta){
    if(detState.loading)return;
    var destino=detState.page+delta;
    if(destino<1||destino>detState.totalPages)return;
    if(!(destino in detState.cursors))return;
    cargarPagina(destino);
}
detPrevEl.addEventListener('click',function(){irPagina(-1);});
detNextEl.addEventListener('click',function(){irPagina(1);});
detRefreshEl.addEventListener('click',resetAndLoad);

cargarEmpresas();
resetAndLoad();

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
      '<button class="vp-btn" data-sig="-1" title="Video más reciente">\u2039 Anterior</button>' +
      '<button class="vp-btn" data-sig="1" title="Video más viejo">Siguiente \u203a</button>' +
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
      mandar(b.getAttribute('data-sig') === '-1' ? '/api/prueba/anterior' : '/api/prueba/siguiente');
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
      nombre.textContent = d.video + (d.videos > 1 ? '  \u00b7  ' + d.indice + ' de ' + d.videos : '');
      nombre.title = 'El 1 es el video más reciente';
      if (!arrastrando && Date.now() > ignorarHasta) base = {pos: d.pos, t: Date.now()};
    }).catch(function () {});
  }
  revisar();
  setInterval(revisar, 1000);
})();
