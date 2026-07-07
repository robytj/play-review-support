/* ============================================================================
   static/web/support.js — shared behavior for NON-chat pages.
   Progressive enhancement ONLY: every page works with JS disabled (SPEC §9,
   "JS on non-chat pages: 0" is a transfer-budget target — this file is tiny and
   deferred, and nothing here is required for the page to function). Vanilla ES6.

   Handles: identity sheet open/close/validate, language picker, helpful vote
   (AJAX with graceful form fallback), toasts.
   ========================================================================== */
(function () {
  'use strict';
  var d = document;
  var $ = function (s, r) { return (r || d).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || d).querySelectorAll(s)); };

  /* ---- Toasts (also used by chat.js via window.PRToast) ------------------ */
  function toast(msg, kind) {
    var layer = $('#toast-layer');
    if (!layer) return;
    var el = d.createElement('div');
    el.className = 'toast' + (kind === 'bad' ? ' toast--bad' : '');
    el.setAttribute('role', 'status');
    el.innerHTML = '<span class="toast__dot"></span><span></span>';
    el.lastChild.textContent = msg;
    layer.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .2s'; el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 220);
    }, 3200);
  }
  window.PRToast = toast;

  /* ---- Identity sheet ----------------------------------------------------- */
  var scrim = $('#identity-sheet');
  var lastFocus = null;

  function openSheet() {
    if (!scrim) return;
    lastFocus = d.activeElement;
    scrim.classList.remove('hidden'); scrim.removeAttribute('hidden');
    var f = scrim.querySelector('input, button'); if (f) f.focus();
    d.addEventListener('keydown', onKey);
  }
  function closeSheet() {
    if (!scrim) return;
    scrim.classList.add('hidden'); scrim.setAttribute('hidden', '');
    d.removeEventListener('keydown', onKey);
    if (lastFocus) lastFocus.focus();
  }
  function onKey(e) { if (e.key === 'Escape') closeSheet(); }

  $$('[data-open-identity]').forEach(function (b) { b.addEventListener('click', openSheet); });
  $$('[data-close-identity]').forEach(function (b) { b.addEventListener('click', closeSheet); });
  $$('[data-skip-identity]').forEach(function (b) {
    b.addEventListener('click', function () { closeSheet(); });
  });
  if (scrim) scrim.addEventListener('click', function (e) { if (e.target === scrim) closeSheet(); });

  /* SID validation — format PR-XXXX-XXXX, inline error, no alert() */
  var form = $('[data-identity-form]');
  if (form) {
    var sid = form.querySelector('[name="sid"]');
    var email = form.querySelector('[name="email"]');
    var err = form.querySelector('[data-sid-err]');
    var SID_RE = /^PR-[A-Z0-9]{4}-[A-Z0-9]{4}$/;

    if (sid) sid.addEventListener('input', function () {
      sid.value = sid.value.toUpperCase();
      if (err) { err.classList.add('hidden'); }
      sid.removeAttribute('aria-invalid');
    });

    form.addEventListener('submit', function (e) {
      var hasSid = sid && sid.value.trim();
      var hasEmail = email && email.value.trim();
      if (hasSid && !SID_RE.test(sid.value.trim())) {
        e.preventDefault();
        if (err) { err.textContent = form.getAttribute('data-err-format') || "That doesn't look like a SID. Check the format PR-XXXX-XXXX."; err.classList.remove('hidden'); }
        sid.setAttribute('aria-invalid', 'true'); sid.focus();
        return;
      }
      if (!hasSid && !hasEmail) {
        e.preventDefault();
        if (err) { err.textContent = 'Enter a SID or a registered email.'; err.classList.remove('hidden'); }
        (sid || email).focus();
      }
      /* valid → let the POST proceed (server links + redirects). */
    });
  }

  /* ---- Helpful vote (AJAX, falls back to form POST) ---------------------- */
  $$('[data-vote]').forEach(function (widget) {
    var formEl = widget.querySelector('[data-vote-form]');
    var label = widget.querySelector('[data-vote-label]');
    if (!formEl) return;
    formEl.addEventListener('submit', function (e) {
      e.preventDefault();
      var val = (e.submitter && e.submitter.value) || 'up';
      fetch(formEl.action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'fetch' },
        body: 'v=' + encodeURIComponent(val)
      }).catch(function () {}).finally(function () {
        var thanks = (val === 'up')
          ? (widget.getAttribute('data-thanks') || 'Thanks for the feedback.')
          : (widget.getAttribute('data-thanks-down') || 'Sorry that didn\u2019t land. Want to ask us directly?');
        formEl.classList.add('hidden');
        if (label) label.innerHTML = '';
        var done = d.createElement('span');
        done.className = 'vote__done'; done.textContent = thanks;
        widget.appendChild(done);
        if (val === 'down') {
          var cta = d.createElement('a');
          cta.className = 'btn btn--sm'; cta.href = '/chat'; cta.textContent = 'Chat with us';
          cta.style.marginInlineStart = '4px';
          widget.appendChild(cta);
        }
      });
    });
  });

  /* ---- Language picker (navigates to ?lang=) ----------------------------- */
  var LANGS = [['en', 'EN'], ['pt-BR', 'PT'], ['es', 'ES'], ['ar', 'AR']];
  $$('[data-lang-picker]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      /* minimal inline menu; server persists choice in session + cookie */
      var cur = (d.documentElement.lang || 'en');
      var idx = LANGS.findIndex(function (l) { return l[0] === cur; });
      var next = LANGS[(idx + 1) % LANGS.length][0];
      var u = new URL(window.location.href);
      u.searchParams.set('lang', next);
      window.location.href = u.toString();
    });
  });
})();
