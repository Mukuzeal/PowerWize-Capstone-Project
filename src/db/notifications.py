"""Company notifications — durable intent, attempts and outcomes.

Every notice to a company contact is a row before it is a send. That ordering
is the point: if the process dies mid-send, the intent survives and an admin
can see it and retry. Nothing is ever marked sent before the transport has
accepted it.

Delivery is leased: a send CLAIMS the row with a unique attempt_id and may
only record an outcome while it still owns it. See the lifecycle constants
below for the exact vocabulary — preview and mock are recorded distinctly
from a real SMTP submission, so a development run can never be mistaken for
one that actually emailed a company.

`dedupe_key` is what stops one event producing two emails. It carries a
version, so an intentionally replaced invoice is not blocked forever by the
notification belonging to the invoice it replaced.
"""
import uuid

import psycopg2.extras

from .core import get_db

# Lifecycle.
#
#   queued     intent recorded, nothing attempted
#   in_flight  an attempt owns this row until its lease expires
#   previewed  written to outbox/ — NOT sent anywhere
#   mocked     recorded in memory by a test — NOT sent anywhere
#   submitted  an SMTP server accepted it. Still not proof of delivery, but
#              the only outcome that means a real message left the host.
#   failed     the transport refused it; last_error says why
#   uncertain  an attempt's lease expired without a terminal outcome. A human
#              decides; nothing retries it automatically.
QUEUED    = "queued"
IN_FLIGHT = "in_flight"
PREVIEWED = "previewed"
MOCKED    = "mocked"
SUBMITTED = "submitted"
FAILED    = "failed"
UNCERTAIN = "uncertain"

# Terminal-success states. Only SUBMITTED represents real delivery; the other
# two record that the configured transport deliberately did not send.
TRANSPORT_OUTCOMES = {"smtp": SUBMITTED, "preview": PREVIEWED, "mock": MOCKED}

# Claimable for a (re)try. IN_FLIGHT is absent on purpose: an active lease is
# owned, and a stale one must go through recover_stale_attempts() first so a
# human sees that an earlier attempt's fate is unknown.
CLAIMABLE = (QUEUED, FAILED, PREVIEWED, MOCKED)

# How long one send may hold the row before its lease is considered stale.
ATTEMPT_LEASE_SECONDS = 120


def queue_notification(cur, intake_id, kind, to_email, subject, dedupe_key,
                       slot_id=None, created_by=None):
    """Record the intent using an EXISTING cursor, so it commits with
    whatever change prompted it.

    Returns the row id, or None if `dedupe_key` has already been queued —
    that is the duplicate guard, enforced by uq_corp_notif_dedupe rather than
    by a prior SELECT that another request could race.
    """
    cur.execute("""
        INSERT INTO corporate_notifications
            (intake_id, kind, slot_id, to_email, subject, status, dedupe_key, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
    """, (intake_id, kind, slot_id, to_email, subject, QUEUED, dedupe_key, created_by))
    row = cur.fetchone()
    if row is None:
        return None
    return row[0] if not isinstance(row, dict) else row["id"]


def begin_attempt(notif_id, lease_seconds=ATTEMPT_LEASE_SECONDS):
    """Claim exclusive ownership of this send. (attempt_id, attempts, reason).

    A single guarded UPDATE both takes the lease and stamps a fresh
    `attempt_id`, so two concurrent requests cannot both believe they own the
    send — the loser matches zero rows. Completion must quote the same
    attempt_id, which stops a slow earlier attempt from overwriting a later
    one's recorded outcome.

    An unexpired IN_FLIGHT row is never claimable: while another attempt may
    still be running, blindly resending risks a duplicate email. Such rows
    become recoverable only via recover_stale_attempts(), which makes the
    uncertainty explicit.
    """
    attempt_id = str(uuid.uuid4())
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_notifications
           SET attempts = attempts + 1,
               status = %s,
               attempt_id = %s,
               attempt_started_at = NOW(),
               attempt_expires_at = NOW() + make_interval(secs => %s)
         WHERE id = %s
           AND (status = ANY(%s)
                OR (status = %s AND attempt_expires_at IS NOT NULL
                    AND attempt_expires_at <= NOW()))
        RETURNING attempts
    """, (IN_FLIGHT, attempt_id, lease_seconds, notif_id,
          list(CLAIMABLE), IN_FLIGHT))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    if row is None:
        return None, 0, ("Another attempt is still in flight, or this "
                         "notification needs explicit recovery.")
    return attempt_id, row[0], None


def finish_attempt(notif_id, attempt_id, transport=None, error=None):
    """Record the terminal outcome for the attempt that owns this row.

    Guarded on `attempt_id`: a late-returning earlier attempt cannot clobber
    the state of the attempt that currently owns the send. Returns the status
    written, or None if this caller no longer owns it.
    """
    status = FAILED if error else TRANSPORT_OUTCOMES.get(transport, SUBMITTED)
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_notifications
           SET status = %s,
               transport = %s,
               last_error = %s,
               sent_at = CASE WHEN %s THEN NOW() ELSE sent_at END,
               attempt_expires_at = NULL
         WHERE id = %s AND attempt_id = %s
        RETURNING status
    """, (status, transport, str(error)[:2000] if error else None,
          error is None, notif_id, attempt_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return row[0] if row else None


def recover_stale_attempts():
    """Move expired in-flight leases to `uncertain`. Returns the ids touched.

    Explicit and non-destructive: it does not resend. An attempt whose lease
    lapsed may or may not have reached the mail server, so the only honest
    thing is to surface it and let a human decide.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_notifications
           SET status = %s,
               last_error = COALESCE(last_error, 'Attempt lease expired before a '
                                                'terminal outcome was recorded.')
         WHERE status = %s AND attempt_expires_at IS NOT NULL
           AND attempt_expires_at <= NOW()
        RETURNING id
    """, (UNCERTAIN, IN_FLIGHT))
    ids = [r[0] for r in cur.fetchall()]
    conn.commit(); cur.close(); conn.close()
    return ids


def force_retry_uncertain(notif_id, actor_note="Operator confirmed a resend"):
    """Deliberately make an `uncertain` row claimable again.

    Separate from begin_attempt() so a resend that might duplicate an email is
    always an explicit human decision, recorded in last_error.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_notifications
           SET status = %s, last_error = %s, attempt_id = NULL,
               attempt_expires_at = NULL
         WHERE id = %s AND status = %s
        RETURNING id
    """, (QUEUED, actor_note, notif_id, UNCERTAIN))
    ok = cur.fetchone() is not None
    conn.commit(); cur.close(); conn.close()
    return ok


def notification_payload(notif_id, link_kind="payment"):
    """(payload, error) — the decrypted retry payload.

    Three outcomes, kept DISTINCT because they need different responses:

      ({}, None)          no payload was ever stored
      ({...}, None)       readable
      (None, "<reason>")  stored but UNREADABLE

    The third used to collapse into the first, which was wrong in a way that
    mattered: a rotated SECRET_KEY would make a real, already-sent payment
    link look like "no link was ever stored", and the operator would be told
    to issue a fresh one — replacing a link the company may already be paying
    against. An undecryptable payload is a recovery problem and must say so.

    NEVER log the payload: it carries a payable URL.
    """
    import json
    from secretbox import decrypt
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT payload FROM corporate_notifications WHERE id = %s",
                (notif_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None, "That notification no longer exists."
    if not row[0]:
        return {}, None
    plain = decrypt(row[0])
    if plain is None:
        return None, (f"The stored {link_kind} link could not be decrypted — "
                      "SECRET_KEY has most likely changed since it was saved. "
                      "Do NOT assume no link was sent: check the delivery "
                      "history, then revoke and re-issue deliberately.")
    try:
        return json.loads(plain), None
    except Exception:
        return None, (f"The stored {link_kind} link is unreadable (corrupt "
                      "payload). Check delivery history before re-issuing.")


def get_notification(notif_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM corporate_notifications WHERE id = %s", (notif_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_notifications(intake_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT n.*, s.full_name AS slot_name
          FROM corporate_notifications n
          LEFT JOIN corporate_intake_slots s ON s.id = n.slot_id
         WHERE n.intake_id = %s
         ORDER BY n.created_at DESC
    """, (intake_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def unresolved_notifications():
    """Everything a human still needs to deal with, across all intakes."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT n.*, i.company_name
          FROM corporate_notifications n
          JOIN corporate_intakes i ON i.id = n.intake_id
         WHERE n.status <> %s
         ORDER BY n.created_at
    """, (SUBMITTED,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows
