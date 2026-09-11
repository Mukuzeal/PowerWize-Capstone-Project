from datetime import date

from flask import render_template, redirect, url_for, abort, current_app, flash

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
        # The certificate is valid whether or not the chain write lands, so a
        # blockchain failure must not block issuance. It must not be silent
        # either: an un-anchored certificate looks identical in the UI, so the
        # only way anyone learns the write failed is this log line.
        anchored = False
        try:
            from blockchain_utils import store_certificate_hash
            result = store_certificate_hash(cert_id, user_id)
            if result:
                lms_update_cert_blockchain(cert_id, result["tx_hash"], result["token_id"],
                                           anchor_version=result.get("anchor_version", 1))
                anchored = True
            else:
                current_app.logger.warning(
                    "Certificate %s issued but NOT anchored on-chain "
                    "(store_certificate_hash returned None)", cert_id)
        except Exception as e:
            current_app.logger.warning(
                "Certificate %s issued but chain write failed: %s: %s",
                cert_id, type(e).__name__, e)
        audit_log(_uid(), "issue_certificate", "certificate", cert_id,
                  f"Issued certificate {cert_id} to user {user_id} "
                  f"(on-chain: {'yes' if anchored else 'NO'})")
        if anchored:
            flash("Certificate issued and anchored on-chain.", "success")
        else:
            flash("Certificate issued, but the blockchain anchor failed. "
                  "It's marked Off-chain below — use Re-anchor to retry.", "warning")
    return redirect(url_for('lms.certificates_manage'))


@lms_bp.route('/lms/certificates/reanchor/<cert_id>', methods=['POST'])
def certificate_reanchor(cert_id):
    if not _uid() or not _is_instructor():
        abort(403)
    cert = lms_get_certificate(cert_id=cert_id)
    if not cert:
        abort(404)
    if cert.get('tx_hash'):
        flash("This certificate is already anchored on-chain.", "success")
        return redirect(url_for('lms.certificates_manage'))
    try:
        from blockchain_utils import store_certificate_hash
        result = store_certificate_hash(cert_id, cert['user_id'])
        if result:
            lms_update_cert_blockchain(cert_id, result["tx_hash"], result["token_id"],
                                       anchor_version=result.get("anchor_version", 1))
            audit_log(_uid(), "reanchor_certificate", "certificate", cert_id,
                      f"Re-anchored certificate {cert_id} on-chain")
            flash("Certificate successfully anchored on-chain.", "success")
        else:
            flash("Re-anchor attempt failed again — still Off-chain.", "warning")
    except Exception as e:
        current_app.logger.warning(
            "Certificate %s re-anchor failed: %s: %s", cert_id, type(e).__name__, e)
        flash("Re-anchor attempt failed again — still Off-chain.", "warning")
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
    chain = None
    if cert:
        try:
            tx_hash = cert.get('tx_hash')
            qr_path = generate_certificate_qr(cert_id, tx_hash)
            cert['qr_code'] = qr_path
        except Exception as e:
            print(f"QR generation failed: {e}")

        # This page used to print the stored tx_hash and assert "Recorded on
        # Polygon" without ever asking the chain. Now it actually checks, so
        # the badge reflects the blockchain rather than the database.
        if cert.get('tx_hash'):
            if (cert.get('anchor_version') or 1) >= 2:
                from blockchain import verify_anchor, compute_anchor
                chain = verify_anchor(cert['tx_hash'], 'certificate', cert)
                # A minted certificate carries its anchor inside the token's
                # on-chain metadata. Reading it back from the contract proves
                # the token itself matches the record, not just that some
                # transaction once mentioned it.
                token_id = cert.get('blockchain_token')
                if token_id and str(token_id).isdigit():
                    try:
                        from blockchain_utils import read_token_anchor
                        on_chain, meta = read_token_anchor(token_id)
                        chain['token_id'] = token_id
                        chain['token_metadata'] = meta
                        if on_chain:
                            expected = compute_anchor('certificate', cert)
                            chain['token_anchor_ok'] = (on_chain.lower() == expected.lower())
                            if not chain['token_anchor_ok']:
                                chain['verified'] = False
                                chain['reason'] = ("The token's on-chain record does not match "
                                                   "this certificate — it has been altered.")
                            else:
                                chain['reason'] = ("Verified on Polygon — tokenised certificate, "
                                                   "unchanged since it was issued.")
                    except Exception as e:
                        chain['token_error'] = f"{type(e).__name__}: {e}"
            else:
                from blockchain import verify_hash_on_chain
                import hashlib
                legacy = hashlib.sha256(
                    f"{cert_id}:{cert['user_id']}".encode()).hexdigest()
                chain = verify_hash_on_chain(cert['tx_hash'], legacy)
                chain['legacy'] = True
    import os
    return render_template('lms/cert_verify.html', cert=cert, chain=chain,
                           contract_address=os.getenv('NFT_CONTRACT_ADDRESS', ''))
