"""Hosted-checkout payment attempts for corporate invoices.

The invariant this module exists to hold: **nothing is asked of the gateway
before it is written down.** An attempt row carries its own identity, an
idempotency key and an immutable snapshot of the request, and is committed
before the remote call. If the response never arrives, the key is still on
disk and replaying it is the only honest way to learn whether a session was
created.

A replacement is never minted while an earlier outcome is unknown —
`uq_corp_attempt_open` enforces that in the database, not in a code path that
a retry could skip.

Settlement itself is NOT re-implemented here. Every entry point funnels into
`db.corporate.mark_corporate_paid()`, whose guarded
`UPDATE ... WHERE status='pending' RETURNING *` already collapses duplicate
webhooks, polls and returns into exactly one settlement. What this module
adds is the validation that must pass *before* that function is allowed to
run.
"""
import hashlib
import json
import secrets
import uuid

import psycopg2.errors
import psycopg2.extras

from .core import get_db

CREATING = "creating"
ACTIVE   = "active"
EXPIRED  = "expired"
PAID     = "paid"
FAILED   = "failed"
UNKNOWN  = "unknown"

OPEN_STATES = (CREATING, ACTIVE, UNKNOWN)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ── Public payment link ──────────────────────────────────────────────────────

def issue_pay_token(corporate_payment_id):
    """Mint the company-facing link. Returns the plaintext ONCE.

    Bumps `link_version`, which scopes payment-link notifications — so
    deliberately replacing a link is not blocked forever by the notice that
    belonged to the previous one.
    """
    token = secrets.token_urlsafe(32)
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payments
           SET pay_token_hash = %s, pay_token_issued_at = NOW(),
               pay_token_revoked_at = NULL, link_version = link_version + 1
         WHERE id = %s AND status = 'pending'
        RETURNING link_version
    """, (hash_token(token), corporate_payment_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return (token, row[0]) if row else (None, None)


def revoke_pay_token(corporate_payment_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payments SET pay_token_revoked_at = NOW() "
                "WHERE id = %s AND pay_token_revoked_at IS NULL",
                (corporate_payment_id,))
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def payment_by_token(token):
    """(invoice, reason) — the invoice if this public link may be used now.

    Unknown / expired / revoked / cancelled all return the same reason: an
    anonymous visitor must not be able to tell them apart.
    """
    if not token:
        return None, "invalid"
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM corporate_payments WHERE pay_token_hash = %s",
                (hash_token(token),))
    rec = cur.fetchone()
    cur.close(); conn.close()
    if not rec:
        return None, "invalid"
    rec = dict(rec)
    if rec["pay_token_revoked_at"] is not None:
        return None, "invalid"
    if rec["status"] == "paid":
        return rec, "paid"
    if rec["status"] != "pending":
        return None, "invalid"
    return rec, None


# ── Attempts ─────────────────────────────────────────────────────────────────

def retire_offline_mock_attempt(corporate_payment_id, actor_id):
    """Retire only a provably local mock before connecting a real sandbox.

    A real or unidentified session is never closed by this operation. The
    id and URL must exactly match our deterministic mock response, and the
    original attempt must be active, test-mode and unpaid.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute('SELECT id FROM corporate_payments WHERE id=%s FOR UPDATE', (corporate_payment_id,))
        cur.execute('SELECT * FROM corporate_payment_attempts WHERE corporate_payment_id=%s AND status=ANY(%s) FOR UPDATE',
                    (corporate_payment_id, list(OPEN_STATES)))
        row = cur.fetchone()
        if not row or not (row['checkout_session_id'] or '').startswith('cs_mock_'):
            conn.rollback(); return True, None
        digest = hashlib.sha256(row['idempotency_key'].encode()).hexdigest()[:24]
        expected_id = 'cs_mock_' + digest
        if (row['status'] != ACTIVE or row['environment'] != 'test' or row['paid_payment_id']
                or row['checkout_session_id'] != expected_id
                or row['checkout_url'] != 'https://mock.paymongo.test/checkout/' + expected_id
                or row['creation_lease_until'] is not None):
            conn.rollback(); return False, 'This attempt cannot be verified as an inactive local mock. Resolve it before connecting another checkout.'
        detail = 'Offline mock checkout retired before connecting PayMongo sandbox. No remote session was expired.'
        cur.execute('UPDATE corporate_payment_attempts SET status=%s,expired_at=NOW(),last_error=%s WHERE attempt_ref=%s',
                    (EXPIRED, detail, row['attempt_ref']))
        cur.execute("INSERT INTO corporate_payment_events (corporate_payment_id,actor_id,action,details) VALUES (%s,%s,'mock_checkout_retired',%s)",
                    (corporate_payment_id, actor_id, detail))
        conn.commit()
        return True, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def open_attempt(corporate_payment_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT * FROM corporate_payment_attempts
         WHERE corporate_payment_id = %s AND status = ANY(%s)
         ORDER BY created_at DESC LIMIT 1
    """, (corporate_payment_id, list(OPEN_STATES)))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def attempt_for_return_token(token):
    """Resolve only the exact return capability sent in a saved gateway request.

    Rotating an invoice's payable link must not break an already-created
    session's immutable success_url. This lookup authorizes a status/receipt
    return only; it never makes the old link payable or recovers the new token.
    Explicit invoice-link revocation is still enforced by the return route.
    """
    from urllib.parse import urlsplit
    if not token or len(token) != 43 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in token):
        return None
    path = '/pay/corporate/' + token + '/return'
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Literal text search only narrows candidates. Parse and compare the
        # success_url below; a token appearing in metadata is not authority.
        cur.execute('SELECT * FROM corporate_payment_attempts WHERE strpos(request_payload,%s)>0 ORDER BY created_at DESC,id DESC', (path,))
        matches = []
        for row in cur.fetchall():
            try:
                payload = json.loads(row['request_payload'])
                parts = urlsplit(payload.get('success_url') or '')
            except (ValueError, TypeError, AttributeError):
                continue
            if (parts.scheme in ('http','https') and parts.netloc and not parts.query and not parts.fragment
                    and secrets.compare_digest(parts.path.encode('utf-8'), path.encode('ascii'))):
                matches.append(dict(row))
        if not matches or len({r['corporate_payment_id'] for r in matches}) != 1:
            return None
        return matches[0]
    finally:
        cur.close(); conn.close()


def get_attempts(corporate_payment_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM corporate_payment_attempts "
                "WHERE corporate_payment_id = %s ORDER BY created_at DESC",
                (corporate_payment_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def attempt_by_session(cs_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM corporate_payment_attempts WHERE checkout_session_id = %s",
                (cs_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def new_attempt_ref():
    """Minted by the CALLER, before the payload is built.

    The outbound request embeds `metadata.attempt_ref`, so the reference has
    to exist before the payload is final. Generating it here and inserting the
    complete payload in one statement removes the second-stage rewrite that
    previously left a committed row whose snapshot did not yet match what
    would be sent.
    """
    return str(uuid.uuid4())


def reserve_attempt(corporate_payment_id, amount_centavos, reference,
                    environment, payload, created_by=None, currency="PHP",
                    attempt_ref=None, lease_seconds=180):
    """Write the COMPLETE attempt before the gateway is called.

    (attempt, error). `uq_corp_attempt_open` refuses a second open attempt for
    the same invoice, so a double-click or a retry while a previous outcome is
    unknown cannot produce two payable sessions.

    The idempotency key is random and persisted here — NOT derived from the
    date. A day-bucketed key silently becomes a different key at midnight,
    which is precisely when a lost response most needs the original.

    `creation_lease_until` is this attempt's explicit ownership window. While
    it holds, the creating request owns the row and reconciliation leaves it
    alone — otherwise a sweep could replay an idempotency key for a request
    that is still in flight.
    """
    key = f"corp-{corporate_payment_id}-{uuid.uuid4()}"
    ref = attempt_ref or str(uuid.uuid4())
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Serialize with price overrides. The caller may have built this
        # payload from an invoice read before another admin changed the total.
        cur.execute('SELECT amount_centavos, reference FROM corporate_payments WHERE id=%s FOR UPDATE',
                    (corporate_payment_id,))
        invoice = cur.fetchone()
        if not invoice or invoice['amount_centavos'] != amount_centavos or invoice['reference'] != reference:
            conn.rollback()
            return None, 'The invoice price or reference changed. Reload it before creating checkout.'
        cur.execute("""
            INSERT INTO corporate_payment_attempts
                (corporate_payment_id, attempt_ref, idempotency_key,
                 request_amount_centavos, request_currency, request_reference,
                 request_payload, environment, status, created_by,
                 idempotency_expires_at, creation_lease_until)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    NOW() + interval '24 hours',
                    NOW() + make_interval(secs => %s))
            RETURNING *
        """, (corporate_payment_id, ref, key, amount_centavos, currency,
              reference, json.dumps(payload, sort_keys=True), environment,
              CREATING, created_by, lease_seconds))
        row = dict(cur.fetchone())
        conn.commit()
        return row, None
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return None, ("An attempt is already open for this invoice. Resolve it "
                      "before creating another.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def record_session(attempt_ref, cs_id, checkout_url, intent_id=None):
    """Attach the gateway's session to the attempt that asked for it."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payment_attempts
           SET checkout_session_id = %s, checkout_url = %s,
               payment_intent_id = %s, status = %s, remote_created_at = NOW(),
               last_error = NULL, creation_lease_until = NULL
         WHERE attempt_ref = %s AND status IN (%s, %s)
        RETURNING id
    """, (cs_id, checkout_url, intent_id, ACTIVE, attempt_ref, CREATING, UNKNOWN))
    ok = cur.fetchone() is not None
    conn.commit(); cur.close(); conn.close()
    return ok


def mark_attempt_unknown(attempt_ref, error):
    """The create call's outcome was never observed.

    Deliberately NOT 'failed': a session may well exist at the gateway. The
    row stays open so `uq_corp_attempt_open` keeps blocking replacements until
    recovery resolves it.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payment_attempts SET status = %s, last_error = %s, "
                "creation_lease_until = NULL "
                "WHERE attempt_ref = %s AND status = %s",
                (UNKNOWN, str(error)[:2000], attempt_ref, CREATING))
    conn.commit(); cur.close(); conn.close()


def mark_attempt_failed(attempt_ref, error):
    """A definite refusal — the gateway rejected the request outright."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payment_attempts SET status = %s, last_error = %s "
                "WHERE attempt_ref = %s AND status IN (%s, %s)",
                (FAILED, str(error)[:2000], attempt_ref, CREATING, UNKNOWN))
    conn.commit(); cur.close(); conn.close()


def mark_attempt_paid(attempt_ref, paid_payment_id, intent_id=None):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payment_attempts
           SET status = %s, paid_payment_id = %s, settled_at = NOW(),
               payment_intent_id = COALESCE(%s, payment_intent_id)
         WHERE attempt_ref = %s
        RETURNING id
    """, (PAID, paid_payment_id, intent_id, attempt_ref))
    ok = cur.fetchone() is not None
    conn.commit(); cur.close(); conn.close()
    return ok


def mark_attempt_expired(attempt_ref):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payment_attempts SET status = %s, expired_at = NOW() "
                "WHERE attempt_ref = %s AND status IN (%s, %s, %s)",
                (EXPIRED, attempt_ref, ACTIVE, CREATING, UNKNOWN))
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def flag_attention(corporate_payment_id, reason):
    """Persist an unresolved-money flag. Cleared only by an explicit action."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payments SET needs_attention_at = NOW(), "
                "attention_reason = %s WHERE id = %s",
                (str(reason)[:2000], corporate_payment_id))
    conn.commit(); cur.close(); conn.close()


def clear_attention(corporate_payment_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payments SET needs_attention_at = NULL, "
                "attention_reason = NULL WHERE id = %s", (corporate_payment_id,))
    conn.commit(); cur.close(); conn.close()


def payments_needing_attention():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM corporate_payments WHERE needs_attention_at IS NOT NULL "
                "ORDER BY needs_attention_at")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def open_attempts_all():
    """Every attempt a reconciliation run must look at."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.status AS invoice_status, p.expires_at, p.reference,
               p.amount_centavos
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status = ANY(%s)
         ORDER BY a.created_at
    """, (list(OPEN_STATES),))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def replayable_attempts():
    """Attempts whose create outcome is unresolved AND still replayable.

    Two conditions, both necessary:

      * `creating` counts as unresolved too. A process that died between the
        INSERT and the gateway call leaves that status forever; treating only
        `unknown` as recoverable would strand it.
      * the stored idempotency key must still be inside PayMongo's 24-hour
        retention window. Replaying a lapsed key does not return the original
        response — it starts a NEW request and can create a second payable
        session, which is the opposite of recovery.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.status AS invoice_status, p.expires_at, p.reference
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status IN (%s, %s)
           AND a.checkout_session_id IS NULL
           AND a.idempotency_expires_at > NOW()
           -- Ownership: a live creation lease means the request may still be
           -- in flight. Replaying its key now would race a real call.
           AND (a.creation_lease_until IS NULL OR a.creation_lease_until <= NOW())
         ORDER BY a.created_at
    """, (CREATING, UNKNOWN))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def expired_key_attempts():
    """Unresolved attempts past the replay window. NOT auto-recoverable.

    Surfaced for investigation instead: the key no longer identifies the
    original request, so only a human looking at the PayMongo dashboard can
    say whether a session exists.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.reference, p.status AS invoice_status
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status IN (%s, %s)
           AND a.checkout_session_id IS NULL
           AND a.idempotency_expires_at <= NOW()
         ORDER BY a.created_at
    """, (CREATING, UNKNOWN))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def unconfirmed_settlements():
    """Attempts marked paid whose invoice never reached 'paid'.

    The gap this closes: marking the attempt and flipping the invoice are two
    statements. A crash between them leaves an attempt in `paid` — which is
    NOT in OPEN_STATES, so the ordinary reconciliation sweep would never look
    at it again, and real money would sit unsettled forever.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.status AS invoice_status, p.reference, p.amount_centavos
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status = %s
           AND a.settlement_confirmed_at IS NULL
           AND p.status <> 'paid'
         ORDER BY a.settled_at
    """, (PAID,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def confirm_settlement(attempt_ref):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payment_attempts "
                "SET settlement_confirmed_at = NOW() WHERE attempt_ref = %s",
                (attempt_ref,))
    conn.commit(); cur.close(); conn.close()


def closable_attempts():
    """Open attempts whose invoice is no longer payable, for ANY reason.

    Includes cancelled and already-expired invoices, not just lapsed pending
    ones. An invoice closed locally while its gateway session stays active is
    exactly how a company pays for something this system considers finished.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.status AS invoice_status, p.reference, p.expires_at
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE a.status = ANY(%s)
           AND (p.status IN ('cancelled','expired')
                OR (p.status = 'pending' AND p.expires_at < NOW()))
         ORDER BY a.created_at
    """, (list(OPEN_STATES),))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


# ── Unresolved gateway events ────────────────────────────────────────────────

def record_unresolved_event(source, event_type, reason, raw_event,
                            cs_id=None, payment_id=None, reference_hint=None,
                            amount_centavos=None, currency=None, livemode=None):
    """Store an event we could not match or validate.

    Money may already have been taken, so the event is kept verbatim for a
    human to replay once the cause is understood. A bare 200 with a log line
    would lose it.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO unresolved_payment_events
            (source, event_type, checkout_session_id, payment_id,
             reference_hint, amount_centavos, currency, livemode, reason, raw_event)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (source, event_type, cs_id, payment_id, reference_hint,
          amount_centavos, currency, livemode, str(reason)[:4000],
          json.dumps(raw_event, default=str)[:60000]))
    eid = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return eid


def unresolved_events(include_resolved=False):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = "SELECT * FROM unresolved_payment_events"
    if not include_resolved:
        sql += " WHERE resolved_at IS NULL"
    sql += " ORDER BY received_at DESC"
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def resolve_event(event_id, actor_id, note):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE unresolved_payment_events SET resolved_at = NOW(), "
                "resolved_by = %s, resolution_note = %s "
                "WHERE id = %s AND resolved_at IS NULL",
                (actor_id, note, event_id))
    ok = cur.rowcount == 1
    conn.commit(); cur.close(); conn.close()
    return ok


def outbound_args(payload):
    """The stored payload, as create_checkout_session() keyword arguments.

    One translation used by BOTH the first call and any replay, so a recovery
    cannot drift from the original request.
    """
    return {
        "line_items":           payload.get("line_items", []),
        "description":          payload.get("description", ""),
        "reference_number":     payload.get("reference_number"),
        "success_url":          payload.get("success_url", ""),
        "cancel_url":           payload.get("cancel_url", ""),
        "payment_method_types": payload.get("payment_method_types"),
        "metadata":             payload.get("metadata") or {},
    }


def resolve_attempt(attempt_ref, actor_id, evidence_kind, evidence, action, result):
    """Close out an attempt on recorded evidence, never on assertion alone.

    `evidence_kind` is one of:
      session_retrieved  — the gateway was asked and answered about a session
      replay_confirmed   — the stored key was replayed inside its window
      operator_verified  — a human checked the PayMongo dashboard and says so

    The guard stays until one of those exists. This writes who resolved it,
    what evidence they had, what they did and what happened, because an
    attempt that blocked payment for a company is exactly the kind of thing
    someone will ask about later.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payment_attempts
           SET status = %s,
               expired_at = NOW(),
               creation_lease_until = NULL,
               last_error = %s
         WHERE attempt_ref = %s AND status = ANY(%s)
        RETURNING corporate_payment_id
    """, (EXPIRED,
          f"resolved[{evidence_kind}] by user {actor_id}: {evidence} | "
          f"action={action} | result={result}",
          attempt_ref, list(OPEN_STATES)))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return row[0] if row else None


PAY_PATH_PREFIX = "/pay/corporate/"


def canonical_pay_url(app_origin, token):
    """The ONE spelling of a payment link this system will ever send."""
    return app_origin.rstrip("/") + PAY_PATH_PREFIX + token


def validate_pay_url(corporate_payment_id, submitted_url, app_origin,
                     expected_version=None):
    """(canonical_url, reason) — the URL to actually use, or why not.

    Returns a URL BUILT SERVER-SIDE from the trusted application origin and
    the verified token, never the submitted string. Checking only the final
    path segment was not enough: `https://evil.test/pay/corporate/<valid>`
    carries a genuine token, so token-only validation would have accepted it
    and the company would have been emailed an attacker's host.

    The origin and path shape are therefore checked too, and what comes back
    is reconstructed rather than echoed.
    """
    if not submitted_url:
        return None, "No payment URL was supplied."

    from urllib.parse import urlparse
    want = urlparse(app_origin)
    got = urlparse(submitted_url)
    if (got.scheme, got.netloc) != (want.scheme, want.netloc):
        return None, (f"That URL points at '{got.netloc or 'nowhere'}', not this "
                      f"application ({want.netloc}). Refusing to send it.")
    # Exactly `<prefix><token>` — no extra segments, no traversal.
    if not got.path.startswith(PAY_PATH_PREFIX):
        return None, "That URL is not a payment link for this application."
    token = got.path[len(PAY_PATH_PREFIX):].strip("/")
    if not token or "/" in token:
        return None, "That URL does not name exactly one payment token."

    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT pay_token_hash, pay_token_revoked_at, link_version "
                "FROM corporate_payments WHERE id = %s", (corporate_payment_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None, "No such invoice."
    if not row["pay_token_hash"]:
        return None, "This invoice has no payment link yet."
    if row["pay_token_revoked_at"] is not None:
        return None, "That payment link has been revoked."
    if hash_token(token) != row["pay_token_hash"]:
        return None, ("That URL is not this invoice's current payment link. "
                      "Issue a link and use the URL it returns.")
    if expected_version is not None and row["link_version"] != expected_version:
        return None, (f"That link is version {expected_version}, but the "
                      f"invoice is now on version {row['link_version']}.")
    return canonical_pay_url(app_origin, token), None


def unresolved_events_for_payment(corporate_payment_id, reference):
    """Unresolved events that belong to one invoice.

    An event is linked two ways, because the webhook may give us either:

      * its checkout session id matches one of this invoice's attempts, or
      * its reference hint matches this invoice's reference.

    Both are needed. A session we never recorded has no attempt to match on,
    and an event that failed validation before the reference was read has no
    hint. Matching on only one would hide half of them.

    Events matching NEITHER are not this invoice's business and stay in the
    global queue — see unresolved_events(). That queue is the only place an
    orphan event can be seen, so it must not be the only one wired up either.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT e.* FROM unresolved_payment_events e
         WHERE e.resolved_at IS NULL
           AND (e.reference_hint = %s
                OR e.checkout_session_id IN (
                     SELECT checkout_session_id FROM corporate_payment_attempts
                      WHERE corporate_payment_id = %s
                        AND checkout_session_id IS NOT NULL))
         ORDER BY e.received_at DESC
    """, (reference, corporate_payment_id))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def unresolved_event(event_id):
    """One event, raw payload included, for inspection in the console."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM unresolved_payment_events WHERE id = %s",
                (event_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None
