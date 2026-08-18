/* ==========================================================================
   ENERGYWIZE SOLUTIONS — MOTION ENGINE
   Zero dependencies. Transform/opacity only. Everything cleans up after itself.
   ========================================================================== */
(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var raf = window.requestAnimationFrame.bind(window);

  /* ------------------------------------------------------------------ *
   * Scroll reveals — one observer for the whole document.
   * Stagger index is assigned per reveal-group so cascades stay local.
   * ------------------------------------------------------------------ */
  function initReveals() {
    var nodes = document.querySelectorAll("[data-reveal], [data-reveal-group]");
    if (!nodes.length) return;

    document.querySelectorAll("[data-reveal-group]").forEach(function (group) {
      var kids = group.querySelectorAll("[data-reveal], .reveal-line");
      for (var i = 0; i < kids.length; i++) kids[i].style.setProperty("--i", i);
    });

    if (reduced || !("IntersectionObserver" in window)) {
      nodes.forEach(function (n) { n.classList.add("is-in"); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("is-in");
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.08 });

    nodes.forEach(function (n) { io.observe(n); });
  }

  /* ------------------------------------------------------------------ *
   * SVG line-draw — measure paths so CSS can dash them.
   * ------------------------------------------------------------------ */
  function initDraw() {
    document.querySelectorAll(".draw").forEach(function (p) {
      var len = 0;
      try { len = p.getTotalLength(); } catch (err) { len = 1200; }
      p.style.setProperty("--len", Math.ceil(len));
    });
  }

  /* ------------------------------------------------------------------ *
   * Navigation — sliding indicator, burger morph, full-screen menu.
   * ------------------------------------------------------------------ */
  function initNav() {
    var rail = document.querySelector(".nav__rail");
    var burger = document.querySelector(".nav__burger");
    var menu = document.getElementById("menu");

    if (rail) {
      var ind = rail.querySelector(".nav__ind");
      var items = rail.querySelectorAll(".nav__item");
      var current = rail.querySelector('.nav__item[aria-current="page"]');

      var place = function (el) {
        if (!el || !ind) return;
        var r = el.getBoundingClientRect();
        var base = rail.getBoundingClientRect();
        ind.style.setProperty("--x", (r.left - base.left) + "px");
        ind.style.setProperty("--sx", r.width / 100);
      };

      var lock = function () {
        if (!ind) return;
        if (current) { place(current); ind.classList.add("is-locked"); }
        else { ind.classList.remove("is-locked"); ind.style.setProperty("--sx", 0); }
      };

      items.forEach(function (el) {
        el.addEventListener("pointerenter", function () { place(el); });
        el.addEventListener("focus", function () { place(el); });
      });
      rail.addEventListener("pointerleave", lock);

      lock();
      window.addEventListener("resize", lock, { passive: true });
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(lock).catch(function () {});
    }

    if (burger && menu) {
      var open = false;
      var toggle = function (next) {
        open = typeof next === "boolean" ? next : !open;
        burger.setAttribute("aria-expanded", String(open));
        menu.classList.toggle("is-open", open);
        menu.setAttribute("aria-hidden", String(!open));
        document.documentElement.style.overflow = open ? "hidden" : "";
      };
      burger.addEventListener("click", function () { toggle(); });
      menu.addEventListener("click", function (e) {
        if (e.target.closest("a")) toggle(false);
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && open) { toggle(false); burger.focus(); }
      });
    }
  }

  /* ------------------------------------------------------------------ *
   * Spotlight cards — pointer position written to CSS custom properties.
   * Throttled to one write per frame.
   * ------------------------------------------------------------------ */
  function initSpotlight() {
    if (reduced) return;
    var cards = document.querySelectorAll(".cap");
    cards.forEach(function (card) {
      var queued = false, px = 0, py = 0;
      card.addEventListener("pointermove", function (e) {
        var r = card.getBoundingClientRect();
        px = e.clientX - r.left;
        py = e.clientY - r.top;
        if (queued) return;
        queued = true;
        raf(function () {
          card.style.setProperty("--mx", px + "px");
          card.style.setProperty("--my", py + "px");
          queued = false;
        });
      }, { passive: true });
    });
  }

  /* ------------------------------------------------------------------ *
   * Magnetic controls — buttons lean toward the cursor. Pointer-fine only.
   * ------------------------------------------------------------------ */
  function initMagnetic() {
    if (reduced || !window.matchMedia("(pointer: fine)").matches) return;
    document.querySelectorAll("[data-magnetic]").forEach(function (el) {
      var queued = false, tx = 0, ty = 0;
      var apply = function () {
        el.style.transform = "translate3d(" + tx + "px," + ty + "px,0)";
        queued = false;
      };
      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        tx = ((e.clientX - r.left) / r.width - 0.5) * 14;
        ty = ((e.clientY - r.top) / r.height - 0.5) * 10;
        if (!queued) { queued = true; raf(apply); }
      }, { passive: true });
      el.addEventListener("pointerleave", function () {
        tx = 0; ty = 0;
        if (!queued) { queued = true; raf(apply); }
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Numeric readouts — count up once, on entry.
   * ------------------------------------------------------------------ */
  function initCounters() {
    var els = document.querySelectorAll("[data-count]");
    if (!els.length) return;

    var run = function (el) {
      var target = parseFloat(el.dataset.count);
      var dec = (el.dataset.count.split(".")[1] || "").length;
      if (reduced) { el.textContent = target.toFixed(dec); return; }
      var t0 = performance.now(), dur = 1500;
      var tick = function (now) {
        var t = Math.min((now - t0) / dur, 1);
        var eased = 1 - Math.pow(1 - t, 4);
        el.textContent = (target * eased).toFixed(dec);
        if (t < 1) raf(tick);
      };
      raf(tick);
    };

    if (!("IntersectionObserver" in window)) { els.forEach(run); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        run(e.target);
        io.unobserve(e.target);
      });
    }, { threshold: 0.5 });
    els.forEach(function (el) { io.observe(el); });
  }

  /* ------------------------------------------------------------------ *
   * Irradiance field — the hero canvas.
   * A lattice of dots that bulges away from the cursor and drifts on a
   * slow wave. Density scales with viewport; work stops when off-screen.
   * ------------------------------------------------------------------ */
  function initField() {
    var host = document.querySelector("[data-field]");
    if (!host || reduced) return;

    var canvas = document.createElement("canvas");
    host.appendChild(canvas);
    var ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var W = 0, H = 0;
    var dots = [];
    var spacing = 22, radius = 1.1;
    var mouse = { x: -9999, y: -9999, px: -9999, py: -9999, speed: 0 };
    var engage = 0;
    var frame = 0;
    var rafId = null;
    var visible = true;
    var resizeTimer = null;

    function build() {
      var step = spacing;
      var cols = Math.floor(W / step);
      var rows = Math.floor(H / step);
      var padX = (W % step) / 2 + step / 2;
      var padY = (H % step) / 2 + step / 2;
      dots = new Array(cols * rows);
      var i = 0;
      for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
          var ax = padX + c * step;
          var ay = padY + r * step;
          dots[i++] = { ax: ax, ay: ay, x: ax, y: ay, seed: (i * 2654435761) >>> 0 };
        }
      }
    }

    function size() {
      var r = host.getBoundingClientRect();
      W = r.width; H = r.height;
      if (W < 2 || H < 2) return;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      spacing = W < 720 ? 26 : 22;
      build();
    }

    function onMove(e) {
      var r = host.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    }

    function onResize() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(size, 140);
    }

    function tick() {
      rafId = raf(tick);
      if (!visible || !dots.length) return;
      frame++;

      var dx = mouse.px - mouse.x, dy = mouse.py - mouse.y;
      var moved = Math.sqrt(dx * dx + dy * dy);
      mouse.speed += (moved - mouse.speed) * 0.35;
      mouse.px = mouse.x; mouse.py = mouse.y;

      var target = Math.min(mouse.speed / 4, 1);
      engage += (target - engage) * 0.055;
      if (engage < 0.002) engage = 0;

      var t = frame * 0.012;
      var cr = 340, crSq = cr * cr;

      ctx.clearRect(0, 0, W, H);

      var grad = ctx.createLinearGradient(0, 0, W, H);
      grad.addColorStop(0, "rgba(53, 199, 124, 0.62)");
      grad.addColorStop(0.55, "rgba(53, 199, 124, 0.30)");
      grad.addColorStop(1, "rgba(233, 169, 59, 0.34)");
      ctx.fillStyle = grad;
      ctx.beginPath();

      for (var i = 0; i < dots.length; i++) {
        var d = dots[i];
        var ox = mouse.x - d.ax, oy = mouse.y - d.ay;
        var distSq = ox * ox + oy * oy;

        if (distSq < crSq && engage > 0.01) {
          var dist = Math.sqrt(distSq) || 0.001;
          var k = 1 - dist / cr;
          var push = k * k * 58 * engage;
          d.x += (d.ax - (ox / dist) * push - d.x) * 0.14;
          d.y += (d.ay - (oy / dist) * push - d.y) * 0.14;
        } else {
          d.x += (d.ax - d.x) * 0.09;
          d.y += (d.ay - d.y) * 0.09;
        }

        var wx = d.x + Math.cos(d.ay * 0.018 + t * 0.7) * 1.6;
        var wy = d.y + Math.sin(d.ax * 0.018 + t) * 1.6;

        // ~2% of dots flare, deterministically, on a slow rotation
        var r2 = ((d.seed ^ (frame >> 4)) % 100) < 2 ? radius * 2.3 : radius;
        ctx.moveTo(wx + r2, wy);
        ctx.arc(wx, wy, r2, 0, Math.PI * 2);
      }
      ctx.fill();
    }

    size();
    window.addEventListener("resize", onResize, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (e) { visible = e[0].isIntersecting; })
        .observe(host);
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }
      else if (!rafId) { rafId = raf(tick); }
    });

    rafId = raf(tick);
  }

  /* ------------------------------------------------------------------ *
   * Page transitions — a curtain wipes up on exit, down on entry.
   * Falls back to a plain navigation if anything is unusual.
   * ------------------------------------------------------------------ */
  function initCurtain() {
    var curtain = document.querySelector(".curtain");
    if (!curtain) return;

    // The incoming reveal is pure CSS (see .curtain). JS only drives the exit.
    if (reduced) return;

    document.addEventListener("click", function (e) {
      var a = e.target.closest("a");
      if (!a) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      if (a.target === "_blank" || a.hasAttribute("download")) return;

      var href = a.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#") return;
      if (a.origin !== window.location.origin) return;
      if (a.pathname === window.location.pathname) return;

      e.preventDefault();
      curtain.classList.add("is-out");
      setTimeout(function () { window.location.href = a.href; }, 560);
    });

    window.addEventListener("pageshow", function (e) {
      if (e.persisted) curtain.classList.remove("is-out");
    });
  }

  /* ------------------------------------------------------------------ *
   * Contact form — inline validation, no backend assumed.
   * ------------------------------------------------------------------ */
  function initForm() {
    var form = document.querySelector("[data-form]");
    if (!form) return;
    var note = form.querySelector(".formnote");

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ok = true;
      form.querySelectorAll("[required]").forEach(function (input) {
        var field = input.closest(".field") || input.closest(".check");
        var valid = input.type === "checkbox" ? input.checked : input.value.trim() !== "";
        if (valid && input.type === "email") valid = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(input.value);
        if (field) field.classList.toggle("is-err", !valid);
        if (!valid && ok) { input.focus(); ok = false; }
      });
      if (!ok || !note) return;
      note.classList.add("is-on");
      note.textContent =
        "Thanks — your message is ready to send. Connect this form to your inbox, or reach us directly at energywizesolutions@gmail.com.";
    });

    form.addEventListener("input", function (e) {
      var field = e.target.closest(".field") || e.target.closest(".check");
      if (field) field.classList.remove("is-err");
    });
  }

  /* ------------------------------------------------------------------ *
   * Boot
   * ------------------------------------------------------------------ */
  function boot() {
    initReveals();
    initDraw();
    initNav();
    initSpotlight();
    initMagnetic();
    initCounters();
    initField();
    initCurtain();
    initForm();
    document.documentElement.classList.add("is-ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
