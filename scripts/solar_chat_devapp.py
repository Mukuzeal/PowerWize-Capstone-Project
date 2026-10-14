"""solar_chat_devapp.py — Hands-on test harness for the Solara chatbot.

Serves the REAL app (imported from app.py, so /solar/chat/msg is the
production route, not a copy) on a second port, plus a /dev/chat page that
puts the real chat UI in an iframe next to a live panel of what the pipeline
actually did on each turn: gate decision, every retrieved chunk and its score,
field extraction, the preview calculation, and the exact system prompt the
model was handed.

Why a separate app instead of a flag on the real one: nothing here should be
reachable in production. The tracing is monkeypatched onto solar_bp from this
process only (the same technique rag_eval.py uses for TEXT_PROVIDER) and no
production file imports this module, so there is no dev-only branch sitting in
a shipped route.

What it shows that the shipped UI cannot: the chat response carries no source
information at all (the Sources line was removed from the chatbot), so the
retrieved set and its scores are invisible in the real UI by design. This panel
is now the only way to see what actually grounded a reply.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_chat_devapp.py
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_chat_devapp.py --provider groq --port 5002
"""
import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# This harness drives the real route, which writes a solar_requests row once a
# conversation has every required field. Harmless locally, junk in a real
# database — so the same guard the seed scripts use applies here.
from _guard import require_local_db
require_local_db()

from flask import Blueprint, Response, jsonify, request

import solar_bp as sbp
from app import app
from rag import retriever


# ── Trace state ─────────────────────────────────────────────────────────────
# One global trace rather than a per-request map: the route already allows only
# one in-flight turn per session (_claim_session_slot), and this is a
# single-operator tool. Lock-guarded anyway, because the route runs the topic
# gate on a worker thread — the writes genuinely are concurrent.
_trace = {"seq": 0, "events": [], "turn": {}}
_trace_lock = threading.Lock()


def _reset_trace(user_msg):
    with _trace_lock:
        _trace["events"] = []
        _trace["turn"] = {"user_msg": user_msg}
        _trace["seq"] += 1


def _note(kind, **payload):
    with _trace_lock:
        _trace["events"].append(dict(kind=kind, **payload))
        _trace["seq"] += 1


def _set(**payload):
    with _trace_lock:
        _trace["turn"].update(payload)
        _trace["seq"] += 1


def _timed(fn, kind, summarize=None):
    """Wrap fn so every call records its wall time and, optionally, a summary
    of what it returned. The wrapper is assigned back onto the solar_bp module:
    the route calls these by global name, so the lookup resolves to the wrapper
    at call time without the route itself knowing.
    """
    def wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            out = fn(*a, **kw)
        except Exception as e:
            _note(kind, ms=round((time.perf_counter() - t0) * 1000),
                  error=f"{type(e).__name__}: {e}")
            raise
        ms = round((time.perf_counter() - t0) * 1000)
        info = {}
        if summarize:
            try:
                info = summarize(out) or {}
            except Exception as e:      # instrumentation must never break a turn
                info = {"error": f"trace: {type(e).__name__}: {e}"}
        _note(kind, ms=ms, **info)
        return out
    wrapper.__name__ = getattr(fn, "__name__", kind)
    return wrapper


def _summarize_gate(out):
    canned, sources, context_section = out
    if canned in (sbp._CANNED_OFF_TOPIC_EN, sbp._CANNED_OFF_TOPIC_TL):
        outcome = "off_topic"
    elif canned in (sbp._CANNED_NO_INFO_EN, sbp._CANNED_NO_INFO_TL):
        outcome = "on_topic_zero_sources"
    elif canned is not None:
        outcome = "canned_other"
    else:
        outcome = "on_topic"
    _set(gate_outcome=outcome,
         context_chars=len(context_section or ""),
         sources=[{"title": s["title"], "source_ref": s["source_ref"],
                   "topic": s["topic"], "score": s["score"],
                   "chars": len(s["content"])} for s in sources])
    return {"outcome": outcome, "n_sources": len(sources)}


def _summarize_extract(out):
    ok, fields = out
    banked = {k: v for k, v in (fields or {}).items() if v is not None}
    _set(extracted=banked, extract_ok=bool(ok))
    return {"ok": bool(ok), "fields": sorted(banked.keys())}


def _install_tracing():
    sbp._ai_extract          = _timed(sbp._ai_extract, "extract", _summarize_extract)
    sbp._is_on_topic         = _timed(sbp._is_on_topic, "llm_topic_gate")
    sbp._gate_and_retrieve   = _timed(sbp._gate_and_retrieve, "gate_and_retrieve", _summarize_gate)
    sbp._answer_general_turn = _timed(sbp._answer_general_turn, "chat_general")
    sbp._answer_numeric_turn = _timed(sbp._answer_numeric_turn, "chat_numeric")

    # These three are called from inside the two answer turns, so they fire
    # nested within the timings above rather than as separate steps.
    _calc = sbp._run_preview_calc

    def calc(collected):
        out = _calc(collected)
        _set(calc=out if isinstance(out, dict) else None)
        return out
    sbp._run_preview_calc = calc

    _build = sbp._build_grounded_system

    def build(*a, **kw):
        out = _build(*a, **kw)
        _set(system_prompt=out)
        return out
    sbp._build_grounded_system = build

    # Flask dispatches through app.view_functions, so wrapping the entry gives
    # a clean per-turn reset boundary plus the final response body without
    # having to re-derive it.
    original_view = app.view_functions["solar.solar_chat_msg"]

    def traced_view(*a, **kw):
        body = request.get_json(force=True, silent=True) or {}
        _reset_trace(str(body.get("user_message", ""))[:500])
        t0 = time.perf_counter()
        resp = original_view(*a, **kw)
        total = round((time.perf_counter() - t0) * 1000)

        payload = resp[0] if isinstance(resp, tuple) else resp
        try:
            data = payload.get_json()
        except Exception:
            data = None
        if isinstance(data, dict):
            _set(answer=data.get("text", ""), collected=data.get("collected", {}),
                 q_index=data.get("q_index"), cancelled=bool(data.get("cancelled")))
        _set(total_ms=total)
        return resp

    traced_view.__name__ = "solar_chat_msg"
    app.view_functions["solar.solar_chat_msg"] = traced_view


def _config():
    return {
        "text_provider": sbp.TEXT_PROVIDER,
        "chat_model": (sbp.LM_STUDIO_TEXT_MODEL if sbp.TEXT_PROVIDER == "lmstudio"
                        else sbp.GROQ_MODEL),
        "lm_studio_url": sbp.LM_STUDIO_URL,
        "embed_provider": os.getenv("EMBED_PROVIDER", "local_cpu"),
        "embed_model": retriever.EMBED_MODEL,
        "rag_min_score": retriever.RAG_MIN_SCORE,
        "rag_cache_ttl": retriever.RAG_CACHE_TTL,
    }


# ── Dev-only routes ─────────────────────────────────────────────────────────
dev_bp = Blueprint("dev", __name__)


@dev_bp.route("/dev/trace/latest")
def trace_latest():
    with _trace_lock:
        return jsonify({"seq": _trace["seq"], "turn": _trace["turn"],
                        "events": list(_trace["events"])})


@dev_bp.route("/dev/chat")
def dev_chat():
    return Response(_PAGE.replace("__CONFIG__", json.dumps(_config())),
                    mimetype="text/html")


# Served as a plain string, not render_template_string: the page is inseparable
# from the harness, and Jinja would have to be escaped around the JS anyway.
_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Solara dev harness</title>
<style>
  :root { --bg:#0e1113; --panel:#161b1e; --line:#242c31; --fg:#d7dee3;
          --dim:#7d8b94; --accent:#5fb8a0; --warn:#d8a657; --bad:#d87b7b; }
  * { box-sizing:border-box; }
  body { margin:0; height:100vh; display:flex; background:var(--bg); color:var(--fg);
         font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }
  #left { flex:1 1 56%; border-right:1px solid var(--line); display:flex;
          flex-direction:column; min-width:0; }
  #left iframe { flex:1; width:100%; border:0; background:#fff; }
  #right { flex:1 1 44%; overflow-y:auto; padding:14px 16px; min-width:0; }
  .bar { display:flex; flex-wrap:wrap; gap:4px 14px; padding:7px 12px;
         border-bottom:1px solid var(--line); background:var(--panel);
         font-size:12px; color:var(--dim); }
  .bar b { color:var(--fg); font-weight:600; }
  h2 { font-size:11px; letter-spacing:.11em; text-transform:uppercase; color:var(--dim);
       margin:18px 0 7px; font-weight:600; border-bottom:1px solid var(--line);
       padding-bottom:5px; }
  h2:first-child { margin-top:0; }
  .kv { display:grid; grid-template-columns:auto 1fr; gap:2px 12px; }
  .kv span:nth-child(odd) { color:var(--dim); }
  .src { display:flex; gap:9px; align-items:baseline; padding:4px 0;
         border-bottom:1px solid #1c2226; }
  .score { color:var(--accent); font-variant-numeric:tabular-nums; min-width:4.2em; }
  .src .t { flex:1; min-width:0; overflow-wrap:anywhere; }
  .sub { color:var(--dim); font-size:11px; }
  .tag { font-size:10px; padding:1px 5px; border-radius:3px; white-space:nowrap;
         background:#1f272c; color:var(--dim); }
  .pill { display:inline-block; padding:2px 8px; border-radius:3px; background:#1f272c; }
  .pill.ok { background:#1b3a33; color:var(--accent); }
  .pill.warn { background:#3a3220; color:var(--warn); }
  .ev { display:flex; justify-content:space-between; gap:10px; padding:2px 0; }
  .ev .ms { color:var(--accent); font-variant-numeric:tabular-nums; }
  .ev .err { color:var(--bad); }
  pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#11161a;
        border:1px solid var(--line); padding:9px; border-radius:4px; margin:0;
        max-height:340px; overflow-y:auto; font-size:12px; }
  details { margin-top:8px; }
  summary { cursor:pointer; color:var(--dim); font-size:12px; }
  .empty { color:var(--dim); font-style:italic; }
  .chip { display:inline-block; font-size:11px; padding:1px 6px; border-radius:3px;
          background:#1b3a33; color:var(--accent); margin:0 4px 4px 0; }
</style></head><body>
<div id="left">
  <div class="bar" id="lbar"></div>
  <iframe src="/solar/chat"></iframe>
</div>
<div id="right"><p class="empty">Send a message in the chat on the left.</p></div>
<script>
var CFG = __CONFIG__;
function E(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}

document.getElementById("lbar").innerHTML =
  "<span>chat <b>" + E(CFG.text_provider) + "</b> " + E(CFG.chat_model) + "</span>" +
  "<span>embed <b>" + E(CFG.embed_model) + "</b></span>" +
  "<span>min_score <b>" + E(CFG.rag_min_score) + "</b></span>" +
  "<span>cache_ttl <b>" + E(CFG.rag_cache_ttl) + "s</b></span>";

var lastSeq = -1;

function renderSources(t) {
  var all = t.sources || [];
  if (!all.length) {
    return '<p class="empty">no chunks scored above RAG_MIN_SCORE (' +
           E(CFG.rag_min_score) + ")</p>";
  }
  return all.map(function (s) {
    return '<div class="src"><span class="score">' + s.score.toFixed(4) + "</span>" +
           '<span class="t">' + E(s.title) +
           '<br><span class="sub">' + E(s.source_ref) + " &middot; " + s.chars + " chars</span></span>" +
           '<span class="tag">' + E(s.topic) + "</span></div>";
  }).join("");
}

function renderEvents(events) {
  if (!events.length) return '<p class="empty">none</p>';
  return events.map(function (e) {
    var extra = "";
    if (e.error) extra = '<span class="err">' + E(e.error) + "</span>";
    else if (e.outcome) extra = '<span class="sub">' + E(e.outcome) + " &middot; " + e.n_sources + " src</span>";
    else if (e.fields) extra = '<span class="sub">' + (e.fields.length ? E(e.fields.join(", ")) : "nothing") + "</span>";
    return '<div class="ev"><span>' + E(e.kind) + " " + extra +
           '</span><span class="ms">' + e.ms + " ms</span></div>";
  }).join("");
}

function gatePill(o) {
  if (o === "on_topic") return '<span class="pill ok">on_topic</span>';
  if (o === "off_topic") return '<span class="pill warn">off_topic &mdash; canned decline, no chat call</span>';
  if (o === "on_topic_zero_sources") return '<span class="pill warn">on_topic, 0 sources &mdash; canned &quot;no info&quot;</span>';
  if (o) return '<span class="pill">' + E(o) + "</span>";
  return '<span class="pill">not a question turn &mdash; gate and retrieval skipped</span>';
}

function render(d) {
  var t = d.turn || {};
  if (!t.user_msg && !t.answer) return;

  var coll = Object.keys(t.collected || {}).filter(function (k) {
    var v = t.collected[k];
    return v !== null && v !== "";
  });
  var ex = Object.keys(t.extracted || {});

  var h = "<h2>turn</h2><div class=\"kv\">" +
    "<span>you said</span><span>" + (E(t.user_msg) || '<span class="empty">(greeting)</span>') + "</span>" +
    "<span>total</span><span>" + (t.total_ms != null ? t.total_ms + " ms" : "running&hellip;") + "</span>" +
    "<span>q_index</span><span>" + E(t.q_index) + "</span></div>";

  h += "<h2>gate</h2>" + gatePill(t.gate_outcome);
  if (t.context_chars) {
    h += '<div class="kv" style="margin-top:6px"><span>CONTEXT</span><span>' +
         t.context_chars + " chars handed to the model</span></div>";
  }

  h += "<h2>retrieval</h2>" + renderSources(t);
  if ((t.sources || []).length) {
    h += '<p class="sub" style="margin:6px 0 0">All of the above went into CONTEXT. ' +
         "None of it is shown to the user — the chatbot has no Sources line.</p>";
  }

  // Only the AI extractor is traced. When it returns ok=false the route falls
  // back to the regex extractor, whose result shows up in "collected so far"
  // but not here — so this must not be read as "nothing was banked".
  h += "<h2>ai extraction</h2>" + (ex.length
    ? ex.map(function (k) { return '<span class="chip">' + E(k) + "=" + E(t.extracted[k]) + "</span>"; }).join("")
    : '<p class="empty">AI extractor banked nothing' +
      (t.extract_ok === false ? " (ok=false &mdash; route fell back to the regex extractor; see collected below)" : "") +
      "</p>");

  h += "<h2>collected so far</h2>" + (coll.length
    ? '<div class="kv">' + coll.map(function (k) {
        return "<span>" + E(k) + "</span><span>" + E(t.collected[k]) + "</span>";
      }).join("") + "</div>"
    : '<p class="empty">empty</p>');

  if (t.calc) {
    var rows = Object.keys(t.calc).filter(function (k) {
      return typeof t.calc[k] !== "object";
    });
    h += "<h2>preview calc (solar_engine)</h2><div class=\"kv\">" + rows.map(function (k) {
      return "<span>" + E(k) + "</span><span>" + E(t.calc[k]) + "</span>";
    }).join("") + "</div>";
  }

  h += "<h2>timings</h2>" + renderEvents(d.events || []);

  h += "<h2>answer</h2><pre>" + (E(t.answer) || "&hellip;") + "</pre>";
  if (t.system_prompt) {
    h += "<details><summary>system prompt actually sent (" + t.system_prompt.length +
         " chars)</summary><pre>" + E(t.system_prompt) + "</pre></details>";
  }

  document.getElementById("right").innerHTML = h;
}

function poll() {
  fetch("/dev/trace/latest", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.seq !== lastSeq) { lastSeq = d.seq; render(d); }
    })
    .catch(function () { /* app restarting — just keep polling */ })
    .then(function () { setTimeout(poll, 600); });
}
poll();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--provider", choices=["lmstudio", "groq"],
                    help="override TEXT_PROVIDER for this process "
                          "(default: whatever .env says, same as rag_eval.py)")
    args = ap.parse_args()

    if args.provider:
        sbp.TEXT_PROVIDER = args.provider

    _install_tracing()
    app.register_blueprint(dev_bp)

    cfg = _config()
    print(f"\n  Solara dev harness  ->  http://127.0.0.1:{args.port}/dev/chat")
    print(f"  chat   : {cfg['text_provider']} / {cfg['chat_model']}"
          + (f"  ({cfg['lm_studio_url']})" if cfg["text_provider"] == "lmstudio" else ""))
    print(f"  embed  : {cfg['embed_provider']} / {cfg['embed_model']}")
    print(f"  RAG    : min_score={cfg['rag_min_score']}  cache_ttl={cfg['rag_cache_ttl']}s\n")

    # debug=False: the reloader would re-import app.py (re-running init_db) in a
    # second process and install tracing on a module the serving process isn't
    # the one using.
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
