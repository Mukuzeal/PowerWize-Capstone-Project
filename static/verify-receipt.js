var scanner = null;

function startScanner() {
  document.getElementById('btn-start').style.display = 'none';
  document.getElementById('btn-stop').style.display  = 'flex';
  // flex, not block — .scan-status centres its icon and label on a row.
  document.getElementById('scan-status').style.display = 'flex';

  scanner = new Html5Qrcode('qr-reader');
  scanner.start(
    { facingMode: 'environment' },
    { fps: 10, qrbox: { width: 250, height: 250 } },
    function(decodedText) {
      document.getElementById('qr-data-input').value = decodedText;
      stopScanner();
      document.getElementById('verify-form').submit();
    },
    function(error) {}
  ).catch(function() {
    var status = document.getElementById('scan-status');
    status.classList.add('is-bad');
    status.innerHTML =
      '<i class="fa-solid fa-triangle-exclamation"></i> Camera unavailable — use manual entry';
  });
}

function stopScanner() {
  if (scanner) { scanner.stop().catch(function() {}); scanner = null; }
  document.getElementById('btn-start').style.display = 'flex';
  document.getElementById('btn-stop').style.display  = 'none';
  // The status line reported an in-progress scan; nothing is in progress now.
  document.getElementById('scan-status').style.display = 'none';
}
