var messages  = [];
var collected = {};
var qIndex    = -1;
var isWaiting = false;

// Set while a /solar/chat/msg call is in flight so Stop (and the pagehide
// handler below) know what to cancel.
var currentRequestId  = null;
var currentController = null;

// True only between the user clicking Stop and that fetch settling — tells
// the catch block in sendMessage() whether an AbortError was requested (show
// nothing, same as always) or came from the watchdog timer instead (show an
// error). Reset per-request in sendMessage(), not left true across turns.
var _stopClicked = false;

// A proxy in front of Flask (ngrok in testing; possibly Render's own in
// production) can drop a response that sat completely silent for too long —
// /solar/chat/msg never streams anything, so a slow turn (extract + topic
// gate + full generation, easily 30-90s against a local model) can leave the
// connection idle the whole time with zero bytes crossing it. When that
// happens the dropped response leaves fetch() neither resolved nor rejected
// — no exception, nothing in the console, nothing to catch — which looked
// exactly like "the chatbot stopped replying" with no error anywhere (2026-
// 09-23 bug report, reproduced only through an ngrok tunnel, not localhost).
// This watchdog is what turns that silent hang into a visible error. Read
// from the page rather than hardcoded so it can't drift from the server's
// own LM_STUDIO_TIMEOUT ceiling (see solar_chat() in solar_bp.py) — the
// +30s gives the response a little room to actually arrive after the
// server-side call itself would have given up.
var _timeoutMeta = document.querySelector('meta[name="chat-timeout-ms"]');
var REPLY_TIMEOUT_MS = (_timeoutMeta && parseInt(_timeoutMeta.content, 10) || 300000) + 30000;

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

// crypto.randomUUID() needs a secure context (HTTPS or localhost) — this
// avoids depending on that for something that's just a correlation id, not
// a security token.
function newRequestId() {
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
}

// Tells the server to stop an in-flight LM Studio call (see
// /solar/chat/cancel in solar_bp.py). Fire-and-forget by design — the
// caller doesn't need to wait for this to resolve, and sendBeacon can't be
// awaited anyway. useBeacon=true is for page-teardown calls (refresh/close),
// where a regular fetch() is frequently killed mid-flight by the browser
// before it's sent.
function cancelServerRequest(requestId, useBeacon) {
  if (!requestId) return;
  var body = JSON.stringify({ request_id: requestId, csrf_token: csrfToken() });
  if (useBeacon && navigator.sendBeacon) {
    navigator.sendBeacon('/solar/chat/cancel', new Blob([body], { type: 'application/json' }));
  } else {
    fetch('/solar/chat/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      keepalive: true
    }).catch(function () {});
  }
}

// Fires on refresh, tab close, or navigating away while a reply is still
// generating — this is what actually stops the server from being left
// blocked inside a non-streamed LM Studio call with no way to notice the
// client is gone (see the 2026-09-23 bug report). 'pagehide' fires only on
// real navigation/teardown (refresh, close, back/forward, URL change) and
// is reliable on every current browser engine, including mobile Safari —
// that reliability used to be a real gap (hence an earlier version of this
// also listened for 'visibilitychange'), but it's been fixed upstream for
// long enough now that carrying the workaround costs more than it's worth.
//
// 'visibilitychange' was tried and removed (2026-09-23): it does NOT mean
// "the user is leaving" — it fires just as easily from alt-tabbing to check
// something else (the terminal, an ngrok inspector tab, devtools) while a
// reply is still generating. Wiring a cancel to it killed real in-flight
// replies with zero client-side error (the server-side cancel makes
// solar_chat_msg return {"cancelled": true}, 200 — a normal, successful
// response the frontend deliberately renders as nothing, by design, for
// the real Stop-button case). That's the exact "stopped replying, no error
// bubble" symptom this was traced to. Don't re-add it without a debounce
// that tolerates a multi-second glance away.
function handlePageLeaving() {
  if (isWaiting && currentRequestId) {
    cancelServerRequest(currentRequestId, true);
  }
}
window.addEventListener('pagehide', handlePageLeaving);

function now() {
  var d = new Date();
  var h = d.getHours(), m = d.getMinutes();
  return (h % 12 || 12) + ':' + (m < 10 ? '0' : '') + m + ' ' + (h < 12 ? 'AM' : 'PM');
}

function scrollBottom() {
  var box = document.getElementById('chat-box');
  box.scrollTop = box.scrollHeight;
}

// Bubble text can be the user's own typed message or the LLM's reply — never
// trust either as safe HTML. Escape first, then apply bold/italic on the
// escaped string so markdown syntax can't reintroduce a tag (e.g. a reply
// containing literal "<img src=x onerror=...>" renders as inert text, not
// markup, even inside a "**...**" span).
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderBubbleText(text) {
  var escaped = escapeHtml(text);
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  return escaped.replace(/\n/g, '<br>');
}

function addBubble(text, role, sources) {
  var box = document.getElementById('chat-box');
  var row = document.createElement('div');
  row.className = 'bubble-row ' + (role === 'user' ? 'user-row' : 'ai-row');
  var icon   = role === 'user' ? 'fa-user' : 'fa-solar-panel';
  var colCls = role === 'user' ? 'user-col' : 'ai-col';
  var sourcesHtml = '';
  if (sources && sources.length) {
    sourcesHtml = '<div class="bubble-sources">Sources: ' + escapeHtml(sources.join(', ')) + '</div>';
  }
  row.innerHTML =
    '<div class="avatar ' + role + '"><i class="fa-solid ' + icon + '"></i></div>' +
    '<div class="bubble-col ' + colCls + '">' +
      '<div class="bubble ' + role + '">' + renderBubbleText(text) + '</div>' +
      sourcesHtml +
      '<span class="bubble-time">' + now() + '</span>' +
    '</div>';
  box.appendChild(row);
  scrollBottom();
}

function showTyping() {
  var box = document.getElementById('chat-box');
  var row = document.createElement('div');
  row.className = 'bubble-row ai-row';
  row.id = 'typing-indicator';
  row.innerHTML =
    '<div class="avatar ai"><i class="fa-solid fa-solar-panel"></i></div>' +
    '<div class="typing-bubble">' +
      '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>' +
    '</div>';
  box.appendChild(row);
  scrollBottom();
}

function removeTyping() {
  var el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

/* ── Solara's face ──────────────────────────────────────────────────────────
   Ten drawn states, one per beat of a turn. Every asset is a self-contained
   animation, so a state change is only ever a swapped src — no player, no
   library. The stage carries the asset path in a data attribute so the URL
   stays Flask's to generate. */
var FACE = {
  neutral:   ['neutral.svg',   'Listening'],
  curious:   ['curious.svg',   'Go ahead'],
  typing:    ['typing.svg',    'You’re typing'],
  sent:      ['sent.svg',      'Got it'],
  thinking:  ['thinking.svg',  'Thinking'],
  answering: ['answering.gif', 'Composing'],
  done:      ['done.svg',      'Answered'],
  offtopic:  ['offtopic.svg',  'Off topic'],
  error:     ['error.svg',     'Trouble']
};

var _stage    = document.getElementById('solara-stage');
var _say      = document.getElementById('solara-say');
var _faces    = document.querySelectorAll('[data-solara-face]');
var _faceBase = _stage ? _stage.dataset.src : '/static/solara/';
var _face     = 'neutral';
var _faceStep = null;

/* Review harness. Neither half of this is reachable by using the page as
   intended: the greeting now returns in milliseconds, so the waking loop never
   gets to loop, and a turn against a local model runs long enough that seeing
   all nine faces means sitting through most of an hour.
     ?boot=8000   hold the waking loop at least 8s before the reveal, so the
                  handoff plays at a speed you can actually judge
     ?faces       cycle every state with its caption, 2s each, on repeat
     ?faces=error park on one state and stay there
   Inert unless named in the URL. */
var _q         = new URLSearchParams(location.search);
var BOOT_FLOOR = parseInt(_q.get('boot'), 10) || 0;
var FACE_DEMO  = _q.has('faces') ? (_q.get('faces') || 'cycle') : null;

// Warmed once at load, so every later change is a repaint rather than a fetch
// the user watches happen.
Object.keys(FACE).forEach(function (k) { new Image().src = _faceBase + FACE[k][0]; });

function paintFace(state) {
  if (!FACE[state] || state === _face) return;
  _face = state;
  Array.prototype.forEach.call(_faces, function (el) {
    var img = el.tagName === 'IMG' ? el : el.querySelector('img');
    if (!img) return;
    img.src = _faceBase + FACE[state][0];
    // A src swap does not restart a running CSS animation, so the settle has
    // to be retriggered by hand or it only ever plays on the first paint.
    img.style.animation = 'none';
    void img.offsetWidth;
    img.style.animation = '';
  });
  if (_stage) _stage.dataset.state = state;
  if (_say)   _say.textContent = FACE[state][1];
}

/* A turn is a short film rather than a single frame: pressed-enter, wind-up,
   then the composing dots for however long the model actually takes. Steps are
   [state, ms]; a duration of 0 holds until something else interrupts. */
function playFaces(steps) {
  clearTimeout(_faceStep);
  var i = 0;
  (function next() {
    if (i >= steps.length) return;
    var s = steps[i++];
    paintFace(s[0]);
    if (s[1]) _faceStep = setTimeout(next, s[1]);
  })();
}

function setFace(state) { playFaces([[state, 0]]); }

/* Whether she is between turns. Focus and blur are ambient signals, so they
   may only speak when nothing louder is mid-sentence — sending with the mouse
   blurs the box and refocuses it on reply, which would otherwise cut the
   answered beat off at the knees. */
function faceIdle() { return _face === 'neutral' || _face === 'curious'; }

/* ── Boot ───────────────────────────────────────────────────────────────────
   Waking loops for however long the greeting actually takes; the reveal then
   plays once and lands on her face. Splitting it this way is what lets the
   curtain be honest — a fixed-length intro either cuts the payoff off on a
   slow server or stalls the user on a fast one.

   REVEAL_MS is where the face finishes forming, a little short of the clip's
   3.1s so the curtain does not sit on a held pose. */
var REVEAL_MS = 2600;
var _boot    = document.getElementById('solara-boot');
var _bootImg = document.getElementById('solara-boot-img');
var _bootSay = document.getElementById('solara-boot-say');

function dismissBoot() {
  if (!_boot || _boot.classList.contains('is-gone')) return;
  _boot.classList.add('is-gone');
  document.removeEventListener('keydown', _bootKey);
  setTimeout(function () {
    _boot.remove();
    var input = document.getElementById('chat-input');
    if (input && !input.disabled) input.focus();
  }, 500);
}

function _bootKey(e) { if (e.key === 'Escape') dismissBoot(); }

/* Solara has answered, so the dots stop waiting and become her. */
function endBoot() {
  if (!_boot || _boot.classList.contains('is-gone')) return;
  if (_bootImg) _bootImg.src = _faceBase + 'reveal.gif';
  if (_bootSay) _bootSay.textContent = 'Solara is awake';
  setTimeout(dismissBoot, REVEAL_MS);
}

if (_boot) {
  _boot.addEventListener('click', dismissBoot);
  document.addEventListener('keydown', _bootKey);
  // The reveal has to be in cache before it is swapped in, or the swap stalls
  // on a 86KB fetch and the dots freeze at the one moment they should not.
  new Image().src = _faceBase + 'reveal.gif';
}

/* Whether the last turn moved the quotation on at all. The backend does not
   flag off-topic messages, and asking it to would cost another model call for
   a face — so this reads the result instead: nothing new banked and the same
   field still outstanding means the turn went sideways. A soft cue only; it is
   wrong occasionally, and nothing but the mascot depends on it. */
function bankedCount(c) {
  return Object.keys(c || {}).filter(function (k) {
    return c[k] !== null && c[k] !== undefined && c[k] !== '';
  }).length;
}

/* The quotation rail. Solara returns everything she has banked on each turn;
   this puts it on screen so the user can see the estimate assembling instead
   of having to trust that it is. */
function titleCase(s) {
  return String(s).charAt(0).toUpperCase() + String(s).slice(1);
}

function peso(n) {
  return '₱' + Number(n).toLocaleString('en-PH', { maximumFractionDigits: 0 });
}

function clip(s, max) {
  s = String(s).trim();
  return s.length > max ? s.slice(0, max - 1).trimEnd() + '…' : s;
}

// fallow-ignore-next-line complexity -- flat lookup; one case per rail row, not interacting branches
function railValue(field, c) {
  var v = c[field];
  switch (field) {
    case 'name':    return v ? clip(v, 28) : null;
    case 'address': return v ? clip(v, 46) : null;
    case 'notes':   return v ? clip(v, 46) : null;
    case 'establishment_type': return v ? titleCase(v) : null;
    case 'ownership':          return v ? titleCase(v) : null;
    case 'electrical_phase':   return v ? (v === 'three' ? 'Three phase' : 'Single phase') : null;
    // One row serves both: the backend stores whichever the user gave and
    // nulls the other, so showing two rows would always leave one dead.
    case 'monthly_bill_php':
      if (c.monthly_bill_php != null) return peso(c.monthly_bill_php) + ' / mo';
      if (c.kwh_monthly      != null) return c.kwh_monthly + ' kWh / mo';
      return null;
    case 'time_of_use_night_pct': return v != null ? v + '% at night' : null;
    case 'target_savings':        return v != null ? v + '% of bill'  : null;
    case 'roof_sqm':              return v != null ? v + ' m²'   : null;
    default: return v != null && v !== '' ? clip(v, 40) : null;
  }
}

function renderRail(c) {
  var rail = document.getElementById('quote-rail');
  if (!rail || !c) return;

  var items = rail.querySelectorAll('.qr-item');
  var done  = 0;

  Array.prototype.forEach.call(items, function (li) {
    var val = railValue(li.dataset.f, c);
    li.querySelector('.qr-v').textContent = val || '—';
    li.classList.toggle('is-set', !!val);
    if (val) done++;
  });

  document.getElementById('qr-done').textContent = done;
  document.getElementById('qr-fill').style.transform = 'scaleX(' + (done / items.length) + ')';
}

/* Openers. They exist only for the empty state — once the user has taken a
   turn the conversation itself is the prompt, and leaving them up would just
   be furniture. */
function showStarters() {
  var box = document.getElementById('chat-starters');
  if (box) box.hidden = false;
}

function hideStarters() {
  var box = document.getElementById('chat-starters');
  if (!box || box.hidden) return;
  var done = function () { box.hidden = true; box.classList.remove('is-leaving'); };
  box.classList.add('is-leaving');
  box.addEventListener('animationend', done, { once: true });
  setTimeout(done, 400);   // in case the animation is suppressed
}

// Swaps the send button between its normal "send" behavior and a "stop"
// control while a reply is generating — same pattern as ChatGPT/Claude.
function setSendButtonMode(mode) {
  var btn  = document.getElementById('send-btn');
  var icon = btn.querySelector('i');
  if (mode === 'stop') {
    icon.className = 'fa-solid fa-stop';
    btn.title = 'Stop';
    btn.disabled = false;
    btn.onclick = stopGeneration;
  } else {
    icon.className = 'fa-solid fa-paper-plane';
    btn.title = 'Send';
    btn.onclick = sendMessage;
  }
}

// Stops the in-flight reply: aborts the client-side wait immediately, and
// separately tells the server to stop (an aborted fetch is a client/network
// event a synchronous WSGI worker never observes mid-request — see
// /solar/chat/cancel in solar_bp.py).
function stopGeneration() {
  if (!isWaiting) return;
  _stopClicked = true;
  if (currentController) currentController.abort();
  cancelServerRequest(currentRequestId, false);
}

// Optimistic UI first, then per-turn request state: the user's own words land
// in the thread before the network is touched.
function beginTurn(text, input) {
  hideStarters();
  addBubble(text, 'user');
  input.value = '';
  input.style.height = 'auto';
  messages.push({ role: 'user', content: text });

  isWaiting = true;
  currentRequestId  = newRequestId();
  currentController = new AbortController();
  _stopClicked = false;
  setSendButtonMode('stop');
  showTyping();
  playFaces([['sent', 600], ['thinking', 700], ['answering', 0]]);
}

async function postTurn(text) {
  var res = await fetch('/solar/chat/msg', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify({
      messages: messages.slice(0, -1), user_message: text, collected: collected,
      q_index: qIndex, request_id: currentRequestId
    }),
    signal: currentController.signal
  });
  return res.json();
}

function applyReply(data, bankedBefore, qBefore) {
  addBubble(data.text, 'ai', data.sources);
  if (data.messages)  messages  = data.messages;
  else messages.push({ role: 'assistant', content: data.text });
  if (data.collected) { collected = data.collected; renderRail(collected); }
  if (data.q_index !== undefined) qIndex = data.q_index;

  // Nothing newly banked and no question advanced means the turn went
  // nowhere, so the face reacts to that instead of looking pleased.
  var stalled = bankedCount(collected) === bankedBefore && qIndex === qBefore;
  playFaces(stalled ? [['offtopic', 2200], ['neutral', 0]]
                    : [['done', 1500], ['neutral', 0]]);
}

// Terminal state: the estimate exists, so the composer stays disabled rather
// than being re-enabled the way an ordinary turn would.
function endConversation(redirect) {
  addBubble(
    'Your solar estimate is ready!<br>' +
    '<a href="' + redirect + '" class="chat-cta">' +
    '<i class="fa-solid fa-solar-panel"></i> View My Estimate</a>',
    'ai'
  );
  setFace('done');   // the conversation is over, so she stays pleased
  isWaiting = false;
  currentRequestId = null; currentController = null;
  document.getElementById('send-btn').disabled = true;
  document.getElementById('chat-input').disabled = true;
}

function reportTurnError(e) {
  if (e.name !== 'AbortError') {
    // A real network failure (connection refused, DNS, TLS, etc.) — always
    // visible, same as before.
    addBubble('Sorry, something went wrong. Please try again or switch to form mode.', 'ai');
    playFaces([['error', 3200], ['neutral', 0]]);
  } else if (!_stopClicked) {
    // Aborted, but not by the user — the watchdog gave up because nothing
    // came back in time. Silence here is exactly the bug this was added
    // to fix, so this is the one AbortError case that still gets shown.
    addBubble('That took longer than expected and the connection was lost — please try again.', 'ai');
    playFaces([['error', 3200], ['neutral', 0]]);
  }
  // else: the user clicked Stop — nothing to show, as always.
}

function endTurn(input) {
  isWaiting = false;
  currentRequestId = null; currentController = null;
  setSendButtonMode('send');
  document.getElementById('send-btn').disabled = false;
  input.focus();
}

async function sendMessage() {
  if (isWaiting) return;
  var input = document.getElementById('chat-input');
  var text  = input.value.trim();
  if (!text) return;

  beginTurn(text, input);

  var bankedBefore = bankedCount(collected);
  var qBefore      = qIndex;

  // Captures this call's own controller rather than reading the (mutable)
  // currentController global at fire time — otherwise a watchdog left
  // running past its own request's cleanup could abort a *later*, unrelated
  // request that happened to start before this timer fired.
  var thisController = currentController;
  var watchdog = setTimeout(function () { thisController.abort(); }, REPLY_TIMEOUT_MS);

  try {
    var data = await postTurn(text);
    removeTyping();

    if (data.cancelled) {
      // Stopped by the user (or the tab was closed and this response just
      // never found anyone listening) — nothing to show.
    } else if (data.redirect) {
      endConversation(data.redirect);
      return;
    } else if (data.text) {
      applyReply(data, bankedBefore, qBefore);
    }
  } catch (e) {
    removeTyping();
    reportTurnError(e);
  } finally {
    clearTimeout(watchdog);
  }

  endTurn(input);
}

function confirmSwitchToForm(e) {
  e.preventDefault();
  if (messages.length <= 2) { window.location.href = '/solar'; return; }
  Swal.fire({
    title: 'Switch to Form Mode?',
    text: 'Your current chat progress will be lost.',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: 'Yes, switch',
    cancelButtonText: 'Stay in chat',
    confirmButtonColor: '#16583C',
    cancelButtonColor: '#6B7280',
  }).then(function(result) {
    if (result.isConfirmed) window.location.href = '/solar';
  });
}

var _starters = document.getElementById('chat-starters');
if (_starters) {
  _starters.addEventListener('click', function (e) {
    var chip = e.target.closest('.starter');
    if (!chip || isWaiting) return;
    var input = document.getElementById('chat-input');
    input.value = chip.textContent.trim();
    sendMessage();
  });
}

var _input = document.getElementById('chat-input');

_input.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  // Solara's own turn outranks the user's — she does not stop mid-answer to
  // notice that someone is typing ahead of her.
  if (isWaiting) return;
  playFaces(this.value.trim() ? [['typing', 2200], ['curious', 0]]
                              : [['curious', 0]]);
});

_input.addEventListener('focus', function() {
  if (!isWaiting && faceIdle() && !this.value.trim()) setFace('curious');
});

_input.addEventListener('blur', function() {
  if (!isWaiting && faceIdle() && !this.value.trim()) setFace('neutral');
});

_input.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

(async function() {
  document.getElementById('send-btn').disabled = true;
  showTyping();
  try {
    var res = await fetch('/solar/chat/msg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ messages: [], user_message: 'Hello', collected: {}, q_index: -1 })
    });
    var data = await res.json();
    removeTyping();
    if (data.text) {
      addBubble(data.text, 'ai', data.sources);
      messages  = [{ role: 'user', content: 'Hello' }, { role: 'assistant', content: data.text }];
      if (data.collected) { collected = data.collected; renderRail(collected); }
      if (data.q_index !== undefined) qIndex = data.q_index;
    }
    showStarters();
  } catch (e) {
    removeTyping();
    addBubble("Hey! I'm Solara, your solar energy assistant from EnergyWize. What's your name and what kind of property are we working with?", 'ai');
    showStarters();
  } finally {
    // The curtain comes down on every path. Anything else and a failed greeting
    // leaves the page behind a permanent loading screen.
    endBoot();
  }
  // The boot loop ends on the face forming, so neutral is where it hands off.
  setFace('neutral');
  document.getElementById('send-btn').disabled = false;
  document.getElementById('chat-input').focus();
})();
