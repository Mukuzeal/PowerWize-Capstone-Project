/* PowerWize capstone site behaviour.
   Three jobs: mobile nav, page-transition curtain, and a reveal fallback for
   browsers without CSS scroll-driven animations. The lightbox and gallery
   builder load only on the pages that declare them.

   There is deliberately no scroll listener anywhere in this file. Reveals use
   IntersectionObserver; the progress bar uses a CSS scroll timeline. */
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── Mobile navigation ─────────────────────────────────────────────── */
  var toggle = document.querySelector(".nav__toggle");
  var links = document.querySelector(".nav__links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* ── Page-transition curtain ───────────────────────────────────────────
     Internal navigations play the curtain out, then follow the link. Anything
     that leaves the site, opens a new tab, downloads, or is modifier-clicked
     is left entirely alone. */
  var curtain = document.querySelector(".curtain");
  if (curtain && !reduce) {
    document.addEventListener("click", function (e) {
      var a = e.target.closest ? e.target.closest("a") : null;
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#") return;
      if (a.target === "_blank" || a.hasAttribute("download")) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      if (a.hostname && a.hostname !== window.location.hostname) return;
      if (/\.(pdf|png|jpe?g|zip)$/i.test(href)) return;

      e.preventDefault();
      curtain.classList.add("is-out");
      window.setTimeout(function () { window.location.href = a.href; }, 400);
    });
    // Restore the curtain when the page is served from the back/forward cache,
    // otherwise returning to a page leaves it covered.
    window.addEventListener("pageshow", function (ev) {
      if (ev.persisted) curtain.classList.remove("is-out");
    });
  }

  /* ── Reveal fallback ───────────────────────────────────────────────────
     Only engaged when the browser cannot drive the reveals from the scroll
     timeline. The hiding class lives on <html>, added here, so a page without
     JS is never blank. */
  var hasScrollTimeline =
    window.CSS && CSS.supports && CSS.supports("animation-timeline", "view()");

  if (!hasScrollTimeline && !reduce && "IntersectionObserver" in window) {
    document.documentElement.classList.add("js-rev");

    document.querySelectorAll(".stag").forEach(function (group) {
      Array.prototype.forEach.call(group.children, function (child, i) {
        child.style.setProperty("--i", i);
      });
    });

    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          en.target.classList.add("is-in");
          io.unobserve(en.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );

    document.querySelectorAll(".rev, .rev-l, .rev-r, .stag").forEach(function (el) {
      io.observe(el);
    });
  }

  /* ── Gallery builder ───────────────────────────────────────────────────
     Runs only where window.PW_GALLERY is defined (the gallery page). Paths are
     relative to the page, which is also the Pages site root. */
  var host = document.getElementById("gallery");
  if (host && window.PW_GALLERY) {
    var html = "";
    window.PW_GALLERY.forEach(function (group) {
      // The reveal goes on the heading, never on the <section>. An entry-based
      // range never completes for an element taller than the viewport, so a
      // whole gallery group would sit at partial opacity forever.
      html +=
        '<section class="gal">' +
        '<div class="gal__head rev"><h2 class="d3">' + group.title + "</h2>" +
        '<span class="count">' + group.shots.length + " frames</span></div>" +
        '<div class="shots stag">';
      group.shots.forEach(function (s) {
        var src = "screenshots/" + group.dir + "/" + s[0];
        html +=
          '<button type="button" class="shot shot--btn shot--tall rev-img" ' +
          'data-src="' + src + '" data-cap="' + s[1] + '">' +
          '<img loading="lazy" decoding="async" src="' + src + '" alt="' + s[1] + '">' +
          "<figcaption>" + s[1] + "</figcaption></button>";
      });
      html += "</div></section>";
    });
    host.innerHTML = html;

    if (!hasScrollTimeline && !reduce && "IntersectionObserver" in window) {
      document.documentElement.classList.add("js-rev");
      var io2 = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            en.target.classList.add("is-in");
            io2.unobserve(en.target);
          });
        },
        { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
      );
      host.querySelectorAll(".rev, .stag").forEach(function (el) {
        if (el.classList.contains("stag")) {
          Array.prototype.forEach.call(el.children, function (c, i) {
            c.style.setProperty("--i", i);
          });
        }
        io2.observe(el);
      });
    }
  }

  /* ── Lightbox ──────────────────────────────────────────────────────────
     Focus is moved to the close control on open and returned to the trigger on
     close, so keyboard users are not dropped at the top of the document. */
  var lb = document.getElementById("lb");
  if (lb) {
    var lbImg = document.getElementById("lbImg");
    var lbCap = document.getElementById("lbCap");
    var lbX = document.getElementById("lbX");
    var lastTrigger = null;

    function open(btn) {
      lastTrigger = btn;
      lbImg.src = btn.getAttribute("data-src");
      lbImg.alt = btn.getAttribute("data-cap");
      lbCap.textContent = btn.getAttribute("data-cap");
      lb.classList.add("is-open");
      document.body.style.overflow = "hidden";
      lbX.focus();
    }
    function close() {
      lb.classList.remove("is-open");
      document.body.style.overflow = "";
      lbImg.removeAttribute("src");
      if (lastTrigger) { lastTrigger.focus(); lastTrigger = null; }
    }

    document.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest(".shot--btn") : null;
      if (btn) { open(btn); return; }
      if (e.target === lb || e.target === lbX) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && lb.classList.contains("is-open")) close();
    });
  }
})();
