/* Vanilla ports of React Bits components (no React/GSAP/Motion in this
   Flask/Jinja stack): a CardNav-style expandable pill nav, a TiltedCard-style
   pointer tilt, and a full BorderGlow port (edge-proximity + cursor-angle
   math ported verbatim, rendered with the same mesh-gradient border /
   conic-gradient direction mask / edge-light glow technique as the original,
   using this project's brand colors instead of the demo's purple/pink/blue).
   All are inert under prefers-reduced-motion; tilt only attaches on
   fine-pointer (non-touch) devices. */
(function () {
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  document.addEventListener('DOMContentLoaded', function () {
    initPillNav();
    if (!reduceMotion && finePointer) {
      initTiltCards();
    }
    if (!reduceMotion) {
      initBorderGlowCards();
    }
  });

  /* ── CardNav-style pill nav ───────────────────────────────────────────── */
  function initPillNav() {
    var nav = document.getElementById('pillNav');
    var toggle = document.getElementById('pillNavToggle');
    if (!nav || !toggle) return;

    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    nav.querySelectorAll('.pill-nav-card a').forEach(function (a) {
      a.addEventListener('click', function () {
        nav.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* ── TiltedCard-style pointer tilt ───────────────────────────────────── */
  function initTiltCards() {
    var cards = document.querySelectorAll('[data-tilt]');
    cards.forEach(function (card) {
      var amplitude = parseFloat(card.dataset.tiltAmplitude) || 8;

      card.addEventListener('pointerenter', function (e) {
        if (e.pointerType !== 'mouse') return;
        card.classList.add('is-tilting');
      });

      card.addEventListener('pointermove', function (e) {
        if (e.pointerType !== 'mouse') return;
        var rect = card.getBoundingClientRect();
        var offsetX = e.clientX - rect.left - rect.width / 2;
        var offsetY = e.clientY - rect.top - rect.height / 2;
        var rotateX = (offsetY / (rect.height / 2)) * -amplitude;
        var rotateY = (offsetX / (rect.width / 2)) * amplitude;
        card.style.transform = 'perspective(900px) rotateX(' + rotateX.toFixed(2) + 'deg) rotateY(' +
          rotateY.toFixed(2) + 'deg) translateY(-6px) scale(1.015)';
      });

      card.addEventListener('pointerleave', function (e) {
        if (e.pointerType !== 'mouse') return;
        card.classList.remove('is-tilting');
        card.style.transform = '';
      });
    });
  }

  /* ── BorderGlow: edge-proximity + cursor-angle (ported verbatim) ────────
     --edge-proximity: 0-100, how close the pointer is to the card's border.
     --cursor-angle: degrees around the card, used by the CSS conic-gradient
     mask to reveal the glow only on the side nearest the cursor. */
  function initBorderGlowCards() {
    var cards = document.querySelectorAll('[data-border-glow]');
    cards.forEach(function (card) {
      card.addEventListener('pointermove', function (e) {
        var rect = card.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var y = e.clientY - rect.top;
        card.style.setProperty('--edge-proximity', (edgeProximity(rect, x, y) * 100).toFixed(2));
        card.style.setProperty('--cursor-angle', cursorAngle(rect, x, y).toFixed(2) + 'deg');
      });
      card.addEventListener('pointerleave', function () {
        card.style.setProperty('--edge-proximity', '0');
      });
    });
  }

  function edgeProximity(rect, x, y) {
    var cx = rect.width / 2;
    var cy = rect.height / 2;
    var dx = x - cx;
    var dy = y - cy;
    var kx = Infinity;
    var ky = Infinity;
    if (dx !== 0) kx = cx / Math.abs(dx);
    if (dy !== 0) ky = cy / Math.abs(dy);
    return Math.min(Math.max(1 / Math.min(kx, ky), 0), 1);
  }

  function cursorAngle(rect, x, y) {
    var cx = rect.width / 2;
    var cy = rect.height / 2;
    var dx = x - cx;
    var dy = y - cy;
    if (dx === 0 && dy === 0) return 0;
    var degrees = Math.atan2(dy, dx) * (180 / Math.PI) + 90;
    if (degrees < 0) degrees += 360;
    return degrees;
  }
})();
