import os
import secrets
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, session, render_template, jsonify, abort
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from db import init_db
from permissions import current_can, role_label, home_url_for
from rag.embeddings import warm as warm_embedder
from auth import auth_bp
from admin import admin_bp
from employee_bp import employee_bp
from registration import registration_bp
from site_bp import site_bp
from onboarding import onboarding_bp
from payment_bp import payment_bp
from solar_bp import solar_bp
from lms_bp import lms_bp
from upload_validation import validation_bp
from company_bp import company_bp
from corporate_public_bp import corporate_public_bp
from classes_bp import classes_bp

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Where uploaded files are written. Kept separate from base_dir because a
# deployed tree is not a safe place to store them: on Azure App Service the
# code lives in /home/site/wwwroot and is replaced wholesale on every
# deployment, while /home itself is the persistent mount — so hosting sets
# POWERWIZE_DATA_DIR=/home/data and the uploads outlive a redeploy. Defaults
# to base_dir, so a local run behaves exactly as it always has.
data_dir = os.getenv("POWERWIZE_DATA_DIR", base_dir)
app = Flask(__name__, template_folder=os.path.join(base_dir, "templates"), static_folder=os.path.join(base_dir, "static"))
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config['JSON_SORT_KEYS'] = False
app.jinja_env.add_extension('jinja2.ext.i18n')
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_hex(32)
    print("[WARNING] SECRET_KEY not set in environment — using a random key for this process. "
          "Set SECRET_KEY to keep sessions valid across restarts.")
app.secret_key = secret_key
# Registration documents (IDs, selfies, resumes) live OUTSIDE static/, like
# the LMS material and exam submissions already do — anything under static/ is
# served by Flask with no authentication, so an upload folder in there is
# world-readable no matter what the admin routes check. Served only through
# admin.registration_document / admin_registration_selfie, both behind
# require("review_registrations").
app.config["UPLOAD_FOLDER"] = os.path.join(data_dir, "uploads", "registrations")
# Where documents lived before Phase 0. Still read — but ONLY by the
# permission-gated admin routes, never by Flask's static handler (see the
# /static/uploads/ block below). Without this fallback every registration
# submitted before the migration would 404 in the review queue, breaking
# approvals for existing applicants. Remove once the migration has run and
# been verified.
app.config["LEGACY_UPLOAD_FOLDER"] = os.path.join(base_dir, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

csrf = CSRFProtect(app)

# Templates gate on the same permission table the routes do, so a button that
# is hidden and the route behind it can never disagree about who may act.
app.jinja_env.globals["can"] = current_can
app.jinja_env.globals["role_label"] = role_label

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(site_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(solar_bp)
app.register_blueprint(lms_bp)
app.register_blueprint(validation_bp)
app.register_blueprint(company_bp)
app.register_blueprint(corporate_public_bp)
app.register_blueprint(classes_bp)

csrf.exempt(app.view_functions["payment.webhook"])
csrf.exempt(app.view_functions["upload_validation.api_face_match"])
csrf.exempt(app.view_functions["upload_validation.validate_upload"])
# Not a "skip CSRF" exemption like the 3 above — navigator.sendBeacon() can't
# set a custom header, so this view reads the token from the JSON body and
# validates it manually (see solar_chat_cancel). Exempted only from
# Flask-WTF's automatic header/form-only check.
csrf.exempt(app.view_functions["solar.solar_chat_cancel"])

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
init_db()

# Move the fastembed/ONNX model load off the first Solara request and into boot
# — it is a per-process cost, so otherwise the first user of every gunicorn
# worker pays it. See rag.embeddings.warm().
warm_embedder()

@app.route("/static/uploads/<path:filename>")
def _blocked_legacy_uploads(filename):
    """Registration documents are never public.

    New uploads go to uploads/registrations/ (see UPLOAD_FOLDER above), but
    files written before that change are still physically present under
    static/, where Flask's static handler would happily serve them to anyone.
    This rule is more specific than the built-in /static/<path:filename>, so
    it wins and closes the hole immediately — before, and independently of,
    the file migration in scripts/migrate_registration_uploads.py.

    Kept permanently: it costs nothing and stops a future upload path from
    silently re-publishing identity documents.
    """
    abort(404)


@app.errorhandler(403)
def forbidden(e):
    # Real browser navigations always send an Accept header that includes
    # text/html; a missing/empty Accept (seen from some HTTP clients, not
    # real browsers) is treated the same way rather than defaulting to JSON.
    accept = request.accept_mimetypes
    wants_json = (request.headers.get("X-Requested-With") == "XMLHttpRequest"
                 or (len(accept) > 0 and "text/html" not in accept))
    if wants_json:
        return jsonify(error="Forbidden"), 403
    home_url = home_url_for(session.get("user_role"))
    return render_template("shared/access_denied.html", home_url=home_url), 403

@app.after_request
def set_charset(response):
    if 'Content-Type' in response.headers:
        ctype = response.headers.get('Content-Type')
        if 'text/html' in ctype and 'charset' not in ctype:
            response.headers['Content-Type'] = ctype + '; charset=utf-8'
    return response

if __name__ == "__main__":
    # threaded=True matters beyond raw throughput: solar_bp's cancel endpoint
    # (Stop button, refresh/close beacon) has to reach the server WHILE a slow
    # LM Studio call is still being read — on the single-threaded default the
    # dev server can't even accept that connection until the blocked request
    # finishes, so cancellation silently can't work at all.
    app.run(debug=True, threaded=True)

