import os
import secrets

from flask import render_template, request, redirect, url_for, jsonify, send_file, send_from_directory, abort, flash

from db import (lms_create_module, lms_get_modules, lms_get_module,
                lms_update_module, lms_toggle_publish, lms_delete_module,
                lms_archive_module, lms_restore_module,
                lms_add_file, lms_get_files, lms_get_file, lms_delete_file,
                lms_get_quiz, lms_get_exam, lms_get_questions)

from . import lms_bp
from ._shared import _uid, _role, _is_instructor, _allowed, _owns_module, LMS_UPLOAD_DIR, EXAM_UPLOAD_DIR, ALLOWED_MATERIAL


# ── INSTRUCTOR ROUTES ─────────────────────────────────────────────────────────

@lms_bp.route('/lms/')
@lms_bp.route('/lms/modules')
def modules():
    if not _uid():
        return redirect(url_for('auth.auth'))
    if _is_instructor():
        inst_id = _uid() if _role() != 'admin' else None
        mods = lms_get_modules(instructor_id=inst_id)
        return render_template('lms/modules.html', modules=mods)
    return redirect(url_for('lms.learn'))


@lms_bp.route('/lms/modules/create', methods=['GET', 'POST'])
def module_create():
    if not _uid() or not _is_instructor():
        return redirect(url_for('auth.auth'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        desc  = request.form.get('description', '').strip()
        training_type = request.form.get('training_type', 'training').strip()
        if title:
            mid = lms_create_module(_uid(), title, desc, training_type)
            return redirect(url_for('lms.module_manage', module_id=mid))
    return render_template('lms/module_form.html', module=None)


@lms_bp.route('/lms/modules/<int:module_id>/edit', methods=['GET', 'POST'])
def module_edit(module_id):
    if not _uid() or not _is_instructor():
        return redirect(url_for('auth.auth'))
    mod = lms_get_module(module_id)
    if not mod:
        abort(404)
    if not _owns_module(mod):
        abort(403)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        desc  = request.form.get('description', '').strip()
        training_type = request.form.get('training_type', mod.get('training_type', 'training')).strip()
        if title:
            lms_update_module(module_id, title, desc, training_type)
            return redirect(url_for('lms.module_manage', module_id=module_id))
    return render_template('lms/module_form.html', module=mod)


@lms_bp.route('/lms/modules/<int:module_id>')
def module_manage(module_id):
    if not _uid() or not _is_instructor():
        return redirect(url_for('auth.auth'))
    mod = lms_get_module(module_id)
    if not mod:
        abort(404)
    if not _owns_module(mod):
        abort(403)
    files     = lms_get_files(module_id)
    quiz      = lms_get_quiz(module_id=module_id)
    exam      = lms_get_exam(module_id=module_id)
    questions = lms_get_questions(quiz['id']) if quiz else []
    return render_template('lms/module_manage.html',
                           mod=mod, files=files, quiz=quiz, exam=exam, questions=questions)


@lms_bp.route('/lms/modules/<int:module_id>/publish', methods=['POST'])
def module_publish(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    mod = lms_get_module(module_id)
    if not _owns_module(mod):
        abort(403)
    if mod:
        lms_toggle_publish(module_id, not mod['is_published'])
    return redirect(url_for('lms.module_manage', module_id=module_id))


@lms_bp.route('/lms/modules/<int:module_id>/delete', methods=['POST'])
def module_delete(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    if not _owns_module(lms_get_module(module_id)):
        abort(403)
    mod = lms_get_module(module_id)
    for f in lms_get_files(module_id):
        fp = os.path.join(LMS_UPLOAD_DIR, f['filename'])
        if os.path.exists(fp):
            os.remove(fp)
    lms_delete_module(module_id)
    flash(f'"{mod["title"]}" permanently deleted.', 'success')
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/archive', methods=['POST'])
def module_archive(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    if not _owns_module(lms_get_module(module_id)):
        abort(403)
    mod = lms_get_module(module_id)
    lms_archive_module(module_id)
    flash(f'"{mod["title"]}" archived - trainees can no longer see it.', 'success')
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/restore', methods=['POST'])
def module_restore(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    if not _owns_module(lms_get_module(module_id)):
        abort(403)
    mod = lms_get_module(module_id)
    lms_restore_module(module_id)
    flash(f'"{mod["title"]}" restored - it is live for trainees again.', 'success')
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/delete-archived', methods=['POST'])
def module_delete_archived(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    if not _owns_module(lms_get_module(module_id)):
        abort(403)
    mod = lms_get_module(module_id)
    lms_delete_module(module_id)
    flash(f'"{mod["title"]}" permanently deleted.', 'success')
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


# Files

@lms_bp.route('/lms/modules/<int:module_id>/files/upload', methods=['POST'])
def file_upload(module_id):
    if not _uid() or not _is_instructor():
        return jsonify(error="Unauthorized"), 403
    if not _owns_module(lms_get_module(module_id)):
        return jsonify(error="Unauthorized"), 403
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify(error="No file"), 400
    if not _allowed(f.filename, ALLOWED_MATERIAL):
        return jsonify(error="File type not allowed"), 400
    ext       = f.filename.rsplit('.', 1)[-1].lower()
    safe_name = secrets.token_hex(16) + '.' + ext
    f.save(os.path.join(LMS_UPLOAD_DIR, safe_name))
    size = os.path.getsize(os.path.join(LMS_UPLOAD_DIR, safe_name))
    fid  = lms_add_file(module_id, safe_name, f.filename, ext, size)
    return jsonify(id=fid, name=f.filename, type=ext, size=size)


@lms_bp.route('/lms/modules/<int:module_id>/files/<int:file_id>/delete', methods=['POST'])
def file_delete(module_id, file_id):
    if not _uid() or not _is_instructor():
        abort(403)
    if not _owns_module(lms_get_module(module_id)):
        abort(403)
    f = lms_get_file(file_id)
    if f:
        fp = os.path.join(LMS_UPLOAD_DIR, f['filename'])
        if os.path.exists(fp):
            os.remove(fp)
        lms_delete_file(file_id)
    return redirect(url_for('lms.module_manage', module_id=module_id))


@lms_bp.route('/lms/files/<path:filename>')
def serve_file(filename):
    if not _uid():
        abort(403)
    return send_from_directory(LMS_UPLOAD_DIR, filename)


@lms_bp.route('/lms/exam-files/<path:filename>')
def serve_exam_file(filename):
    if not _uid() or not _is_instructor():
        abort(403)
    return send_from_directory(EXAM_UPLOAD_DIR, filename)
    if not safe or not os.path.exists(safe):
        abort(404)
    return send_file(safe)
