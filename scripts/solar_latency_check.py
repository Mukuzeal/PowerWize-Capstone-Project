"""solar_latency_check.py — Per-stage latency benchmark for a Solara turn.

Drives the real /solar/chat/msg route N times per representative turn type and
reports where the wall time actually goes, so "the chatbot feels slow" becomes a
number attached to a stage.

Reuses solar_chat_devapp's instrumentation rather than re-wrapping solar_bp
itself — the same reason rag_eval.py shares _gate_and_retrieve with production:
two copies of the tracing would drift.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_latency_check.py
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_latency_check.py --provider lmstudio -n 5

Run it once per provider and diff the two tables — that is the apples-to-apples
local-GPU vs Groq comparison. The stage breakdown is what makes the comparison
useful: a provider swap only moves the LLM stages, so if those are not where
your time is going, a faster model will not fix it.
"""
import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import solar_chat_devapp as harness   # also applies require_local_db()
import solar_bp as sbp
from rag.embeddings import embed

_HISTORY = [{"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hey! I'm Solara from EnergyWize."}]

# Each case is the shape of turn a real conversation actually produces, chosen
# because they take measurably different paths through the pipeline — not as a
# quality eval (that's rag_eval.py), purely to time each path.
CASES = [
    # Domain vocabulary present -> _has_topic_keyword hits -> the LLM topic gate
    # is skipped entirely, so this is the cheapest question path.
    {"name": "question, keyword hit (no LLM gate)",
     "msg": "How does net metering work in the Philippines?",
     "collected": {}},
    # No domain keyword -> the speculative LLM gate runs, overlapped with
    # extraction. Shows whether that overlap is actually hiding the gate's cost.
    {"name": "question, no keyword (LLM gate runs)",
     "msg": "Is it actually worth the money for a small place like mine?",
     "collected": {}},
    # Gate says off-topic -> canned reply, no chat LLM call at all. The floor.
    {"name": "off-topic (canned, no chat call)",
     "msg": "What is the best recipe for chicken adobo?",
     "collected": {}},
    # Plain field answer -> extraction banks a value, no retrieval.
    {"name": "field answer (extract, no retrieval)",
     "msg": "My monthly bill is around 5000 pesos",
     "collected": {}},
    # Numeric question with enough banked to run the real sizing engine ->
    # _answer_numeric_turn instead of _answer_general_turn.
    {"name": "numeric question (preview calc path)",
     "msg": "So how big a system would I need and what would it cost?",
     "collected": {"monthly_bill_php": "5000", "establishment_type": "residential",
                    "name": "Test User", "grid_connection": "grid_tie"}},
]


def _client():
    harness._install_tracing()
    harness.app.register_blueprint(harness.dev_bp)
    # The route is CSRF-protected and rightly so; this harness drives it
    # directly rather than through a browser, so there is no token to carry.
    harness.app.config["WTF_CSRF_ENABLED"] = False
    return harness.app.test_client()


def _run_turn(client, case):
    t0 = time.perf_counter()
    r = client.post("/solar/chat/msg", json={
        "user_message": case["msg"], "messages": list(_HISTORY),
        "q_index": 0, "collected": dict(case["collected"]),
    })
    round_trip = (time.perf_counter() - t0) * 1000

    with harness._trace_lock:
        stages = {e["kind"]: e["ms"] for e in harness._trace["events"]}
        turn = dict(harness._trace["turn"])

    # A turn the provider refused is not a turn — it is a fast failure, and
    # averaging it in makes the provider look faster the harder you hammer it.
    # This is not hypothetical: the first version of this script fired runs
    # back to back, tripped Groq's rate limit, and reported a 468ms "chat"
    # stage that was really _RATE_LIMITED_MSG coming back from a refused call.
    answer = turn.get("answer") or ""
    if answer == sbp._RATE_LIMITED_MSG:
        verdict = "rate_limited"
    elif answer.startswith("[ERROR:"):
        verdict = "error"
    else:
        verdict = "ok"

    return {"round_trip": round_trip, "stages": stages,
            "gate": turn.get("gate_outcome"), "status": r.status_code,
            "verdict": verdict, "answer_chars": len(answer)}


def _fmt(values):
    if not values:
        return "      -"
    return f"{statistics.median(values):7.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["lmstudio", "groq"],
                    help="override TEXT_PROVIDER for this run (default: .env)")
    ap.add_argument("-n", type=int, default=3, help="runs per case (default 3)")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds to pause between turns (default 2.0). Cloud "
                          "providers rate-limit back-to-back calls, and a refused "
                          "call times fast — which silently flatters the provider.")
    args = ap.parse_args()

    if args.provider:
        sbp.TEXT_PROVIDER = args.provider

    client = _client()

    # Warm-up is not optional. The fastembed/ONNX model loads lazily on the
    # first embed() call in a process — hundreds of ms to seconds — and the
    # retriever's chunk matrix is fetched on first retrieve(). Measuring
    # without this attributes a one-time process cost to every turn and makes
    # retrieval look ~100x more expensive than it is.
    print(f"\nprovider={sbp.TEXT_PROVIDER}  n={args.n}  warming up (embedder + retrieval cache)...")
    t0 = time.perf_counter()
    embed(["warmup"], kind="query")
    warm_embed = (time.perf_counter() - t0) * 1000
    _run_turn(client, CASES[0])
    print(f"  embedding model load: {warm_embed:.0f} ms  "
          f"(paid once per process — see the cold-start note below)\n")

    rows, discarded = [], 0
    for case in CASES:
        runs = []
        for _ in range(args.n):
            runs.append(_run_turn(client, case))
            if args.delay:
                time.sleep(args.delay)
        good = [r for r in runs if r["verdict"] == "ok"]
        discarded += len(runs) - len(good)
        if not good:
            rows.append({"name": case["name"], "agg": {}, "total": [], "chars": 0,
                          "note": f"ALL {len(runs)} runs {runs[0]['verdict']}"})
            continue
        agg = {}
        for k in ("extract", "llm_topic_gate", "gate_and_retrieve",
                   "chat_general", "chat_numeric"):
            agg[k] = [r["stages"][k] for r in good if k in r["stages"]]
        rows.append({"name": case["name"], "agg": agg,
                      "total": [r["round_trip"] for r in good],
                      "chars": statistics.median(r["answer_chars"] for r in good),
                      "note": None if len(good) == len(runs)
                              else f"{len(runs) - len(good)}/{len(runs)} discarded"})

    hdr = ("extract", "llm_topic_gate", "gate_and_retrieve", "chat_general", "chat_numeric")
    labels = {"extract": "extract", "llm_topic_gate": "gate(llm)",
              "gate_and_retrieve": "retrieve", "chat_general": "chat",
              "chat_numeric": "chat(num)"}
    print(f"  median ms per stage ({args.n} runs/case)\n")
    print(f"  {'turn type':<40}" + "".join(f"{labels[h]:>11}" for h in hdr) + f"{'TOTAL':>11}{'chars':>8}")
    print("  " + "-" * (40 + 11 * len(hdr) + 19))
    for r in rows:
        line = f"  {r['name']:<40}"
        if not r["total"]:
            print(line + f"   {r['note']}")
            continue
        for h in hdr:
            line += f"{_fmt(r['agg'].get(h, [])):>11}"
        line += f"{statistics.median(r['total']):>11.0f}{r['chars']:>8.0f}"
        if r["note"]:
            line += f"   ({r['note']})"
        print(line)

    if discarded:
        print(f"\n  !! {discarded} run(s) discarded as rate-limited or errored — not timed.")
        print("     Raise --delay, or the surviving sample may be too small to trust.")

    print("\n  Reading this table:")
    print("   - extract and chat are sequential LLM calls on the critical path.")
    print("   - gate(llm) is launched in a thread before extract, so its cost is")
    print("     mostly hidden; what you pay is whatever outlasts extraction.")
    print("   - retrieve is embed-one-query + cached cosine. If it is not single")
    print("     digit ms, the chunk-matrix cache is off (RAG_CACHE_TTL=0) or cold.")
    print("   - a provider swap moves only extract/chat. Compare those columns")
    print("     between --provider groq and --provider lmstudio.\n")


if __name__ == "__main__":
    main()
