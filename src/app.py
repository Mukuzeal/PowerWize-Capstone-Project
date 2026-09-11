import os
import secrets
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, session, render_template, jsonify
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from db import init_db
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

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
app.config["UPLOAD_FOLDER"] = os.path.join(base_dir, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

csrf = CSRFProtect(app)

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

csrf.exempt(app.view_functions["payment.webhook"])
csrf.exempt(app.view_functions["upload_validation.api_face_match"])
csrf.exempt(app.view_functions["upload_validation.validate_upload"])

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
init_db()

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
    home_url = {"admin": "/admin", "employee": "/employee", "trainee": "/portal"}.get(
        session.get("user_role"), "/auth")
    return render_template("shared/access_denied.html", home_url=home_url), 403

@app.after_request
def set_charset(response):
    if 'Content-Type' in response.headers:
        ctype = response.headers.get('Content-Type')
        if 'text/html' in ctype and 'charset' not in ctype:
            response.headers['Content-Type'] = ctype + '; charset=utf-8'
    return response

if __name__ == "__main__":
    app.run(debug=True)

