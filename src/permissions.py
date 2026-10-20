"""One permission map for every role check in the app.

Roles are stored in `users.role` and mirrored into `session['user_role']`.
`employee` is the stored value for what the UI calls a **Trainer** — the label
changed, the value never did, so existing accounts and routes keep working.

Every guard in the app resolves through `can()` rather than comparing role
strings inline, so a capability moves between roles by editing this table and
nothing else. Templates get `can()` and `role_label()` as Jinja globals (see
app.py), so a hidden button and the route behind it can never disagree.
"""
from flask import session, redirect, abort

ADMIN      = "admin"
SUPER_USER = "super_user"
SECRETARY  = "secretary"
TRAINER    = "employee"   # stored value; displayed as "Trainer"
TRAINEE    = "trainee"

VALID_ROLES = (ADMIN, SUPER_USER, SECRETARY, TRAINER, TRAINEE)

ROLE_LABELS = {
    ADMIN:      "Admin",
    SUPER_USER: "Super User",
    SECRETARY:  "Secretary",
    TRAINER:    "Trainer",
    TRAINEE:    "Trainee",
}

# Roles that work inside the staff consoles rather than the trainee portal.
# Used for "is this person staff at all" questions (portal redirects, receipt
# disclosure) where no finer capability applies.
STAFF_ROLES = (ADMIN, SUPER_USER, SECRETARY, TRAINER)

# Roles whose home is /admin. A Trainer's console is /employee instead.
ADMIN_CONSOLE_ROLES = (ADMIN, SUPER_USER, SECRETARY)

CAPABILITIES = {
    # Staff consoles
    "view_admin_console":   {ADMIN, SUPER_USER, SECRETARY},
    "view_reports":         {ADMIN, SUPER_USER, SECRETARY},

    # User management — Admin only; Super User is explicitly an Admin *minus*
    # the ability to mint or remove accounts.
    "manage_users":         {ADMIN},

    # Registrations and the batch schedule they are booked against
    "review_registrations": {ADMIN, SUPER_USER, SECRETARY},
    "manage_schedules":     {ADMIN, SUPER_USER, SECRETARY},

    # LMS. `manage_modules` is the instructor capability (create/edit/publish
    # your own); `manage_any_module` is the override that lets Admin act on
    # — and delete — a module someone else owns.
    "manage_modules":       {ADMIN, SUPER_USER, SECRETARY, TRAINER},
    "manage_any_module":    {ADMIN},

    # PV consultations (solar admin review). Secretary is deliberately absent.
    "review_solar":         {ADMIN, SUPER_USER, TRAINER},

    # Billing
    "corporate_payments":   {ADMIN, SUPER_USER, SECRETARY},
    "discount_codes":       {ADMIN, SUPER_USER, SECRETARY},
}


def can(role, capability):
    """True if `role` holds `capability`. An unknown capability is False rather
    than an exception — a typo in a template must hide the button, not blank
    the page."""
    return role in CAPABILITIES.get(capability, ())


def current_role():
    return session.get("user_role", "")


def current_can(capability):
    """`can()` for whoever is logged in. This is the Jinja global."""
    return can(current_role(), capability)


def role_label(role):
    return ROLE_LABELS.get(role, (role or "").replace("_", " ").title())


def is_staff(role=None):
    return (role if role is not None else current_role()) in STAFF_ROLES


def home_url_for(role):
    """Where a role belongs after login, and where the 403 page offers to send
    them back to."""
    if role in ADMIN_CONSOLE_ROLES:
        return "/admin"
    if role == TRAINER:
        return "/employee"
    if role == TRAINEE:
        return "/portal"
    return "/auth"


def require(capability):
    """None if the caller may proceed; otherwise the response to return.

    Not logged in -> send to login. Logged in without the capability -> 403,
    so the user sees "you don't have access" instead of being silently bounced
    back to the login page as if they'd never signed in.
    """
    if not session.get("user_id"):
        return redirect("/auth")
    if not current_can(capability):
        abort(403)
    return None
