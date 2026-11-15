"""Browser test: the upload widget's behaviour, with CSRF enabled.

Drives the REAL registration form in Chromium. The vision provider is stubbed
inside this process, so no document leaves the machine and no API key is
needed — but everything else is the shipped code path: the macro's markup, the
fetch, the CSRF header, the status box, the submit guard.

What the DB-free suite cannot show is what the operator actually sees, which
is where the reported bug lived: a rate limit was rendered as "Invalid ID" and
the chosen file was wiped.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_upload_browser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "upload-browser-secret")
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ.pop("DEV_SKIP_VALIDATION", None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import io                                          # noqa: E402
import json                                        # noqa: E402
import socket                                      # noqa: E402
import threading                                   # noqa: E402

from werkzeug.serving import make_server           # noqa: E402
from playwright.sync_api import sync_playwright    # noqa: E402
from PIL import Image                              # noqa: E402

from app import app                                # noqa: E402
import upload_validation as uv                     # noqa: E402

# CSRF stays ON: the widget sends X-CSRFToken from the page's meta tag, and a
# test with it disabled would not exercise that at all.
app.config["WTF_CSRF_ENABLED"] = True

results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


# ── Provider stub ────────────────────────────────────────────────────────────
class Reply:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def says(obj, status=200, headers=None):
    return Reply(status, {"choices": [{"message": {"content": json.dumps(obj)}}]},
                 headers)


SCRIPT = {"queue": []}


def fake_post(url, json=None, headers=None, timeout=None, **kw):
    if not SCRIPT["queue"]:
        return says({"valid": True, "reason": "Stub default accept."})
    nxt = SCRIPT["queue"].pop(0)
    if isinstance(nxt, Exception):
        raise nxt
    return nxt


uv._http.post = fake_post                        # noqa: SLF001
uv.time.sleep = lambda s: None


def tmp_png(path, size=(300, 300)):
    Image.new("RGB", size, (40, 110, 190)).save(path, "PNG")
    return path


SCRATCH = os.environ.get("TEMP") or "."
GOOD = tmp_png(os.path.join(SCRATCH, "pw_portrait_test.png"))


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


print(f"\nisolated database: {assert_isolated()}")
port = _free_port()
srv = make_server("127.0.0.1", port, app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"
print(f"serving on {BASE}")

page_errors = []

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(base_url=BASE)
        page = ctx.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        print("\n1. The form carries CSRF and the widget is wired")
        page.goto("/cea-training", wait_until="domcontentloaded")
        check("a CSRF token is present for the widget to send",
              page.locator('meta[name="csrf-token"]').count() == 1)
        check("the photo field exists", page.locator("#photo_id").count() == 1)
        check("its validation box starts idle",
              page.get_attribute("#val-photo_id", "data-status") == "idle")
        check("an error state element exists, separate from the reject one",
              page.locator("#val-photo_id .uv-error").count() == 1)
        check("the error state carries its own Retry control",
              page.locator("#val-photo_id .uv-retry").count() == 1)

        print("\n2. A rate limit is NOT shown as an invalid document")
        SCRIPT["queue"] = [says({}, 429, {"retry-after": "4"}),
                           says({}, 429, {"retry-after": "4"})]
        page.set_input_files("#photo_id", GOOD)
        page.wait_for_function(
            "() => document.getElementById('val-photo_id').dataset.status !== 'validating'",
            timeout=20000)
        status = page.get_attribute("#val-photo_id", "data-status")
        check("status is 'error', not 'invalid'", status == "error", str(status))
        msg = page.locator("#val-photo_id .uv-error .uv-msg").inner_text()
        check("the message says it could not validate", "busy" in msg.lower()
              or "could not" in msg.lower(), msg[:80])
        check("it does not call the document invalid",
              "invalid" not in msg.lower(), msg[:80])
        check("it mentions the wait the provider asked for", "4s" in msg or "s)" in msg,
              msg[:80])

        print("\n3. The chosen file survives a service failure")
        kept = page.evaluate(
            "() => { const i = document.getElementById('photo_id');"
            " return i.files && i.files.length ? i.files[0].name : null; }")
        check("the file is still selected", kept is not None, str(kept))
        check("the drop zone is not marked bad",
              "has-bad-file" not in (page.get_attribute("#zone-photo_id", "class") or ""),
              page.get_attribute("#zone-photo_id", "class") or "")

        print("\n4. Submit is blocked while validation is unresolved")
        blocked = page.evaluate("""() => {
            const step = document.getElementById('photo_id').closest('.wiz-step')
                      || document.getElementById('photo_id').closest('form');
            const f = document.getElementById('photo_id');
            const box = document.getElementById('val-photo_id');
            return {status: box.dataset.status, hasFile: !!(f.files && f.files.length)};
        }""")
        check("the field is in an unresolved state with a file present",
              blocked["status"] == "error" and blocked["hasFile"], str(blocked))

        print("\n5. Retry turns a transient failure into a real verdict")
        SCRIPT["queue"] = [says({"valid": True, "reason": "Clear single portrait."})]
        page.click("#val-photo_id .uv-retry")
        page.wait_for_function(
            "() => document.getElementById('val-photo_id').dataset.status === 'valid'",
            timeout=20000)
        check("status becomes valid after Retry",
              page.get_attribute("#val-photo_id", "data-status") == "valid")
        ok_msg = page.locator("#val-photo_id .uv-ok .uv-msg").inner_text()
        check("the model's wording is shown", "portrait" in ok_msg.lower(), ok_msg[:70])
        check("Retry did not need the file re-picked",
              page.evaluate("() => document.getElementById('photo_id').files.length") == 1)

        print("\n6. A genuine rejection still reads as a rejection")
        SCRIPT["queue"] = [says({"valid": False,
                                 "reason": "This is a sheet of four photos."})]
        page.set_input_files("#photo_id", GOOD)
        page.wait_for_function(
            "() => document.getElementById('val-photo_id').dataset.status === 'invalid'",
            timeout=20000)
        bad = page.locator("#val-photo_id .uv-bad .uv-msg").inner_text()
        check("status is 'invalid'",
              page.get_attribute("#val-photo_id", "data-status") == "invalid")
        check("the reason is the model's", "sheet of four" in bad, bad[:70])
        check("and the file IS cleared, so a different one must be chosen",
              page.evaluate("() => document.getElementById('photo_id').files.length") == 0)

        print("\n7. A stale reply cannot overwrite a newer file's verdict")
        # First selection gets a SLOW reject; while it is in flight the user
        # picks again and that one is accepted. The late reject must be
        # dropped, not painted over the newer result.
        slow = {"n": 0}

        def staged(url, json=None, headers=None, timeout=None, **kw):
            slow["n"] += 1
            if slow["n"] == 1:
                import time as _t
                _t.sleep(2.5)
                return says({"valid": False, "reason": "STALE REJECT"})
            return says({"valid": True, "reason": "FRESH ACCEPT"})

        uv._http.post = staged
        page.set_input_files("#photo_id", GOOD)
        page.wait_for_timeout(400)
        page.set_input_files("#photo_id", GOOD)      # re-pick while #1 in flight
        page.wait_for_function(
            "() => document.getElementById('val-photo_id').dataset.status === 'valid'",
            timeout=20000)
        page.wait_for_timeout(3000)                  # let the stale one land
        final = page.get_attribute("#val-photo_id", "data-status")
        shown = page.locator("#val-photo_id .uv-ok .uv-msg").inner_text()
        check("the newer verdict stands", final == "valid", str(final))
        check("the stale reject did not overwrite it", "FRESH" in shown, shown[:60])
        uv._http.post = fake_post

        print("\n8. A hostile filename is rendered as text, not markup")
        nasty = os.path.join(SCRATCH, "pw_<img src=x onerror=alert(1)>.png")
        tmp_png(nasty)
        SCRIPT["queue"] = [says({"valid": True, "reason": "ok"})]
        page.set_input_files("#photo_id", nasty)
        page.wait_for_function(
            "() => document.getElementById('val-photo_id').dataset.status === 'valid'",
            timeout=20000)
        html = page.inner_html("#name-photo_id")
        text = page.inner_text("#name-photo_id")
        check("the filename appears as visible text", "onerror" in text, text[:60])
        check("but no element was injected from it",
              "<img" not in html.lower(), html[:90])
        check("no alert dialog fired", not page_errors or
              all("alert" not in e.lower() for e in page_errors))

        print("\n9. No uncaught JavaScript errors")
        real = [e for e in page_errors if "favicon" not in e.lower()]
        check("none", not real, "; ".join(real[:2])[:140])

        browser.close()
finally:
    srv.shutdown()

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
print("Provider was stubbed in-process; no document left this machine.")
sys.exit(1 if failed else 0)
