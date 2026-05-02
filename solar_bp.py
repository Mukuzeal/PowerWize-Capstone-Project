import os, json
import requests as _http
from datetime import datetime
from flask import Blueprint, request, render_template, redirect, session, jsonify, url_for, flash
from dotenv import load_dotenv
from db import (save_solar_request, update_solar_request,
                get_solar_request, get_solar_requests)
from solar_engine import compute as solar_compute
from ocr_module import extract_bill_data
from utils import save_file

load_dotenv()

solar_bp = Blueprint("solar", __name__)

UPLOAD_FOLDER = os.path.join("static", "uploads", "solar_bills")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Ollama helpers ─────────────────────────────────────────────────────────────

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


def _ai_chat(messages: list, system: str) -> str:
    """Chat via Ollama (llama3.1:8b)."""
    data = _ollama_chat(messages, system=system)
    return data.get("message", {}).get("content", "").strip()


def _ollama_chat(messages: list, system: str = None, tools: list = None) -> dict:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    payload = {"model": OLLAMA_MODEL, "messages": msgs, "stream": False}

    if tools:
        payload["tools"] = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
        } for t in tools]

    resp = _http.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


CHAT_BASE_SYSTEM = """You are Solara, a knowledgeable and friendly Solar PV specialist at EnergyWize Solutions in the Philippines. You talk like a real person — warm, engaging, and genuinely helpful. NOT like a robot or a form.

STRICT TOPIC RULE: Only discuss solar PV and gathering quotation info. For anything else say: "That's outside my area — I'm here for solar PV questions and quotations!"

HOW TO BEHAVE:
- Sound like a knowledgeable friend, not a customer service script
- Show genuine interest ("A ₱8,000 monthly bill? Solar could seriously cut that down!")
- Group related questions naturally instead of asking one at a time ("Since it's residential — is the property owned or rented? And roughly how much roof space do you have available?")
- React naturally to what the user shares, don't just acknowledge robotically
- If they ask a solar PV question (panels, inverters, batteries, net metering, hybrid vs grid-tie, ROI), answer it in 2–3 sentences and naturally continue the conversation
- Keep each response to 3–5 sentences max
- NEVER say "Got it", "Noted", "Understood", or list all the fields you need at once
- NEVER sound like you're reading from a checklist
"""

QUESTION_FLOW = [
    {"field": "name",                  "ask": "What is your full name?"},
    {"field": "address",               "ask": "What is your complete address?"},
    {"field": "establishment_type",    "ask": "What type of establishment is it — Residential, Commercial, or Industrial?"},
    {"field": "ownership",             "ask": "Is the property owned or rented?"},
    {"field": "electrical_phase",      "ask": "What is your electrical setup — Single Phase or Three Phase?"},
    {"field": "monthly_bill_php",      "ask": "What is your average monthly electric bill in PHP? (Or you can give your monthly kWh consumption instead.)"},
    {"field": "time_of_use_night_pct", "ask": "Roughly what percentage of your electricity is used at night after 6 PM? (Enter 0–100, or say 30 if unsure.)"},
    {"field": "target_savings",        "ask": "What is your target savings — 100%, 75%, or 50% of your current bill?"},
    {"field": "roof_sqm",              "ask": "What is your available roof area in square meters? (An estimate is fine.)"},
    {"field": "notes",                 "ask": "Any additional notes or concerns? (Say 'none' to skip.)"},
]


def _extract_answer(field: str, text: str, lenient: bool = False):
    """Extract a single field value from text.
    lenient=True: accept text without explicit signal words (used when that field was directly asked).
    """
    import re
    t = text.lower().strip()

    if field == "establishment_type":
        if "residential" in t: return "residential"
        if "commercial"  in t: return "commercial"
        if "industrial"  in t: return "industrial"

    elif field == "ownership":
        if any(w in t for w in ("owned", "own", "owner")): return "owned"
        if "rent" in t: return "rented"

    elif field == "electrical_phase":
        if "three" in t or "3-phase" in t or "3 phase" in t: return "three"
        if "single" in t or "1-phase" in t or "1 phase" in t or "one phase" in t: return "single"

    elif field == "target_savings":
        # Require explicit % marker or savings context for bare numbers
        if "100%" in t: return "100"
        if "75%"  in t: return "75"
        if "50%"  in t: return "50"
        if any(k in t for k in ("percent", "savings", "offset", "target")):
            if "100" in t: return "100"
            if "75"  in t: return "75"
            if "50"  in t: return "50"

    elif field == "monthly_bill_php":
        has_kwh  = any(k in t for k in ("kwh", " kw ", "kilowatt", "kilo-watt"))
        has_bill = any(k in t for k in ("php", "₱", "peso", "bill", "electricity cost"))
        if has_kwh or has_bill or lenient:
            nums = re.findall(r'[\d,]+(?:\.\d+)?', t)
            for n in nums:
                try:
                    val = float(n.replace(',', ''))
                    if 1 <= val <= 100000:
                        if has_kwh:    return ("kwh",  val)
                        elif has_bill: return ("bill", val)
                        else:          return ("kwh",  val) if val < 500 else ("bill", val)
                except ValueError:
                    pass

    elif field == "roof_sqm":
        # Require explicit area signal; never infer from bare numbers
        has_sqm = any(k in t for k in ("sqm", "sq m", "square meter", "square metre",
                                        "sq. m", "roof area", "roof space"))
        if has_sqm or lenient:
            nums = re.findall(r'[\d,]+(?:\.\d+)?', t)
            for n in nums:
                try:
                    val = float(n.replace(',', ''))
                    if 1 <= val <= 10000:
                        return val
                except ValueError:
                    pass

    elif field == "time_of_use_night_pct":
        has_night = any(k in t for k in ("night", "evening", "after 6", "6pm", "nighttime"))
        has_pct   = "%" in t or "percent" in t
        if has_night or has_pct or lenient:
            nums = re.findall(r'\d+', t)
            for n in nums:
                val = int(n)
                if 0 <= val <= 100:
                    return val

    elif field == "notes":
        if t in ("none", "no", "n/a", "nothing", "none.", "no.", "skip", "n/a."): return ""
        if lenient:
            return text.strip() or None

    else:  # name, address, email, contact
        _TECH = {"kwh", "kw", "php", "peso", "watt", "panel", "solar", "volt", "amp", "consume"}
        first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
        fl = first_line.lower()
        _leads = {
            "name":    ["my name is ", "i am ", "i'm ", "name: ", "call me ", "this is "],
            "address": ["i live at ", "i live in ", "my address is ", "address: ",
                        "located at ", "residing at "],
            "email":   ["my email is ", "email address is ", "email: ", "reach me at "],
            "contact": ["my number is ", "my contact is ", "contact: ",
                        "phone: ", "mobile: ", "call me at "],
        }
        result, has_lead = first_line, False
        for phrase in _leads.get(field, []):
            if fl.startswith(phrase):
                result, has_lead = first_line[len(phrase):], True
                break

        if field == "name":
            # Reject if technical terms or digits are present — not a name
            if any(k in fl for k in _TECH) or any(c.isdigit() for c in fl):
                return None
        elif not lenient and not has_lead:
            return None  # Strict: address/email/contact require a lead-in phrase

        return result.strip() or None

    return None


def _ack(field: str, value) -> str:
    if field == "name":                  return f"Nice to meet you, {value}!"
    if field == "address":               return "Got it, thank you."
    if field == "email":                 return "Noted."
    if field == "contact":               return "Got it."
    if field == "establishment_type":    return f"{str(value).title()} — understood."
    if field == "ownership":             return f"{str(value).title()} — noted."
    if field == "electrical_phase":      return f"{str(value).title()}-phase — got it."
    if field == "time_of_use_night_pct": return f"Got it — {value}% usage at night."
    if field == "target_savings":        return f"{value}% target savings — noted."
    if field == "roof_sqm":              return f"Got it — {value} sqm of roof space."
    if field == "notes":                 return "Noted!" if value else "No problem, skipping additional notes."
    return "Got it."


def _llama_recommendations(req: dict, result: dict) -> str:
    prompt = f"""A Solar PV quotation has been computed for a customer. Provide a friendly, clear explanation of the results and recommendations in 3–4 short paragraphs. Do NOT restate every number — explain what it means and give actionable advice.

Customer Profile:
- Establishment: {req['establishment_type'].title()}, {req['ownership']}
- Electrical: {req['electrical_phase']}-phase
- Monthly consumption: {result['kwh_monthly']} kWh
- Target savings: {req['target_savings']}%

Computed Results:
- System size: {result['system_size_kw']} kWp
- Panels needed: {result['panel_count']} × 400W panels
- Estimated cost: ₱{result['cost_min']:,} – ₱{result['cost_max']:,}
- Monthly savings: ₱{result['monthly_savings']:,}
- Payback period: {result['roi_years']} years
- Roof feasibility: {result['feasibility']}
- Recommended system: {result['system_type']}
- Battery storage: {'Recommended' if result['battery_recommended'] else 'Optional'}
{result.get('phase_note','')}

Write in a helpful, professional tone suitable for a Philippine audience. Mention if battery storage is advisable and why, comment on the payback period, and note any concerns about roof space if applicable."""

    try:
        return _ai_chat([{"role": "user", "content": prompt}],
                        system="You are a helpful solar energy advisor. Be clear and concise.")
    except Exception as e:
        print(f"[SOLAR AI ERROR] {e}")
        return ""


def _process_and_save(form_data: dict, bill_path: str | None = None,
                      ocr_kwh: float | None = None, ocr_amount: float | None = None) -> int:
    kwh  = form_data.get("kwh_monthly") or ocr_kwh
    bill = form_data.get("monthly_bill_php") or ocr_amount

    result = solar_compute(
        kwh_monthly           = float(kwh)  if kwh  else None,
        bill_php              = float(bill) if bill else None,
        target_savings        = form_data.get("target_savings", "100"),
        roof_sqm              = float(form_data["roof_sqm"]) if form_data.get("roof_sqm") else None,
        time_of_use_night_pct = int(form_data["time_of_use_night_pct"]) if form_data.get("time_of_use_night_pct") else None,
        electrical_phase      = form_data.get("electrical_phase", "single"),
    )

    db_data = {
        "user_id":              session.get("user_id"),
        "name":                 form_data.get("name",""),
        "address":              form_data.get("address",""),
        "email":                form_data.get("email",""),
        "contact":              form_data.get("contact",""),
        "establishment_type":   form_data.get("establishment_type","residential"),
        "ownership":            form_data.get("ownership","owned"),
        "electrical_phase":     form_data.get("electrical_phase","single"),
        "monthly_bill_php":     bill,
        "kwh_monthly":          result["kwh_monthly"],
        "time_of_use_night_pct":form_data.get("time_of_use_night_pct"),
        "target_savings":       form_data.get("target_savings","100"),
        "roof_sqm":             form_data.get("roof_sqm"),
        "notes":                form_data.get("notes",""),
        "bill_path":            bill_path,
        "ocr_kwh":              ocr_kwh,
        "ocr_bill_amount":      ocr_amount,
    }
    req_id = save_solar_request(db_data)

    ai_text = _llama_recommendations(db_data, result)

    update_solar_request(req_id,
        system_size_kw     = result["system_size_kw"],
        panel_count        = result["panel_count"],
        cost_min           = result["cost_min"],
        cost_max           = result["cost_max"],
        monthly_savings    = result["monthly_savings"],
        roi_years          = result["roi_years"],
        feasibility        = result["feasibility"],
        system_type        = result["system_type"],
        battery_recommended= int(result["battery_recommended"]),
        ai_explanation     = ai_text,
        status             = "ai_processed",
    )
    return req_id


# ── Routes ─────────────────────────────────────────────────────────────────────

@solar_bp.route("/solar")
def solar_form():
    prefill = {}
    if "user_id" in session:
        prefill["name"]  = session.get("user_name", "")
        prefill["email"] = session.get("user_email", "")
    return render_template("solar_request.html", prefill=prefill)


@solar_bp.route("/solar/chat")
def solar_chat():
    prefill = {
        "name":  session.get("user_name", ""),
        "email": session.get("user_email", ""),
    }
    return render_template("solar_chat.html", prefill=prefill)


@solar_bp.route("/solar/chat/msg", methods=["POST"])
def solar_chat_msg():
    data      = request.get_json(force=True)
    messages  = data.get("messages", [])
    user_msg  = data.get("user_message", "").strip()
    collected = data.get("collected", {})
    q_index   = data.get("q_index", -1)  # index of the field Solara last prioritised

    if not user_msg:
        return jsonify({"text": ""}), 400

    FREE_TEXT = {"name", "address", "email", "contact", "notes"}

    def _store(f, val):
        if f == "monthly_bill_php" and isinstance(val, tuple):
            kind, num = val
            if kind == "kwh":
                collected["kwh_monthly"] = num;      collected["monthly_bill_php"] = None
            else:
                collected["monthly_bill_php"] = num; collected["kwh_monthly"] = None
        else:
            collected[f] = val

    # 1. Lenient extraction for the field Solara last prioritised
    if 0 <= q_index < len(QUESTION_FLOW):
        cur = QUESTION_FLOW[q_index]["field"]
        if cur == "monthly_bill_php":
            already = "monthly_bill_php" in collected or "kwh_monthly" in collected
        else:
            already = cur in collected
        if not already:
            v = _extract_answer(cur, user_msg, lenient=True)
            if v is not None:
                _store(cur, v)

    # 2. Strict greedy scan for all remaining structured fields
    for q in QUESTION_FLOW:
        f = q["field"]
        if f in FREE_TEXT: continue
        if f == "monthly_bill_php":
            if "monthly_bill_php" in collected or "kwh_monthly" in collected: continue
        elif f in collected: continue
        v = _extract_answer(f, user_msg, lenient=False)
        if v is not None:
            _store(f, v)

    # 3. Free-text fields with explicit lead-in (any field, any time)
    for q in QUESTION_FLOW:
        f = q["field"]
        if f not in FREE_TEXT or f in collected: continue
        v = _extract_answer(f, user_msg, lenient=False)
        if v is not None:
            _store(f, v)

    # ── Check completion ────────────────────────────────────────────────────────
    REQUIRED = {"name", "address",
                "establishment_type", "ownership", "electrical_phase",
                "target_savings", "roof_sqm"}
    has_consumption = "monthly_bill_php" in collected or "kwh_monthly" in collected
    if all(f in collected for f in REQUIRED) and has_consumption:
        collected.setdefault("time_of_use_night_pct", 30)
        collected.setdefault("notes", "")
        form_data = {k: v for k, v in collected.items() if v is not None}
        form_data.setdefault("target_savings", "100")
        req_id = _process_and_save(form_data)
        return jsonify({"redirect": f"/solar/result/{req_id}"})

    # ── Find next priority missing field ────────────────────────────────────────
    _LABELS = {
        "name":                  "full name",
        "address":               "complete address",
        "email":                 "email address",
        "contact":               "contact number",
        "establishment_type":    "type of establishment (residential/commercial/industrial)",
        "ownership":             "ownership (owned/rented)",
        "electrical_phase":      "electrical phase (single/three)",
        "monthly_bill_php":      "monthly electricity bill (PHP) or kWh consumption",
        "time_of_use_night_pct": "nighttime usage percentage (0–100)",
        "target_savings":        "target savings (100%/75%/50%)",
        "roof_sqm":              "available roof area in sqm",
        "notes":                 "additional notes or concerns",
    }
    next_qi, next_label = None, ""
    for i, q in enumerate(QUESTION_FLOW):
        f = q["field"]
        if f == "monthly_bill_php":
            if "monthly_bill_php" not in collected and "kwh_monthly" not in collected:
                next_qi, next_label = i, _LABELS[f]; break
        elif f not in collected:
            next_qi, next_label = i, _LABELS.get(f, f); break

    done_parts = [f"{_LABELS.get(k,k)}: {v}" for k, v in collected.items()
                  if v is not None and k in _LABELS]
    missing_labels = []
    for q in QUESTION_FLOW:
        f = q["field"]
        if f == "monthly_bill_php":
            if "monthly_bill_php" not in collected and "kwh_monthly" not in collected:
                missing_labels.append(_LABELS[f])
        elif f not in collected:
            missing_labels.append(_LABELS.get(f, f))

    done_str    = "; ".join(done_parts)    or "nothing yet"
    missing_str = ", ".join(missing_labels) or "all collected!"

    # ── Initial greeting (no LLM, instant) ─────────────────────────────────────
    if q_index == -1 and not messages:
        intro = ("Hey! I'm Solara, EnergyWize's solar specialist. "
                 "I'll help you figure out what solar PV setup makes sense for your property and budget — "
                 "and I can answer any solar questions along the way. "
                 "To kick things off, what's your name and what kind of property are we looking at?")
        msgs_out = [{"role": "user", "content": user_msg},
                    {"role": "assistant", "content": intro}]
        return jsonify({"text": intro, "messages": msgs_out,
                        "collected": collected, "q_index": 0})

    # ── LLM generates the full conversational response ──────────────────────────
    system = (CHAT_BASE_SYSTEM + f"""
Context (internal — do not recite this back to the user):
Already shared: {done_str}
Still need to gather: {missing_str}
Next thing to naturally work into the conversation: {next_label}""")

    messages_out = messages + [{"role": "user", "content": user_msg}]
    try:
        text = _ai_chat(messages_out, system=system)
    except Exception as e:
        text = f"I'm having a bit of trouble right now — please try again in a moment."
        print(f"[SOLAR CHAT ERROR] {e}")

    return jsonify({
        "text":      text,
        "messages":  messages_out + [{"role": "assistant", "content": text}],
        "collected": collected,
        "q_index":   next_qi if next_qi is not None else q_index,
    })


@solar_bp.route("/solar/ocr", methods=["POST"])
def solar_ocr():
    if "bill" not in request.files:
        return jsonify({"error": "No file"}), 400
    f   = request.files["bill"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        return jsonify({"error": "Unsupported file type"}), 400

    path = os.path.join(UPLOAD_FOLDER, f"ocr_temp_{os.urandom(4).hex()}{ext}")
    f.save(path)
    result = extract_bill_data(path)
    if result:
        return jsonify(result)
    return jsonify({"error": "Could not extract data — please enter manually"})


@solar_bp.route("/solar/submit", methods=["POST"])
def solar_submit():
    f = request.form

    # Validate required fields
    errors = []
    for field, label in [("name","Name"),("email","Email"),("contact","Contact"),
                          ("address","Address"),("establishment_type","Establishment type"),
                          ("ownership","Ownership"),("electrical_phase","Electrical phase"),
                          ("target_savings","Target savings")]:
        if not f.get(field,"").strip():
            errors.append(f"{label} is required.")
    if not f.get("monthly_bill_php") and not f.get("kwh_monthly"):
        errors.append("Please enter either your monthly bill (PHP) or kWh consumption.")
    if errors:
        prefill = dict(f)
        return render_template("solar_request.html", errors=errors, prefill=prefill)

    # Handle bill upload
    bill_path  = None
    ocr_kwh    = None
    ocr_amount = None
    if "bill" in request.files and request.files["bill"].filename:
        bf  = request.files["bill"]
        ext = os.path.splitext(bf.filename)[1].lower()
        fname = f"bill_{os.urandom(6).hex()}{ext}"
        save_path = os.path.join(UPLOAD_FOLDER, fname)
        bf.save(save_path)
        bill_path = os.path.join("static", "uploads", "solar_bills", fname)
        ocr = extract_bill_data(save_path)
        if ocr:
            ocr_kwh    = ocr.get("kwh")
            ocr_amount = ocr.get("amount")

    form_data = {
        "name":                  f.get("name","").strip(),
        "email":                 f.get("email","").strip(),
        "contact":               f.get("contact","").strip(),
        "address":               f.get("address","").strip(),
        "establishment_type":    f.get("establishment_type","residential"),
        "ownership":             f.get("ownership","owned"),
        "electrical_phase":      f.get("electrical_phase","single"),
        "monthly_bill_php":      f.get("monthly_bill_php") or None,
        "kwh_monthly":           f.get("kwh_monthly") or ocr_kwh or None,
        "time_of_use_night_pct": f.get("time_of_use_night_pct") or None,
        "target_savings":        f.get("target_savings","100"),
        "roof_sqm":              f.get("roof_sqm") or None,
        "notes":                 f.get("notes","").strip(),
    }

    req_id = _process_and_save(form_data, bill_path, ocr_kwh, ocr_amount)
    return redirect(f"/solar/result/{req_id}")


@solar_bp.route("/solar/result/<int:req_id>")
def solar_result(req_id):
    req = get_solar_request(req_id)
    if not req:
        return redirect("/solar")
    return render_template("solar_result.html", req=req)


@solar_bp.route("/solar/decision/<int:req_id>", methods=["POST"])
def solar_decision(req_id):
    decision = request.form.get("decision")
    req = get_solar_request(req_id)
    if not req:
        return redirect("/solar")

    # Save contact details if provided (collected at decision time for expert/consult)
    contact_updates = {}
    if request.form.get("email"):
        contact_updates["email"] = request.form.get("email").strip()
    if request.form.get("contact"):
        contact_updates["contact"] = request.form.get("contact").strip()

    if decision == "expert_review":
        update_solar_request(req_id, status="pending_review", **contact_updates)
        flash("Your request has been forwarded to our solar specialist. We'll contact you shortly.", "success")
    elif decision == "proceed":
        update_solar_request(req_id, status="completed", **contact_updates)
        flash("Thank you! Your preliminary quotation has been noted. Contact us to proceed with installation.", "success")
    elif decision == "consult":
        update_solar_request(req_id, status="pending_review", **contact_updates)
        flash("A consultation request has been sent. Our team will reach out to schedule a site visit.", "success")

    return redirect(f"/solar/result/{req_id}")


# ── Admin: review & finalize ───────────────────────────────────────────────────

@solar_bp.route("/admin/solar/<int:req_id>/data")
def admin_solar_data(req_id):
    if session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    req = get_solar_request(req_id)
    if not req:
        return jsonify({"error": "Not found"}), 404
    # Convert datetime for JSON
    for key in ("created_at", "reviewed_at"):
        if req.get(key):
            req[key] = req[key].strftime("%b %d, %Y %I:%M %p")
    return jsonify(req)


@solar_bp.route("/admin/solar/<int:req_id>/review", methods=["POST"])
def admin_solar_review(req_id):
    if session.get("user_role") != "admin":
        return redirect("/admin")
    f = request.form
    update_solar_request(req_id,
        final_system_kw  = f.get("final_system_kw") or None,
        final_panel_count= f.get("final_panel_count") or None,
        final_cost       = f.get("final_cost") or None,
        reviewer_notes   = f.get("reviewer_notes",""),
        reviewed_at      = datetime.now(),
        status           = "reviewed",
    )
    _send_quotation_email(req_id)
    flash("Quotation reviewed and sent to client.", "success")
    return redirect("/admin#solar")


def _send_quotation_email(req_id: int):
    req = get_solar_request(req_id)
    if not req:
        return
    try:
        from email_utils import _send
        system_kw  = req.get("final_system_kw") or req.get("system_size_kw")
        panels     = req.get("final_panel_count") or req.get("panel_count")
        cost       = req.get("final_cost")
        cost_range = f"₱{req['cost_min']:,.0f} – ₱{req['cost_max']:,.0f}" if not cost else f"₱{cost:,.0f}"
        html = f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0D3B27,#1E7A4B);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#fff;font-size:22px;margin:0">Solar PV Quotation</h1>
    <p style="color:rgba(255,255,255,0.75);font-size:13px;margin:6px 0 0">EnergyWize Solutions Inc.</p>
  </div>
  <div style="background:#fff;border:1px solid #E5E7EB;border-top:none;padding:28px;border-radius:0 0 12px 12px">
    <p style="font-size:14px;color:#374151">Dear <strong>{req['name']}</strong>,</p>
    <p style="font-size:13px;color:#6B7280">Your Solar PV quotation has been reviewed by our specialist. Here is your preliminary estimate:</p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin:16px 0">
      <tr style="background:#F9FAFB"><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">System Size</td><td style="padding:8px 12px;font-weight:600;border:1px solid #E5E7EB">{system_kw} kWp</td></tr>
      <tr><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">No. of Panels</td><td style="padding:8px 12px;font-weight:600;border:1px solid #E5E7EB">{panels} × 400W panels</td></tr>
      <tr style="background:#F9FAFB"><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">Estimated Cost</td><td style="padding:8px 12px;font-weight:600;border:1px solid #E5E7EB">{cost_range}</td></tr>
      <tr><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">Monthly Savings</td><td style="padding:8px 12px;font-weight:600;color:#16A34A;border:1px solid #E5E7EB">₱{req['monthly_savings']:,.2f}</td></tr>
      <tr style="background:#F9FAFB"><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">System Type</td><td style="padding:8px 12px;font-weight:600;border:1px solid #E5E7EB">{(req.get('system_type') or 'Grid-Tie').title()}</td></tr>
      <tr><td style="padding:8px 12px;color:#6B7280;border:1px solid #E5E7EB">Payback Period</td><td style="padding:8px 12px;font-weight:600;border:1px solid #E5E7EB">{req['roi_years']} years</td></tr>
    </table>
    {"<p style='font-size:13px;color:#374151;background:#F0FDF4;padding:12px;border-radius:8px;border:1px solid #86EFAC'><strong>Specialist Notes:</strong> " + req['reviewer_notes'] + "</p>" if req.get('reviewer_notes') else ""}
    <p style="font-size:13px;color:#6B7280">This is a <strong>preliminary AI-assisted estimate</strong>. Final pricing is subject to site assessment and current equipment availability.</p>
    <p style="font-size:13px;color:#374151">Contact us to schedule a site visit or to proceed with your installation.</p>
    <div style="text-align:center;margin-top:24px">
      <span style="background:#16583C;color:#fff;padding:10px 24px;border-radius:8px;font-size:13px;font-weight:600">EnergyWize Solutions Inc.</span>
    </div>
  </div>
</div>"""
        _send(req["email"], f"Your Solar PV Quotation – EnergyWize", html)
        update_solar_request(req_id, status="quotation_sent")
    except Exception as e:
        print(f"[SOLAR EMAIL ERROR] {e}")
