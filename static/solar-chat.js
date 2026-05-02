var messages  = [];
var collected = {};
var qIndex    = -1;
var isWaiting = false;

function now() {
  var d = new Date();
  var h = d.getHours(), m = d.getMinutes();
  return (h % 12 || 12) + ':' + (m < 10 ? '0' : '') + m + ' ' + (h < 12 ? 'AM' : 'PM');
}

function scrollBottom() {
  var box = document.getElementById('chat-box');
  box.scrollTop = box.scrollHeight;
}

function addBubble(text, role) {
  var box = document.getElementById('chat-box');
  var row = document.createElement('div');
  row.className = 'bubble-row ' + (role === 'user' ? 'user-row' : 'ai-row');
  var icon   = role === 'user' ? 'fa-user' : 'fa-solar-panel';
  var colCls = role === 'user' ? 'user-col' : 'ai-col';
  row.innerHTML =
    '<div class="avatar ' + role + '"><i class="fa-solid ' + icon + '"></i></div>' +
    '<div class="bubble-col ' + colCls + '">' +
      '<div class="bubble ' + role + '">' + text.replace(/\n/g, '<br>') + '</div>' +
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

async function sendMessage() {
  if (isWaiting) return;
  var input = document.getElementById('chat-input');
  var text  = input.value.trim();
  if (!text) return;

  addBubble(text, 'user');
  input.value = '';
  input.style.height = 'auto';
  messages.push({ role: 'user', content: text });

  isWaiting = true;
  document.getElementById('send-btn').disabled = true;
  showTyping();

  try {
    var res = await fetch('/solar/chat/msg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: messages.slice(0, -1), user_message: text, collected: collected, q_index: qIndex })
    });
    var data = await res.json();
    removeTyping();

    if (data.redirect) {
      addBubble('<i class="fa-solid fa-circle-notch fa-spin"></i> Computing your quotation — please wait…', 'ai');
      setTimeout(function() { window.location.href = data.redirect; }, 1400);
      return;
    }

    if (data.text) {
      addBubble(data.text, 'ai');
      if (data.messages)  messages  = data.messages;
      else messages.push({ role: 'assistant', content: data.text });
      if (data.collected) collected = data.collected;
      if (data.q_index !== undefined) qIndex = data.q_index;
    }
  } catch (e) {
    removeTyping();
    addBubble('Sorry, something went wrong. Please try again or switch to form mode.', 'ai');
  }

  isWaiting = false;
  document.getElementById('send-btn').disabled = false;
  input.focus();
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

document.getElementById('chat-input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 160) + 'px';
});

(async function() {
  document.getElementById('send-btn').disabled = true;
  showTyping();
  try {
    var res = await fetch('/solar/chat/msg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [], user_message: 'Hello', collected: {}, q_index: -1 })
    });
    var data = await res.json();
    removeTyping();
    if (data.text) {
      addBubble(data.text, 'ai');
      messages  = [{ role: 'user', content: 'Hello' }, { role: 'assistant', content: data.text }];
      if (data.collected) collected = data.collected;
      if (data.q_index !== undefined) qIndex = data.q_index;
    }
  } catch (e) {
    removeTyping();
    addBubble("Hey! I'm Solara, your solar energy assistant from EnergyWize. What's your name and what kind of property are we working with?", 'ai');
  }
  document.getElementById('send-btn').disabled = false;
  document.getElementById('chat-input').focus();
})();
