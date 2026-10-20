from flask import Blueprint

from permissions import require

admin_bp = Blueprint("admin", __name__)


def require_admin():
    """Guard for the admin console itself.

    Kept as a named helper because most of this package only needs "may this
    person be on /admin at all"; anything narrower (creating users, reviewing
    registrations, exporting reports) calls require(<capability>) directly so
    the permission table in permissions.py stays the single source of truth.
    """
    return require("view_admin_console")


from . import dashboard      # noqa: E402,F401
from . import users          # noqa: E402,F401
from . import registrations  # noqa: E402,F401
from . import analytics      # noqa: E402,F401
from . import exports        # noqa: E402,F401
from . import corporate      # noqa: E402,F401
from . import discounts      # noqa: E402,F401
