import os
import json
from datetime import datetime

from flask import session, request, redirect, url_for
import requests as _http

from permissions import can, home_url_for

from db import (lms_get_files, lms_get_progress, lms_get_quiz, lms_get_exam, lms_update_progress,
               lms_get_modules_for_trainee)

_PROJECT_ROOT    = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
LMS_UPLOAD_DIR   = os.path.join(_PROJECT_ROOT, 'uploads', 'lms')
EXAM_UPLOAD_DIR  = os.path.join(_PROJECT_ROOT, 'uploads', 'exam_submissions')
os.makedirs(LMS_UPLOAD_DIR,  exist_ok=True)
os.makedirs(EXAM_UPLOAD_DIR, exist_ok=True)

# Quiz generation and hints are text work, so they follow TEXT_PROVIDER rather
# than whichever model is configured for reading documents. See solar_bp.py for
# the full split; AI_PROVIDER remains the fallback for both.
AI_PROVIDER     = os.getenv("TEXT_PROVIDER", os.getenv("AI_PROVIDER", "groq")).lower()
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_TEXT_MODEL",
                            os.getenv("LM_STUDIO_MODEL", "local-model"))

ALLOWED_MATERIAL = {'pdf','docx','pptx','xlsx','txt','mp4','mkv','avi','png','jpg','jpeg'}
ALLOWED_SUBMISSION = {'pdf','docx','zip','txt','png','jpg','jpeg'}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _uid():
    return session.get('user_id')

def _role():
    return session.get('user_role', '')

def _is_instructor():
    return can(_role(), 'manage_modules')

def _is_trainee():
    return _role() == 'trainee'

def _allowed(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def _owns_module(mod):
    """May the caller act on this module (edit, publish, lock, delete)?

    Only Admin holds `manage_any_module`; every other instructor role --
    Super User, Secretary, Trainer -- is limited to modules they created.
    """
    return (can(_role(), 'manage_any_module')
            or (mod is not None and mod.get('instructor_id') == _uid()))

def _back_to_modules():
    """Return to wherever a module action (archive/restore/delete) was
    submitted from, rather than always jumping to the role dashboard.

    The trainer console is a hash-routed single-page app, and a referrer
    can't carry a fragment — so a bare /employee would land on the Dashboard
    pane, hiding the module list the trainer was just looking at. Every
    other caller (the standalone /lms/modules page, /admin) is a real URL
    the referrer preserves correctly, so it's trusted there.
    """
    if _role() == 'employee':
        return redirect('/employee#modules')
    if request.referrer:
        return redirect(request.referrer)
    if can(_role(), 'view_admin_console'):
        return redirect(home_url_for(_role()))
    return redirect(url_for('lms.modules'))


# ── AI helpers ────────────────────────────────────────────────────────────────

def _extract_pdf_text(filepath):
    """PyMuPDF first — it's already a hard dependency (see upload_validation.py's
    ID-render path), so this works with zero extra installs. pdfplumber/PyPDF2
    are only used if someone happens to have them; neither is in requirements.txt."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(filepath)
        text = '\n'.join(doc[i].get_text() for i in range(min(10, doc.page_count)))
        doc.close()
        return text
    except ImportError:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            return '\n'.join(p.extract_text() or '' for p in pdf.pages[:10])
    except ImportError:
        pass
    try:
        import PyPDF2
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            return '\n'.join(pg.extract_text() or '' for pg in reader.pages[:10])
    except ImportError:
        return ''


def _extract_docx_text(filepath):
    """python-docx isn't in requirements.txt either, so fall back to reading
    word/document.xml directly — a .docx is just a zip, no extra package needed."""
    try:
        import docx
        doc = docx.Document(filepath)
        return '\n'.join(p.text for p in doc.paragraphs)
    except ImportError:
        pass
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        with zipfile.ZipFile(filepath) as z:
            tree = ET.fromstring(z.read('word/document.xml'))
        paragraphs = [
            ''.join(node.text or '' for node in p.iter(f'{W_NS}t'))
            for p in tree.iter(f'{W_NS}p')
        ]
        return '\n'.join(paragraphs)
    except Exception:
        return ''


def _extract_text(filepath, original_name):
    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    text = ''
    try:
        if ext == 'pdf':
            text = _extract_pdf_text(filepath)
        elif ext == 'docx':
            text = _extract_docx_text(filepath)
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
        'STRICT TOPIC RULE: You only discuss this module\'s training content. If asked '
        'about anything unrelated to it (politics, cooking, general tech, homework for '
        'other subjects, other companies\' products, etc.), say: "That\'s outside what I '
        'can help with here — I\'m here for questions about this module\'s material." '
        'Do not answer the off-topic part even partially, even as a joke or a one-liner.\n\n'
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
    quiz_ok     = (not quiz) or bool(p.get('quiz_passed'))
    exam_ok     = (not exam) or bool(p.get('exam_graded'))
    material_ok = _material_complete(module_id, p)
    if material_ok and quiz_ok and exam_ok and not p.get('completed'):
        lms_update_progress(user_id, module_id, completed=True, completed_at=datetime.now())


def _progress_steps(prog, req):
    """What a trainee still has to do in one module, and how far along they are.

    Deliberately the same rule as _check_completion() above, so a module's bar can
    never disagree with its "Completed" badge. Opening the module is the first
    step; the quiz and practical exam are only counted when the module has one.
    """
    prog  = prog or {}
    req   = req or {}
    study_done = (prog.get('material_pct') or 0) >= 100 if req.get('has_pdf') else bool(prog)
    steps = [{'key': 'study', 'label': 'Open the material', 'done': study_done}]
    if req.get('has_quiz'):
        steps.append({'key': 'quiz', 'label': 'Pass the quiz',
                      'done': bool(prog.get('quiz_passed'))})
    if req.get('has_exam'):
        steps.append({'key': 'exam', 'label': 'Practical exam graded',
                      'done': bool(prog.get('exam_graded'))})
    # A stored `completed` flag wins over the individual signals. Older rows can
    # carry completed=1 while a step still reads 0 (e.g. an exam was attached to
    # the module after the trainee finished it); without this the bar would say
    # 100% while still naming a next step.
    if prog.get('completed'):
        for s in steps:
            s['done'] = True
    total = len(steps)
    done  = sum(1 for s in steps if s['done'])
    return {'steps': steps, 'done': done, 'total': total,
            'pct': round(done / total * 100) if total else 0}


# ── Module locking / sequential unlock ───────────────────────────────────────
#
# One admin/trainer-controlled `is_locked` flag per module (and separately per
# quiz/exam) always wins — a locked module is inaccessible to every trainee no
# matter their progress. Below that, a module is unlocked for a given trainee
# once the module before it (by sort_order within their training_type) has
# been completed; the first module in the program is always open.

def _module_access(user_id, module_id):
    """(unlocked, mods, prog_map, index) for one trainee's view of module_id.

    `mods` is the trainee's full syllabus in program order — callers that
    already need the list (e.g. learn()) can reuse it instead of re-querying.
    `index` is None if module_id isn't in the trainee's published syllabus.
    """
    mods = lms_get_modules_for_trainee(user_id, published_only=True)
    prog_map = {p['module_id']: p for p in lms_get_progress(user_id)}
    ids = [m['id'] for m in mods]
    if module_id not in ids:
        return False, mods, prog_map, None
    index = ids.index(module_id)
    unlocked = _module_unlocked(mods, prog_map, index)
    return unlocked, mods, prog_map, index


def _module_unlocked(mods, prog_map, index):
    mod = mods[index]
    if mod.get('is_locked'):
        return False
    if index == 0:
        return True
    prev_prog = prog_map.get(mods[index - 1]['id'])
    return bool(prev_prog and prev_prog.get('completed'))


def _material_complete(module_id, prog):
    """True once a module's PDF material has been fully viewed (100% of
    pages, tracked by the in-modal viewer), or immediately true if the
    module has no PDF to page through (other file types, or none at all) —
    page-percentage tracking only exists for the PDF viewer."""
    files = lms_get_files(module_id)
    has_pdf = any(f.get('file_type') == 'pdf' for f in files)
    if not has_pdf:
        return True
    return bool(prog and (prog.get('material_pct') or 0) >= 100)
