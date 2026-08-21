/* Busy state for plain form submits.

   The async flows already draw their own feedback — payment buttons (payment.js),
   solar chat and the module chat (typing indicators), bill OCR, upload validation.
   What had nothing was the ordinary server-rendered POST: login, password reset,
   the registration wizard, quiz submission. On a slow request those buttons looked
   dead and could be clicked twice, which on a graded quiz means two submissions.

   Opt a form out with data-no-busy (use it when the form already manages its own
   button, as solar-request.js does). Override the wording with data-busy-label on
   the submit button. */
(function () {
  var HOLD_MS = 15000;  // never leave a button permanently dead

  var CSS =
    '.pw-busy-dot{display:inline-block;width:.85em;height:.85em;margin-right:.5em;' +
    'vertical-align:-.1em;border:2px solid currentColor;border-right-color:transparent;' +
    'border-radius:50%;animation:pw-busy-spin .6s linear infinite}' +
    '@keyframes pw-busy-spin{to{transform:rotate(360deg)}}' +
    '@media(prefers-reduced-motion:reduce){.pw-busy-dot{animation:none;opacity:.6}}';

  function injectCss() {
    if (document.getElementById('pw-busy-css')) return;
    var s = document.createElement('style');
    s.id = 'pw-busy-css';
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function setBusy(btn) {
    if (btn.hasAttribute('data-pw-busy')) return;
    var isInput = btn.tagName === 'INPUT';
    btn.setAttribute('data-pw-busy', isInput ? btn.value : btn.innerHTML);
    var label = btn.getAttribute('data-busy-label') || 'Working…';
    if (isInput) btn.value = label;
    else btn.innerHTML = '<span class="pw-busy-dot"></span>' + label;
    btn.setAttribute('aria-busy', 'true');
    btn.disabled = true;
    setTimeout(function () { clearBusy(btn); }, HOLD_MS);
  }

  function clearBusy(btn) {
    if (!btn.hasAttribute('data-pw-busy')) return;
    var prev = btn.getAttribute('data-pw-busy');
    if (btn.tagName === 'INPUT') btn.value = prev;
    else btn.innerHTML = prev;
    btn.removeAttribute('data-pw-busy');
    btn.removeAttribute('aria-busy');
    btn.disabled = false;
  }

  function arm(form) {
    form.addEventListener('submit', function (e) {
      var btn = e.submitter ||
                form.querySelector('button[type=submit],input[type=submit],.btn-submit');
      if (!btn || btn.disabled) return;
      setTimeout(function () {
        // Checked here, not synchronously: wizard.js loads without defer, so its
        // validating listener may be registered after this one. Reading
        // defaultPrevented once the event has finished propagating means listener
        // order does not matter — a blocked submit never shows a busy button.
        if (e.defaultPrevented) return;
        // Deferring also keeps the button's own name/value in the payload, which
        // the admin forms rely on.
        setBusy(btn);
      }, 0);
    });
  }

  function boot() {
    injectCss();
    var forms = document.querySelectorAll('form:not([data-no-busy])');
    Array.prototype.forEach.call(forms, arm);
  }

  // Back-navigation restores the page from bfcache with the button still disabled.
  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    var stuck = document.querySelectorAll('[data-pw-busy]');
    Array.prototype.forEach.call(stuck, clearBusy);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
