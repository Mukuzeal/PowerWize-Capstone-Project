"""Reconcile corporate hosted-checkout payments.

Built for an EXTERNAL scheduler (Render Cron, host cron, Task Scheduler).
This application has no worker process — `Procfile` is a single gunicorn line
— so nothing inside the app can be relied on to fire on time.

What one `--apply` run does, in order:

  1. resolve attempts whose create outcome was never observed, by replaying
     the EXACT stored payload with the stored idempotency key — and only
     while that key is still inside PayMongo's 24-hour retention window
  2. finish settlements whose invoice flip and attempt bookkeeping diverged
  3. poll open sessions and settle any that genuinely read paid, through the
     same validation gate the webhook uses
  4. close gateway sessions for invoices that are no longer payable —
     cancelled and expired alike, not just lapsed pending ones
  5. recover stale notification leases
  6. report everything still unresolved

Deliberately does NOT import the Flask app for reporting: importing it runs
init_db(), which would create or alter schema on whatever DATABASE_URL
happens to be set. The destination guard therefore runs BEFORE any import
that could mutate a database.

    python scripts/reconcile_corporate_payments.py            # report only
    python scripts/reconcile_corporate_payments.py --apply
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))


def _report():
    """Read-only. Touches no schema and imports no application code.

    Uses a plain connection rather than `db`, because importing the db
    package pulls in modules that other code expects to have been
    initialised; a reporting run should be able to look at a database it is
    not allowed to change.
    """
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    conn = psycopg2.connect(url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def q(sql, args=()):
        try:
            cur.execute(sql, args)
            return cur.fetchall()
        except Exception as e:
            conn.rollback()
            print(f"  (unavailable: {type(e).__name__})")
            return []

    open_attempts = q("""
        SELECT a.status, a.request_reference, a.checkout_session_id,
               a.idempotency_expires_at, p.status AS invoice_status
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status IN ('creating','active','unknown')
         ORDER BY a.created_at""")
    print(f"open attempts        : {len(open_attempts)}")
    now = datetime.now()
    for a in open_attempts:
        replayable = (a["checkout_session_id"] is None
                      and a["idempotency_expires_at"]
                      and a["idempotency_expires_at"] > now)
        note = ("replayable" if replayable
                else "has session" if a["checkout_session_id"]
                else "KEY EXPIRED — needs investigation")
        print(f"  [{a['status']:8}] {a['request_reference']} "
              f"invoice={a['invoice_status']} ({note})")

    unconfirmed = q("""
        SELECT a.request_reference, p.status AS invoice_status
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status = 'paid' AND a.settlement_confirmed_at IS NULL
           AND p.status <> 'paid'""")
    print(f"unconfirmed settlements: {len(unconfirmed)}")
    for u in unconfirmed:
        print(f"  {u['request_reference']} (invoice {u['invoice_status']})")

    closures = q("""
        SELECT a.request_reference, p.status AS invoice_status
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE p.status IN ('cancelled','expired')
           AND a.status IN ('creating','active','unknown')""")
    print(f"sessions to close    : {len(closures)}")

    attention = q("SELECT reference, attention_reason FROM corporate_payments "
                  "WHERE needs_attention_at IS NOT NULL")
    print(f"payments needing attention: {len(attention)}")
    for p in attention:
        print(f"  {p['reference']}: {p['attention_reason']}")

    events = q("SELECT id, source, event_type, reason FROM unresolved_payment_events "
               "WHERE resolved_at IS NULL")
    print(f"unresolved gateway events : {len(events)}")
    for e in events:
        print(f"  #{e['id']} {e['source']}/{e['event_type']}: {str(e['reason'])[:90]}")

    notices = q("SELECT id, kind, to_email, status FROM corporate_notifications "
                "WHERE status <> 'submitted'")
    print(f"unresolved notices   : {len(notices)}")

    cur.close(); conn.close()
    print("\nREPORT ONLY — no application code imported, no schema touched.")
    print("Re-run with --apply to act.")
    return 0


def _apply():
    from _guard import require_local_db
    # Guard the DESTINATION before importing anything that runs init_db().
    require_local_db()

    from app import app
    import paymongo
    from corporate_checkout import (poll_attempt, expire_attempt_remotely,
                                    SettlementRefused)
    from db import (replayable_attempts, expired_key_attempts,
                    unconfirmed_settlements, closable_attempts,
                    open_attempts_all, outbound_args, record_session,
                    confirm_settlement, payments_needing_attention,
                    recover_stale_attempts, unresolved_notifications,
                    unresolved_events, get_corporate_payment)

    with app.app_context():
        print(f"gateway mode : {'MOCKED' if paymongo.MOCK_GATEWAY else 'LIVE CALLS'}")
        print(f"environment  : {paymongo.environment()}")
        recovered = settled = closed = confirmed = 0
        problems = []

        # 1. Unresolved create outcomes, still inside the replay window.
        for a in replayable_attempts():
            ref = a["request_reference"]
            try:
                payload = json.loads(a["request_payload"] or "{}")
                # Byte-identical replay. PayMongo refuses a repeated key whose
                # parameters differ, so the stored payload is used verbatim
                # rather than rebuilt.
                sess = paymongo.create_checkout_session(
                    **outbound_args(payload),
                    idempotency_key=a["idempotency_key"])
                record_session(a["attempt_ref"], sess["id"],
                               sess.get("checkout_url"),
                               sess.get("payment_intent_id"))
                recovered += 1
                print(f"  recovered  {ref} -> {sess['id']}")
            except Exception as e:
                problems.append(f"{ref}: replay failed: {e}")

        # Past the window, replay would CREATE rather than recover.
        for a in expired_key_attempts():
            problems.append(
                f"{a['request_reference']}: idempotency key expired with no "
                f"session recorded — check the PayMongo dashboard by hand; "
                f"an automatic replay could create a second payable session.")

        # 2. Settlement bookkeeping that diverged from the invoice.
        for a in unconfirmed_settlements():
            try:
                ok, msg = poll_attempt(a, source="reconcile")
                if ok or "settled" in (msg or "").lower():
                    confirm_settlement(a["attempt_ref"])
                    confirmed += 1
                    print(f"  confirmed  {a['request_reference']}: {msg}")
                else:
                    problems.append(f"{a['request_reference']}: attempt is paid "
                                    f"but invoice is not: {msg}")
            except SettlementRefused as e:
                problems.append(f"{a['request_reference']}: {e}")

        # 3. Poll everything still open.
        for a in open_attempts_all():
            if not a.get("checkout_session_id"):
                continue
            try:
                ok, msg = poll_attempt(a, source="reconcile")
                if ok:
                    settled += 1
                    print(f"  settled    {a['request_reference']}: {msg}")
            except SettlementRefused as e:
                problems.append(f"{a['request_reference']}: {e}")
            except Exception as e:
                problems.append(f"{a['request_reference']}: poll failed: {e}")

        # 4. Close sessions behind invoices that are no longer payable —
        #    cancelled and expired included, not only lapsed pending ones.
        for a in closable_attempts():
            ok, msg = expire_attempt_remotely(a)
            if ok:
                closed += 1
                print(f"  closed     {a['request_reference']}: {msg}")
            else:
                problems.append(f"{a['request_reference']}: {msg}")

        # 5. Notification leases.
        stale = recover_stale_attempts()
        if stale:
            print(f"  notifications moved to 'uncertain': {len(stale)}")

        print(f"\nrecovered {recovered} · confirmed {confirmed} · "
              f"settled {settled} · closed {closed}")

        attention = payments_needing_attention()
        if attention:
            print(f"\nNEEDS ATTENTION ({len(attention)}):")
            for p in attention:
                print(f"  {p['reference']}: {p['attention_reason']}")
        events = unresolved_events()
        if events:
            print(f"\nUNRESOLVED GATEWAY EVENTS ({len(events)}):")
            for e in events:
                print(f"  #{e['id']} {e['source']}/{e['event_type']}: "
                      f"{str(e['reason'])[:90]}")
        notices = unresolved_notifications()
        if notices:
            print(f"\nUNRESOLVED NOTICES ({len(notices)}):")
            for n in notices:
                print(f"  #{n['id']} {n['kind']} -> {n['to_email']} [{n['status']}]")
        if problems:
            print(f"\nPROBLEMS ({len(problems)}):")
            for p in problems:
                print(f"  {p}")
        return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="perform recovery/settlement; default is report-only")
    args = ap.parse_args()
    return _apply() if args.apply else _report()


if __name__ == "__main__":
    sys.exit(main())
