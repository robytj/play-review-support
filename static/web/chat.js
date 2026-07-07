/* ============================================================================
   static/web/chat.js — /chat screen only (SPEC-02a §7). Vanilla ES6, no deps.
   Target < 40 KB uncompressed.

   Responsibilities:
     • Render all 11 server-driven message kinds by `type`.
     • Optimistic player-bubble render; POST to endpoint; poll for replies.
     • Transport ABSTRACTED in one place: Transport.send() / Transport.poll().
       Swap fetch-poll → SSE by replacing that object only (SPEC §7 behavior).
     • Scroll pinned to bottom unless user scrolled up (then "↓ new reply" chip).
     • Session restore from server (SSR seed [data-seed] then poll) — NO
       localStorage persistence of message content (SPEC §7).
     • Offline: composer disabled + banner. Char cap 1000, counter after 800.
     • Reduced motion respected (min typing display honored but CSS kills pulse).
   ========================================================================== */
(function () {
  'use strict';
  var d = document;
  var root = d.querySelector('[data-chat]');
  if (!root) return;

  var $ = function (s, r) { return (r || root).querySelector(s); };
  var transcript = $('[data-transcript]');
  var composer = $('[data-composer]');
  var input = $('[data-input]');
  var sendBtn = $('[data-send]');
  var counter = $('[data-count]');
  var newReplyChip = $('[data-new-reply]');
  var offlineBanner = $('[data-offline]');
  var ticketEyebrow = $('[data-ticket-eyebrow]');
  var sidNudge = $('[data-sid-nudge]');

  var ENABLED = root.getAttribute('data-enabled') === 'true';
  var SESSION = root.getAttribute('data-session');
  var ENDPOINT = root.getAttribute('data-endpoint');
  var POLL_URL = root.getAttribute('data-poll');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var state = {
    lastId: 0,          // highest server message id seen
    pinned: true,       // auto-scroll to bottom
    awaiting: false,    // reply in flight (composer spinner)
    pollDelay: 1500,    // fetch-poll base; backoff on failure
    pollTimer: null
  };

  /* ---------- tiny markdown-lite (bold **x**, links [t](u), lists) --------- */
  function esc(s) { return String(s).replace(/[&<>"]/g, function (m) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]; }); }

  function mdLite(text) {
    var out = esc(text);
    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // simple lists: lines starting with "- "
    var lines = out.split('\n'), html = '', inList = false;
    lines.forEach(function (ln) {
      if (/^\s*-\s+/.test(ln)) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += '<li>' + ln.replace(/^\s*-\s+/, '') + '</li>';
      } else {
        if (inList) { html += '</ul>'; inList = false; }
        if (ln.trim()) html += '<p>' + ln + '</p>';
      }
    });
    if (inList) html += '</ul>';
    return html || '<p>' + out + '</p>';
  }

  /* ---------- DOM helpers ------------------------------------------------- */
  function el(tag, cls, html) {
    var n = d.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function botLabel() {
    var l = el('div', 'bot-label');
    l.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 27" fill="none" aria-hidden="true">'
      + '<path d="M12 1 22 6.75V20.25L12 26 2 20.25V6.75L12 1Z" stroke="currentColor" stroke-width="1.5"/></svg>'
      + '<span>' + tt('chat.title', 'PRIME RUSH SUPPORT') + '</span>';
    return l;
  }
  // translated strings injected on root as data-t-* (server-provided); fallback given.
  function tt(key, fallback) {
    var attr = 'data-t-' + key.replace(/[.]/g, '-');
    return root.getAttribute(attr) || fallback;
  }
  function fmtTime(iso) {
    if (!iso) return '';
    try { var dt = new Date(iso);
      return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch (e) { return ''; }
  }

  /* ---------- scroll management ------------------------------------------- */
  function atBottom() {
    return transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 60;
  }
  function scrollToEnd(force) {
    if (force || state.pinned) {
      transcript.scrollTop = transcript.scrollHeight;
      hideNewReply();
    }
  }
  function showNewReply() { newReplyChip.classList.remove('hidden'); newReplyChip.removeAttribute('hidden'); }
  function hideNewReply() { newReplyChip.classList.add('hidden'); newReplyChip.setAttribute('hidden', ''); }

  transcript.addEventListener('scroll', function () {
    state.pinned = atBottom();
    if (state.pinned) hideNewReply();
  });
  newReplyChip.addEventListener('click', function () { state.pinned = true; scrollToEnd(true); });

  /* =========================================================================
     RENDERERS — one per message `type` (SPEC §7 kinds 1–11)
     Each returns a DOM node appended to the transcript.
     ======================================================================= */
  var renderers = {

    /* 1. typing — 3-dot pulse, min 400ms (handled by caller timing) */
    typing: function () {
      var g = el('div', 'msg-group msg-group--bot');
      g.setAttribute('data-typing', '');
      g.appendChild(botLabel());
      var b = el('div', 'bubble bubble--bot');
      b.style.padding = '0';
      b.appendChild(el('div', 'typing', '<span></span><span></span><span></span>'));
      g.appendChild(b);
      return g;
    },

    /* 2. text — markdown-lite; may carry article_ref inline (kind 6) */
    text: function (m) {
      var g = el('div', 'msg-group ' + (m.author === 'player' ? 'msg-group--player' : 'msg-group--bot'));
      if (m.author !== 'player') g.appendChild(botLabel());
      var b = el('div', 'bubble ' + (m.author === 'player' ? 'bubble--player' : 'bubble--bot'), mdLite(m.text || ''));
      if (m.article_ref) b.appendChild(articleRef(m.article_ref));
      g.appendChild(b);
      if (m.time) g.appendChild(el('div', 'bubble-time', fmtTime(m.time)));
      return g;
    },

    /* 3. chips — quick replies; disable after choose, echo as player bubble */
    chips: function (m) {
      var wrap = el('div', 'chips');
      wrap.setAttribute('role', 'group');
      (m.options || []).forEach(function (opt) {
        var chip = el('button', 'chip');
        chip.type = 'button';
        chip.textContent = opt.label;
        chip.setAttribute('aria-pressed', 'false');
        chip.addEventListener('click', function () {
          if (wrap.getAttribute('data-answered') === 'true') return;
          wrap.setAttribute('data-answered', 'true');
          chip.setAttribute('aria-pressed', 'true');
          echoPlayer(opt.label);
          sendMessage({ chip: opt.value, label: opt.label });
        });
        wrap.appendChild(chip);
      });
      return wrap;
    },

    /* 4. context_card — "what we can see" */
    context_card: function (m) {
      var card = el('div', 'card');
      card.appendChild(el('div', 'card__title', tt('chat.we-know', 'WHAT WE CAN SEE')));
      var dl = el('dl', 'card__list');
      (m.items || []).forEach(function (it) {
        var row = el('div', 'card__li');
        row.innerHTML = '<dt>' + esc(it.label) + '</dt><dd dir="ltr">' + esc(it.value) + '</dd>';
        dl.appendChild(row);
      });
      card.appendChild(dl);
      var editBtn = el('button', 'btn btn--sm btn--ghost card__edit', tt('chat.edit', 'EDIT'));
      editBtn.type = 'button';
      editBtn.addEventListener('click', openIdentity);
      card.appendChild(editBtn);
      return card;
    },

    /* 5. sid_prompt — inline identity trigger; dismiss → persistent nudge */
    sid_prompt: function (m) {
      var card = el('div', 'card');
      card.appendChild(el('div', '', '<p style="margin:0 0 12px">' + esc(m.text || tt('chat.add-sid-prompt', 'Add your SID to unlock account help.')) + '</p>'));
      var actions = el('div', '', '');
      actions.style.display = 'flex'; actions.style.gap = '8px'; actions.style.flexWrap = 'wrap';
      var link = el('button', 'btn btn--sm', tt('chat.link-account', 'LINK ACCOUNT'));
      link.type = 'button'; link.addEventListener('click', openIdentity);
      var dismiss = el('button', 'link-muted', tt('chat.dismiss', 'Dismiss'));
      dismiss.type = 'button';
      dismiss.addEventListener('click', function () {
        card.parentNode && card.parentNode.remove ? card.remove() : null;
        card.remove();
        if (sidNudge) { sidNudge.classList.remove('hidden'); sidNudge.removeAttribute('hidden'); }
      });
      actions.appendChild(link); actions.appendChild(dismiss);
      card.appendChild(actions);
      return card;
    },

    /* 7. escalation_card — ticket id + status + optional email capture */
    escalation_card: function (m) {
      if (ticketEyebrow && m.ticket_id) ticketEyebrow.textContent = m.ticket_id;
      var card = el('div', 'card');
      card.appendChild(el('div', 'card__title', tt('chat.escalated-title', 'A human will take it from here.')));
      card.appendChild(el('div', 'big-id', '<span dir="ltr">' + esc(m.ticket_id || '') + '</span>'));
      card.appendChild(pillNode('open'));
      card.appendChild(el('p', 'muted', esc(m.note || tt('chat.escalated-sub', "We'll reply here and at your ticket page."))));
      if (m.needs_email) {
        var f = el('form', ''); f.style.marginBlockStart = '12px';
        f.innerHTML = '<input class="field__input" type="email" name="email" placeholder="you@example.com" style="margin-block-end:8px">';
        var sub = el('button', 'btn btn--sm btn--block', tt('identity.continue', 'Continue'));
        sub.type = 'submit'; f.appendChild(sub);
        f.addEventListener('submit', function (e) { e.preventDefault();
          sendMessage({ email: f.querySelector('[name=email]').value }); f.remove(); });
        card.appendChild(f);
      }
      if (m.ticket_id) {
        var link = el('a', 'btn btn--sm btn--block', 'View ticket');
        link.href = '/ticket/' + encodeURIComponent(m.ticket_id);
        link.style.marginBlockStart = '10px';
        card.appendChild(link);
      }
      return card;
    },

    /* 8. csat — "Did this solve it?" 👍/👎 */
    csat: function (m) {
      var wrap = el('div', 'csat');
      wrap.appendChild(el('div', 'csat__q', esc(m.text || tt('chat.csat-q', 'Did this solve it?'))));
      var btns = el('div', 'csat__btns');
      [['up', 'thumb-up'], ['down', 'thumb-down']].forEach(function (pair) {
        var b = el('button', 'csat__btn');
        b.type = 'button';
        b.setAttribute('aria-label', pair[0] === 'up' ? 'Yes, solved' : 'No, not solved');
        b.innerHTML = svgIcon(pair[1]);
        b.addEventListener('click', function () {
          wrap.querySelectorAll('button').forEach(function (x) { x.disabled = true; x.style.opacity = '.4'; });
          b.style.opacity = '1'; b.style.borderColor = 'var(--white)';
          if (pair[0] === 'up') { systemNote(tt('chat.resolved', "Glad that's sorted.")); }
          sendMessage({ csat: pair[0] });
        });
        btns.appendChild(b);
      });
      wrap.appendChild(btns);
      return wrap;
    },

    /* 9. offer_card — coupon; monochrome, no gold, no confetti */
    offer_card: function (m) {
      var card = el('div', 'card');
      if (m.campaign) card.appendChild(el('div', 'card__title', esc(m.campaign)));
      if (m.text) card.appendChild(el('p', '', '<span style="font-size:14px">' + esc(m.text) + '</span>'));
      var codeRow = el('div', 'offer-code');
      codeRow.innerHTML = '<span class="offer-code__val" dir="ltr">' + esc(m.code || '') + '</span>';
      var copy = el('button', 'offer-code__copy', tt('chat.copy', 'COPY'));
      copy.type = 'button';
      copy.addEventListener('click', function () {
        try { navigator.clipboard.writeText(m.code || ''); } catch (e) {}
        copy.textContent = tt('chat.copied', 'Copied');
        window.PRToast && window.PRToast(tt('chat.copied', 'Copied'));
      });
      codeRow.appendChild(copy);
      card.appendChild(codeRow);
      if (m.expiry) card.appendChild(el('div', 'offer__expiry', tt('chat.expires', 'Expires {date}').replace('{date}', esc(m.expiry))));
      var redeem = el('a', 'btn btn--sm btn--block', tt('chat.redeem', 'REDEEM IN STORE'));
      redeem.href = m.redeem_url || 'https://store.primerush.gg';
      redeem.style.marginBlockStart = '12px';
      card.appendChild(redeem);
      return card;
    },

    /* 10. recognition — plain text bubble, NO special styling (human warmth) */
    recognition: function (m) {
      var g = el('div', 'msg-group msg-group--bot');
      g.appendChild(botLabel());
      g.appendChild(el('div', 'bubble bubble--bot', mdLite(m.text || '')));
      return g;
    },

    /* 11. unavailable — busy / kill-switch */
    unavailable: function (m) {
      var wrap = el('div', 'sysnote sysnote--stack');
      wrap.appendChild(el('span', '', esc(m.text || tt('chat.unavailable', 'Chat is busy — browse help articles or leave a ticket.'))));
      var actions = el('div', 'sysnote__actions');
      var a1 = el('a', 'btn btn--sm', 'Browse help'); a1.href = '/';
      var a2 = el('a', 'btn btn--sm btn--ghost', 'Leave a ticket'); a2.href = '/ticket/new';
      actions.appendChild(a1); actions.appendChild(a2);
      wrap.appendChild(actions);
      return wrap;
    },

    /* system note (escalation/resolution one-liners) */
    system: function (m) {
      return el('div', 'sysnote', '<span>' + esc(m.text || '') + '</span>');
    }
  };

  /* article_ref (kind 6) — mini row appended inside a text bubble */
  function articleRef(ref) {
    var a = el('a', 'artref');
    a.href = '/kb/article/' + encodeURIComponent(ref.slug);
    a.target = '_blank'; a.rel = 'noopener';
    a.innerHTML = '<span class="artref__title">' + esc(ref.title) + '</span>' + svgIcon('chevron', 15);
    return a;
  }
  function pillNode(status) {
    var p = el('span', 'pill pill--' + status);
    p.innerHTML = '<span class="pill__dot"></span><span dir="ltr">' + (tt('ticket.status.' + status, status.toUpperCase())) + '</span>';
    return p;
  }
  function svgIcon(name, size) {
    size = size || 20;
    var paths = {
      'thumb-up': '<path d="M7 10v10H4V10h3Zm0 0 4-7a2 2 0 0 1 2 2v3h5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 16.8 20H7"/>',
      'thumb-down': '<path d="M17 14V4h3v10h-3Zm0 0-4 7a2 2 0 0 1-2-2v-3H6a2 2 0 0 1-2-2.3l1.2-6A2 2 0 0 1 7.2 4H17"/>',
      'chevron': '<path d="m9 5 7 7-7 7"/>'
    };
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="1.5" stroke-linecap="square" aria-hidden="true">'
      + (paths[name] || '') + '</svg>';
  }

  /* append a rendered message; manage typing lifecycle + scroll */
  function appendMessage(m) {
    var fn = renderers[m.type] || renderers.text;
    var node = fn(m);
    node.setAttribute('data-mid', m.id || '');
    transcript.appendChild(node);
    if (m.id && m.id > state.lastId) state.lastId = m.id;
    if (state.pinned) scrollToEnd(); else showNewReply();
    return node;
  }

  function echoPlayer(text) { appendMessage({ type: 'text', author: 'player', text: text, time: new Date().toISOString() }); }
  function systemNote(text) { appendMessage({ type: 'system', text: text }); }
  function openIdentity() { var b = d.querySelector('[data-open-identity]'); if (b) b.click(); }

  /* =========================================================================
     TRANSPORT — the ONE place that touches the network. Swap for SSE here.
     ======================================================================= */
  var Transport = {
    send: function (payload) {
      return fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({ session: SESSION }, payload))
      }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    },
    poll: function (since) {
      return fetch(POLL_URL + '?session=' + encodeURIComponent(SESSION) + '&since=' + since, {
        headers: { 'X-Requested-With': 'fetch' }
      }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    }
  };

  /* show typing skeleton for >= 400ms, then render server replies */
  function withTyping(promise) {
    var typingNode = appendMessage({ type: 'typing' });
    var started = Date.now();
    function clear() {
      var wait = Math.max(0, (reduce ? 0 : 400) - (Date.now() - started));
      setTimeout(function () { typingNode.remove(); }, wait);
    }
    return promise.then(function (res) { clear(); return res; },
                        function (err) { clear(); throw err; });
  }

  /* send a player message (typed or chip) */
  function sendMessage(payload) {
    if (!ENABLED) { appendMessage({ type: 'unavailable' }); return; }
    setAwaiting(true);
    withTyping(Transport.send(payload))
      .then(function (res) {
        (res.messages || []).forEach(appendMessage);
      })
      .catch(function () {
        systemNote('Message failed to send. Tap to retry.');
      })
      .finally(function () { setAwaiting(false); });
  }

  function setAwaiting(on) {
    state.awaiting = on;
    if (on) {
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<svg class="spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9" stroke-linecap="round"/></svg>';
    } else {
      sendBtn.innerHTML = svgIcon('send-arrow');
      sendBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="square" aria-hidden="true"><path d="M4 12h14M12 6l6 6-6 6"/></svg>';
      syncSendState();
    }
  }

  /* =========================================================================
     COMPOSER
     ======================================================================= */
  function autogrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 132) + 'px';
  }
  function syncSendState() {
    var has = input.value.trim().length > 0 && !state.awaiting && ENABLED;
    sendBtn.disabled = !has;
    sendBtn.setAttribute('data-active', has ? 'true' : 'false');
    var len = input.value.length;
    if (len > 800) {
      counter.classList.remove('hidden');
      counter.textContent = len + '/1000';
    } else { counter.classList.add('hidden'); }
  }
  input.addEventListener('input', function () { autogrow(); syncSendState(); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); composer.requestSubmit(); }
  });
  composer.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || state.awaiting || !ENABLED) return;
    echoPlayer(text);
    input.value = ''; autogrow(); syncSendState();
    sendMessage({ text: text });
  });

  /* =========================================================================
     OFFLINE
     ======================================================================= */
  function updateOnline() {
    var off = !navigator.onLine;
    if (offlineBanner) {
      offlineBanner.classList.toggle('hidden', !off);
      off ? offlineBanner.removeAttribute('hidden') : offlineBanner.setAttribute('hidden', '');
    }
    input.disabled = off || !ENABLED;
    if (off) { sendBtn.disabled = true; } else { syncSendState(); }
  }
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);

  /* =========================================================================
     POLLING (session restore + live replies). Backoff on error.
     ======================================================================= */
  function poll() {
    if (!ENABLED) return;
    Transport.poll(state.lastId)
      .then(function (res) {
        (res.messages || []).forEach(appendMessage);
        state.pollDelay = 1500;
      })
      .catch(function () { state.pollDelay = Math.min(state.pollDelay * 1.6, 15000); })
      .finally(function () { state.pollTimer = setTimeout(poll, state.pollDelay); });
  }

  /* =========================================================================
     BOOT — hydrate SSR seed, then start polling. No localStorage of content.
     ======================================================================= */
  function boot() {
    var seedTag = transcript.querySelector('[data-seed]');
    var seed = [];
    if (seedTag) { try { seed = JSON.parse(seedTag.textContent); } catch (e) {} seedTag.remove(); }
    seed.forEach(appendMessage);
    scrollToEnd(true);
    updateOnline();
    syncSendState();
    autogrow();
    if (ENABLED) { state.pollTimer = setTimeout(poll, state.pollDelay); }
    else { appendMessage({ type: 'unavailable' }); }
  }
  boot();

  /* expose renderers for /dev/components gallery harness */
  window.PRChat = { append: appendMessage, renderers: renderers };
})();
