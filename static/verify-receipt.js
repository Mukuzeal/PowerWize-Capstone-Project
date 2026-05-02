var scanner = null;

function startScanner() {
  document.getElementById('btn-start').style.display = 'none';
  document.getElementById('btn-stop').style.display  = 'flex';
  document.getElementById('scan-status').style.display = 'block';

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
    document.getElementById('scan-status').innerHTML =
      '<i class="fa-solid fa-triangle-exclamation"></i> Camera not available. Use manual entry below.';
  });
}

function stopScanner() {
  if (scanner) { scanner.stop().catch(function() {}); scanner = null; }
  document.getElementById('btn-start').style.display = 'flex';
  document.getElementById('btn-stop').style.display  = 'none';
}
