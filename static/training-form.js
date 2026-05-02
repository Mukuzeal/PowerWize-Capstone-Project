function selectTraining(card, key) {
  document.querySelectorAll('.training-card').forEach(function(c) { c.classList.remove('selected'); });
  card.classList.add('selected');
  card.querySelector('input[type=radio]').checked = true;
  loadSchedules(key);
}

function loadSchedules(key) {
  if (key === 'selfpaced_online') key = 'online';
  if (key === 'selfpaced_f2f')    key = 'face_to_face';
  var list   = document.getElementById('schedule-list');
  var hidden = document.getElementById('schedule-hidden');
  var ph     = document.getElementById('schedule-placeholder');
  if (ph) ph.remove();
  list.innerHTML = '';
  (SCHEDULES[key] || []).forEach(function(s) {
    var label = document.createElement('label');
    label.className = 'sched-opt' + (hidden.value === String(s.id) ? ' selected' : '');
    label.innerHTML = '<input type="radio" name="_sched_display" value="' + s.id + '" ' +
      (hidden.value === String(s.id) ? 'checked' : '') + '> ' + s.label;
    label.querySelector('input').addEventListener('change', function() {
      document.querySelectorAll('.sched-opt').forEach(function(o) { o.classList.remove('selected'); });
      label.classList.add('selected');
      hidden.value = String(s.id);
    });
    list.appendChild(label);
  });
}

(function() {
  var bd    = document.querySelector('[name="birthdate"]');
  if (!bd) return;
  var today = new Date();
  bd.max = today.toISOString().split('T')[0];
  bd.min = (today.getFullYear() - 90) + '-01-01';

  bd.addEventListener('input', function() {
    if (this.value > this.max) this.value = this.max;
    if (this.value < this.min) this.value = this.min;
  });

  bd.addEventListener('change', function() {
    var birth = new Date(this.value);
    if (isNaN(birth.getTime())) return;
    var now = new Date();
    var age = now.getFullYear() - birth.getFullYear();
    var m   = now.getMonth() - birth.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < birth.getDate())) age--;
    if (age >= 0) document.querySelector('[name="age"]').value = age;
  });
})();
