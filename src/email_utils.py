import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

EMAIL_CONFIG = {
    "host":      "smtp.gmail.com",
    "port":      587,
    "user":      os.environ["EMAIL_USER"],
    "password":  os.environ["EMAIL_PASSWORD"],
    "from_name": os.getenv("EMAIL_FROM_NAME", "EnergyWize"),
}


def _send(to_email: str, subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['user']}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(EMAIL_CONFIG["host"], EMAIL_CONFIG["port"]) as server:
        server.starttls()
        server.login(EMAIL_CONFIG["user"], EMAIL_CONFIG["password"])
        server.sendmail(EMAIL_CONFIG["user"], to_email, msg.as_string())


def send_password_reset_email(to_email, full_name, token, base_url):
    reset_link = f"{base_url.rstrip('/')}/reset-password/{token}"
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#0D3B27;padding:28px 32px;text-align:center">
    <span style="display:inline-block;background:#D4A72A;border-radius:8px;padding:8px 16px;font-size:22px;font-weight:700;color:#0D3B27">E</span>
    <h1 style="color:#fff;font-size:22px;margin:12px 0 0">Energy<span style="color:#D4A72A">Wize</span></h1>
  </div>
  <div style="padding:32px">
    <h2 style="color:#0D3B27;font-size:20px;margin:0 0 16px">Reset Your Password</h2>
    <p style="color:#374151;line-height:1.7;margin:0 0 12px">Dear <strong>{full_name}</strong>,</p>
    <p style="color:#374151;line-height:1.7;margin:0 0 20px">
      We received a request to reset your EnergyWize password. Click the button below to set a new password.
      This link expires in <strong>1 hour</strong>.
    </p>
    <div style="text-align:center;margin:28px 0">
      <a href="{reset_link}"
         style="background:#16583C;color:#fff;text-decoration:none;padding:13px 32px;border-radius:8px;font-size:15px;font-weight:600;display:inline-block">
        Reset Password &rarr;
      </a>
    </div>
    <p style="color:#6B7280;font-size:12px;line-height:1.6;margin:0 0 8px">
      If you did not request a password reset, you can safely ignore this email. Your password will not change.
    </p>
    <p style="color:#9CA3AF;font-size:11px;word-break:break-all;margin:0">
      Or copy: {reset_link}
    </p>
  </div>
  <div style="background:#F3F4F6;padding:16px 32px;text-align:center">
    <p style="color:#9CA3AF;font-size:11px;margin:0">&copy; 2026 EnergyWize &middot; DOE Training Program</p>
  </div>
</div>
</body>
</html>"""
    _send(to_email, "Reset Your EnergyWize Password", html)


def send_acceptance_email(to_email, full_name, token, is_qualified, base_url):
    account_link = f"{base_url.rstrip('/')}/create-account/{token}"

    unqualified_notice = ""
    if not is_qualified:
        unqualified_notice = """
        <div style="background:#FEF9C3;border:1px solid #D97706;border-radius:8px;padding:16px 20px;margin:20px 0">
          <p style="font-weight:600;color:#92400E;margin:0 0 8px">&#9888; Qualification Notice</p>
          <p style="color:#78350F;margin:0;line-height:1.7;font-size:14px">
            You do not currently meet all required qualifications for this training.
            However, you are still welcome to participate.<br><br>
            The training certificate carries an approximate validity of <strong>3 years</strong>,
            giving you time to meet the requirements. You must comply with
            <strong>Department of Energy (DOE)</strong> requirements before applying
            for official certification.
          </p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#0D3B27;padding:28px 32px;text-align:center">
    <span style="display:inline-block;background:#D4A72A;border-radius:8px;padding:8px 16px;font-size:22px;font-weight:700;color:#0D3B27">E</span>
    <h1 style="color:#fff;font-size:22px;margin:12px 0 0">Energy<span style="color:#D4A72A">Wize</span></h1>
  </div>
  <div style="padding:32px">
    <h2 style="color:#0D3B27;font-size:20px;margin:0 0 16px">Registration Accepted!</h2>
    <p style="color:#374151;line-height:1.7;margin:0 0 12px">Dear <strong>{full_name}</strong>,</p>
    <p style="color:#374151;line-height:1.7;margin:0 0 16px">
      We are pleased to inform you that your registration has been <strong>accepted</strong>.
      Click the button below to create your EnergyWize account and access your training dashboard.
    </p>
    {unqualified_notice}
    <div style="text-align:center;margin:28px 0">
      <a href="{account_link}"
         style="background:#16583C;color:#fff;text-decoration:none;padding:13px 32px;border-radius:8px;font-size:15px;font-weight:600;display:inline-block">
        Create Your Account &rarr;
      </a>
    </div>
    <p style="color:#6B7280;font-size:12px;line-height:1.6;margin:0 0 8px">
      This link expires in <strong>7 days</strong>. If you did not apply, please ignore this email.
    </p>
    <p style="color:#9CA3AF;font-size:11px;word-break:break-all;margin:0">
      Or copy: {account_link}
    </p>
  </div>
  <div style="background:#F3F4F6;padding:16px 32px;text-align:center">
    <p style="color:#9CA3AF;font-size:11px;margin:0">&copy; 2026 EnergyWize &middot; DOE Training Program</p>
  </div>
</div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your EnergyWize Registration Has Been Accepted"
    msg["From"]    = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['user']}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(EMAIL_CONFIG["host"], EMAIL_CONFIG["port"]) as server:
        server.starttls()
        server.login(EMAIL_CONFIG["user"], EMAIL_CONFIG["password"])
        server.sendmail(EMAIL_CONFIG["user"], to_email, msg.as_string())
