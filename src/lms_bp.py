import os, json, secrets
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, jsonify, send_file, send_from_directory, abort)
from qr_gen import generate_certificate_qr
from db import (get_db, dict_cur, save_feedback, get_user_feedback, audit_log, lms_get_wrong_questions,
                lms_create_module, lms_get_modules, lms_get_modules_for_trainee, lms_get_module,
                lms_update_module, lms_toggle_publish, lms_delete_module,
                lms_archive_module, lms_restore_module,
                lms_add_file, lms_get_files, lms_get_file, lms_delete_file,
                lms_save_quiz, lms_get_quiz, lms_save_questions, lms_save_quiz_questions,
                lms_get_questions, lms_publish_quiz,
                lms_save_exam, lms_get_exam,
                lms_start_attempt, lms_record_tab_switch, lms_submit_quiz,
                lms_get_attempt, lms_get_user_attempt,
                lms_submit_exam, lms_get_exam_submissions,
                lms_get_user_exam_submission, lms_grade_submission,
                lms_get_all_submissions,
                lms_update_progress, lms_get_progress,
                lms_issue_certificate, lms_update_cert_blockchain,
                lms_get_certificate, lms_get_certificates,
                lms_get_eligible_for_cert,
                lms_get_exam_questions, lms_save_exam_questions,
                lms_submit_exam_answers, lms_get_exam_submission_detail)
import requests as _http

lms_bp = Blueprint('lms', __name__)

LMS_UPLOAD_DIR   = os.path.join(os.path.dirname(__file__), 'uploads', 'lms')
EXAM_UPLOAD_DIR  = os.path.join(os.path.dirname(__file__), 'uploads', 'exam_submissions')
os.makedirs(LMS_UPLOAD_DIR,  exist_ok=True)
os.makedirs(EXAM_UPLOAD_DIR, exist_ok=True)

AI_PROVIDER     = os.getenv("AI_PROVIDER", "groq")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")

ALLOWED_MATERIAL = {'pdf','docx','pptx','xlsx','txt','mp4','mkv','avi','png','jpg','jpeg'}
ALLOWED_SUBMISSION = {'pdf','docx','zip','txt','png','jpg','jpeg'}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _uid():
    return session.get('user_id')

def _role():
    return session.get('user_role', '')

def _is_instructor():
    return _role() in ('admin', 'employee')

def _is_trainee():
    return _role() == 'trainee'

def _allowed(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set


# ── AI helpers ────────────────────────────────────────────────────────────────

def _extract_text(filepath, original_name):
    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    text = ''
    try:
        if ext == 'pdf':
            try:
                import pdfplumber
                with pdfplumber.open(filepath) as pdf:
                    text = '\n'.join(p.extract_text() or '' for p in pdf.pages[:10])
            except ImportError:
                try:
                    import PyPDF2
                    with open(filepath, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = '\n'.join(pg.extract_text() or '' for pg in reader.pages[:10])
                except ImportError:
                    pass
        elif ext == 'docx':
            try:
                import docx
                doc = docx.Document(filepath)
                text = '\n'.join(p.text for p in doc.paragraphs)
            except ImportError:
                pass
        elif ext == 'txt':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read(8000)
    except Exception:
        pass
    return text[:6000]


def _ai_generate_quiz(content_text, module_title, num_questions=10):
    prompt = (
        f'You are creating a quiz for a training module titled "{module_title}".\n\n'
        f'Based on the following content, generate {num_questions} multiple-choice questions.\n\n'
        f'Content:\n{content_text}\n\n'
        'Return ONLY a JSON array (no other text) with this exact structure:\n'
        '[\n'
        '  {\n'
        '    "text": "Question?",\n'
        '    "type": "multiple_choice",\n'
        '    "points": 1,\n'
        '    "choices": [\n'
        '      {"text": "Choice A", "is_correct": true},\n'
        '      {"text": "Choice B", "is_correct": false},\n'
        '      {"text": "Choice C", "is_correct": false},\n'
        '      {"text": "Choice D", "is_correct": false}\n'
        '    ]\n'
        '  }\n'
        ']\n'
        'Each question must have exactly 4 choices with exactly 1 correct answer.'
    )
    resp = _http.post(
        f"{LM_STUDIO_URL}/v1/chat/completions",
        json={"model": LM_STUDIO_MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 3000, "temperature": 0.3, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    start, end = raw.find('['), raw.rfind(']') + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


def _ai_module_chat(messages, module_title, module_content):
    system = (
        f'You are a learning assistant for the module: "{module_title}".\n\n'
        'Help trainees understand module content, concepts, and materials.\n\n'
        'STRICT RULES — you must NEVER:\n'
        '- Answer quiz questions or reveal quiz answers\n'
        '- Solve or hint at practical exam tasks\n'
        '- Provide answers to any assessment questions\n\n'
        'If asked about quizzes or exams, politely decline and redirect to the materials.\n\n'
        f'Module content summary:\n{module_content[:2500] if module_content else "No content available."}'
    )
    resp = _http.post(
        f"{LM_STUDIO_URL}/v1/chat/completions",
        json={"model": LM_STUDIO_MODEL,
              "messages": [{"role": "system", "content": system}] + messages[-10:],
              "max_tokens": 512, "temperature": 0.7, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _module_content_text(module_id):
    files = lms_get_files(module_id)
    text = ''
    for f in files:
        fp = os.path.join(LMS_UPLOAD_DIR, f['filename'])
        t = _extract_text(fp, f['original_name'])
        if t:
            text += t + '\n'
            if len(text) >= 4000:
                break
    return text


def _check_completion(user_id, module_id):
    p = lms_get_progress(user_id, module_id)
    if not p:
        return
    quiz = lms_get_quiz(module_id=module_id)
    exam = lms_get_exam(module_id=module_id)
    quiz_ok = (not quiz) or bool(p.get('quiz_passed'))
    exam_ok = (not exam) or bool(p.get('exam_graded'))
    if quiz_ok and exam_ok and not p.get('completed'):
        lms_update_progress(user_id, module_id, completed=True, completed_at=datetime.now())


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
    if mod:
        lms_toggle_publish(module_id, not mod['is_published'])
    return redirect(url_for('lms.module_manage', module_id=module_id))


@lms_bp.route('/lms/modules/<int:module_id>/delete', methods=['POST'])
def module_delete(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    for f in lms_get_files(module_id):
        fp = os.path.join(LMS_UPLOAD_DIR, f['filename'])
        if os.path.exists(fp):
            os.remove(fp)
    lms_delete_module(module_id)
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/archive', methods=['POST'])
def module_archive(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    lms_archive_module(module_id)
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/restore', methods=['POST'])
def module_restore(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    lms_restore_module(module_id)
    if _role() == 'admin':
        return redirect('/admin')
    elif _role() == 'employee':
        return redirect('/employee')
    return redirect(url_for('lms.modules'))


@lms_bp.route('/lms/modules/<int:module_id>/delete-archived', methods=['POST'])
def module_delete_archived(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    lms_delete_module(module_id)
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


# Quiz management

@lms_bp.route('/lms/modules/<int:module_id>/quiz', methods=['GET', 'POST'])
def quiz_manage(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    mod       = lms_get_module(module_id)
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

        return redirect(url_for('lms.quiz_manage', module_id=module_id))

    return render_template('lms/quiz_manage.html', mod=mod, quiz=quiz, questions=questions)


@lms_bp.route('/lms/modules/<int:module_id>/quiz/generate', methods=['POST'])
def quiz_generate(module_id):
    if not _uid() or not _is_instructor():
        return jsonify(error="Unauthorized"), 403
    mod   = lms_get_module(module_id)
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
        return jsonify(error="Could not extract text from the uploaded files. Make sure the PDF or DOCX is not a scanned image. Required packages: pdfplumber or PyPDF2 (for PDF), python-docx (for DOCX)."), 400

    try:
        data = request.get_json() or {}
        num_questions = data.get('num_questions', 10)
        num_questions = max(1, min(int(num_questions), 50))
        questions = _ai_generate_quiz(content_text, mod['title'], num_questions)
        return jsonify(questions=questions)
    except Exception as e:
        return jsonify(error=f"AI generation failed: {e}"), 500


# Practical exam management

@lms_bp.route('/lms/modules/<int:module_id>/exam', methods=['GET', 'POST'])
def exam_manage(module_id):
    if not _uid() or not _is_instructor():
        abort(403)
    mod  = lms_get_module(module_id)
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
        return redirect(url_for('lms.exam_manage', module_id=module_id))
    return render_template('lms/exam_manage.html', mod=mod, exam=exam, exam_questions=exam_questions)


# Submissions (instructor)

@lms_bp.route('/lms/submissions')
def submissions():
    if not _uid() or not _is_instructor():
        abort(403)
    inst_id = _uid() if _role() != 'admin' else None
    subs    = lms_get_all_submissions(instructor_id=inst_id)
    return render_template('lms/submissions.html', submissions=subs)


@lms_bp.route('/lms/submissions/<int:sub_id>/answers', methods=['GET'])
def get_submission_answers(sub_id):
    if not _uid() or not _is_instructor():
        abort(403)
    submission = lms_get_exam_submission_detail(sub_id)
    if not submission:
        abort(404)
    return jsonify(submission=submission)


@lms_bp.route('/lms/submissions/<int:sub_id>/grade', methods=['POST'])
def grade_submission(sub_id):
    if not _uid() or not _is_instructor():
        abort(403)
    grade    = int(request.form.get('grade', 0))
    feedback = request.form.get('feedback', '').strip()
    lms_grade_submission(sub_id, grade, feedback, _uid())

    conn = get_db(); cur = dict_cur(conn)
    cur.execute("""SELECT s.user_id, e.module_id FROM lms_exam_submissions s
                   JOIN lms_practical_exams e ON s.exam_id=e.id WHERE s.id=%s""", (sub_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        lms_update_progress(row['user_id'], row['module_id'], exam_graded=True, exam_grade=grade)
        _check_completion(row['user_id'], row['module_id'])
    return redirect(url_for('lms.submissions'))


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


# ── TRAINEE ROUTES ────────────────────────────────────────────────────────────

@lms_bp.route('/lms/learn')
def learn():
    if not _uid():
        return redirect(url_for('auth.auth'))
    mods         = lms_get_modules_for_trainee(_uid(), published_only=True)
    progress_list = lms_get_progress(_uid())
    prog_map     = {p['module_id']: p for p in progress_list}
    total        = len(mods)
    completed    = sum(1 for m in mods if prog_map.get(m['id'], {}).get('completed'))
    pct          = round(completed / total * 100) if total else 0
    return render_template('lms/learn.html', modules=mods, prog_map=prog_map,
                           completed=completed, total=total, pct=pct)


@lms_bp.route('/lms/learn/<int:module_id>')
def learn_module(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod = lms_get_module(module_id)
    if not mod or not mod['is_published']:
        abort(404)
    uid          = _uid()
    files        = lms_get_files(module_id)
    quiz         = lms_get_quiz(module_id=module_id)
    exam         = lms_get_exam(module_id=module_id)
    quiz_attempt = lms_get_user_attempt(uid, quiz['id']) if quiz and quiz['is_published'] else None
    exam_sub     = lms_get_user_exam_submission(uid, exam['id']) if exam else None
    progress     = lms_get_progress(uid, module_id)
    my_feedback  = get_user_feedback(uid, module_id) if _is_trainee() else None
    lms_update_progress(uid, module_id)
    return render_template('lms/learn_module.html', mod=mod, files=files,
                           quiz=quiz, exam=exam, quiz_attempt=quiz_attempt,
                           exam_sub=exam_sub, progress=progress, my_feedback=my_feedback)


@lms_bp.route('/lms/learn/<int:module_id>/quiz')
def quiz_take(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod  = lms_get_module(module_id)
    quiz = lms_get_quiz(module_id=module_id)
    if not quiz or not quiz['is_published']:
        abort(404)
    uid     = _uid()
    existing = lms_get_user_attempt(uid, quiz['id'])
    if existing:
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


@lms_bp.route('/lms/learn/<int:module_id>/exam', methods=['GET', 'POST'])
def exam_submit_route(module_id):
    if not _uid():
        return redirect(url_for('auth.auth'))
    mod  = lms_get_module(module_id)
    exam = lms_get_exam(module_id=module_id)
    if not exam:
        abort(404)
    uid      = _uid()
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


@lms_bp.route('/lms/progress')
def progress():
    if not _uid():
        return redirect(url_for('auth.auth'))
    uid          = _uid()
    mods         = lms_get_modules(published_only=True)
    progress_list = lms_get_progress(uid)
    prog_map     = {p['module_id']: p for p in progress_list}
    total        = len(mods)
    completed    = sum(1 for m in mods if prog_map.get(m['id'], {}).get('completed'))
    pct          = round(completed / total * 100) if total else 0
    return render_template('lms/progress.html', modules=mods, prog_map=prog_map,
                           completed=completed, total=total, pct=pct)


@lms_bp.route('/lms/certificates')
def certificates():
    if not _uid():
        return redirect(url_for('auth.auth'))
    from datetime import date
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
