"""Application ownership, sponsored waiting states, and secure corrections.

No email-string ownership inference. Browser-selected enrolments are checked
against explicit links on every read. Notification payloads contain secrets;
never return them in staff JSON or logs.
"""
import hashlib
import json
import secrets
from contextvars import ContextVar
from contextlib import contextmanager

from .core import get_db, dict_cur

CORRECTION_FIELDS = {
    'photo_id': 'Recent photo', 'resume': 'Resume (PDF)',
    'expired_doe': 'Expired DOE certificate', 'valid_id': 'Valid identification',
    'selfie_with_id': 'Selfie with identification',
    'full_name': 'Full name', 'middle_name': 'Middle name',
    'contact_number': 'Contact number', 'residence': 'Residence address',
    'designation': 'Designation', 'company_address': 'Company address',
    'birthdate': 'Birthdate',
}
UPLOAD_FIELDS = {'photo_id', 'resume', 'expired_doe', 'valid_id', 'selfie_with_id'}
CORRECTION_LIMITS = {'full_name':200,'middle_name':100,'contact_number':30,
                     'residence':300,'designation':150,'company_address':300,'birthdate':20}
_ENROLMENT_SCOPE = ContextVar('powerwize_enrolment', default=None)


@contextmanager
def enrolment_scope(user_id, reg_id):
    """Internal syllabus/assessment context; all reads still check ownership."""
    scope = _ENROLMENT_SCOPE.set((user_id,reg_id))
    try:
        yield
    finally:
        _ENROLMENT_SCOPE.reset(scope)


def selected_registration_id(user_id):
    """A request selection is only a hint; callers must check its ownership."""
    scoped = _ENROLMENT_SCOPE.get()
    if scoped and scoped[0] == user_id:
        return scoped[1]
    from flask import has_request_context, session
    if has_request_context() and session.get('user_id') == user_id:
        return session.get('active_registration_id')
    return None


def lms_registration_id(user_id, cur):
    selected = selected_registration_id(user_id)
    if selected:
        if not _owned(cur,user_id,selected):
            raise ValueError('This enrolment does not belong to the account.')
        return selected
    cur.execute('SELECT registration_id FROM users WHERE id=%s', (user_id,))
    user = cur.fetchone()
    if not user:
        return None
    return user['registration_id'] if isinstance(user,dict) else user[0]


def _owned(cur, user_id, reg_id, lock=False):
    cur.execute("""SELECT r.* FROM registrations r WHERE r.id=%s AND (
        EXISTS (SELECT 1 FROM trainee_enrolments e WHERE e.registration_id=r.id AND e.user_id=%s)
        OR EXISTS (SELECT 1 FROM users u WHERE u.id=%s AND u.registration_id=r.id))"""
        + (' FOR SHARE OF r' if lock else ''), (reg_id, user_id, user_id))
    return cur.fetchone()


def enrolments_for_user(user_id):
    conn = get_db(); cur = dict_cur(conn)
    try:
        cur.execute("""SELECT r.id,r.form_type,r.training_type,r.status,r.submitted_at,
            i.company_name FROM registrations r
            LEFT JOIN corporate_intake_slots s ON s.registration_id=r.id
            LEFT JOIN corporate_intakes i ON i.id=s.intake_id
            WHERE EXISTS (SELECT 1 FROM trainee_enrolments e WHERE e.user_id=%s AND e.registration_id=r.id)
               OR EXISTS (SELECT 1 FROM users u WHERE u.id=%s AND u.registration_id=r.id)
            ORDER BY r.submitted_at DESC,r.id""", (user_id, user_id))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()


def sponsored_enrolment(user_id, reg_id=None):
    """Current application's company and invoice, even before invoicing.

    A paid invoice wins over a pending replacement. Cancelled/expired bookings
    stay corporate, so they cannot fall through to individual checkout.
    """
    from .registrations import get_registration_for_user
    if reg_id is None:
        reg = get_registration_for_user(user_id)
        reg_id = reg['id'] if reg else None
    if not reg_id:
        return None
    conn = get_db(); cur = dict_cur(conn)
    try:
        reg = _owned(cur, user_id, reg_id)
        if not reg:
            return None
        cur.execute("""SELECT s.id AS slot_id,s.invite_revoked_at,i.id AS intake_id,
            i.company_name,i.status AS intake_status
            FROM corporate_intake_slots s JOIN corporate_intakes i ON i.id=s.intake_id
            WHERE s.registration_id=%s""", (reg_id,))
        slot = cur.fetchone()
        cur.execute("""SELECT p.id,p.reference,p.status,p.intake_id,p.company_name
            FROM corporate_payment_items it JOIN corporate_payments p ON p.id=it.corporate_payment_id
            WHERE it.registration_id=%s OR (it.registration_id IS NULL AND it.user_id=%s)
            ORDER BY (p.status='paid') DESC,(p.status='pending') DESC,p.id DESC LIMIT 1""",
            (reg_id, user_id))
        inv = cur.fetchone()
        if not slot and not inv:
            return None
        legacy_paid = False
        if not inv:
            cur.execute("SELECT 1 FROM users WHERE id=%s AND registration_id=%s AND payment_status='paid'", (user_id,reg_id))
            legacy_paid = cur.fetchone() is not None
        from review_policy import readiness
        return {**(dict(slot) if slot else {'intake_id': inv['intake_id'],
                  'company_name': inv['company_name'], 'intake_status': None,
                  'invite_revoked_at': None}),
                'registration_id': reg_id, 'review': readiness(dict(reg)),
                'training_type':reg['training_type'],
                'invoice': dict(inv) if inv else None,
                'paid': bool(inv and inv['status'] == 'paid') or legacy_paid}
    finally:
        cur.close(); conn.close()


def attach_enrolment(cur, user_id, reg_id):
    """Called only after a token + identity claim, in the caller's transaction."""
    cur.execute("""INSERT INTO trainee_enrolments(registration_id,user_id) VALUES(%s,%s)
        ON CONFLICT (registration_id) DO NOTHING""", (reg_id, user_id))
    cur.execute('SELECT user_id FROM trainee_enrolments WHERE registration_id=%s', (reg_id,))
    if cur.fetchone()['user_id'] != user_id:
        raise ValueError('This application already belongs to another account.')
    # The invoice line is an application snapshot, not an inferred email link.
    cur.execute('UPDATE corporate_payment_items SET user_id=%s WHERE registration_id=%s AND user_id IS NULL',
                (user_id, reg_id))
    # Preserve the legacy account flag for its original application only.
    cur.execute("""UPDATE users u SET payment_status='paid' WHERE u.id=%s
        AND u.registration_id=%s AND EXISTS (
            SELECT 1 FROM corporate_payment_items it JOIN corporate_payments p ON p.id=it.corporate_payment_id
            WHERE it.registration_id=%s AND p.status='paid')""", (user_id, reg_id, reg_id))


def claim_existing_enrolment(token, user_id):
    """Authenticated existing account explicitly accepts its emailed invitation."""
    from .users import _hash_token
    from review_policy import readiness
    conn = get_db(); cur = dict_cur(conn)
    try:
        cur.execute('SELECT * FROM account_tokens WHERE token=%s AND used_at IS NULL AND expires_at>NOW() FOR UPDATE', (_hash_token(token),))
        tok = cur.fetchone()
        cur.execute('SELECT id,email,role FROM users WHERE id=%s AND archived_at IS NULL FOR UPDATE', (user_id,))
        user = cur.fetchone()
        if not tok or not user or user['role'] != 'trainee' or user['email'].strip().lower() != tok['email'].strip().lower():
            conn.rollback(); return None, 'Sign in to the trainee account this invitation was addressed to.'
        cur.execute('SELECT * FROM registrations WHERE id=%s FOR SHARE', (tok['reg_id'],))
        reg = cur.fetchone()
        if not reg or not readiness(dict(reg))['ready']:
            conn.rollback(); return None, 'This application is no longer approved for activation.'
        attach_enrolment(cur, user_id, reg['id'])
        cur.execute('UPDATE account_tokens SET used_at=NOW() WHERE token=%s', (_hash_token(token),))
        cur.execute("""INSERT INTO registration_review_history(reg_id,review_version,action,snapshot,actor_id)
            VALUES(%s,%s,'enrolment_claimed','{}',%s)""", (reg['id'], reg['review_version'], user_id))
        conn.commit(); return reg['id'], None
    except ValueError as exc:
        conn.rollback(); return None, str(exc)
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def request_correction(reg_id, note, fields, actor_id, origin, expected_version=None):
    """Save request, review history, and both delivery intents atomically."""
    from .notifications import queue_notification
    from secretbox import encrypt
    from review_policy import REQUIRED_DOCS
    fields = set(fields)
    if fields & {'valid_id','full_name','birthdate'}:
        fields.update({'valid_id','selfie_with_id'})
    fields = sorted(fields)
    if not note.strip() or len(note)>2000 or not fields or any(f not in CORRECTION_FIELDS for f in fields):
        return None, 'Describe the correction and select at least one requirement.'
    conn = get_db(); cur = dict_cur(conn)
    try:
        # Serialize with roster/invoice operations before taking application locks.
        cur.execute('SELECT intake_id FROM corporate_intake_slots WHERE registration_id=%s', (reg_id,))
        linked = cur.fetchone()
        if linked:
            cur.execute('SELECT id FROM corporate_intakes WHERE id=%s FOR UPDATE', (linked['intake_id'],))
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('registration-review:'+reg_id,))
        cur.execute('SELECT * FROM registrations WHERE id=%s FOR UPDATE', (reg_id,))
        reg = cur.fetchone()
        if not reg:
            conn.rollback(); return None, 'No such registration.'
        if expected_version is not None and str(reg['review_version']) != str(expected_version):
            conn.rollback(); return None, 'This application changed. Reload it before reviewing.'
        permitted = set(CORRECTION_FIELDS) - (UPLOAD_FIELDS - set(REQUIRED_DOCS.get(reg['form_type'], ())) - {'selfie_with_id'})
        if not set(fields) <= permitted:
            conn.rollback(); return None, 'Select requirements belonging to this program.'
        # A repeated identical pending request is the same event, not new email.
        cur.execute('SELECT * FROM registration_corrections WHERE reg_id=%s AND used_at IS NULL AND expires_at>NOW() ORDER BY version DESC LIMIT 1', (reg_id,))
        old = cur.fetchone()
        if old and old['note'] == note.strip() and old['fields'] == fields and reg['status'] == 'needs_correction':
            conn.rollback(); return {'notification_ids': [], 'duplicate': True}, None
        version = reg['correction_version'] + 1
        token = secrets.token_urlsafe(32)
        snapshot = json.dumps({k: reg.get(k) for k in ('status','selfie_outcome','selfie_reviewed_at','is_qualified','documents_purged_at')}, default=str)
        cur.execute("""INSERT INTO registration_review_history(reg_id,review_version,action,snapshot,actor_id)
            VALUES(%s,%s,'correction_requested',%s,%s)""", (reg_id,reg['review_version'],snapshot,actor_id))
        cur.execute('UPDATE registration_corrections SET expires_at=LEAST(expires_at,NOW()) WHERE reg_id=%s AND used_at IS NULL', (reg_id,))
        prior_status = old['prior_status'] if old and reg['status'] == 'needs_correction' else reg['status']
        cur.execute("""INSERT INTO registration_corrections(reg_id,version,token_hash,fields,note,requested_by,prior_status)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""", (reg_id,version,hashlib.sha256(token.encode()).hexdigest(),fields,note.strip(),actor_id,prior_status))
        cur.execute("""UPDATE registrations SET status='needs_correction',correction_note=%s,
            correction_set_at=NOW(),correction_version=%s WHERE id=%s""", (note.strip(),version,reg_id))
        # Outstanding approval links must not survive a reopened application.
        cur.execute('DELETE FROM account_tokens WHERE reg_id=%s AND used_at IS NULL', (reg_id,))
        cur.execute("""SELECT s.id,s.email,i.id AS intake_id,i.contact_email,i.company_name
            FROM corporate_intake_slots s JOIN corporate_intakes i ON i.id=s.intake_id WHERE s.registration_id=%s""", (reg_id,))
        slot = cur.fetchone()
        recipient = (reg['email'] or '').strip()
        if not recipient or recipient.count('@')!=1 or len(recipient)>150 or any(c.isspace() for c in recipient):
            conn.rollback(); return None, 'The application needs a valid trainee email before requesting corrections.'
        nid = queue_notification(cur, slot['intake_id'] if slot else None, 'trainee_correction', recipient,
            'Correct your EnergyWize requirements', f'trainee-correction:{reg_id}:v{version}',
            slot_id=slot['id'] if slot else None, created_by=actor_id)
        payload = {'reg_id': reg_id, 'version': version, 'name': reg['full_name'], 'note': note.strip(),
                   'url': origin.rstrip('/') + '/registration/correct/' + token}
        cur.execute('UPDATE corporate_notifications SET payload=%s WHERE id=%s', (encrypt(json.dumps(payload)),nid))
        ids = [nid]
        if slot:
            company_nid = queue_notification(cur, slot['intake_id'], 'needs_correction', slot['contact_email'],
                'Action needed: trainee registration', f'correction:{reg_id}:v{version}',
                slot_id=slot['id'],created_by=actor_id)
            ids.append(company_nid)
        conn.commit(); return {'notification_ids': ids, 'notification_id': company_nid if slot else None,
                              'company': slot['company_name'] if slot else None}, None
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def correction_access(token):
    if not token or len(token) != 43:
        return None
    conn = get_db(); cur = dict_cur(conn)
    try:
        cur.execute("""SELECT c.*,r.form_type,r.full_name,r.email,r.status,r.correction_version
            FROM registration_corrections c JOIN registrations r ON r.id=c.reg_id
            WHERE c.token_hash=%s AND c.used_at IS NULL AND c.expires_at>NOW()
              AND r.status='needs_correction' AND r.correction_version=c.version""",
            (hashlib.sha256(token.encode()).hexdigest(),))
        row = cur.fetchone(); return dict(row) if row else None
    finally:
        cur.close(); conn.close()


def submit_correction(token, values):
    """Consume once and update the SAME application, reopening affected gates."""
    conn = get_db(); cur = dict_cur(conn)
    try:
        cur.execute('SELECT reg_id FROM registration_corrections WHERE token_hash=%s', (hashlib.sha256(token.encode()).hexdigest(),))
        scope = cur.fetchone()
        if not scope:
            conn.rollback(); return None, 'This correction link is unavailable.'
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('registration-review:'+scope['reg_id'],))
        cur.execute("""SELECT c.* FROM registration_corrections c WHERE token_hash=%s
            AND used_at IS NULL AND expires_at>NOW() FOR UPDATE""", (hashlib.sha256(token.encode()).hexdigest(),))
        correction = cur.fetchone()
        if not correction:
            conn.rollback(); return None, 'This correction link is expired, replaced, or already used.'
        cur.execute('SELECT * FROM registrations WHERE id=%s FOR UPDATE', (correction['reg_id'],))
        reg = cur.fetchone()
        if reg['status'] != 'needs_correction' or reg['correction_version'] != correction['version']:
            conn.rollback(); return None, 'The review changed. Ask the administrator for the current correction link.'
        if set(values) != set(correction['fields']) or any(not str(v or '').strip() for v in values.values()):
            conn.rollback(); return None, 'Complete every requested correction.'
        if any(len(str(v))>CORRECTION_LIMITS.get(f,255) for f,v in values.items()):
            conn.rollback();return None,'A corrected value is too long. Use the field limits shown on the form.'
        age=None
        if 'birthdate' in values:
            from datetime import date
            try:
                born=date.fromisoformat(values['birthdate'])
            except ValueError:
                conn.rollback();return None,'Enter a valid birthdate in YYYY-MM-DD format.'
            cur.execute('SELECT CURRENT_DATE AS today')
            today=cur.fetchone()['today']
            if born>today:
                conn.rollback();return None,'Birthdate cannot be in the future.'
            age=str(today.year-born.year-((today.month,today.day)<(born.month,born.day)))
        old_files = {f: reg[f] for f in values if f in UPLOAD_FIELDS and reg.get(f)}
        for field, filename in old_files.items():
            cur.execute("""INSERT INTO registration_retired_uploads(reg_id,field,filename,review_version)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (reg['id'],field,filename,reg['review_version']))
        cur.execute("""INSERT INTO registration_review_history(reg_id,review_version,action,snapshot)
            VALUES(%s,%s,'correction_submitted',%s)""",
            (reg['id'],reg['review_version'],json.dumps({'fields': correction['fields'], 'note': correction['note'], 'previous_values':{f:reg[f] for f in values if f not in UPLOAD_FIELDS}},default=str)))
        assignments = [f'{f}=%s' for f in values]  # keys checked against the saved allowlist
        identity = 'selfie_with_id' in values or 'valid_id' in values
        # Keep an approved identity when only application/profile facts changed.
        extra = ",selfie_reviewed_at=NULL,selfie_outcome=NULL" if identity else ''
        if age is not None:
            assignments.append('age=%s')
        application_status = correction['prior_status'] if set(values) == {'selfie_with_id'} else 'pending'
        if application_status not in ('accepted','pending','rejected'):
            application_status = 'pending'
        cur.execute('UPDATE registrations SET ' + ','.join(assignments) +
            ",status=%s,review_version=review_version+1" +
            (',documents_purged_at=NULL' if set(values) & UPLOAD_FIELDS else '') +
            ",correction_note=NULL,correction_set_at=NULL" + extra +
            ' WHERE id=%s', list(values.values()) + ([age] if age is not None else []) + [application_status,reg['id']])
        cur.execute('UPDATE registration_corrections SET used_at=NOW() WHERE id=%s', (correction['id'],))
        conn.commit(); return {'reg_id':reg['id'],'old_files':old_files, 'old_version':reg['review_version']}, None
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def purge_retired_uploads(reg_id, roots):
    """Retryable cleanup of replacements; never clear another live pointer.

    Called after commit. The durable journal survives a process/filesystem
    failure. Only private/legacy configured roots are examined.
    """
    import os
    conn = get_db(); cur = dict_cur(conn)
    try:
        cur.execute('SELECT * FROM registration_retired_uploads WHERE reg_id=%s AND purged_at IS NULL FOR UPDATE', (reg_id,))
        for entry in cur.fetchall():
            cur.execute("SELECT 1 FROM registrations WHERE %s IN (photo_id,resume,expired_doe,valid_id,selfie_with_id) LIMIT 1", (entry['filename'],))
            if cur.fetchone():
                cur.execute("UPDATE registration_retired_uploads SET last_error='Still referenced by a live application' WHERE id=%s", (entry['id'],))
                continue
            digest = None; size = None; failure = None
            for root in roots:
                if not root:
                    continue
                root = os.path.realpath(root)
                path = os.path.realpath(os.path.join(root, entry['filename']))
                if os.path.commonpath([root,path]) != root:
                    failure = 'Invalid document path'; break
                if os.path.isfile(path):
                    try:
                        with open(path, 'rb') as source:
                            content = source.read()
                        digest = hashlib.sha256(content).hexdigest(); size = len(content)
                        os.remove(path)
                    except OSError:
                        failure = 'File deletion failed; retry cleanup'; break
            if failure:
                cur.execute('UPDATE registration_retired_uploads SET last_error=%s WHERE id=%s', (failure,entry['id']))
                continue
            cur.execute("""INSERT INTO registration_document_reviews(reg_id,field,sha256,byte_size,file_ext,outcome,note,review_version)
                VALUES(%s,%s,%s,%s,%s,'superseded',%s,%s)
                ON CONFLICT(reg_id,field,review_version) DO NOTHING""",
                (reg_id,entry['field'],digest,size,os.path.splitext(entry['filename'])[1],
                 'deleted' if digest else 'missing',entry['review_version']))
            cur.execute('UPDATE registration_retired_uploads SET purged_at=NOW(),last_error=NULL WHERE id=%s', (entry['id'],))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()
