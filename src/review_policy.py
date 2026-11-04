"""The one readiness rule for a registration.

Four facts are kept deliberately separate, because conflating any two of them
is how this workflow goes subtly wrong:

  1. document completeness    — are the required uploads present (or already
                                purged after a finished review)?
  2. registration acceptance  — has an admin accepted the application?
  3. identity review          — has the selfie been reviewed, and approved?
  4. professional qualification — `is_qualified`, a DOE-certification matter

Only (2) and (3) decide readiness. (1) is an input to review, not a verdict.
(4) is ADVISORY and gates nothing: an accepted-but-unqualified trainee may
train and may be certified; the acceptance email simply tells them to satisfy
DOE requirements before applying for official certification. No new
restriction is introduced here on the strength of that email wording.

Pure logic, no database access, so the admin console, the company portal, the
account-invitation path and payment eligibility all read the same answer.
"""

# Whether a program's application includes an identity selfie.
#
# Stated explicitly rather than inferred from whether a row happens to have a
# filename: "no selfie on file" is ambiguous between "this program never asks
# for one" and "this applicant has not provided one", and those must not be
# treated alike. All six current programs render selfie_capture() through
# templates/training/_program_form.html.
SELFIE_REQUIRED_FORMS = {
    "training":     True,
    "cea_training": True,
    "cem_renewal":  True,
    "cea_renewal":  True,
    "gemp_lgu":     True,
    "gemp_oge":     True,
}

# Required upload columns per program.
REQUIRED_DOCS = {
    "training":     ("photo_id", "resume", "valid_id"),
    "cea_training": ("photo_id", "resume", "valid_id"),
    "cem_renewal":  ("photo_id", "expired_doe", "valid_id"),
    "cea_renewal":  ("photo_id", "expired_doe", "valid_id"),
    "gemp_lgu":     ("photo_id", "valid_id"),
    "gemp_oge":     ("photo_id", "valid_id"),
}

# Identity-review outcomes.
IDENTITY_NOT_REQUIRED = "not_required"
IDENTITY_APPROVED     = "approved"
IDENTITY_REJECTED     = "rejected"
IDENTITY_PENDING      = "pending"
IDENTITY_MISSING      = "missing"


def selfie_required(form_type):
    return SELFIE_REQUIRED_FORMS.get(form_type, True)


def identity_state(reg):
    """Where identity review stands for one registration row.

    Order matters. `selfie_reviewed_at` is checked FIRST because a finished
    review purges the file: after a purge `selfie_with_id` is NULL while the
    review definitely happened. Reading the filename first would mis-read a
    completed review as missing.

    A NULL `selfie_reviewed_at` is never read as approval. The absence of a
    timestamp means the review has not been recorded — not that it passed.
    """
    if not selfie_required(reg.get("form_type")):
        return IDENTITY_NOT_REQUIRED

    if reg.get("selfie_reviewed_at") is not None:
        outcome = (reg.get("selfie_outcome") or "").lower()
        if outcome == "approved":
            return IDENTITY_APPROVED
        if outcome == "rejected":
            return IDENTITY_REJECTED
        # Reviewed but with no recorded outcome: treat as unresolved rather
        # than guessing which way it went.
        return IDENTITY_PENDING

    # Not reviewed. Distinguish "nothing to review" from "awaiting review",
    # because a required selfie that was never supplied is NOT a pass.
    if not (reg.get("selfie_with_id") or "").strip():
        return IDENTITY_MISSING
    return IDENTITY_PENDING


def documents_complete(reg):
    """Required uploads present, or already purged after a finished review.

    `documents_purged_at` means the files existed and both gates closed, so
    their absence now is the expected end state, not an incomplete submission.
    """
    if reg.get("documents_purged_at") is not None:
        return True
    required = REQUIRED_DOCS.get(reg.get("form_type"), ())
    return all((reg.get(col) or "").strip() for col in required)


def readiness(reg):
    """The single verdict. Returns a dict, never a bare bool, so callers can
    show *why* rather than inventing their own second rule.

    `ready` means: the application is accepted AND identity review has
    finished successfully (or the program genuinely requires none). It does
    NOT consider qualification.
    """
    status   = (reg.get("status") or "").lower()
    identity = identity_state(reg)
    accepted = status == "accepted"
    identity_ok = identity in (IDENTITY_APPROVED, IDENTITY_NOT_REQUIRED)
    identity_label = {
        IDENTITY_APPROVED: 'Approved', IDENTITY_REJECTED: 'Rejected',
        IDENTITY_PENDING: 'Pending', IDENTITY_MISSING: 'Missing',
        IDENTITY_NOT_REQUIRED: 'Not required',
    }.get(identity, 'Pending')
    if accepted and identity_ok:
        display_label = 'Approved'
    elif accepted:
        display_label = f'Accepted — identity {identity_label.lower()}'
    else:
        display_label = {'pending': 'Pending registration review', 'rejected': 'Not approved',
                         'needs_correction': 'Needs correction'}.get(status, 'Pending registration review')

    blockers = []
    if not accepted:
        blockers.append({
            "pending":          "Application is awaiting review.",
            "needs_correction": "Applicant has been asked to correct their requirements.",
            "rejected":         "Application was not approved.",
        }.get(status, "Application has not been accepted."))
    if not identity_ok:
        blockers.append({
            IDENTITY_PENDING:  "Identity (selfie) review is still pending.",
            IDENTITY_REJECTED: "Identity (selfie) review was rejected.",
            IDENTITY_MISSING:  "A required identity selfie has not been provided.",
        }.get(identity, "Identity review is incomplete."))

    return {
        "ready":                 accepted and identity_ok,
        "registration_accepted": accepted,
        "registration_status":   status,
        "identity":              identity,
        "identity_label":        identity_label,
        "display_label":         display_label,
        "identity_ok":           identity_ok,
        "documents_complete":    documents_complete(reg),
        # Reported, never gating. Preserved exactly as the admin recorded it.
        "qualified":             bool(reg.get("is_qualified", 1)),
        "blockers":              blockers,
    }


def may_issue_account_invitation(reg):
    """(allowed, reason) — the gate for minting an account-setup token.

    Requires acceptance AND completed identity review, in either order. This
    is what stops a selfie approval from issuing an invitation on its own.
    """
    r = readiness(reg)
    if r["ready"]:
        return True, None
    return False, " ".join(r["blockers"])
