"""Company checkout presentation and browser checks; no gateway or mail calls.

App startup is isolated before import. Route fixtures replace only invoice
reads; payment validation is exercised separately by test_corporate_checkout.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated

use_test_db()
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ["PAYMONGO_SECRET_KEY"] = "sk_test_company_page"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timedelta
from pathlib import Path
import copy
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import app
import corporate_public_bp as public
import paymongo

results = []


def check(name, ok):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")


def no_external_call(*args, **kwargs):
    raise AssertionError("A UI check must not contact a gateway or mail server")


print(f"isolated database: {assert_isolated()}")
app.config["WTF_CSRF_ENABLED"] = True
invoice = {"id": 999, "reference": "CORP-UI-CHECK", "company_name": "Rivera Engineering",
           "form_type": "training", "amount_centavos": 1234567, "status": "pending",
           "expires_at": datetime.now() + timedelta(hours=1)}
attempt = {"status": "active", "environment": "test", "checkout_session_id": "cs_mock_example",
           "checkout_url": "https://mock.paymongo.test/checkout/cs_mock_example",
           "request_payload": {"payment_method_types": ["card", "gcash"]}}
state = {"invoice": invoice, "attempt": attempt, "reason": None}


def token_lookup(token):
    return (state["invoice"], state["reason"]) if token == "company-page-test" else (None, "invalid")


with patch.object(public, "payment_by_token", token_lookup), \
     patch.object(public, "get_corporate_items", return_value=[{"name": "PRIVATE-TRAINEE", "document": "secret-id.png"}] * 3), \
     patch.object(public, "open_attempt", side_effect=lambda _: state["attempt"]), \
     patch.object(public, 'get_attempts', return_value=[{'status':'paid','environment':'test'}]), \
     patch.object(public, "audit_log"), \
     patch("corporate_checkout.poll_attempt", return_value=(False, "Payment has not been confirmed.")) as poll, \
     patch("requests.sessions.Session.request", no_external_call), \
     patch("smtplib.SMTP", no_external_call):
    client = app.test_client()
    path = "/pay/corporate/company-page-test"
    response = client.get(path)
    body = response.get_data(as_text=True)
    check("company page renders", response.status_code == 200)
    check("invoice total comes from server", "12,345.67" in body)
    check("company and invoice reference shown", "Rivera Engineering" in body and "CORP-UI-CHECK" in body)
    check("trainee count shown without identities", "3 trainees" in body and "PRIVATE-TRAINEE" not in body)
    check("no uploaded document names", "secret-id.png" not in body)
    check("mock mode explained", "Demo checkout" in body and "No money will be charged" in body)
    check("mock host never rendered", "mock.paymongo.test" not in body)
    check("no payable link in mock mode", "data-company-checkout" not in body)
    check("no embedded card or discount fields", 'autocomplete="cc-' not in body and 'id="card-number"' not in body and 'id="discount-code"' not in body)
    check("no unsupported QRPH promise", "QRPH" not in body)
    check("private response headers retained with HTTPS form support", response.headers["Referrer-Policy"] == "same-origin" and response.headers["Cache-Control"] == "no-store" and "noindex" in response.headers["X-Robots-Tag"])
    check("unknown payment token refused", client.get("/pay/corporate/wrong").status_code == 404)

    paymongo.MOCK_GATEWAY = False  # Rendering only; all network is forbidden.
    check('old mock page offers a direct sandbox connection', 'Connect PayMongo test checkout' in client.get(path).get_data(as_text=True))
    check('sandbox connection requires CSRF', client.post(path+'/connect-sandbox').status_code == 400)
    check("persisted mock stays blocked after config switch", "data-company-checkout" not in client.get(path).get_data(as_text=True))
    poll.reset_mock()
    body = client.get(path + "/return").get_data(as_text=True)
    check("persisted mock status does not query a real gateway", "Demo checkout cannot confirm" in body and not poll.called)
    real_attempt = copy.deepcopy(attempt)
    real_attempt.update(checkout_session_id="cs_test_ui", checkout_url="https://checkout.paymongo.com/ui-test")
    state["attempt"] = real_attempt
    body = client.get(path).get_data(as_text=True)
    check("sandbox labelled separately from mock", "PayMongo test mode" in body and "Demo checkout" not in body)
    check("real checkout URL rendered", 'href="https://checkout.paymongo.com/ui-test"' in body)
    check("tabs explicitly describe final method selection", "Both tabs open the same secure invoice checkout" in body)

    real_attempt["status"] = "unknown"
    check("unresolved attempt offers no pay action", "data-company-checkout" not in client.get(path).get_data(as_text=True))
    real_attempt["status"] = "active"
    real_attempt["environment"] = "live"
    check("environment mismatch blocks payment", "data-company-checkout" not in client.get(path).get_data(as_text=True))
    real_attempt["environment"] = "test"
    real_attempt["checkout_url"] = "javascript:alert(1)"
    check("non-HTTPS checkout refused", "data-company-checkout" not in client.get(path).get_data(as_text=True))
    real_attempt["checkout_url"] = "https://checkout.paymongo.com/ui-test"
    real_attempt["request_payload"]["payment_method_types"] = ["card"]
    body = client.get(path).get_data(as_text=True)
    check("single-method invoice omits tabs and wallets", 'role="tablist"' not in body and "E-wallet" not in body)
    real_attempt["request_payload"]["payment_method_types"] = ["gcash", "qrph"]
    body = client.get(path).get_data(as_text=True)
    check("QRPH shown only when configured", "GCash / QRPH" in body)
    real_attempt["request_payload"]["payment_method_types"] = ["card", "gcash"]
    state["attempt"] = None
    check("missing attempt is not payable", "data-company-checkout" not in client.get(path).get_data(as_text=True))
    state["attempt"] = real_attempt
    body = client.get(path + "/return").get_data(as_text=True)
    check("return does not manufacture settlement", "Not confirmed yet" in body and "Payment received" not in body)
    check("pending page offers recheck and back navigation", "Check again" in body and "Back to invoice" in body)

    server = make_server("127.0.0.1", 0, app, threaded=True)
    origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            state['attempt'] = attempt
            page.goto(origin+path)
            connected_requests = []
            def connect_from_browser(route):
                connected_requests.append(route.request.headers.get('x-csrftoken'))
                state['attempt'] = real_attempt
                route.fulfill(status=200,content_type='application/json',body='{"ok":true,"url":"/pay/corporate/company-page-test"}')
            page.route('**/connect-sandbox', connect_from_browser)
            page.get_by_role('button',name='Connect PayMongo test checkout',exact=True).click()
            page.locator('[data-company-checkout]').first.wait_for(state='visible')
            check('browser connects the old mock without replacing its company URL', page.url == origin+path and connected_requests and bool(connected_requests[0]))
            page.goto(origin + path)
            page.wait_for_selector('[role="tablist"]:visible')
            check("browser selects card panel initially", page.locator("#company-panel-card").is_visible() and not page.locator("#company-panel-wallet").is_visible())
            page.get_by_role("tab", name="E-wallet", exact=True).click()
            check("e-wallet tab switches panel", page.locator("#company-panel-wallet").is_visible() and not page.locator("#company-panel-card").is_visible())
            check("selected tab accessibility state follows click", page.locator("#company-tab-wallet").get_attribute("aria-selected") == "true")
            page.keyboard.press("ArrowLeft")
            check("keyboard switches to card tab", page.locator("#company-tab-card").evaluate("el => el === document.activeElement") and page.locator("#company-panel-card").is_visible())
            page.keyboard.press("End")
            check("End key selects last method", page.locator("#company-panel-wallet").is_visible())
            check("both methods use the same reserved session", len(set(page.locator("[data-company-checkout]").evaluate_all("els => els.map(el => el.href)"))) == 1)
            check('sandbox card instructions are visible on the card tab', '4343 4343 4343 4345' in page.locator('#company-panel-card').inner_text())
            page.route('**/sandbox-action', lambda route: route.fulfill(status=200,content_type='application/json',body='{"url":"https://test-sources.paymongo.com/qrph/browser","message":"Choose a test outcome.","kind":"qrph"}'))
            page.locator('[data-get-test-action]').click()
            page.get_by_role('link', name='Simulate payment on PayMongo (test mode)').wait_for(state='visible')
            check('wallet simulation button displays PayMongo-provided action', page.get_by_role('link', name='Simulate payment on PayMongo (test mode)').get_attribute('href') == 'https://test-sources.paymongo.com/qrph/browser')
            checkout_requests = []

            def intercepted_checkout(route):
                checkout_requests.append(route.request.url)
                route.fulfill(status=200, content_type="text/html", body="<p>Intercepted sandbox checkout</p>")

            context.route("https://checkout.paymongo.com/**", intercepted_checkout)
            with page.expect_popup() as checkout_popup:
                page.locator("[data-company-checkout]:visible").click()
            checkout_page = checkout_popup.value
            checkout_page.wait_for_load_state()
            checkout_page.close()
            check("Pay navigates to hosted checkout without card submission", checkout_requests == ["https://checkout.paymongo.com/ui-test"])

            # Polling must wait for server-verified success; opening a test
            # page alone never reports a completed payment.
            check('opening sandbox checkout only shows waiting state', 'Waiting for PayMongo' in page.locator('[data-payment-poll-result]').inner_text())
            state['reason'] = 'paid'
            invoice.update(receipt_id='RCP-UI-RECEIPT',receipt_hash='ab'*32,tx_hash='0x'+'ab'*32,
                           method='qrph',paymongo_id='pay_ui_test',paid_at=datetime.now(),qr_code_path=None)
            page.route('**/status', lambda route: route.fulfill(status=200,content_type='application/json',body='{"paid":true,"url":"/pay/corporate/company-page-test"}'))
            page.wait_for_selector('.company-receipt', timeout=8000)
            check('verified success automatically opens company receipt', page.locator('.company-receipt').is_visible() and 'RCP-UI-RECEIPT' in page.locator('.company-receipt').inner_text())
            check('receipt has blockchain verification and print controls', page.get_by_role('button',name='Verify company receipt on blockchain').is_visible() and page.get_by_role('button',name='Print receipt').is_visible())
            page.set_viewport_size({'width':390,'height':844})
            check('receipt fingerprint does not overflow mobile viewport', page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            state['reason'] = None
            page.unroute('**/status')
            page.set_viewport_size({'width':1280,'height':1000})

            page.goto(origin + path)
            page.locator(".form-card").first.scroll_into_view_if_needed()
            page.wait_for_function("document.querySelector('.curtain').getBoundingClientRect().height < 1 && getComputedStyle(document.querySelector('.form-card')).opacity === '1'")
            page.evaluate("Promise.all(document.getAnimations().filter(a => a.effect && a.effect.target.closest('.company-payment')).map(a => a.finished.catch(() => {})))")
            desktop_shot = Path(tempfile.gettempdir()) / "powerwize-company-payment-desktop.png"
            page.screenshot(path=str(desktop_shot))
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(origin + path)
            page.wait_for_function("document.querySelector('.curtain').getBoundingClientRect().height < 1")
            check("mobile has no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            check("mobile Pay button fits the viewport", page.locator("[data-company-checkout]:visible").bounding_box()["width"] < 390)
            mobile_shot = Path(tempfile.gettempdir()) / "powerwize-company-payment-mobile.png"
            page.locator(".form-card").first.scroll_into_view_if_needed()
            page.wait_for_function("getComputedStyle(document.querySelector('.form-card')).opacity === '1'")
            page.evaluate("Promise.all(document.getAnimations().filter(a => a.effect && a.effect.target.closest('.company-payment')).map(a => a.finished.catch(() => {})))")
            page.screenshot(path=str(mobile_shot))
            paymongo.MOCK_GATEWAY = True
            page.reload()
            check("browser mock mode disables checkout", page.locator("[data-company-checkout]").count() == 0 and page.get_by_role("button", name="Unavailable in demo mode").first.is_disabled())
            page.get_by_role("link", name="Check payment status").click()
            page.get_by_role("heading", name="Not confirmed yet").wait_for(state="visible")
            check("status check shows pending without payment proof", page.get_by_role("heading", name="Not confirmed yet").is_visible())
            page.get_by_role("link", name="Back to invoice").click()
            page.locator(".company-payment").wait_for(state="visible")
            check("pending back link returns to invoice", page.locator(".company-payment").is_visible())
            check("browser has no uncaught JavaScript errors", not errors)
            no_js = browser.new_context(java_script_enabled=False)
            no_js.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
            paymongo.MOCK_GATEWAY = False
            simple_page = no_js.new_page()
            simple_page.goto(origin + path)
            check("checkout remains usable without JavaScript", simple_page.locator("[data-company-checkout]").count() == 2 and simple_page.locator("[data-company-checkout]").first.is_visible())
            browser.close()
            print(f"Screenshots: {desktop_shot}, {mobile_shot}")
    finally:
        server.shutdown()
        thread.join(timeout=5)

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
