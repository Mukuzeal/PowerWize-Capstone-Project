"""Company-facing intake views.

Scoped, revocable, time-limited links:

  /company/roster/<token>   coordinator status view for one intake
  /company/register/<token> shared class code and roster email select a trainee
  /company/invite/<token>   compatibility with previously issued invitations

Deliberately a separate module that never imports `permissions.require`. Every
other admin surface is guarded by it, so putting unauthenticated routes in the
same file would make "is this route public?" a per-function question a future
edit could silently get wrong. Here the answer is structural: this blueprint
has no staff capability available to it at all.

What a coordinator may see is narrow on purpose: names they supplied, whether
each person has submitted, where the review stands, and any correction the
applicant has been asked to make. Never an uploaded document, never a private
review note, never another company's intake.
"""
from flask import Blueprint, render_template, redirect, abort, request, session, current_app, g, url_for

from db import (coordinator_access, get_slots, invitation_state, audit_log,
                registration_link_access, enter_registration_with_class_code,
                registration_class_grant_valid, get_schedules)
from pricing import program_label

company_bp = Blueprint("company", __name__)

FORM_PATHS = {
    "training": "/training", "cea_training": "/cea-training",
    "cem_renewal": "/renewalCEM", "cea_renewal": "/renewalCEA",
    "gemp_lgu": "/gemp-lgu", "gemp_oge": "/gemp-oge",
}

COMPANY_FORMS = {
    'training': ('training/training.html', 'training_submit'),
    'cea_training': ('training/cea_training.html', 'cea_training_submit'),
    'cem_renewal': ('training/renewalCEM.html', 'renewal_cem_submit'),
    'cea_renewal': ('training/renewalCEA.html', 'renewal_submit'),
    'gemp_lgu': ('training/gemp_lgu.html', 'gemp_lgu_submit'),
    'gemp_oge': ('training/gemp_oge.html', 'gemp_oge_submit'),
}


@company_bp.context_processor
def company_upload_context():
    intake = getattr(g, 'company_registration_intake', None)
    if not intake:
        return {}
    return {'company_registration': intake,
            'company_program_label': program_label(intake['form_type']),
            'company_registration_action': url_for('company.company_register', token=request.view_args['token'])}


@company_bp.route('/company/register/<token>', methods=['GET', 'POST'])
def company_register(token):
    """One shared URL and class code; a roster email selects an unused slot."""
    intake = registration_link_access(token)
    if not intake:
        response = _no_leak(render_template('auth/token_invalid.html',
            reason='This registration link is not valid or has expired.'))
        response.status_code = 404
        return response

    action = request.form.get('action')
    if action == 'change_email':
        session.pop('company_registration_grant', None)
        session.pop('company_entry_challenge', None)
        return _no_leak(redirect(url_for('company.company_register', token=token)))
    if action == 'enter_class':
        session.pop('company_registration_grant', None)
    grant = session.get('company_registration_grant') or {}
    if grant.get('link_token') == token:
        slot, _ = invitation_state(grant.get('token', ''))
        if (slot and slot['email_key'] == grant.get('email_key') and slot['form_type'] == intake['form_type']
                and registration_class_grant_valid(intake['id'], grant.get('class_id'), grant.get('class_code_hash'))):
            g.company_registration_intake = intake
            template, submit_name = COMPANY_FORMS[intake['form_type']]
            if request.method == 'GET':
                return _no_leak(render_template(template, schedules=get_schedules(), errors=[],
                    form_data={'email': grant['email_key'], 'company_name': intake['company_name'],
                               'full_name': slot['full_name']}, uploaded={}))
            if action == 'submit_registration':
                if request.form.get('intake_invite', grant['token']) != grant['token']:
                    abort(400)
                # Keep the same URL and validation/upload pipeline. No second
                # registration implementation and no redirect to public forms.
                import registration
                from flask import make_response
                return _no_leak(make_response(getattr(registration, submit_name)()))
        else:
            session.pop('company_registration_grant', None)
    if action == 'submit_registration':
        response = _no_leak(render_template('auth/token_invalid.html',
            reason='Your upload session expired. Open the company link and enter your class code again.'))
        response.status_code = 403
        return response
    session.pop('company_entry_challenge', None)
    message, error = None, None
    email = ''
    if request.method == 'POST' and action == 'enter_class':
        email = request.form.get('email', '').strip().lower()
        if len(email) > 150 or '@' not in email or any(c.isspace() for c in email):
            error = 'Enter a valid email address.'
        else:
            grant = enter_registration_with_class_code(token, email, request.form.get('class_code', '')[:64])
            if not grant:
                error = ('We could not open this registration. Check the class code and your roster email, '
                         'or contact your coordinator if you have already submitted.')
            else:
                if grant['form_type'] not in COMPANY_FORMS:
                    abort(404)
                session['company_registration_grant'] = dict(grant, link_token=token)
                audit_log(None, 'company_registration_code_entered', 'corporate_intake', intake['id'],
                          'Trainee entered shared class code and selected a listed roster email')
                return _no_leak(redirect(url_for('company.company_register', token=token)))
    elif request.method == 'POST':
        error = 'Enter the class code your coordinator shared and your roster email to continue.'

    return _no_leak(render_template('company/register.html', intake=intake,
        email=email,
        message=message, error=error))

# Fields a coordinator is allowed to see, enumerated rather than filtered out
# of a wider row — an allowlist cannot leak a column added later.
_VISIBLE = ("full_name", "email", "derived_status", "submitted_at",
            "correction_note", "invite_used", "invite_revoked")


def _project(slot):
    return {
        "full_name":      slot["full_name"],
        "email":          slot["email"],
        "status":         slot["derived_status"],
        "status_label":   slot['readiness']['display_label'] if slot['readiness'] else 'Not submitted',
        "submitted_at":   slot["submitted_at"],
        # The only review text the company sees. Written FOR the applicant;
        # private notes and rejection reasoning are never surfaced here.
        "correction":     slot["correction_note"],
        "invite_used":    slot["invite_used_at"] is not None,
        "invite_revoked": slot["invite_revoked_at"] is not None,
    }


@company_bp.route("/company/roster/<token>")
def company_roster(token):
    intake, reason = coordinator_access(token)
    if not intake:
        # One generic page for unknown / expired / revoked / cancelled: telling
        # an anonymous visitor which one it is turns this into an oracle.
        return render_template("auth/token_invalid.html",
                               reason="This company link is not valid or has expired."), 404

    slots = [_project(s) for s in get_slots(intake["id"])]
    counts = {}
    for s in slots:
        counts[s["status"]] = counts.get(s["status"], 0) + 1

    audit_log(None, "company_roster_viewed", "corporate_intake", intake["id"],
              f"Coordinator viewed the roster ({len(slots)} slot(s))")

    resp = render_template("company/roster.html", intake=intake, slots=slots,
                           counts=counts, total=len(slots))
    return _no_leak(resp)


@company_bp.route("/company/invite/<token>")
def company_invite(token):
    """Send an invited trainee to the right public form, carrying the token."""
    slot, reason = invitation_state(token)
    if not slot:
        return render_template(
            "auth/token_invalid.html",
            reason=("This invitation has already been used."
                    if reason == "used"
                    else "This invitation is not valid or has expired.")), 404

    form_path = {
        "training":     "/training",
        "cea_training": "/cea-training",
        "cem_renewal":  "/renewalCEM",
        "cea_renewal":  "/renewalCEA",
        "gemp_lgu":     "/gemp-lgu",
        "gemp_oge":     "/gemp-oge",
    }.get(slot["form_type"])
    if not form_path:
        abort(404)
    # The form itself validates and re-checks the token on POST; this only
    # routes the person to it.
    return redirect(f"{form_path}?intake_invite={token}")


def _no_leak(body):
    """Keep a forwarded company link out of referrers and search engines."""
    from flask import make_response
    resp = make_response(body)
    # HTTPS form POSTs need a same-origin Referer for Flask-WTF's strict
    # check. Never send the bearer URL to external sites; the read-only
    # coordinator page can continue suppressing all referrers.
    resp.headers["Referrer-Policy"] = (
        "same-origin" if request.endpoint == "company.company_register" else "no-referrer")
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp
