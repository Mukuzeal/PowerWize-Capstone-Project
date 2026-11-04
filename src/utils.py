import os
import uuid
from flask import request, current_app, session
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}

# Filenames this browser session actually uploaded. A multi-step form that
# fails validation re-renders with `<field>_existing` hidden inputs so the
# user doesn't re-pick every file — but that value is client-supplied, so
# without this allowlist anyone could post
# `valid_id_existing=<someone else's file>` and attach a stranger's ID to
# their own registration. Membership here is the ownership proof.
_SESSION_KEY = "uploaded_files"


def allowed_file(filename, pdf_only=False):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext == "pdf" if pdf_only else ext in ALLOWED_EXTENSIONS


def remember_upload(name, field=None):
    """Record a filename this session may reference later, bound to the field
    it was uploaded for.

    Binding the field matters: without it a session could post its own valid
    ID back as `photo_id_existing`, so one document would stand in for a
    different required document type.
    """
    owned = session.get(_SESSION_KEY) or []
    entry = f"{field or ''}:{name}"
    if entry not in owned:
        owned.append(entry)
        # Bounded so a scripted client can't grow the session cookie forever;
        # far more than any one registration needs.
        session[_SESSION_KEY] = owned[-40:]
    return name


def owns_upload(name, field=None):
    if not name:
        return False
    return f"{field or ''}:{name}" in (session.get(_SESSION_KEY) or [])


def save_file(field_name, pdf_only=False):
    f = request.files.get(field_name)
    if f and f.filename and allowed_file(f.filename, pdf_only):
        # Always random: the old `<uid>_<role>_<First>_<Last>_<field>.<ext>`
        # scheme was derivable from the registrant's name, and two people
        # sharing a name silently overwrote each other's documents.
        ext = secure_filename(f.filename).rsplit(".", 1)[-1].lower()
        name = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        return remember_upload(name, field_name)
    existing = request.form.get(f"{field_name}_existing", "").strip()
    return existing if owns_upload(existing, field_name) else None


def check_required(**kwargs):
    return [f"{label} is required." for label, val in kwargs.items() if not val]


def base_url():
    fixed = os.getenv("APP_BASE_URL")
    if fixed:
        return fixed.rstrip("/") + "/"
    return request.host_url
