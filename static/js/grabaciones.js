var currentCam = 1;
var DIAS_ES = ['Domingo','Lunes','Martes','Mi\u00e9rcoles','Jueves','Viernes','S\u00e1bado'];
var MESES_ES = ['enero','febrero','marzo','abril','mayo','junio',
                'julio','agosto','septiembre','octubre','noviembre','diciembre'];

function switchCam(num) {
  currentCam = num;
  document.querySelectorAll('.cam-tab').forEach(function(t) {
    t.classList.toggle('active', parseInt(t.dataset.cam) === num);
  });
  loadRecordings();
}

function parseFilename(name) {
  var m = name.match(/(cam\d)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.mp4/);
  if (!m) return null;
  var y = parseInt(m[2]), mo = parseInt(m[3])-1, d = parseInt(m[4]);
  var h = parseInt(m[5]), mi = parseInt(m[6]);
  var date = new Date(y, mo, d, h, mi, 0);
  var endDate = new Date(date.getTime() + 3600000);
  return {
    filename: name,
    date: date,
    endDate: endDate,
    dateKey: y + '-' + String(mo+1).padStart(2,'0') + '-' + String(d).padStart(2,'0'),
    startTime: String(h).padStart(2,'0') + ':' + String(mi).padStart(2,'0'),
    endTime: String(endDate.getHours()).padStart(2,'0') + ':' + String(endDate.getMinutes()).padStart(2,'0'),
  };
}

function fmtSize(bytes) {
  if (bytes < 1024*1024) return Math.round(bytes/1024) + ' KB';
  if (bytes < 1024*1024*1024) return (bytes/(1024*1024)).toFixed(1) + ' MB';
  return (bytes/(1024*1024*1024)).toFixed(2) + ' GB';
}

function fmtDayHeader(dateObj) {
  var dia = DIAS_ES[dateObj.getDay()];
  var num = dateObj.getDate();
  var mes = MESES_ES[dateObj.getMonth()];
  var anio = dateObj.getFullYear();
  return { name: dia, full: num + ' de ' + mes + ' ' + anio };
}

function loadRecordings() {
  var content = document.getElementById('content');
  content.innerHTML = '<div class="loading">Cargando grabaciones...</div>';

  fetch('/api/grabaciones?cam=' + currentCam)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var files = data.files || [];
      document.getElementById('stat-total').textContent = files.length + ' segmentos';
      document.getElementById('stat-size').textContent = fmtSize(data.total_size || 0);

      if (files.length === 0) {
        content.innerHTML = '<div class="empty-msg">No hay grabaciones de Cam ' + currentCam + '</div>';
        return;
      }

      var parsed = [];
      for (var i = 0; i < files.length; i++) {
        var p = parseFilename(files[i].name);
        if (p) {
          p.size = files[i].size;
          parsed.push(p);
        }
      }

      parsed.sort(function(a, b) { return b.date - a.date; });

      var byDay = {};
      var dayOrder = [];
      for (var j = 0; j < parsed.length; j++) {
        var key = parsed[j].dateKey;
        if (!byDay[key]) { byDay[key] = []; dayOrder.push(key); }
        byDay[key].push(parsed[j]);
      }

      var html = '';
      for (var d = 0; d < dayOrder.length; d++) {
        var dk = dayOrder[d];
        var segs = byDay[dk];
        var hdr = fmtDayHeader(segs[0].date);

        html += '<div class="day-section">';
        html += '<div class="day-header">';
        html += '<div class="day-icon">&#128197;</div>';
        html += '<div><div class="day-name">' + hdr.name + '</div>';
        html += '<div class="day-date">' + hdr.full + '</div></div>';
        html += '<span class="day-count">' + segs.length + ' segmento' + (segs.length > 1 ? 's' : '') + '</span>';
        html += '</div>';
        html += '<div class="segments-grid">';

        segs.sort(function(a, b) { return a.date - b.date; });

        for (var s = 0; s < segs.length; s++) {
          var seg = segs[s];
          html += '<div class="segment" onclick="playVideo(\'' + seg.filename + '\', \'' + seg.startTime + ' — ' + seg.endTime + '\')">';
          html += '<div class="seg-time">' + seg.startTime + ' — ' + seg.endTime + '</div>';
          html += '<div class="seg-size">' + fmtSize(seg.size) + '</div>';
          html += '<div class="seg-play"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></div>';
          html += '</div>';
        }

        html += '</div></div>';
      }

      content.innerHTML = html;
    })
    .catch(function(e) {
      content.innerHTML = '<div class="empty-msg">Error al cargar grabaciones</div>';
      console.error(e);
    });
}

function playVideo(filename, title) {
  var cam = currentCam;
  var video = document.getElementById('player-video');
  video.src = '/grabaciones/file/' + cam + '/' + filename;
  document.getElementById('player-title').textContent = 'Cam ' + cam + ' · ' + title;
  document.getElementById('player-modal').classList.add('open');
}

function closePlayer() {
  var video = document.getElementById('player-video');
  video.pause();
  video.src = '';
  document.getElementById('player-modal').classList.remove('open');
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closePlayer();
});

loadRecordings();