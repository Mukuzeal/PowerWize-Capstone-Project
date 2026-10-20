import os
import secrets

from flask import render_template, request, redirect, url_for, jsonify, abort, flash

from db import (lms_get_module, lms_get_exam, lms_get_exam_questions,
                lms_save_exam, lms_save_exam_questions, lms_toggle_exam_lock,
                lms_get_all_submissions, lms_get_exam_submission_detail,
                lms_grade_submission, lms_get_submission_user_module,
                lms_update_progress, lms_get_user_exam_submission,
                lms_submit_exam, lms_submit_exam_answers)

from . import lms_bp
from permissions import can

from ._shared import (_uid, _role, _is_instructor, _is_trainee, _allowed, _owns_module,
                      EXAM_UPLOAD_DIR, ALLOWED_SUBMISSION, _check_completion, _module_access)


# Practical exam management

@lms_bp.route('/lms/modules/<int:module_id>/exam', methods=['GET', 'POST'])
def exam_manage(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    mod  = lms_get_module(module_id)
    if not _owns_module(mod):
        abort(403)
    exam = lms_get_exam(module_id=module_id)
    exam_questions = lms_get_exam_questions(exam['id']) if exam else []
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save_meta':
            title    = request.form.get('title', '').strip()
            instruct = request.form.get('instructions', '').strip()
            criteria = request.form.get('criteria', '').strip()
            camera   = 'requires_camera' in request.form
            if title and instruct:
                lms_save_exam(module_id, title, instruct, criteria, camera)
                exam = lms_get_exam(module_id=module_id)
        elif action == 'save_questions' and exam:
            q_texts = request.form.getlist('eq_text[]')
            q_types = request.form.getlist('eq_type[]')
            qs = []
            for i, text in enumerate(q_texts):
                q_type = q_types[i] if i < len(q_types) else 'essay'
                if not text.strip():
                    continue
                correct_answer = request.form.get(f'eq_correct_{i}', '').strip()
                if q_type != 'essay' and not correct_answer:
                    continue
                qs.append({
                    "text": text.strip(),
                    "type": q_type,
                    "points": 1,
                    "correct_answer": correct_answer if q_type != 'essay' else None
                })
            lms_save_exam_questions(exam['id'], qs)
            exam_questions = lms_get_exam_questions(exam['id'])
        elif action == 'lock' and exam:
            lms_toggle_exam_lock(exam['id'], True)
            exam = lms_get_exam(module_id=module_id)
        elif action == 'unlock' and exam:
            lms_toggle_exam_lock(exam['id'], False)
            exam = lms_get_exam(module_id=module_id)
        return redirect(url_for('lms.exam_manage', module_id=module_id))
    return render_template('lms/exam_manage.html', mod=mod, exam=exam, exam_questions=exam_questions)


# Submissions (instructor)

@lms_bp.route('/lms/submissions')
def submissions():
    if not _uid() or not _is_instructor():
        abort(403)
    inst_id = None if can(_role(), 'manage_any_module') else _uid()
    subs    = lms_get_all_submissions(instructor_id=inst_id)
    return render_template('lms/submissions.html', submissions=subs)


@lms_bp.route('/lms/submissions/<int:sub_id>/answers', methods=['GET'])
def get_submission_answers(sub_id):
    if not _uid() or not _is_instructor():
        abort(403)
    row = lms_get_submission_user_module(sub_id)
    if not row or not _owns_module(lms_get_module(row['module_id'])):
        abort(403)
    submission = lms_get_exam_submission_detail(sub_id)
    if not submission:
        abort(404)
    return jsonify(submission=submission)


@lms_bp.route('/lms/submissions/<int:sub_id>/grade', methods=['POST'])
def grade_submission(sub_id):
    if not _uid() or not _is_instructor():
        abort(403)
    row = lms_get_submission_user_module(sub_id)
    if not row or not _owns_module(lms_get_module(row['module_id'])):
        abort(403)
    grade    = int(request.form.get('grade', 0))
    feedback = request.form.get('feedback', '').strip()
    lms_grade_submission(sub_id, grade, feedback, _uid())

    if row:
        lms_update_progress(row['user_id'], row['module_id'], exam_graded=True, exam_grade=grade)
        _check_completion(row['user_id'], row['module_id'])
    return redirect(url_for('lms.submissions'))


@lms_bp.route('/lms/learn/<int:module_id>/exam', methods=['GET', 'POST'])
def exam_submit_route(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod  = lms_get_module(module_id)
    exam = lms_get_exam(module_id=module_id)
    if not exam:
        abort(404)
    uid = _uid()
    if _is_trainee():
        unlocked, _mods, _pm, _idx = _module_access(uid, module_id)
        if not unlocked or exam.get('is_locked'):
            flash('This practical exam is locked. Ask your trainer to unlock it.', 'warning')
            return redirect(url_for('lms.learn_module', module_id=module_id))
    existing = lms_get_user_exam_submission(uid, exam['id'])
    if existing:
        return redirect(url_for('lms.learn_module', module_id=module_id))
    exam_questions = lms_get_exam_questions(exam['id'])
    if request.method == 'POST':
        file_path = None
        f = request.files.get('submission_file')
        if f and f.filename and _allowed(f.filename, ALLOWED_SUBMISSION):
            ext       = f.filename.rsplit('.', 1)[-1].lower()
            safe_name = f"exam_{exam['id']}_{uid}_{secrets.token_hex(8)}.{ext}"
            f.save(os.path.join(EXAM_UPLOAD_DIR, safe_name))
            file_path = safe_name
        sub_id = lms_submit_exam(uid, exam['id'], file_path)
        answers = {k[3:]: v for k, v in request.form.items() if k.startswith('eq_')}
        if answers:
            lms_submit_exam_answers(sub_id, answers)
        lms_update_progress(uid, module_id)
        return redirect(url_for('lms.learn_module', module_id=module_id))
    return render_template('lms/exam_submit.html', mod=mod, exam=exam, exam_questions=exam_questions)
