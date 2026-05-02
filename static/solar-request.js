function syncRadio(input) {
  document.querySelectorAll('.radio-group').forEach(function(g) {
    g.querySelectorAll('.radio-opt').forEach(function(opt) {
      opt.classList.toggle('selected', opt.querySelector('input').checked);
    });
  });
}
document.querySelectorAll('.radio-opt input').forEach(function(r) {
  if (r.checked) syncRadio(r);
});

async function handleBillUpload(input) {
  if (!input.files[0]) return;
  var file = input.files[0];
  var drop = document.getElementById('bill-drop');
  drop.classList.add('has-file');
  document.getElementById('bill-name').textContent = '✓ ' + file.name;
  drop.querySelector('i.upload-ico').className = 'fa-solid fa-circle-check upload-ico';
  document.getElementById('ocr-result').classList.remove('show');
  document.getElementById('ocr-error').style.display = 'none';
  document.getElementById('ocr-spinner').style.display = 'block';

  var fd = new FormData();
  fd.append('bill', file);
  try {
    var res = await fetch('/solar/ocr', { method: 'POST', body: fd });
    var data = await res.json();
    document.getElementById('ocr-spinner').style.display = 'none';
    if (data.error) {
      document.getElementById('ocr-error').textContent = data.error;
      document.getElementById('ocr-error').style.display = 'block';
      return;
    }
    if (data.kwh) {
      document.getElementById('field-kwh').value = data.kwh;
      document.getElementById('ocr-kwh-val').textContent = data.kwh + ' kWh';
    }
    if (data.amount) {
      document.getElementById('field-bill').value = data.amount;
      document.getElementById('ocr-amount-val').textContent = '₱' + Number(data.amount).toLocaleString();
    }
    document.getElementById('ocr-result').classList.add('show');
  } catch (e) {
    document.getElementById('ocr-spinner').style.display = 'none';
    document.getElementById('ocr-error').textContent = 'Could not scan bill. Please enter values manually.';
    document.getElementById('ocr-error').style.display = 'block';
  }
}

document.getElementById('solar-form').addEventListener('submit', function() {
  var btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Computing estimate…';
});
