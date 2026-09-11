from flask import render_template, request, redirect, url_for, jsonify, abort, flash
import requests as _http

from db import (lms_get_module, lms_get_quiz, lms_get_questions,
                lms_save_quiz, lms_save_quiz_questions, lms_publish_quiz,
                lms_toggle_quiz_lock, lms_get_progress,
                lms_get_files, lms_start_attempt, lms_record_tab_switch,
                lms_submit_quiz, lms_get_attempt, lms_get_user_attempt,
                lms_get_wrong_questions, lms_update_progress)

from . import lms_bp
from ._shared import (_uid, _role, _is_instructor, _is_trainee, _module_content_text,
                       _ai_generate_quiz, _check_completion, _owns_module,
                       _module_access, _material_complete,
                       AI_PROVIDER, GROQ_API_KEY, GROQ_MODEL, LM_STUDIO_URL, LM_STUDIO_MODEL)


# Quiz management

@lms_bp.route('/lms/modules/<int:module_id>/quiz', methods=['GET', 'POST'])
def quiz_manage(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    mod       = lms_get_module(module_id)
    if not _owns_module(mod):
        abort(403)
    quiz      = lms_get_quiz(module_id=module_id)
    questions = lms_get_questions(quiz['id']) if quiz else []

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_meta':
            title   = request.form.get('title', (mod['title'] + ' Quiz')).strip()
            desc    = request.form.get('description', '').strip()
            t_limit = int(request.form.get('time_limit', 30))
            passing = int(request.form.get('passing_score', 70))
            lms_save_quiz(module_id, title, desc, t_limit, passing)
            quiz      = lms_get_quiz(module_id=module_id)
            questions = lms_get_questions(quiz['id'])

        elif action == 'save_questions' and quiz:
            q_texts = request.form.getlist('q_text[]')
            q_types = request.form.getlist('q_type[]')
            qs = []
            for i, text in enumerate(q_texts):
                q_type = q_types[i] if i < len(q_types) else "multiple_choice"
                if not text.strip():
                    continue
                if q_type == "multiple_choice":
                    choice_texts = request.form.getlist(f'c_text_{i}[]')
                    correct_idx  = request.form.get(f'c_correct_{i}', '0')
                    choices = [{"text": ct, "is_correct": str(j) == correct_idx}
                               for j, ct in enumerate(choice_texts) if ct.strip()]
                    if choices:
                        qs.append({"text": text.strip(), "type": "multiple_choice",
                                   "points": 1, "choices": choices})
                else:
                    correct_answer = request.form.get(f'q_correct_{i}', '').strip()
                    if q_type == 'essay' or correct_answer:
                        qs.append({"text": text.strip(), "type": q_type,
                                   "points": 1,
                                   "correct_answer": correct_answer if q_type != 'essay' else None,
                                   "choices": []})
            lms_save_quiz_questions(quiz['id'], qs)
            questions = lms_get_questions(quiz['id'])

        elif action == 'publish' and quiz:
            lms_publish_quiz(quiz['id'], True)
            quiz = lms_get_quiz(module_id=module_id)

        elif action == 'unpublish' and quiz:
            lms_publish_quiz(quiz['id'], False)
            quiz = lms_get_quiz(module_id=module_id)

        elif action == 'lock' and quiz:
            lms_toggle_quiz_lock(quiz['id'], True)
            quiz = lms_get_quiz(module_id=module_id)

        elif action == 'unlock' and quiz:
            lms_toggle_quiz_lock(quiz['id'], False)
            quiz = lms_get_quiz(module_id=module_id)

        return redirect(url_for('lms.quiz_manage', module_id=module_id))

    return render_template('lms/quiz_manage.html', mod=mod, quiz=quiz, questions=questions)


@lms_bp.route('/lms/modules/<int:module_id>/quiz/generate', methods=['POST'])
def quiz_generate(module_id):
    if not _uid() or not _is_instructor():
        return jsonify(error="Unauthorized"), 403
    mod   = lms_get_module(module_id)
    if not _owns_module(mod):
        return jsonify(error="Unauthorized"), 403
    files = lms_get_files(module_id)

    if not files:
        return jsonify(error="No files uploaded to this module. Upload a PDF, DOCX, or TXT file first, then try again."), 400

    readable_exts = {'pdf', 'docx', 'txt'}
    readable = [f for f in files if f['original_name'].rsplit('.', 1)[-1].lower() in readable_exts]
    if not readable:
        types = ', '.join(sorted({f['original_name'].rsplit('.',1)[-1].lower() for f in files}))
        return jsonify(error=f"No readable files found (uploaded: {types}). AI generation requires a PDF, DOCX, or TXT file — videos and images cannot be read."), 400

    content_text = _module_content_text(module_id)
    if not content_text.strip():
        return jsonify(error="Could not extract text from the uploaded files. Make sure the PDF or DOCX has selectable text — scanned image pages (photos or picture-only PDFs) can't be read."), 400

    try:
        data = request.get_json() or {}
        num_questions = data.get('num_questions', 10)
        num_questions = max(1, min(int(num_questions), 50))
        questions = _ai_generate_quiz(content_text, mod['title'], num_questions)
        return jsonify(questions=questions)
    except Exception as e:
        return jsonify(error=f"AI generation failed: {e}"), 500


def _quiz_locked_reason(uid, module_id, quiz):
    """None if the trainee may take this quiz, otherwise a flash message
    explaining why not (module locked/not yet reached, quiz locked by the
    trainer, or the module's PDF material isn't 100% viewed yet)."""
    unlocked, _mods, _pm, _idx = _module_access(uid, module_id)
    if not unlocked:
        return 'This module is locked. Complete the previous module, or ask your trainer to unlock it.'
    if quiz.get('is_locked'):
        return 'This quiz has been locked by your trainer.'
    prog = lms_get_progress(uid, module_id)
    if not _material_complete(module_id, prog):
        return 'Finish viewing the module material before starting the quiz.'
    return None


@lms_bp.route('/lms/learn/<int:module_id>/quiz')
def quiz_take(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod  = lms_get_module(module_id)
    quiz = lms_get_quiz(module_id=module_id)
    if not quiz or not quiz['is_published']:
        abort(404)
    uid     = _uid()
    if _is_trainee():
        reason = _quiz_locked_reason(uid, module_id, quiz)
        if reason:
            flash(reason, 'warning')
            return redirect(url_for('lms.learn_module', module_id=module_id))
    attempt_id = lms_start_attempt(uid, quiz['id'])
    questions  = lms_get_questions(quiz['id'])
    return render_template('lms/quiz_take.html', mod=mod, quiz=quiz,
                           questions=questions, attempt_id=attempt_id)


@lms_bp.route('/lms/learn/<int:module_id>/quiz/submit', methods=['POST'])
def quiz_submit(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    attempt_id = int(request.form.get('attempt_id', 0))
    attempt    = lms_get_attempt(attempt_id)
    if not attempt or attempt['user_id'] != _uid():
        abort(403)
    if _is_trainee():
        quiz_row = lms_get_quiz(quiz_id=attempt['quiz_id'])
        if quiz_row and _quiz_locked_reason(_uid(), module_id, quiz_row):
            abort(403)
    answers = {k[2:]: v for k, v in request.form.items() if k.startswith('q_')}
    score   = lms_submit_quiz(attempt_id, answers)
    quiz    = lms_get_quiz(module_id=module_id)
    passed  = score >= quiz['passing_score']
    lms_update_progress(_uid(), module_id, quiz_score=score, quiz_passed=passed)
    _check_completion(_uid(), module_id)
    return redirect(url_for('lms.learn_module', module_id=module_id))


@lms_bp.route('/lms/learn/<int:module_id>/quiz/tabswitch', methods=['POST'])
def quiz_tabswitch(module_id):
    if not _uid():
        return jsonify(ok=False), 403
    data = request.get_json() or {}
    aid  = data.get('attempt_id')
    if aid:
        lms_record_tab_switch(int(aid))
    return jsonify(ok=True)


@lms_bp.route('/lms/learn/<int:module_id>/quiz/hints')
def quiz_hints(module_id):
    uid = _uid()
    role = _role()
    is_trainee = _is_trainee()
    if not uid or not is_trainee:
        return jsonify(error=f"Unauthorized (uid={uid}, role={role}, is_trainee={is_trainee})"), 403
    quiz = lms_get_quiz(module_id=module_id)
    if not quiz:
        return jsonify(error="No quiz"), 404
    attempt = lms_get_user_attempt(uid, quiz['id'])
    if not attempt:
        return jsonify(error=f"No quiz attempt found for quiz {quiz['id']}"), 400
    if attempt['score'] >= quiz['passing_score']:
        return jsonify(error=f"Quiz already passed ({attempt['score']}% >= {quiz['passing_score']}%)"), 400
    wrong = lms_get_wrong_questions(attempt['id'])
    mod = lms_get_module(module_id)
    content_text = _module_content_text(module_id)
    if wrong:
        wrong_lines = '\n'.join(
            f"- Q: {w['question_text']}\n  Your answer: {w['given_answer'] or '(none)'}\n  Correct: {w['correct_answer'] or '(unknown)'}"
            for w in wrong
        )
    else:
        wrong_lines = "(No specific wrong answers recorded — general review recommended.)"
    prompt = (
        f'A trainee failed the quiz for the training module "{mod["title"]}" '
        f'with a score of {attempt["score"]}% (passing is {quiz["passing_score"]}%).\n\n'
        f'Questions they answered incorrectly:\n{wrong_lines}\n\n'
        f'Module content summary:\n{content_text[:3000] if content_text else "Not available."}\n\n'
        'Provide 3-5 concise, targeted study hints that will help the trainee understand '
        'the specific concepts they missed. Focus on WHY the correct answers are right, '
        'not just restating facts. Keep each hint to 2-3 sentences. Use numbered list format.'
    )
    try:
        if AI_PROVIDER == "lmstudio":
            resp = _http.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                json={"model": LM_STUDIO_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800, "temperature": 0.5, "stream": False},
                timeout=120,
            )
        else:
            resp = _http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800, "temperature": 0.5},
                timeout=30,
            )
        resp.raise_for_status()
        hints_text = resp.json()["choices"][0]["message"]["content"].strip()
        return jsonify(hints=hints_text)
    except Exception as e:
        return jsonify(error=f"AI unavailable: {str(e)}"), 503
