import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from db import init_db
from auth import auth_bp
from admin import admin_bp
from employee_bp import employee_bp
from registration import registration_bp
from onboarding import onboarding_bp
from payment_bp import payment_bp
from solar_bp import solar_bp
from lms_bp import lms_bp

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(base_dir, "templates"), static_folder=os.path.join(base_dir, "static"))
app.config['JSON_SORT_KEYS'] = False
app.jinja_env.add_extension('jinja2.ext.i18n')
app.secret_key = os.getenv("SECRET_KEY", "energywize-secret-2026")
app.config["UPLOAD_FOLDER"] = os.path.join(base_dir, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(solar_bp)
app.register_blueprint(lms_bp)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
init_db()

@app.after_request
def set_charset(response):
    if 'Content-Type' in response.headers:
        ctype = response.headers.get('Content-Type')
        if 'text/html' in ctype and 'charset' not in ctype:
            response.headers['Content-Type'] = ctype + '; charset=utf-8'
    return response

if __name__ == "__main__":
    app.run(debug=True)

