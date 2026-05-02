import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from db import init_db
from auth import auth_bp
from admin import admin_bp
from registration import registration_bp
from onboarding import onboarding_bp
from payment_bp import payment_bp
from solar_bp import solar_bp

app = Flask(__name__)
app.secret_key = "energywize-secret-2026"
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(solar_bp)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
init_db()

if __name__ == "__main__":
    app.run(debug=True)

