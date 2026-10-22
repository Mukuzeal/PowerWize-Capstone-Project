/* Opens the legal docs (privacy policy, terms) in a SweetAlert2 modal.
   The registration forms are multi-step wizards holding uploaded files, so
   following the link would throw away the trainee's progress mid-fill.

   Any anchor carrying data-legal="<api url>" is intercepted; its href stays a
   real link to the full page, which is what happens if SweetAlert2, fetch, or
   the request itself is unavailable.

   Those anchors must keep target="_blank". initCurtain() in ewize.js installs
   its own document-level click handler on every <a> and navigates with
   window.location.href on a timer, so preventDefault here cannot stop it --
   its listener is registered first because base.html loads ewize.js ahead of
   the page's scripts block. target="_blank" is the one condition that makes
   the curtain skip a link, and it doubles as the right no-JS fallback: open
   the policy in a new tab rather than discarding a half-filled wizard. */
(function () {
  var cache = {};

  function show(doc) {
    var note = doc.effective ? 'Effective ' + doc.effective : '';
    if (doc.version) note += (note ? ' \u00b7 ' : '') + doc.version;

    Swal.fire({
      title: doc.title,
      html: '<div class="legal-modal">' + doc.html + '</div>',
      footer: note || undefined,
      width: '46rem',
      showCloseButton: true,
      confirmButtonText: 'Close',
      confirmButtonColor: '#16583C'
    });
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('a[data-legal]');
    if (!link) return;
    if (typeof Swal === 'undefined' || !window.fetch) return;  // plain link

    e.preventDefault();
    var url = link.getAttribute('data-legal');

    if (cache[url]) { show(cache[url]); return; }

    Swal.fire({
      title: 'Loading\u2026',
      showConfirmButton: false,
      allowOutsideClick: false,
      didOpen: function () { Swal.showLoading(); }
    });

    fetch(url, { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (doc) {
        cache[url] = doc;
        show(doc);
      })
      .catch(function () {
        Swal.close();
        window.open(link.href, '_blank', 'noopener');
      });
  });
})();
