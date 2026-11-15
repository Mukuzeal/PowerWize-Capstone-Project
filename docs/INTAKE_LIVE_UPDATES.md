# Company intake live status

The Company Intake tab checks recorded status every five seconds while the
browser tab and intake section are visible. Returning to the section or browser
window triggers a check. Requests never overlap, time out after ten seconds,
and back off to at most thirty seconds after failures.

The list includes new intakes, archive changes and submitted counts. An open
workspace updates its next step, metrics, roster, delivery history and billing
summary. The Training tab also updates its class list and expanded member /
progress panels. An open invoice refreshes its payment operations while staff
are not editing an evidence or attention field.

Updates patch display regions rather than reloading the dashboard. Roster and
correction drafts, issued-link boxes, selected tabs and invoice forms remain
in place. If another action changes an application while its review is open,
the panel warns the reviewer to reopen it; it does not replace their draft.
Failures retain the last known facts and show a retrying message. Access-denied
responses stop polling and request sign-in.

## Payment labels

The server uses the invoice record, not a client return URL or an email-send
timestamp, as evidence of payment. A settled invoice takes priority over
`payment_link_sent_at`. Cancelled and expired invoices also replace that
historical label. A paid/pending invoice whose covered applications differ
from the current roster shows **Roster changed - review billing**.

The live GET endpoints do not contact PayMongo, send notifications, settle
payments, or recover payment attempts. Gateway reconciliation and verified
webhook handling remain separate responsibilities. In particular, a rejected
webhook cannot make an invoice paid simply because its page is being polled.

`/payment/webhook` returns 400 when `PAYMONGO_WEBHOOK_SECRET` is missing or
signature verification fails. Configure the signing secret for the actual
PayMongo webhook in the Flask process; preserve signature verification.

## Verification

Run sequentially; these scripts share the isolated `powerwize_test` database:

```powershell
venv/Scripts/python.exe -B scripts/test_intake_live_updates.py
venv/Scripts/python.exe -B scripts/test_phase_c_ui.py
venv/Scripts/python.exe -B scripts/test_class_browser.py
venv/Scripts/python.exe -B scripts/test_admin_browser.py
venv/Scripts/python.exe -B scripts/test_payment_recovery.py
```

The live-update check uses Chromium, CSRF-enabled Flask routes, mock mail and
mock gateway configuration. It verifies automatic payment/list changes,
draft/focus retention, class membership, failure recovery, filters, access
control, GET-only requests and absence of polling audit writes. It does not
establish genuine PayMongo sandbox delivery or production scheduler deployment.
