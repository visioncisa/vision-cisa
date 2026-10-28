'use strict';

/* ════════════════════════════════════════════════════════════
    CONFIG
═══════════════════════════════════════════════════════════════ */
// Debe coincidir con HORA_CORTE_DIA en config.py (backend).
// Si cambias uno, cambia el otro.
var HORA_CORTE_DIA = 3;

/* ════════════════════════════════════════════════════════════
    PALETA
═══════════════════════════════════════════════════════════════ */
var C = {
    blue:'#0b4f9e', blueLt:'#4a90d9',
    red:'#d72631',  redLt:'#ef5b63',
    ink:'#0f1f33',  ink2:'#54657c',   ink3:'#93a2b5',
    line:'#e2e9f1',
    amber:'#e08a1e', teal:'#1f9d9d',  gray:'#9aa7b8',
    ok:'#1f9d57',   blue2:'#1a7abd'
};

var EMPRESA_COLOR = {
    'CISA':        C.blue,
    'COPATSA':     C.red,
    'CCISA':       C.teal,
    'Desconocida': C.gray
};

var ZONA_COLOR = {
    'Delantero': C.blue,
    'Trasero':   C.red,
    'Lateral':   C.amber
};

/* ════════════════════════════════════════════════════════════
    DATOS DEMO (fallback sin backend)
═══════════════════════════════════════════════════════════════ */
var DEMO = {
    detecciones_hoy: 80,
    detecciones_ayer: 68,
    entradas: 46,
    salidas: 34,
    promedio_hora: 7,
    total_acumulado: 2084,
    telegram_hoy: 80,
    ultima: { numero:'585', empresa:'CISA', zona:'Lateral', movimiento:'Entrada', conf:0.95, ts:'18:45:11' },
    por_hora: {
        horas:    ['03','04','05','06','07','08','09','10','11','12','13','14','15','16','17','18','19','20','21','22','23','00','01','02'],
        entradas: [0,0,3,8,12,6,4,2,3,1,1,2,3,2,3,4,5,3,2,1,0,2,1,0],
        salidas:  [0,0,2,6,10,5,3,2,2,1,1,1,2,2,3,3,4,2,1,1,0,1,0,0]
    },
    por_semana: {
        horas:    ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'],
        entradas: [42,38,50,46,41,20,10],
        salidas:  [40,35,47,34,39,18,8]
    },
    por_mes: {
        horas:    ['S1','S2','S3','S4'],
        entradas: [180,210,195,220],
        salidas:  [170,200,188,215]
    },
    por_anio: {
        horas:    ['Ago','Sep','Oct','Nov','Dic','Ene','Feb','Mar','Abr','May','Jun','Jul'],
        entradas: [820,790,850,910,880,760,700,910,940,960,980,1005],
        salidas:  [800,780,830,895,870,745,690,895,930,945,965,990]
    },
    por_empresa: { 'CISA':72, 'COPATSA':8, 'CCISA':0, 'Desconocida':0 },
    por_zona:    { 'Lateral':75, 'Delantero':1, 'Trasero':4 },
    top_unidades: [
        { numero:'585',  empresa:'CISA',    count:4 },
        { numero:'5020', empresa:'CISA',    count:3 },
        { numero:'522',  empresa:'CISA',    count:3 },
        { numero:'587',  empresa:'CISA',    count:2 },
        { numero:'2514', empresa:'COPATSA', count:2 }
    ],
    dentro_ahora: { 'CISA':10, 'COPATSA':2, 'CCISA':0 },
    prom_estancia: { 'CISA':102, 'COPATSA':125 },
    estancias: [
        { no_economico:'585',  empresa:'CISA',    ultimo_ingreso:'14:20', ultima_salida:null,    minutos_dentro:null, minutos_fuera:78,  viajes:2, status:'dentro' },
        { no_economico:'5020', empresa:'CISA',    ultimo_ingreso:'11:05', ultima_salida:'16:22', minutos_dentro:195,  minutos_fuera:null,viajes:2, status:'fuera'  },
        { no_economico:'522',  empresa:'CISA',    ultimo_ingreso:'04:10', ultima_salida:'08:30', minutos_dentro:260,  minutos_fuera:null,viajes:1, status:'fuera'  },
        { no_economico:'587',  empresa:'CISA',    ultimo_ingreso:'15:10', ultima_salida:null,    minutos_dentro:null, minutos_fuera:42,  viajes:2, status:'dentro' },
        { no_economico:'2514', empresa:'COPATSA', ultimo_ingreso:'06:00', ultima_salida:'10:30', minutos_dentro:270,  minutos_fuera:null,viajes:1, status:'fuera'  },
        { no_economico:'506',  empresa:'CISA',    ultimo_ingreso:'19:00', ultima_salida:null,    minutos_dentro:null, minutos_fuera:20,  viajes:3, status:'dentro' },
        { no_economico:'5028', empresa:'CISA',    ultimo_ingreso:'08:20', ultima_salida:'12:00', minutos_dentro:220,  minutos_fuera:null,viajes:1, status:'fuera'  },
        { no_economico:'2501', empresa:'COPATSA', ultimo_ingreso:'07:00', ultima_salida:null,    minutos_dentro:null, minutos_fuera:60,  viajes:1, status:'dentro' },
        { no_economico:'583',  empresa:'CISA',    ultimo_ingreso:'03:45', ultima_salida:'17:10', minutos_dentro:385,  minutos_fuera:null,viajes:2, status:'fuera'  },
        { no_economico:'576',  empresa:'CISA',    ultimo_ingreso:'02:30', ultima_salida:'09:15', minutos_dentro:165,  minutos_fuera:null,viajes:1, status:'fuera'  }
    ]
};

/* ════════════════════════════════════════════════════════════
    ESTADO GLOBAL
═══════════════════════════════════════════════════════════════ */
var currentView   = 'cliente';
var currentPeriod = 'hoy';        // 'hoy' | 'semana' | 'mes' | 'anio'
var usingDemo     = false;
var estanciasData = [];   // fila completa por unidad
var POR_PAGINA = 15;       // unidades por página en la tabla
var paginaUnidades = 1;
function cambiarPagina(d) { paginaUnidades += d; filterUnidades(true); }
var tickerInterval = null; // setInterval para el ticker de tiempo en vivo

/* ════════════════════════════════════════════════════════════
    UTILS
═══════════════════════════════════════════════════════════════ */
function $(id) { return document.getElementById(id); }
function nf(n) { return (n == null ? '—' : Number(n).toLocaleString('es-MX')); }
function setDot(id, ok) { $(id).className = 'dot' + (ok ? ' ok' : ' err'); }

function flagDemo(on) {
    usingDemo = on;
    $('demo-flag').classList.toggle('show', on);
}

function hexA(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}

/**
 * Convierte minutos (number) a string "Xh Ym" o "Ym".
 * Si se pasa null/NaN devuelve '—'.
 */
function minsToHm(mins) {
    if (mins == null || isNaN(mins)) return '—';
    var m = Math.round(mins);
    if (m <= 0) return '0m';
    var h = Math.floor(m / 60);
    var rem = m % 60;
    if (h > 0 && rem > 0) return h + 'h ' + rem + 'm';
    if (h > 0)             return h + 'h';
    return rem + 'm';
}

/**
 * Dado un string "HH:MM" o "HH:MM:SS" de hoy,
 * devuelve los minutos transcurridos desde esa hora hasta ahora.
 * Maneja cruce de medianoche: si el resultado es negativo suma 1440.
 */
function minutesSince(timeStr) {
    if (!timeStr) return null;
    if (timeStr.indexOf('T') > 0) {              // fecha y hora completas
        var t = new Date(timeStr);
        return isNaN(t) ? null : Math.max(0, (new Date() - t) / 60000);
    }
    var parts = timeStr.split(':');
    if (parts.length < 2) return null;
    var now  = new Date();
    var then = new Date(now.getFullYear(), now.getMonth(), now.getDate(),
                        parseInt(parts[0], 10), parseInt(parts[1], 10),
                        parts[2] ? parseInt(parts[2], 10) : 0);
    var diff = (now - then) / 60000; // ms → min
    if (diff < 0) diff += 1440;      // cruce de medianoche
    return diff;
}

/** Formatea un ISO "2026-07-22T14:20:05" a "14:20" */
function horaCorta(iso) {
    if (!iso) return null;
    var t = iso.split('T')[1];
    return t ? t.slice(0,5) : iso;
}

/** Formatea un ISO "2026-07-22T14:20:05" a "22 jul" */
function fechaCorta(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d)) return iso.split('T')[0];
    var meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    return d.getDate() + ' ' + meses[d.getMonth()];
}

/* ════════════════════════════════════════════════════════════
    TOGGLE DE VISTA
═══════════════════════════════════════════════════════════════ */
function switchView(v) {
    currentView = v;
    $('sec-cliente').style.display = (v === 'cliente') ? 'flex' : 'none';
    $('sec-dev').style.display     = (v === 'dev')     ? 'flex' : 'none';
    $('vbtn-cliente').classList.toggle('active', v === 'cliente');
    $('vbtn-dev').classList.toggle('active',     v === 'dev');
    $('pills-dev').style.display = (v === 'dev') ? 'flex' : 'none';
}

$('pills-dev').style.display = 'none';

/* ════════════════════════════════════════════════════════════
    GRÁFICAS — FLUJO CLIENTE (selector período)
═══════════════════════════════════════════════════════════════ */
var flujoClienteChart = null;

function buildFlujoCliente(d) {
    var ctx = $('flujoChartCliente').getContext('2d');
    var gG = ctx.createLinearGradient(0,0,0,260);
    gG.addColorStop(0,'rgba(31,157,87,.9)');
    gG.addColorStop(1,'rgba(31,157,87,.55)');
    var gR = ctx.createLinearGradient(0,0,0,260);
    gR.addColorStop(0,'rgba(215,38,49,.9)');
    gR.addColorStop(1,'rgba(215,38,49,.55)');

    var labels = d.horas.map(function(h) {
        var clean = (h || '').replace(/:00$/, '');
        return (currentPeriod === 'hoy') ? clean + ':00' : h;
    });

    var cfg = {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                { label:'Entradas', data:d.entradas, backgroundColor:gG, borderRadius:4, maxBarThickness:20 },
                { label:'Salidas',  data:d.salidas,  backgroundColor:gR, borderRadius:4, maxBarThickness:20 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor:'#fff', titleColor:C.ink, bodyColor:C.ink2,
                    borderColor:C.line, borderWidth:1, padding:10, cornerRadius:10,
                    titleFont:{weight:'700'}, displayColors:true, boxPadding:4
                }
            },
            scales: {
                x: { grid:{display:false}, ticks:{font:{size:10}, color:C.ink3, autoSkip:true, autoSkipPadding:6, maxRotation:45, minRotation:0} },
                y: { beginAtZero:true, grid:{color:C.line, drawBorder:false}, ticks:{stepSize:5, color:C.ink3, font:{size:11}} }
            }
        }
    };

    if (flujoClienteChart) {
        flujoClienteChart.data = cfg.data;
        flujoClienteChart.update();
    } else {
        flujoClienteChart = new Chart(ctx, cfg);
    }
}

/**
 * Cambia el período activo (hoy/semana/mes/anio). Actualiza:
 *   1. la gráfica de flujo
 *   2. la tabla de control de unidades (vía /api/estancias?rango=…)
 */
function setPeriod(btn) {
    currentPeriod = btn.dataset.period;
    document.querySelectorAll('.pbtn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    refreshFlujoCliente();
    loadEstancias();
}

function refreshFlujoCliente() {
    var data = lastDashData || DEMO;
    var d;
    if (currentPeriod === 'semana')     d = data.por_semana || DEMO.por_semana;
    else if (currentPeriod === 'mes')   d = data.por_mes    || DEMO.por_mes;
    else if (currentPeriod === 'anio')  d = data.por_anio   || DEMO.por_anio;
    else                                d = data.por_hora;
    buildFlujoCliente(d);
}

/* ════════════════════════════════════════════════════════════
    GRÁFICAS — FLUJO DEV
═══════════════════════════════════════════════════════════════ */
var flujoChart = null;
Chart.defaults.font.family = "'Barlow', sans-serif";
Chart.defaults.color = C.ink2;

function buildFlujo(d) {
    var ctx = $('flujoChart').getContext('2d');
    var gB = ctx.createLinearGradient(0,0,0,260);
    gB.addColorStop(0,'rgba(11,79,158,.9)');
    gB.addColorStop(1,'rgba(11,79,158,.55)');
    var gR = ctx.createLinearGradient(0,0,0,260);
    gR.addColorStop(0,'rgba(215,38,49,.9)');
    gR.addColorStop(1,'rgba(215,38,49,.55)');

    var cfg = {
        type: 'bar',
        data: {
            labels: d.horas.map(function(h){ var c=(h||'').replace(/:00$/,''); return c+':00'; }),
            datasets: [
                { label:'Entradas', data:d.entradas, backgroundColor:gB, borderRadius:5, maxBarThickness:22 },
                { label:'Salidas',  data:d.salidas,  backgroundColor:gR, borderRadius:5, maxBarThickness:22 }
            ]
        },
        options: {
            responsive:true, maintainAspectRatio:false,
            plugins:{
                legend:{display:false},
                tooltip:{backgroundColor:'#fff',titleColor:C.ink,bodyColor:C.ink2,
                    borderColor:C.line,borderWidth:1,padding:10,cornerRadius:10,
                    titleFont:{weight:'700'},displayColors:true,boxPadding:4}
            },
            scales:{
                x:{grid:{display:false},ticks:{font:{size:10},color:C.ink3,autoSkip:true,autoSkipPadding:6,maxRotation:45,minRotation:0}},
                y:{beginAtZero:true,grid:{color:C.line,drawBorder:false},ticks:{stepSize:3,color:C.ink3,font:{size:11}}}
            }
        }
    };
    if (flujoChart) { flujoChart.data = cfg.data; flujoChart.update(); }
    else flujoChart = new Chart(ctx, cfg);
}

/* ════════════════════════════════════════════════════════════
    DONUTS
═══════════════════════════════════════════════════════════════ */
var empresaChart = null, zonaChart = null;

function buildDonut(canvasId, obj, colorMap, totalId, legendId) {
    var labels = Object.keys(obj).filter(function(k){ return obj[k] > 0; });
    var vals   = labels.map(function(k){ return obj[k]; });
    var cols   = labels.map(function(k){ return colorMap[k] || C.gray; });
    var total  = vals.reduce(function(a,b){ return a+b; }, 0);
    $(totalId).textContent = nf(total);

    var ctx = $(canvasId).getContext('2d');
    var cfg = {
        type:'doughnut',
        data:{ labels:labels, datasets:[{data:vals, backgroundColor:cols, borderColor:'#fff', borderWidth:3, hoverOffset:6}] },
        options:{
            responsive:true, maintainAspectRatio:false, cutout:'68%',
            plugins:{ legend:{display:false},
                tooltip:{backgroundColor:'#fff',titleColor:C.ink,bodyColor:C.ink2,
                    borderColor:C.line,borderWidth:1,padding:10,cornerRadius:10,
                    callbacks:{label:function(c){
                        var p = total ? Math.round(c.parsed/total*100) : 0;
                        return ' '+c.label+': '+c.parsed+' ('+p+'%)';
                    }}}
            }
        }
    };
    var existing = (canvasId === 'empresaChart') ? empresaChart : zonaChart;
    if (existing) { existing.data = cfg.data; existing.update(); }
    else {
        var ch = new Chart(ctx, cfg);
        if (canvasId === 'empresaChart') empresaChart = ch; else zonaChart = ch;
    }

    var lg = $(legendId); lg.innerHTML = '';
    labels.forEach(function(k, i) {
        var pct = total ? Math.round(vals[i]/total*100) : 0;
        var el = document.createElement('span'); el.className = 'lg';
        el.innerHTML = '<i style="background:'+cols[i]+'"></i>'+k+' <b style="color:'+C.ink+';margin-left:2px">'+pct+'%</b>';
        lg.appendChild(el);
    });
}

/* ════════════════════════════════════════════════════════════
    TOP UNIDADES
═══════════════════════════════════════════════════════════════ */
function buildUnidades(list) {
    var max = list.length ? Math.max.apply(null, list.map(function(u){ return u.count; })) : 1;
    var html = '';
    list.slice(0,5).forEach(function(u, i) {
        var w = Math.round(u.count / max * 100);
        html += '<div class="uni">'
            + '<span class="uni-rank">'+(i+1)+'</span>'
            + '<div class="uni-mid">'
            +   '<div class="uni-top"><span class="uni-num">'+u.numero+' <span class="uni-emp">'+(u.empresa||'')+'</span></span>'
            +     '<span class="uni-cnt">'+u.count+' <small>veces</small></span></div>'
            +   '<div class="uni-bar"><i style="width:'+w+'%"></i></div>'
            + '</div></div>';
    });
    $('unidades').innerHTML = html || '<div style="color:var(--ink-3);font-size:13px;text-align:center;padding:20px">Sin datos</div>';
}

/* ════════════════════════════════════════════════════════════
    VISTA CLIENTE — barras empresas en patio
═══════════════════════════════════════════════════════════════ */
function buildDentroEmpresa(dentroObj, promObj) {
    var total = Object.values(dentroObj).reduce(function(a,b){ return a+b; }, 0);
    var html = '';
    var empresas = Object.keys(EMPRESA_COLOR);
    empresas.forEach(function(emp) {
        var cnt = dentroObj[emp] || 0;
        var w   = total > 0 ? Math.round(cnt/total*100) : 0;
        var col = EMPRESA_COLOR[emp] || C.gray;
        html += '<div class="emp-bar-row">'
            + '<span class="emp-bar-label">'+emp+'</span>'
            + '<div class="emp-bar-track"><div class="emp-bar-fill" style="width:'+w+'%;background:'+col+'"></div></div>'
            + '<span class="emp-bar-count">'+cnt+'</span>'
            + '</div>';
    });
    $('dentro-empresa-bars').innerHTML = html || '<div style="color:var(--ink-3);padding:10px 0;font-size:13px">Sin datos</div>';

    var promHtml = '';
    Object.keys(promObj || {}).forEach(function(emp) {
        var mins = promObj[emp];
        promHtml += '<div class="est-prom-item">'
            + '<div class="est-prom-lbl">'+emp+'</div>'
            + '<div class="est-prom-val">'+minsToHm(mins)+'</div>'
            + '<div class="est-prom-sub">prom. estancia</div>'
            + '</div>';
    });
    $('estancia-promedios').innerHTML = promHtml || '';
}

/* ════════════════════════════════════════════════════════════
    VISTA CLIENTE — KPIs
═══════════════════════════════════════════════════════════════ */
function renderKpisCliente(d) {
    $('c-ent').textContent   = nf(d.entradas);
    $('c-sal').textContent   = nf(d.salidas);
    $('c-total').textContent = nf(d.total_acumulado);

    var dentro = 0;
    if (d.dentro_ahora) {
        Object.values(d.dentro_ahora).forEach(function(v){ dentro += (v || 0); });
    }
    $('c-dentro').textContent = dentro > 0 ? nf(dentro) : '—';

    var promMins = null;
    if (d.prom_estancia) {
        var vals = Object.values(d.prom_estancia).filter(function(v){ return v != null && v > 0; });
        if (vals.length) promMins = vals.reduce(function(a,b){ return a+b; },0) / vals.length;
    }
    $('c-prom-est').textContent = promMins ? minsToHm(promMins) : '—';
}

/* ════════════════════════════════════════════════════════════
    VISTA DEV — KPIs
═══════════════════════════════════════════════════════════════ */
function renderKpisDev(d) {
    $('k-hoy').textContent   = nf(d.detecciones_hoy);
    $('k-ent').textContent   = nf(d.entradas);
    $('k-sal').textContent   = nf(d.salidas);
    $('k-prom').textContent  = nf(d.promedio_hora);
    $('k-total').textContent = nf(d.total_acumulado);

    if (d.detecciones_ayer != null) {
        var diff = d.detecciones_hoy - d.detecciones_ayer;
        var pct  = d.detecciones_ayer ? Math.round(diff/d.detecciones_ayer*100) : 0;
        var cls  = diff >= 0 ? 'up' : 'down';
        var arrow = diff >= 0 ? '▲' : '▼';
        $('k-hoy-sub').innerHTML = '<b class="'+cls+'">'+arrow+' '+Math.abs(pct)+'%</b> vs ayer';
    }

    if (d.top_unidades && d.top_unidades[0]) {
        $('k-top').textContent     = d.top_unidades[0].numero;
        $('k-top-sub').textContent = (d.top_unidades[0].empresa||'')+' · '+d.top_unidades[0].count+' veces';
    }
}

/* ════════════════════════════════════════════════════════════
    ÚLTIMA DETECCIÓN
═══════════════════════════════════════════════════════════════ */
function renderUltima(u) {
    if (!u) return;
    $('last-num').textContent  = u.numero    || '----';
    $('last-emp').textContent  = u.empresa   || '—';
    $('last-zona').textContent = u.zona      || '—';
    $('last-conf').textContent = (u.conf != null) ? Math.round(u.conf*100)+'% conf.' : '—';
    $('last-mov').textContent  = u.movimiento || '—';
    $('last-time').textContent = u.ts || u.hora_paso || '—';
    var c = EMPRESA_COLOR[u.empresa] || C.gray;
    $('last-emp').style.background  = hexA(c, .1);
    $('last-emp').style.color       = c;
    $('last-emp').style.borderColor = c;
}

/* ════════════════════════════════════════════════════════════
    TABLA DE CONTROL DE UNIDADES
    ──────────────────────────────────────────────────────────
    Lógica de tiempos:
    • status='dentro': el tiempo dentro se calcula en vivo
      (minutesSince(ultimo_ingreso) + minutos_dentro_previos)
      y se actualiza cada 30s vía tickerInterval.
    • status='fuera': minutos_dentro viene del backend (suma
      de todas las estancias cerradas del periodo).
    • Cada fila es clickeable → abre el modal de trayectoria
      detallada de esa unidad (openTrayectoria()).
═══════════════════════════════════════════════════════════════ */

function buildUnitTable(data) {
    estanciasData = data;
    filterUnidades(true);      // la actualización no cambia de página
    startTicker();
}

function filterUnidades(mantenerPagina) {
    if (!mantenerPagina) paginaUnidades = 1;   // buscar o filtrar regresa a la página 1
    var q      = ($('filter-search').value  || '').toLowerCase().trim();
    var emp    = ($('filter-emp').value     || '').toLowerCase();
    var status = ($('filter-status').value  || '').toLowerCase();

    var filtered = estanciasData.filter(function(u) {
        var mQ = !q      || (u.no_economico||'').toLowerCase().includes(q)
                         || (u.empresa||'').toLowerCase().includes(q);
        var mE = !emp    || (u.empresa||'').toLowerCase() === emp;
        var mS = !status || (u.status||'') === status;
        return mQ && mE && mS;
    });

    renderUnitTable(filtered);
}

/**
 * Calcula los minutos que una unidad lleva en el patio en este
 * tramo actual (desde ultimo_ingreso hasta ahora).
 * Suma los minutos_dentro_previos si el backend los mandó
 * (corresponde a estancias cerradas previas del mismo periodo).
 */
function calcMinutosDentroAhora(u) {
    var transcurridos = minutesSince(u.ultimo_ingreso_iso || u.ultimo_ingreso) || 0;
    var previos       = (u.minutos_dentro_previos != null) ? u.minutos_dentro_previos : 0;
    return transcurridos + previos;
}

function renderUnitTable(rows) {
    var tbody  = $('unit-tbody');
    var empty  = $('table-empty');
    var footer = $('table-footer');

    if (!rows || rows.length === 0) {
        tbody.innerHTML = '';
        empty.style.display  = 'flex';
        footer.textContent   = '';
        return;
    }
    empty.style.display = 'none';

    var total   = rows.length;
    var paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
    if (paginaUnidades > paginas) paginaUnidades = paginas;
    if (paginaUnidades < 1) paginaUnidades = 1;
    var desde  = (paginaUnidades - 1) * POR_PAGINA;
    var pagina = rows.slice(desde, desde + POR_PAGINA);

    var html = '';
    pagina.forEach(function(u) {
        var statusCls, statusLbl;
        if (u.status === 'dentro') {
            statusCls = 'dentro'; statusLbl = 'Dentro';
        } else if (u.sin_movimiento) {
            statusCls = 'fuera'; statusLbl = 'Sin movimiento';
        } else {
            statusCls = 'fuera'; statusLbl = 'Fuera';
        }
        var rowStyle = u.sin_movimiento ? ' style="opacity:.5"' : '';

        /* ── Tiempo dentro ──────────────────────────────────── */
        var dentroHtml;
        if (u.status === 'dentro') {
            var mins = calcMinutosDentroAhora(u);
            dentroHtml = '<span class="td-dur td-live-dentro" '
                + 'data-ingreso="'+(u.ultimo_ingreso_iso||u.ultimo_ingreso||'')+'" '
                + 'data-previos="'+(u.minutos_dentro_previos||0)+'">'
                + minsToHm(mins)
                + '</span>';
        } else {
            dentroHtml = u.minutos_dentro != null
                ? '<span class="td-dur">'+minsToHm(u.minutos_dentro)+'</span>'
                : '<span class="td-na">—</span>';
        }

        /* ── Tiempo fuera ───────────────────────────────────── */
        var fueraHtml = u.minutos_fuera != null
            ? '<span class="td-dur">'+minsToHm(u.minutos_fuera)+'</span>'
            : '<span class="td-na">—</span>';

        /* ── Última salida ──────────────────────────────────── */
        var salidaTxt = u.ultima_salida
            ? '<span class="td-time">'+u.ultima_salida+'</span>'
            : '<span class="td-na">—</span>';

        html += '<tr class="tr-click" data-numero="'+(u.no_economico||'')+'" onclick="openTrayectoria(this.dataset.numero)"'+rowStyle+'>'
            + '<td class="td-num">'+(u.no_economico||'—')+'</td>'
            + '<td class="td-emp">'+(u.empresa||'—')+'</td>'
            + '<td class="td-time">'+(u.ultimo_ingreso||'—')+'</td>'
            + '<td>'+salidaTxt+'</td>'
            + '<td>'+dentroHtml+'</td>'
            + '<td>'+fueraHtml+'</td>'
            + '<td class="td-viajes">'+(u.viajes||1)+'</td>'
            + '<td><span class="tbl-badge '+statusCls+'">'+statusLbl+'</span></td>'
            + '</tr>';
    });
    tbody.innerHTML = html;
    footer.innerHTML = '<span>Mostrando ' + (desde + 1) + '–' + (desde + pagina.length) + ' de ' + total
        + ' unidad' + (total !== 1 ? 'es' : '') + '</span>'
        + (paginas > 1
            ? '<span class="pag-ctrl">'
              + '<button class="pag-btn" onclick="cambiarPagina(-1)"' + (paginaUnidades <= 1 ? ' disabled' : '') + '>‹ Anterior</button>'
              + '<span class="pag-num">Página ' + paginaUnidades + ' de ' + paginas + '</span>'
              + '<button class="pag-btn" onclick="cambiarPagina(1)"' + (paginaUnidades >= paginas ? ' disabled' : '') + '>Siguiente ›</button>'
              + '</span>'
            : '');
}

/**
 * Ticker: actualiza cada 30 segundos solo las celdas td-live-dentro,
 * sin re-renderizar toda la tabla (evita flicker y pérdida de scroll).
 */
function startTicker() {
    if (tickerInterval) clearInterval(tickerInterval);
    tickerInterval = setInterval(tickLiveCells, 30000);
}

function tickLiveCells() {
    var cells = document.querySelectorAll('.td-live-dentro');
    cells.forEach(function(cell) {
        var ingreso = cell.dataset.ingreso;
        var previos = parseFloat(cell.dataset.previos) || 0;
        if (!ingreso) return;
        var transcurridos = minutesSince(ingreso) || 0;
        cell.textContent = minsToHm(transcurridos + previos);
    });
}

/* ════════════════════════════════════════════════════════════
    MODAL DE TRAYECTORIA — bitácora + mini-Gantt por día
    ──────────────────────────────────────────────────────────
    Al hacer clic en una fila de la tabla, se pide
    /api/trayectoria/<numero>?rango=<currentPeriod> y se pinta:
      1. Una bitácora tipo lista (entrada → salida → duración)
      2. Un mini-Gantt: una fila por día operativo, barra de 24h
         (desde HORA_CORTE_DIA hasta HORA_CORTE_DIA del día
         siguiente) con los tramos dentro/fuera resaltados.
═══════════════════════════════════════════════════════════════ */

function openTrayectoria(numero) {
    if (!numero) return;
    $('tray-modal').classList.add('show');
    $('tray-numero').textContent = numero;
    $('tray-body').innerHTML = '<div class="tray-loading">Cargando trayectoria…</div>';

    fetch('/api/trayectoria/' + encodeURIComponent(numero) + '?rango=' + currentPeriod)
        .then(function(r){ if(!r.ok) throw 0; return r.json(); })
        .then(function(d){ renderTrayectoria(d); })
        .catch(function(){
            $('tray-body').innerHTML = '<div class="tray-loading">No se pudo cargar la trayectoria.</div>';
        });
}

function closeTrayectoria() {
    $('tray-modal').classList.remove('show');
}

function renderTrayectoria(d) {
    $('tray-empresa').textContent = d.empresa || '—';
    $('tray-rango').textContent   = ({hoy:'Hoy', semana:'Últimos 7 días', mes:'Último mes', anio:'Último año'})[d.rango] || d.rango;

    if (!d.tramos || d.tramos.length === 0) {
        $('tray-body').innerHTML = '<div class="tray-loading">Sin movimientos en este periodo.</div>';
        return;
    }

    var html = '<div class="tray-gantt">' + renderGanttPorDias(d.tramos) + '</div>';
    html += '<div class="tray-bitacora">' + renderBitacora(d.tramos) + '</div>';
    $('tray-body').innerHTML = html;
}

/** Lista cronológica: entrada → salida → duración, con "en curso" cuando aplica. */
function renderBitacora(tramos) {
    var html = '<div class="tray-bit-title">Bitácora</div><ul class="tray-bit-list">';
    tramos.forEach(function(t) {
        var horaE = horaCorta(t.hora_entrada);
        var fechaE = fechaCorta(t.hora_entrada);
        var horaS = t.hora_salida ? horaCorta(t.hora_salida) : null;

        html += '<li class="tray-bit-item">';
        html += '<span class="tray-bit-fecha">'+fechaE+'</span>';
        html += '<span class="tray-bit-tramo">';
        html += '<b>'+horaE+'</b> Entrada';
        if (horaS) {
            html += ' → <b>'+horaS+'</b> Salida <span class="tray-bit-dur">('+minsToHm(t.minutos_dentro)+' dentro)</span>';
        } else if (t.en_curso) {
            html += ' → <span class="tray-bit-live">en el patio ahora</span> <span class="tray-bit-dur">('+minsToHm(t.minutos_dentro)+')</span>';
        }
        if (t.minutos_fuera_antes != null) {
            html += '<div class="tray-bit-fuera">'+minsToHm(t.minutos_fuera_antes)+' fuera antes de esta entrada</div>';
        }
        html += '</span></li>';
    });
    html += '</ul>';
    return html;
}

/**
 * Agrupa los tramos por día operativo y dibuja una barra de 24h
 * por día (desde HORA_CORTE_DIA hasta HORA_CORTE_DIA del día
 * siguiente). Los tramos que exceden ese día quedan recortados
 * visualmente en esa fila (aproximación razonable para estancias
 * largas, que son la excepción).
 */
function renderGanttPorDias(tramos) {
    var dias = {};   // "2026-07-22" -> [tramos]
    tramos.forEach(function(t) {
        var dt = new Date(t.hora_entrada);
        var op = new Date(dt);
        op.setHours(op.getHours() - HORA_CORTE_DIA);
        var key = op.getFullYear() + '-' + String(op.getMonth()+1).padStart(2,'0') + '-' + String(op.getDate()).padStart(2,'0');
        if (!dias[key]) dias[key] = [];
        dias[key].push(t);
    });

    var keys = Object.keys(dias).sort();
    var ejeLabels = [];
    for (var h = 0; h < 24; h++) {
        ejeLabels.push(String((HORA_CORTE_DIA + h) % 24).padStart(2,'0'));
    }

    var html = '<div class="tray-gantt-title">Vista diaria</div>';
    html += '<div class="tray-gantt-eje">' + ejeLabels.filter(function(_,i){return i%3===0;}).map(function(h){return '<span>'+h+':00</span>';}).join('') + '</div>';

    keys.forEach(function(key) {
        var domainStart = new Date(key + 'T00:00:00');
        domainStart.setHours(HORA_CORTE_DIA, 0, 0, 0);
        var domainEnd = new Date(domainStart);
        domainEnd.setHours(domainEnd.getHours() + 24);
        var domainMs = domainEnd - domainStart;

        var bars = '';
        dias[key].forEach(function(t) {
            var entrada = new Date(t.hora_entrada);
            var salida  = t.hora_salida ? new Date(t.hora_salida) : new Date();
            var start   = Math.max(entrada, domainStart);
            var end     = Math.min(salida, domainEnd);
            if (end <= start) return;
            var leftPct  = (start - domainStart) / domainMs * 100;
            var widthPct = (end - start) / domainMs * 100;
            var cls = t.en_curso ? 'en-curso' : 'cerrado';
            bars += '<div class="tray-gantt-bar ' + cls + '" style="left:' + leftPct + '%;width:' + widthPct + '%" '
                  + 'title="' + horaCorta(t.hora_entrada) + (t.hora_salida ? ' - ' + horaCorta(t.hora_salida) : ' (en curso)') + '"></div>';
        });

        html += '<div class="tray-gantt-row">'
              + '<span class="tray-gantt-label">' + fechaCorta(key + 'T12:00:00') + '</span>'
              + '<div class="tray-gantt-track">' + bars + '</div>'
              + '</div>';
    });

    return html;
}

/* ════════════════════════════════════════════════════════════
    RENDER COMPLETO DE DASHBOARD
═══════════════════════════════════════════════════════════════ */
var lastDashData = null;

function renderAll(d) {
    lastDashData = d;

    renderUltima(d.ultima);
    $('tg-num').textContent = nf(d.telegram_hoy);

    renderKpisCliente(d);
    refreshFlujoCliente();
    // NOTA: "dentro_ahora", "prom_estancia" y "estancias" NO se leen de
    // aquí a propósito. /api/dashboard nunca los incluye (solo vienen de
    // /api/estancias), así que si se leyeran de `d` (mezclado con DEMO
    // vía Object.assign), cada 15s la tabla y el panel "dentro del patio
    // ahora" se pisaban con los datos de muestra de DEMO. Esos tres
    // campos se actualizan exclusivamente en loadEstancias().

    renderKpisDev(d);
    buildFlujo(d.por_hora);
    buildDonut('empresaChart', d.por_empresa, EMPRESA_COLOR, 'emp-total', 'emp-legend');
    buildDonut('zonaChart',    d.por_zona,    ZONA_COLOR,    'zona-total','zona-legend');
    buildUnidades(d.top_unidades || []);
}

/* ════════════════════════════════════════════════════════════
    FETCH — /api/dashboard
═══════════════════════════════════════════════════════════════ */
function loadDashboard() {
    fetch('/api/dashboard')
        .then(function(r){ if(!r.ok) throw 0; return r.json(); })
        .then(function(d){
            flagDemo(false);
            renderAll(Object.assign({}, DEMO, d));
        })
        .catch(function(){
            flagDemo(true);
            renderAll(DEMO);
        });
}

/* ════════════════════════════════════════════════════════════
    FETCH — /api/estancias?rango=currentPeriod
═══════════════════════════════════════════════════════════════ */
function loadEstancias() {
    fetch('/api/estancias?rango=' + currentPeriod)
        .then(function(r){ if(!r.ok) throw 0; return r.json(); })
        .then(function(d){
            if (d.estancias)     buildUnitTable(d.estancias);
            if (d.dentro_ahora) {
                if (lastDashData) lastDashData.dentro_ahora = d.dentro_ahora;
                buildDentroEmpresa(d.dentro_ahora, d.prom_estancia || (lastDashData && lastDashData.prom_estancia) || {});
            }
            if (d.prom_estancia && lastDashData) {
                lastDashData.prom_estancia = d.prom_estancia;
                renderKpisCliente(lastDashData);
            }
        })
        .catch(function(){
            // Backend no responde: mostrar DEMO en vez de dejar la tabla
            // pegada con el último dato válido (evita confusión sobre si
            // el dato sigue vivo).
            // Servidor sin respuesta: se queda la última tabla buena (nunca datos de ejemplo)
            if (!estanciasData || !estanciasData.length) buildUnitTable([]);
        });
}

/* ════════════════════════════════════════════════════════════
    ESTADO EN VIVO (pills + snapshot + última detección)
═══════════════════════════════════════════════════════════════ */
function pollEstado() {
    fetch('/api/estado')
        .then(function(r){ return r.json(); })
        .then(function(d){
            setDot('dot-yolo', d.yolo_fps > 0);
            $('txt-yolo').textContent = 'YOLO '+(d.yolo_fps||0)+' fps';
            setDot('dot-pg', d.pg_conectada);
            $('txt-pg').textContent = d.pg_conectada ? 'PG '+(d.unidades_registradas||0)+'u' : 'PG ERR';
            setDot('dot-cam', d.pipeline);
            $('txt-cam').textContent = d.pipeline ? 'CAM OK' : 'CAM ERR';
            if (d.active_camera) $('snap-cam').textContent = 'CAM '+d.active_camera;

            if ($('d-m1-fps'))       $('d-m1-fps').textContent       = (d.yolo_fps||'—')+' fps';
            if ($('d-cola'))         $('d-cola').textContent          = d.queue_size != null ? d.queue_size : '0';
            if ($('d-descartadas'))  $('d-descartadas').textContent   = d.descartadas != null ? d.descartadas : '—';
            if ($('d-frames'))       $('d-frames').textContent        = d.frame_count != null ? nf(d.frame_count) : '—';
            if ($('d-eventos'))      $('d-eventos').textContent       = d.total_detecciones != null ? nf(d.total_detecciones) : '—';
            if ($('d-estancias-abiertas')) {
                var ea = d.estancias_abiertas;
                $('d-estancias-abiertas').textContent  = ea != null ? ea : '—';
                $('d-estancias-abiertas').className    = 'dev-stat-val' + (ea > 0 ? ' ok' : '');
            }
            if ($('d-no-padron')) {
                var np = d.no_padron_hoy;
                $('d-no-padron').textContent = np != null ? np : '—';
                $('d-no-padron').className   = 'dev-stat-val' + (np > 0 ? ' warn' : '');
            }
            if ($('d-tg-pending'))   $('d-tg-pending').textContent    = d.tg_pendientes != null ? d.tg_pendientes : '0';
            if ($('d-cam-ok')) {
                $('d-cam-ok').textContent  = d.conexion ? 'OK' : 'Sin señal';
                $('d-cam-ok').className    = 'dev-stat-val ' + (d.conexion ? 'ok' : 'err');
            }

            if (d.snapshot_url && !liveOk) {   // la miniatura solo mientras no hay video
                var img = $('snapshot');
                img.src = d.snapshot_url + '?t=' + Date.now();
                img.onload = function(){ img.classList.add('show'); };
            }

            if (d.numero) {
                renderUltima({
                    numero:d.numero, empresa:d.empresa, zona:d.zona,
                    movimiento:d.movimiento, conf:d.conf, ts:d.ts
                });
            }

            $('hora').textContent = new Date().toLocaleTimeString('es-MX');
        })
        .catch(function(){
            $('hora').textContent = new Date().toLocaleTimeString('es-MX');
        });
}

/* ════════════════════════════════════════════════════════════
    CROPS STATS
═══════════════════════════════════════════════════════════════ */
function loadCropsStats() {
    fetch('/api/crops/stats')
        .then(function(r){ return r.json(); })
        .then(function(d){
            var total = (d.autobus || 0) + (d.numero || 0);
            if ($('d-crops')) $('d-crops').textContent = nf(total);
        })
        .catch(function(){});
}

/* ════════════════════════════════════════════════════════════
    VIDEO EN VIVO (MJPEG) EN LA TARJETA DE CÁMARA
    Flask manda los frames como JPEG seguidos (/api/video.mjpeg).
    Mientras no llega imagen, se sigue viendo la miniatura.
═══════════════════════════════════════════════════════════════ */
var liveOk = false, liveRetries = 0;

function startLiveVideo() {
    var img = $('live-video');
    if (!img) return;
    img.onerror = function() {
        liveOk = false;
        img.classList.remove('show');
        img.parentNode.classList.remove('playing');
        liveRetries++;
        setTimeout(startLiveVideo, Math.min(liveRetries * 2000, 10000));
    };
    img.src = '/api/video.mjpeg?t=' + Date.now();
}

function initLiveVideo() {
    startLiveVideo();
    setInterval(function() {            // en cuanto llega el primer cuadro, se muestra
        var img = $('live-video');
        if (img && img.naturalWidth > 0 && !liveOk) {
            liveOk = true; liveRetries = 0;
            img.classList.add('show');
            img.parentNode.classList.add('playing');
        }
    }, 500);
}

/* ════════════════════════════════════════════════════════════
    ARRANQUE
═══════════════════════════════════════════════════════════════ */
initLiveVideo();
loadDashboard();
pollEstado();
loadCropsStats();
loadEstancias();

setInterval(loadDashboard,  15000);
setInterval(pollEstado,      1000);
setInterval(loadEstancias,  10000);
setInterval(loadCropsStats, 60000);