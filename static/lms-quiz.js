/* LMS Quiz anti-cheat + timer */

function initQuiz(opts) {
  var attemptId    = opts.attemptId;
  var timeLimitMin = opts.timeLimitMin || 30;
  var tabSwitchUrl = opts.tabSwitchUrl;
  var tabSwitches  = 0;

  // ── Disable right-click ───────────────────────────────────────────────────
  document.addEventListener('contextmenu', function(e) { e.preventDefault(); });

  // ── Disable text selection ────────────────────────────────────────────────
  document.addEventListener('selectstart', function(e) { e.preventDefault(); });

  // ── Disable copy / cut ───────────────────────────────────────────────────
  document.addEventListener('copy',  function(e) { e.preventDefault(); });
  document.addEventListener('cut',   function(e) { e.preventDefault(); });

  // ── Disable common keyboard shortcuts ────────────────────────────────────
  document.addEventListener('keydown', function(e) {
    var blocked = (
      (e.ctrlKey && ['c','x','u','s','a','p'].includes(e.key.toLowerCase())) ||
      e.key === 'F12' ||
      (e.ctrlKey && e.shiftKey && e.key === 'I') ||
      (e.ctrlKey && e.shiftKey && e.key === 'J') ||
      (e.ctrlKey && e.shiftKey && e.key === 'C')
    );
    if (blocked) e.preventDefault();
  });

  // ── Tab / window focus detection ──────────────────────────────────────────
  function onVisibilityChange() {
    if (document.hidden) {
      tabSwitches++;
      document.getElementById('tab-count').textContent = tabSwitches;
      document.getElementById('tab-warn').style.display = 'flex';
      // Record server-side
      fetch(tabSwitchUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attempt_id: attemptId })
      }).catch(function() {});
    }
  }
  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('blur', onVisibilityChange);

  // ── Watermark with user name ──────────────────────────────────────────────
  var wm = document.getElementById('quiz-watermark');
  if (wm) {
    // Repeat the watermark in a diagonal pattern via JS
    var text = wm.textContent || wm.innerText;
    var repeated = '';
    for (var i = 0; i < 40; i++) {
      repeated += text + ' · ';
    }
    wm.textContent = repeated;
  }

  // ── Countdown timer ───────────────────────────────────────────────────────
  var totalSeconds = timeLimitMin * 60;
  var timerEl = document.getElementById('quiz-timer');

  function updateTimer() {
    var min = Math.floor(totalSeconds / 60);
    var sec = totalSeconds % 60;
    timerEl.textContent = min + ':' + (sec < 10 ? '0' : '') + sec;

    if (totalSeconds <= 300) {
      timerEl.classList.add('timer-warning');
    }
    if (totalSeconds <= 60) {
      timerEl.classList.add('timer-critical');
    }
    if (totalSeconds <= 0) {
      clearInterval(timerInterval);
      timerEl.textContent = '0:00';
      // Auto-submit
      var form = document.getElementById('quiz-form');
      if (form) {
        var notice = document.createElement('p');
        notice.style.cssText = 'color:#DC2626;font-weight:700;text-align:center;margin:8px';
        notice.textContent = 'Time is up! Submitting your quiz…';
        form.appendChild(notice);
        setTimeout(function() { form.submit(); }, 1500);
      }
      return;
    }
    totalSeconds--;
  }
  updateTimer();
  var timerInterval = setInterval(updateTimer, 1000);

  // ── Confirm before submit ─────────────────────────────────────────────────
  window.confirmSubmit = function() {
    var questions = document.querySelectorAll('.quiz-question-block');
    var answered  = 0;
    questions.forEach(function(qBlock) {
      var checked = qBlock.querySelector('input[type=radio]:checked');
      if (checked) answered++;
    });
    var unanswered = questions.length - answered;
    if (unanswered > 0) {
      return confirm(unanswered + ' question(s) unanswered. Submit anyway?');
    }
    return confirm('Submit your quiz? This cannot be undone.');
  };

  // ── Prevent page unload during quiz ──────────────────────────────────────
  var submitted = false;
  document.getElementById('quiz-form').addEventListener('submit', function() {
    submitted = true;
  });
  window.addEventListener('beforeunload', function(e) {
    if (!submitted) {
      e.preventDefault();
      e.returnValue = 'Leaving will not save your answers. Are you sure?';
    }
  });
}
