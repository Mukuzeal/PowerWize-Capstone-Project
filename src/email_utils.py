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


# Mail transport.
#
#   smtp     — real delivery (production)
#   preview  — write the message to outbox/ and return; nothing leaves the host
#   mock     — record in memory only; what tests use
#
# `preview` is the development default so a local run never emails a real
# company contact. Set MAIL_TRANSPORT=smtp deliberately.
VALID_TRANSPORTS = ("preview", "mock", "smtp")
MAIL_TRANSPORT = os.getenv("MAIL_TRANSPORT", "preview").strip().lower()
if MAIL_TRANSPORT not in VALID_TRANSPORTS:
    # Fail loudly rather than guessing. A typo like MAIL_TRANSPORT=smpt must
    # not silently fall back to something that does — or does not — send.
    raise RuntimeError(
        f"MAIL_TRANSPORT={MAIL_TRANSPORT!r} is not valid. "
        f"Use one of: {', '.join(VALID_TRANSPORTS)}.")
_PROJECT_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTBOX_DIR     = os.path.join(_PROJECT_ROOT, "outbox")

# Populated by the mock transport so tests can assert on what WOULD be sent.
SENT_MESSAGES = []


class MailDeliveryError(Exception):
    """Transport-level failure. Raised so callers can record an attempt and
    retry, rather than a send silently appearing to succeed."""


def _render(to_email, subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['user']}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))
    return msg


def _send(to_email: str, subject: str, html: str):
    """Hand the message to the configured transport.

    Returns a short string naming what actually happened, so a caller can
    record "submitted to the mail server" rather than asserting "delivered" —
    SMTP acceptance is not proof of delivery, and nothing here can observe
    the recipient's mailbox.
    """
    msg = _render(to_email, subject, html)

    if MAIL_TRANSPORT == "mock":
        SENT_MESSAGES.append({"to": to_email, "subject": subject, "html": html})
        return "mock"

    if MAIL_TRANSPORT == "preview":
        os.makedirs(OUTBOX_DIR, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in to_email)
        from datetime import datetime as _dt
        path = os.path.join(
            OUTBOX_DIR, f"{_dt.now().strftime('%Y%m%d-%H%M%S-%f')}_{safe}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- To: {to_email}\n     Subject: {subject} -->\n{html}")
        print(f"[mail:preview] {to_email} — {subject} -> {path}")
        return "preview"

    try:
        with smtplib.SMTP(EMAIL_CONFIG["host"], EMAIL_CONFIG["port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["user"], EMAIL_CONFIG["password"])
            server.sendmail(EMAIL_CONFIG["user"], to_email, msg.as_string())
    except Exception as e:
        raise MailDeliveryError(f"{type(e).__name__}: {e}") from e
    return "submitted"


def send_registration_code(to_email, company_name, code):
    from html import escape
    return _send(to_email, 'Your EnergyWize registration verification code',
        '<html><body><h2>Verify your registration email</h2><p>Use this code to register for ' +
        escape(company_name) + ':</p><p style="font-size:28px;letter-spacing:6px"><strong>' +
        escape(code) + '</strong></p><p>This code expires in 10 minutes. '
        'Do not share it. If you did not request it, you can ignore this message.</p></body></html>')


def send_company_registration_link(to_email, company_name, contact_person,
                                   program_label, registration_url, class_code, expires_at):
    from html import escape
    html = f'''<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#173c2b;padding:24px">
      <div style="max-width:600px;margin:auto">
        <h2>Company trainee registration</h2>
        <p>Dear {escape(contact_person)},</p>
        <p>Registration is ready for <strong>{escape(company_name)}</strong>:
           {escape(program_label)}.</p>
        <p>Share this same registration link and class code with all trainees on your company roster.</p>
        <p><a href="{escape(registration_url, quote=True)}">Open company registration</a></p>
        <p>Class code: <strong style="font-size:24px;letter-spacing:3px">{escape(class_code)}</strong></p>
        <p>Each trainee enters this code and their own roster email, then completes their
           registration and uploads their requirements. No email verification code is needed.</p>
        <p>The registration link is valid until {escape(expires_at)}, unless replaced or revoked.</p>
        <p>Staff review the requirements before account invitations and training access.
           Approved, paid trainees can also use the class code to join their training class.</p>
        <p style="word-break:break-all">Registration link: {escape(registration_url)}</p>
        <p>EnergyWize Solutions</p>
      </div></body></html>'''
    return _send(to_email, 'Company trainee registration - EnergyWize', html)


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

    return _send(to_email, "Your EnergyWize Registration Has Been Accepted", html)


def send_corporate_payment_confirmation(to_email, staff_name, rec, items, base_url):
    """Sent to the staff member who raised a corporate invoice, once it is
    paid and every listed trainee has been unlocked."""
    detail_link = f"{base_url.rstrip('/')}/admin/corporate/{rec['id']}"
    amount      = rec["amount_centavos"] / 100
    list_total  = float(rec["list_total_php"] or 0)

    rows = "".join(
        f"<tr><td style=\"padding:8px 12px;border:1px solid #E5E7EB;font-size:13px\">"
        f"{i['fname']} {i['lname']}</td>"
        f"<td style=\"padding:8px 12px;border:1px solid #E5E7EB;font-size:13px;color:#6B7280\">"
        f"{i.get('price_label') or i['training_type']}</td>"
        f"<td style=\"padding:8px 12px;border:1px solid #E5E7EB;font-size:13px;text-align:right\">"
        f"&#8369;{float(i['price_php']):,.2f}</td></tr>"
        for i in items
    )

    override_block = ""
    if rec.get("custom_total_php") is not None:
        override_block = (
            f"<p style=\"background:#FEF9C3;border:1px solid #D97706;border-radius:8px;"
            f"padding:12px 16px;color:#78350F;font-size:13px;line-height:1.6;margin:16px 0\">"
            f"<strong>Price override applied.</strong> List total was "
            f"&#8369;{list_total:,.2f}; charged &#8369;{amount:,.2f}.<br>"
            f"Reason: {rec.get('override_note') or '&mdash;'}</p>"
        )

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px">
<div style="max-width:620px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#0D3B27;padding:28px 32px;text-align:center">
    <span style="display:inline-block;background:#D4A72A;border-radius:8px;padding:8px 16px;font-size:22px;font-weight:700;color:#0D3B27">E</span>
    <h1 style="color:#fff;font-size:22px;margin:12px 0 0">Energy<span style="color:#D4A72A">Wize</span></h1>
  </div>
  <div style="padding:32px">
    <h2 style="color:#0D3B27;font-size:20px;margin:0 0 16px">Corporate Payment Confirmed</h2>
    <p style="color:#374151;line-height:1.7;margin:0 0 12px">Dear <strong>{staff_name}</strong>,</p>
    <p style="color:#374151;line-height:1.7;margin:0 0 16px">
      Invoice <strong>{rec['reference']}</strong> for <strong>{rec['company_name']}</strong>
      has been paid. All {len(items)} listed trainee(s) are now marked paid and can
      proceed to the LMS.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <thead>
        <tr style="background:#F9FAFB">
          <th style="padding:8px 12px;border:1px solid #E5E7EB;text-align:left;font-size:12px;color:#6B7280">Trainee</th>
          <th style="padding:8px 12px;border:1px solid #E5E7EB;text-align:left;font-size:12px;color:#6B7280">Program</th>
          <th style="padding:8px 12px;border:1px solid #E5E7EB;text-align:right;font-size:12px;color:#6B7280">List price</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    {override_block}
    <p style="font-size:15px;color:#0D3B27;font-weight:700;margin:16px 0">
      Amount paid: &#8369;{amount:,.2f}
    </p>
    <div style="text-align:center;margin:28px 0">
      <a href="{detail_link}"
         style="background:#16583C;color:#fff;text-decoration:none;padding:13px 32px;border-radius:8px;font-size:15px;font-weight:600;display:inline-block">
        Open the record &rarr;
      </a>
    </div>
  </div>
  <div style="background:#F3F4F6;padding:16px 32px;text-align:center">
    <p style="color:#9CA3AF;font-size:11px;margin:0">&copy; 2026 EnergyWize &middot; DOE Training Program</p>
  </div>
</div>
</body>
</html>"""
    _send(to_email, f"Corporate payment confirmed - {rec['reference']}", html)


def send_company_correction_notice(to_email, company_name, trainee_name,
                                   correction_note, program_label, base_url):
    """Tell a company contact that one of their nominated trainees must fix
    something.

    Company-safe by construction: the trainee's name, the program, and the
    correction text an admin wrote FOR the applicant. No uploaded document, no
    link to one, no private reviewer note, and no other trainee's details.
    """
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#0D3B27;padding:28px 32px;text-align:center">
    <span style="display:inline-block;background:#D4A72A;border-radius:8px;padding:8px 16px;font-size:22px;font-weight:700;color:#0D3B27">E</span>
    <h1 style="color:#fff;font-size:22px;margin:12px 0 0">Energy<span style="color:#D4A72A">Wize</span></h1>
  </div>
  <div style="padding:32px">
    <p style="margin:0 0 16px">Hello {company_name},</p>
    <p style="margin:0 0 16px;line-height:1.7">
      One of your nominated trainees for <strong>{program_label}</strong> needs to
      correct part of their registration before we can approve it.
    </p>
    <div style="background:#FEF9C3;border:1px solid #D97706;border-radius:8px;padding:16px 20px;margin:20px 0">
      <p style="font-weight:600;color:#92400E;margin:0 0 8px">{trainee_name}</p>
      <p style="color:#78350F;margin:0;line-height:1.7;font-size:14px">{correction_note}</p>
    </div>
    <p style="margin:0 0 16px;line-height:1.7">
      We have contacted them directly as well. They can resubmit using the same
      registration link you shared with them.
    </p>
    <p style="margin:0;line-height:1.7;color:#6B7280;font-size:13px">
      You can check the status of everyone on your roster using the company
      status link EnergyWize sent you.
    </p>
  </div>
</div>
</body>
</html>"""
    return _send(to_email,
                 f"Action needed: {trainee_name} — registration requirements",
                 html)


def send_company_payment_link(to_email, company_name, contact_person, reference,
                              amount_php, trainee_count, pay_url, expires_at):
    """The final company email: one link to settle one invoice.

    Deliberately carries no roster. The payer needs the amount, the reference
    and the link; a forwarded email should not disclose who is enrolled.
    """
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#0D3B27;padding:28px 32px;text-align:center">
    <span style="display:inline-block;background:#D4A72A;border-radius:8px;padding:8px 16px;font-size:22px;font-weight:700;color:#0D3B27">E</span>
    <h1 style="color:#fff;font-size:22px;margin:12px 0 0">Energy<span style="color:#D4A72A">Wize</span></h1>
  </div>
  <div style="padding:32px">
    <p style="margin:0 0 16px">Hello {contact_person},</p>
    <p style="margin:0 0 16px;line-height:1.7">
      All {trainee_count} nominated trainee(s) from <strong>{company_name}</strong>
      have been approved. Your invoice is ready to settle.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:20px 0">
      <tr><td style="padding:8px 0;color:#6B7280">Reference</td>
          <td style="padding:8px 0;text-align:right;font-family:monospace">{reference}</td></tr>
      <tr><td style="padding:8px 0;color:#6B7280">Trainees</td>
          <td style="padding:8px 0;text-align:right">{trainee_count}</td></tr>
      <tr><td style="padding:8px 0;color:#6B7280;border-top:1px solid #E5E7EB">Amount due</td>
          <td style="padding:8px 0;text-align:right;font-weight:700;border-top:1px solid #E5E7EB">PHP {amount_php:,.2f}</td></tr>
    </table>
    <p style="text-align:center;margin:24px 0">
      <a href="{pay_url}" style="display:inline-block;background:#0D3B27;color:#fff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:600">Pay this invoice</a>
    </p>
    <p style="margin:0;line-height:1.7;color:#6B7280;font-size:13px">
      This payment link expires on {expires_at}. Payment is processed by PayMongo —
      EnergyWize never sees your card details.
    </p>
  </div>
</div>
</body>
</html>"""
    return _send(to_email, f"Payment link — {company_name} training invoice {reference}", html)
