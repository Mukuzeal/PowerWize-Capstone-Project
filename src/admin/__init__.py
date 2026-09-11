from flask import Blueprint, session, redirect, abort

admin_bp = Blueprint("admin", __name__)


def require_admin():
    """None if the caller may proceed; otherwise the response to return.
    Not logged in -> send to login. Logged in as the wrong role -> 403,
    so the user sees "you don't have access" instead of being silently
    bounced back to the login page as if they'd never signed in."""
    if not session.get("user_id"):
        return redirect("/auth")
    if session.get("user_role") != "admin":
        abort(403)
    return None


from . import dashboard      # noqa: E402,F401
from . import users          # noqa: E402,F401
from . import registrations  # noqa: E402,F401
from . import analytics      # noqa: E402,F401
from . import exports        # noqa: E402,F401
