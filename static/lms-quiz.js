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
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
        },
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
  // Always intercepts the click (returns false) and shows a custom modal
  // instead of the native confirm() — it lists exactly which question
  // numbers are still blank (radio groups AND text/textarea types, unlike
  // the old count-only check) and requires an explicit "Submit" either way.
  window.confirmSubmit = function() {
    var questions   = document.querySelectorAll('.quiz-question-block');
    var unanswered  = [];
    questions.forEach(function(qBlock, idx) {
      var radios = qBlock.querySelectorAll('input[type=radio]');
      if (radios.length) {
        if (!qBlock.querySelector('input[type=radio]:checked')) unanswered.push(idx + 1);
        return;
      }
      var field = qBlock.querySelector('input[type=text], textarea');
      if (field && !field.value.trim()) unanswered.push(idx + 1);
    });

    var modal = document.getElementById('quiz-confirm-modal');
    var body  = document.getElementById('quiz-confirm-body');
    if (unanswered.length) {
      body.innerHTML =
        '<p><i class="fa-solid fa-triangle-exclamation" style="color:#f59e0b"></i> ' +
        'You have <strong>' + unanswered.length + '</strong> unanswered question' +
        (unanswered.length > 1 ? 's' : '') + ': <strong>#' + unanswered.join(', #') + '</strong>.</p>' +
        '<p>Are you sure you want to submit?</p>';
    } else {
      body.innerHTML = '<p>Submit your quiz now? <strong>This cannot be undone</strong> and you will not be able to retake it.</p>';
    }
    modal.style.display = 'flex';
    return false;
  };

  window.quizConfirmGoBack = function() {
    document.getElementById('quiz-confirm-modal').style.display = 'none';
  };

  window.quizConfirmSubmitAnyway = function() {
    document.getElementById('quiz-confirm-modal').style.display = 'none';
    submitted = true;
    document.getElementById('quiz-form').submit();
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
