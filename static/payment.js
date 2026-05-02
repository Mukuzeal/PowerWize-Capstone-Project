/* Payment page JS — CONFIG object injected inline by template */

var _pollInterval = null;
var _timerInterval = null;
var _qrPiId = null;

function switchTab(tab, btn) {
  document.querySelectorAll('.pay-tab').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('.pay-panel').forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  clearError();
}

function showError(msg) {
  var el = document.getElementById('err-box');
  el.textContent = msg;
  el.classList.add('shown');
}
function clearError() {
  var el = document.getElementById('err-box');
  el.textContent = '';
  el.classList.remove('shown');
}

document.getElementById('card-number').addEventListener('input', function() {
  var v = this.value.replace(/\D/g, '').substring(0, 16);
  this.value = v.match(/.{1,4}/g)?.join(' ') || v;
});
document.getElementById('card-expiry').addEventListener('input', function() {
  var v = this.value.replace(/\D/g, '').substring(0, 4);
  if (v.length >= 2) v = v.substring(0, 2) + ' / ' + v.substring(2);
  this.value = v;
});
document.getElementById('card-cvc').addEventListener('input', function() {
  this.value = this.value.replace(/\D/g, '').substring(0, 4);
});

async function payCard() {
  clearError();
  var numRaw = document.getElementById('card-number').value.replace(/\s/g, '');
  var expRaw = document.getElementById('card-expiry').value.replace(/\s/g, '').replace('/', '');
  var cvc    = document.getElementById('card-cvc').value.trim();
  var name   = document.getElementById('card-name').value.trim();

  if (!numRaw || !expRaw || !cvc || !name) { showError('Please fill in all card details.'); return; }

  var expMonth = parseInt(expRaw.substring(0, 2));
  var expYear  = parseInt('20' + expRaw.substring(2, 4));

  var btn = document.getElementById('btn-card-pay');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Processing…';

  try {
    var init = await fetch('/payment/card/initiate', { method: 'POST' }).then(function(r) { return r.json(); });
    if (init.error) { showError(init.error); resetCardBtn(); return; }

    var pm = await paymongo.createPaymentMethod({
      type: 'card',
      card: { number: numRaw, exp_month: expMonth, exp_year: expYear, cvc: cvc },
      billing: { name: name }
    });
    if (!pm?.data?.id) { showError('Failed to process card. Please check your details.'); resetCardBtn(); return; }

    var attach = await fetch('/payment/card/attach', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payment_method_id: pm.data.id, client_key: init.client_key })
    }).then(function(r) { return r.json(); });

    if (attach.status === 'paid') {
      window.location.href = '/payment/success';
    } else if (attach.status === 'redirect') {
      window.location.href = attach.url;
    } else if (attach.error) {
      showError(attach.error); resetCardBtn();
    } else {
      showError('Payment could not be completed. Please try again.'); resetCardBtn();
    }
  } catch (e) {
    showError('An error occurred. Please try again.'); resetCardBtn();
  }
}

function resetCardBtn() {
  var btn = document.getElementById('btn-card-pay');
  btn.disabled = false;
  btn.innerHTML = '<i class="fa-solid fa-lock"></i> Pay ' + CONFIG.feeDisplay;
}

async function generateQR() {
  clearError();
  var btn = document.getElementById('btn-gen-qr');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Generating…';

  try {
    var data = await fetch('/payment/qrph/initiate', { method: 'POST' }).then(function(r) { return r.json(); });
    if (data.error) { showError(data.error); resetQRBtn(); return; }

    _qrPiId = data.pi_id;
    var qrImg = document.getElementById('qr-img');
    if (data.qr_image) {
      qrImg.src = data.qr_image;
    } else {
      showError('QR code could not be generated. Please try again.'); resetQRBtn(); return;
    }

    document.getElementById('qr-box').classList.add('shown');
    btn.style.display = 'none';

    if (data.test_url) {
      var link = document.getElementById('qr-test-link');
      link.href = data.test_url;
      link.style.display = 'inline-block';
    }

    var seconds = data.expire_at
      ? Math.max(0, Math.floor(data.expire_at - Date.now() / 1000))
      : 15 * 60;
    startTimer(seconds);
    startPolling();
  } catch (e) {
    showError('Failed to generate QR. Please try again.'); resetQRBtn();
  }
}

function startTimer(seconds) {
  clearInterval(_timerInterval);
  var remaining = seconds;
  _timerInterval = setInterval(function() {
    remaining--;
    var m = Math.floor(remaining / 60);
    var s = remaining % 60;
    document.getElementById('qr-timer').textContent =
      String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    if (remaining <= 0) {
      clearInterval(_timerInterval);
      clearInterval(_pollInterval);
      setQRStatus('failed', '<i class="fa-solid fa-clock"></i> QR code expired. Please generate a new one.');
      document.getElementById('btn-gen-qr').style.display = '';
      resetQRBtn();
    }
  }, 1000);
}

function startPolling() {
  clearInterval(_pollInterval);
  _pollInterval = setInterval(async function() {
    if (!_qrPiId) return;
    try {
      var http = await fetch('/payment/qrph/poll/' + _qrPiId);
      if (http.status === 400 || http.status === 401 || http.status === 403) {
        clearInterval(_pollInterval); clearInterval(_timerInterval); return;
      }
      var res = await http.json();
      if (res.status === 'paid') {
        clearInterval(_pollInterval); clearInterval(_timerInterval);
        setQRStatus('paid', '<i class="fa-solid fa-circle-check"></i> Payment received! Redirecting…');
        setTimeout(function() { window.location.href = '/payment/success'; }, 1500);
      } else if (res.status === 'failed' || res.status === 'cancelled') {
        clearInterval(_pollInterval); clearInterval(_timerInterval);
        setQRStatus('failed', '<i class="fa-solid fa-circle-xmark"></i> Payment failed. Please try again.');
        document.getElementById('btn-gen-qr').style.display = '';
        resetQRBtn();
      }
    } catch (e) { /* network hiccup, keep polling */ }
  }, 3000);
}

function setQRStatus(type, html) {
  var el = document.getElementById('qr-status');
  el.className = 'qr-status ' + type;
  el.innerHTML = html;
}

function resetQRBtn() {
  var btn = document.getElementById('btn-gen-qr');
  btn.disabled = false;
  btn.innerHTML = '<i class="fa-solid fa-qrcode"></i> Generate QR Code';
}
