(function () {
  'use strict';
  var tablist = document.querySelector('[data-company-payment-tabs]');
  if (tablist) {
  var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));
  function selectTab(selected) {
    tabs.forEach(function (tab) {
      var active = tab === selected;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
      var panel = document.getElementById(tab.getAttribute('aria-controls'));
      panel.setAttribute('role', 'tabpanel');
      panel.hidden = !active;
    });
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () { selectTab(tab); });
    tab.addEventListener('keydown', function (event) {
      var next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(tabs[next]);
      tabs[next].focus();
    });
  });
  selectTab(tabs[0]);
  tablist.hidden = false;
  }

  var page = document.querySelector('.company-payment');
  if (!page) return;
  var connectButton = page.querySelector('[data-connect-test-checkout]');
  if (connectButton) {
    connectButton.addEventListener('click', async function () {
      var output = page.querySelector('[data-connect-test-result]');
      connectButton.disabled = true;
      output.textContent = 'Connecting PayMongo test checkout...';
      try {
        var csrf = document.querySelector('meta[name="csrf-token"]');
        var response = await fetch(page.dataset.connectTestApi, {
          method: 'POST', credentials: 'same-origin',
          headers: {'X-CSRFToken': csrf ? csrf.content : ''}
        });
        var result = await response.json();
        if (response.ok && result.ok) {
          window.location.assign(result.url);
          return;
        }
        output.textContent = result.error || 'Could not confirm the connection. Reload before retrying.';
      } catch (error) {
        output.textContent = 'Could not confirm the connection. Reload this page before trying again.';
      } finally {
        connectButton.disabled = false;
      }
    });
  }
  var pollTimer = null;
  var pollCount = 0;
  var checking = false;
  var pollResult = page.querySelector('[data-payment-poll-result]');
  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }
  async function checkStatus() {
    if (checking || document.hidden) return;
    if (++pollCount > 75) {
      stopPolling();
      pollResult.textContent = 'Automatic checks paused. Use Check payment status to check again.';
      return;
    }
    checking = true;
    try {
      var response = await fetch(page.dataset.statusApi, {credentials: 'same-origin', cache: 'no-store'});
      var result = await response.json();
      if (response.status === 404) stopPolling();
      if (response.ok && result.paid === true) {
        stopPolling();
        window.location.assign(result.url);
        return;
      }
      pollResult.textContent = result.error || 'Waiting for PayMongo to confirm the test payment...';
    } catch (error) {
      pollResult.textContent = 'Could not check confirmation just now. Use Check payment status to try again.';
    } finally {
      checking = false;
    }
  }
  function startPolling() {
    if (!pollTimer) {
      pollCount = 0;
      pollTimer = setInterval(checkStatus, 4000);
      pollResult.textContent = 'Waiting for PayMongo to confirm the test payment...';
    }
  }
  page.querySelectorAll('[data-test-checkout]').forEach(function (link) {
    link.addEventListener('click', startPolling);
  });
  page.querySelectorAll('[data-get-test-action]').forEach(function (button) {
    button.addEventListener('click', async function () {
      var output = button.parentElement.querySelector('[data-test-action-result]');
      button.disabled = true;
      output.textContent = 'Checking PayMongo for a simulation link...';
      try {
        var response = await fetch(page.dataset.testActionApi, {credentials: 'same-origin', cache: 'no-store'});
        var result = await response.json();
        output.textContent = result.message || result.error || 'Could not retrieve the simulation link.';
        if (response.ok && result.url) {
          var link = document.createElement('a');
          link.href = result.url;
          link.target = '_blank';
          link.rel = 'noreferrer noopener';
          link.className = 'chain-link';
          link.textContent = 'Simulate payment on PayMongo (test mode)';
          link.addEventListener('click', startPolling);
          output.appendChild(document.createElement('br'));
          output.appendChild(link);
        }
      } catch (error) {
        output.textContent = 'Could not retrieve the simulation link. Try again shortly.';
      } finally {
        button.disabled = false;
      }
    });
  });
  document.addEventListener('visibilitychange', function () {
    if (pollTimer && !document.hidden) checkStatus();
  });
  window.addEventListener('pagehide', stopPolling);
}());
