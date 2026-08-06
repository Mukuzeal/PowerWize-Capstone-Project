from flask import Blueprint

lms_bp = Blueprint('lms', __name__)

from . import modules       # noqa: E402,F401
from . import quizzes       # noqa: E402,F401
from . import exams         # noqa: E402,F401
from . import certificates  # noqa: E402,F401
from . import learning      # noqa: E402,F401
