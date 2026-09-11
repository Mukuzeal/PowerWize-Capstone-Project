/* Secure in-modal document viewer: renders PDFs page-by-page to a canvas
 * (never a downloadable/openable file link), tracks the highest page
 * reached as a view-percentage, and applies the same anti-cheat measures
 * used on the quiz screen while the modal is open. */

var _docViewer = { pdf: null, pageNum: 1, totalPages: 0, maxPageSeen: 0, moduleId: null };

if (window.pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
}

function _docViewerOpen() {
  var overlay = document.getElementById('docviewer-overlay');
  return overlay && overlay.style.display === 'flex';
}

function openDocModal(fileUrl, filename, opts) {
  opts = opts || {};
  var overlay = document.getElementById('docviewer-overlay');
  if (!overlay) return;
  document.getElementById('docviewer-title').textContent = filename;
  var wm = document.getElementById('docviewer-watermark');
  var wmText = opts.watermark || '';
  wm.innerHTML = '';
  for (var i = 0; i < 24; i++) {
    var span = document.createElement('span');
    span.style.cssText = 'margin:1.5rem 2rem';
    span.textContent = wmText;
    wm.appendChild(span);
  }
  overlay.style.display = 'flex';
  _docViewer.moduleId = opts.moduleId || null;
  _docViewer.maxPageSeen = 0;

  var isPdf = /\.pdf$/i.test(filename);
  if (isPdf && window.pdfjsLib) {
    document.getElementById('docviewer-pdf-area').style.display = 'flex';
    document.getElementById('docviewer-fallback').style.display = 'none';
    pdfjsLib.getDocument(fileUrl).promise.then(function(pdf) {
      _docViewer.pdf = pdf;
      _docViewer.totalPages = pdf.numPages;
      _docViewer.pageNum = 1;
      _docViewerRenderPage(1);
    }).catch(function() {
      _docViewerFallback(fileUrl);
    });
  } else {
    _docViewerFallback(fileUrl);
  }
}

function _docViewerFallback(fileUrl) {
  document.getElementById('docviewer-pdf-area').style.display = 'none';
  var fb = document.getElementById('docviewer-fallback');
  fb.style.display = 'block';
  fb.innerHTML = '<iframe src="' + fileUrl + '#toolbar=0"></iframe>';
}

function _docViewerRenderPage(num) {
  if (!_docViewer.pdf) return;
  _docViewer.pdf.getPage(num).then(function(page) {
    var canvas = document.getElementById('docviewer-canvas');
    var ctx = canvas.getContext('2d');
    var viewport = page.getViewport({ scale: 1.35 });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    page.render({ canvasContext: ctx, viewport: viewport }).promise.then(function() {
      document.getElementById('docviewer-page-label').textContent =
        'Page ' + num + ' of ' + _docViewer.totalPages;
      if (num > _docViewer.maxPageSeen) {
        _docViewer.maxPageSeen = num;
        _docViewerReportProgress();
      }
    });
  });
}

function docViewerNext() {
  if (_docViewer.pageNum < _docViewer.totalPages) {
    _docViewer.pageNum++;
    _docViewerRenderPage(_docViewer.pageNum);
  }
}

function docViewerPrev() {
  if (_docViewer.pageNum > 1) {
    _docViewer.pageNum--;
    _docViewerRenderPage(_docViewer.pageNum);
  }
}

function _docViewerReportProgress() {
  if (!_docViewer.moduleId || !_docViewer.totalPages) return;
  var pct = Math.round((_docViewer.maxPageSeen / _docViewer.totalPages) * 100);
  var label = document.getElementById('docviewer-progress-label');
  if (label) label.textContent = pct + '% viewed';
  fetch('/lms/learn/' + _docViewer.moduleId + '/material-progress', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
    },
    body: JSON.stringify({ pct: pct })
  }).then(function() {
    if (pct >= 100) window._docViewerReachedFull = true;
  }).catch(function() {});
}

function closeDocModal() {
  var overlay = document.getElementById('docviewer-overlay');
  if (!overlay) return;
  overlay.style.display = 'none';
  // The quiz card's "view material to unlock" gate reads server-side state,
  // so reload once the trainee has actually reached 100% to reflect the
  // newly-unlocked quiz without them needing to navigate away and back.
  if (window._docViewerReachedFull) {
    window._docViewerReachedFull = false;
    location.reload();
  }
}

document.addEventListener('contextmenu', function(e) {
  if (_docViewerOpen()) e.preventDefault();
});
document.addEventListener('selectstart', function(e) {
  if (_docViewerOpen()) e.preventDefault();
});
document.addEventListener('copy', function(e) {
  if (_docViewerOpen()) e.preventDefault();
});
document.addEventListener('keydown', function(e) {
  if (!_docViewerOpen()) return;
  var blocked = (
    (e.ctrlKey && ['c', 'x', 'u', 's', 'a', 'p'].indexOf(e.key.toLowerCase()) !== -1) ||
    e.key === 'F12' ||
    (e.ctrlKey && e.shiftKey && ['I', 'J', 'C'].indexOf(e.key) !== -1) ||
    e.key === 'Escape'
  );
  if (e.key === 'Escape') { closeDocModal(); return; }
  if (blocked) e.preventDefault();
});
