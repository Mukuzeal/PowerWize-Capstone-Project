import os
import uuid
from flask import request, current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def allowed_file(filename, pdf_only=False):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext == "pdf" if pdf_only else ext in ALLOWED_EXTENSIONS


def save_file(field_name, pdf_only=False, prefix=None):
    f = request.files.get(field_name)
    if f and f.filename and allowed_file(f.filename, pdf_only):
        ext = secure_filename(f.filename).rsplit(".", 1)[-1]
        if prefix:
            name = f"{prefix}_{field_name}.{ext}"
        else:
            name = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        return name
    existing = request.form.get(f"{field_name}_existing", "").strip()
    return existing or None


def check_required(**kwargs):
    return [f"{label} is required." for label, val in kwargs.items() if not val]
