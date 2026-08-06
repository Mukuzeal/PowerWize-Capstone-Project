from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

from . import dashboard      # noqa: E402,F401
from . import users          # noqa: E402,F401
from . import registrations  # noqa: E402,F401
from . import analytics      # noqa: E402,F401
from . import exports        # noqa: E402,F401
