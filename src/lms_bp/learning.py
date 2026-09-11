from flask import render_template, request, redirect, url_for, jsonify, abort, flash

from db import (lms_get_modules_for_trainee, lms_get_progress, lms_get_module,
                lms_get_files, lms_get_quiz, lms_get_exam, lms_get_user_attempt,
                lms_get_user_exam_submission, get_user_feedback, lms_update_progress,
                lms_get_module_requirements, save_feedback, lms_update_material_pct)

from . import lms_bp
from ._shared import (_uid, _is_trainee, _module_content_text, _ai_module_chat,
                      _progress_steps, _module_access, _module_unlocked, _check_completion)


# ── TRAINEE ROUTES ────────────────────────────────────────────────────────────

@lms_bp.route('/lms/learn')
def learn():
    if not _uid():
        return redirect(url_for('auth.auth'))
    mods         = lms_get_modules_for_trainee(_uid(), published_only=True)
    progress_list = lms_get_progress(_uid())
    prog_map     = {p['module_id']: p for p in progress_list}
    reqs         = lms_get_module_requirements([m['id'] for m in mods])
    steps_map    = {m['id']: _progress_steps(prog_map.get(m['id']), reqs.get(m['id']))
                    for m in mods}
    unlocked_map = {m['id']: _module_unlocked(mods, prog_map, i) for i, m in enumerate(mods)}
    total        = len(mods)
    completed    = sum(1 for m in mods if prog_map.get(m['id'], {}).get('completed'))
    pct          = round(completed / total * 100) if total else 0
    return render_template('lms/learn.html', modules=mods, prog_map=prog_map,
                           steps_map=steps_map, unlocked_map=unlocked_map,
                           completed=completed, total=total, pct=pct)


@lms_bp.route('/lms/learn/<int:module_id>')
def learn_module(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod = lms_get_module(module_id)
    if not mod or not mod['is_published']:
        abort(404)
    uid = _uid()
    if _is_trainee():
        unlocked, _mods, _pm, _idx = _module_access(uid, module_id)
        if not unlocked:
            flash('This module is locked. Complete the previous module, or ask your trainer to unlock it.', 'warning')
            return redirect(url_for('lms.learn'))
    files        = lms_get_files(module_id)
    quiz         = lms_get_quiz(module_id=module_id)
    exam         = lms_get_exam(module_id=module_id)
    quiz_attempt = lms_get_user_attempt(uid, quiz['id']) if quiz and quiz['is_published'] else None
    exam_sub     = lms_get_user_exam_submission(uid, exam['id']) if exam else None
    progress     = lms_get_progress(uid, module_id)
    my_feedback  = get_user_feedback(uid, module_id) if _is_trainee() else None
    lms_update_progress(uid, module_id)
    _check_completion(uid, module_id)
    progress     = lms_get_progress(uid, module_id)
    material_pct = (progress or {}).get('material_pct') or 0
    has_pdf      = any(f.get('file_type') == 'pdf' for f in files)
    quiz_needs_material = bool(quiz) and has_pdf and material_pct < 100

    # Finishing one module doesn't mean the certificate is ready — that needs
    # every module in the trainee's syllabus, not just this one.
    mods_total = mods_done = 0
    if _is_trainee():
        syllabus = lms_get_modules_for_trainee(uid, published_only=True)
        prog_map = {p['module_id']: p for p in lms_get_progress(uid)}
        mods_total = len(syllabus)
        mods_done  = sum(1 for m in syllabus if prog_map.get(m['id'], {}).get('completed'))
    all_mods_done = mods_total > 0 and mods_done == mods_total

    return render_template('lms/learn_module.html', mod=mod, files=files,
                           quiz=quiz, exam=exam, quiz_attempt=quiz_attempt,
                           exam_sub=exam_sub, progress=progress, my_feedback=my_feedback,
                           material_pct=material_pct, quiz_needs_material=quiz_needs_material,
                           all_mods_done=all_mods_done, mods_total=mods_total, mods_done=mods_done)


@lms_bp.route('/lms/learn/<int:module_id>/material-progress', methods=['POST'])
def material_progress(module_id):
    if not _uid() or not _is_trainee():
        return jsonify(error="Unauthorized"), 403
    data = request.get_json() or {}
    try:
        pct = max(0, min(100, int(data.get('pct', 0))))
    except (TypeError, ValueError):
        return jsonify(error="Invalid percentage"), 400
    lms_update_material_pct(_uid(), module_id, pct)
    _check_completion(_uid(), module_id)
    return jsonify(ok=True)


@lms_bp.route('/lms/progress')
def progress():
    if not _uid():
        return redirect(url_for('auth.auth'))
    uid          = _uid()
    mods         = lms_get_modules_for_trainee(uid, published_only=True)
    progress_list = lms_get_progress(uid)
    prog_map     = {p['module_id']: p for p in progress_list}
    reqs         = lms_get_module_requirements([m['id'] for m in mods])
    steps_map    = {m['id']: _progress_steps(prog_map.get(m['id']), reqs.get(m['id']))
                    for m in mods}
    total        = len(mods)
    completed    = sum(1 for m in mods if prog_map.get(m['id'], {}).get('completed'))
    pct          = round(completed / total * 100) if total else 0
    return render_template('lms/progress.html', modules=mods, prog_map=prog_map,
                           steps_map=steps_map, reqs=reqs,
                           completed=completed, total=total, pct=pct)


# AI chatbot per module

@lms_bp.route('/lms/learn/<int:module_id>/feedback', methods=['POST'])
def submit_feedback(module_id):
    if not _uid() or not _is_trainee():
        return jsonify(error="Unauthorized"), 403
    rating  = request.form.get('rating', '').strip()
    comment = request.form.get('comment', '').strip()
    if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
        return jsonify(error="Rating must be 1–5"), 400
    save_feedback(_uid(), module_id, int(rating), comment or None)
    return redirect(url_for('lms.learn_module', module_id=module_id))


@lms_bp.route('/lms/chat/<int:module_id>/msg', methods=['POST'])
def chat_msg(module_id):
    if not _uid():
        return jsonify(error="Unauthorized"), 403
    mod = lms_get_module(module_id)
    if not mod:
        return jsonify(error="Module not found"), 404
    data     = request.get_json() or {}
    messages = data.get('messages', [])
    user_msg = data.get('user_message', '').strip()
    if not user_msg:
        return jsonify(error="Empty message"), 400
    content_text   = _module_content_text(module_id)
    messages_out   = messages + [{"role": "user", "content": user_msg}]
    try:
        reply = _ai_module_chat(messages_out, mod['title'], content_text)
        return jsonify(text=reply,
                       messages=messages_out + [{"role": "assistant", "content": reply}])
    except Exception as e:
        return jsonify(error=str(e)), 500
