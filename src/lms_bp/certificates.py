from datetime import date

from flask import render_template, redirect, url_for, abort

from db import (lms_get_certificates, lms_get_eligible_for_cert, lms_get_certificate,
                lms_issue_certificate, lms_update_cert_blockchain, audit_log)
from qr_gen import generate_certificate_qr

from . import lms_bp
from ._shared import _uid, _is_instructor


# Certificates (instructor/admin)

@lms_bp.route('/lms/certificates/manage')
def certificates_manage():
    if not _uid() or not _is_instructor():
        abort(403)
    certs    = lms_get_certificates()
    eligible = lms_get_eligible_for_cert()
    return render_template('lms/certificates_manage.html', certs=certs, eligible=eligible)


@lms_bp.route('/lms/certificates/issue/<int:user_id>', methods=['POST'])
def certificate_issue(user_id):
    if not _uid() or not _is_instructor():
        abort(403)
    existing = lms_get_certificate(user_id=user_id)
    if not existing:
        cid, cert_id = lms_issue_certificate(user_id, _uid())
        try:
            from blockchain_utils import store_certificate_hash
            result = store_certificate_hash(cert_id, user_id)
            if result:
                lms_update_cert_blockchain(cert_id, result["tx_hash"], result["token_id"])
        except Exception:
            pass
        audit_log(_uid(), "issue_certificate", "certificate", cert_id,
                  f"Issued certificate {cert_id} to user {user_id}")
    return redirect(url_for('lms.certificates_manage'))


@lms_bp.route('/lms/certificates')
def certificates():
    if not _uid():
        return redirect(url_for('auth.auth'))
    cert = lms_get_certificate(user_id=_uid())
    cert_status = None
    if cert and cert.get('expires_at'):
        today     = date.today()
        exp       = cert['expires_at']
        days_left = (exp - today).days
        if days_left < 0:
            cert_status = 'expired'
        elif days_left <= 180:
            cert_status = 'expiring'
        else:
            cert_status = 'valid'
    if cert:
        try:
            tx_hash = cert.get('tx_hash')
            qr_path = generate_certificate_qr(cert['cert_id'], tx_hash)
            cert['qr_code'] = qr_path
        except Exception as e:
            print(f"QR generation failed: {e}")
    return render_template('lms/certificates.html', cert=cert, cert_status=cert_status)


@lms_bp.route('/lms/certificates/verify/<cert_id>')
def verify_certificate(cert_id):
    cert = lms_get_certificate(cert_id=cert_id)
    if cert:
        try:
            tx_hash = cert.get('tx_hash')
            qr_path = generate_certificate_qr(cert_id, tx_hash)
            cert['qr_code'] = qr_path
        except Exception as e:
            print(f"QR generation failed: {e}")
    return render_template('lms/cert_verify.html', cert=cert)
