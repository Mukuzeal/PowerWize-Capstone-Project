"""Phase 0 regression checks — registration document security.

Guards the five properties Phase 0 is supposed to establish:

  1. uploads are no longer inside the public static tree
  2. an unauthenticated request cannot read a document
  3. a trainee session cannot read a document (403, not a login bounce)
  4. a client-supplied `<field>_existing` / selfie filename this session did
     not upload is rejected, so a registration cannot reference someone
     else's ID
  5. two registrants sharing a name get distinct files instead of silently
     overwriting each other

Uses Flask's test client — no network, no real browser. Importing `app` runs
init_db(), so a live database is required (same as every other script here).
Nothing is written to `registrations`; the upload-path tests hit utils
directly inside a request context.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\phase0_security_check.py
"""
import io
import shutil
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from werkzeug.datastructures import FileStorage, MultiDict

from app import app
from utils import save_file, owns_upload, remember_upload

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _png():
    # 1x1 PNG; enough to exercise the save path without shipping a real image.
    return (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00'
            b'\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


def _post_env(field, filename, extra=None):
    data = MultiDict()
    data.add(field, FileStorage(io.BytesIO(_png()), filename=filename,
                                content_type="image/png"))
    for k, v in (extra or {}).items():
        data.add(k, v)
    return data


print("\n1. Storage location")
upload_folder = app.config["UPLOAD_FOLDER"]
static_folder = app.static_folder
inside_static = os.path.commonpath([os.path.abspath(upload_folder),
                                    os.path.abspath(static_folder)]) == os.path.abspath(static_folder)
check("UPLOAD_FOLDER is outside static/", not inside_static, upload_folder)
check("UPLOAD_FOLDER is uploads/registrations",
      os.path.abspath(upload_folder) ==
      os.path.abspath(os.path.join(PROJECT_ROOT, "uploads", "registrations")))

print("\n2. Unauthenticated access")
client = app.test_client()
# Probe with a REAL legacy filename when one exists — a synthetic name would
# 404 simply by not existing and prove nothing. The name is never printed.
_legacy_dir = app.config.get("LEGACY_UPLOAD_FOLDER") or ""
_real = next((f for f in sorted(os.listdir(_legacy_dir))
              if os.path.isfile(os.path.join(_legacy_dir, f))), None) \
    if os.path.isdir(_legacy_dir) else None
legacy = client.get("/static/uploads/" + (_real or "nonexistent.jpg"))
check("legacy /static/uploads/<name> is not served", legacy.status_code == 404,
      f"HTTP {legacy.status_code}" + ("" if _real else " (no real file to probe)"))
doc = client.get("/admin/registration/ABC12345/document/valid_id")
check("document route redirects anonymous to login",
      doc.status_code in (301, 302) and "/auth" in doc.headers.get("Location", ""),
      f"HTTP {doc.status_code} -> {doc.headers.get('Location')}")

print("\n3. Wrong-role access")
with client.session_transaction() as s:
    s["user_id"], s["user_role"] = 999999, "trainee"
doc = client.get("/admin/registration/ABC12345/document/valid_id")
check("trainee session gets 403, not a login bounce", doc.status_code == 403,
      f"HTTP {doc.status_code}")

print("\n4. Field allowlist")
with client.session_transaction() as s:
    s["user_id"], s["user_role"] = 999999, "admin"
bad = client.get("/admin/registration/ABC12345/document/password_hash")
check("non-document column is rejected", bad.status_code == 404,
      f"HTTP {bad.status_code}")
trav = client.get("/admin/registration/ABC12345/document/..%2F..%2Fapp.py")
check("traversal in field is rejected", trav.status_code == 404,
      f"HTTP {trav.status_code}")

print("\n5. Unauthorized file reference (the *_existing vector)")
with app.test_request_context(
        "/training/submit", method="POST",
        data={"valid_id_existing": "0_trainee_Someone_Else_valid_id.jpg"}):
    stolen = save_file("valid_id")
check("foreign <field>_existing is refused", stolen is None, repr(stolen))

with app.test_request_context("/training/submit", method="POST",
                              data={"valid_id_existing": "../../src/app.py"}):
    trav2 = save_file("valid_id")
check("traversal via <field>_existing is refused", trav2 is None, repr(trav2))

with app.test_request_context("/x", method="POST"):
    remember_upload("mine.png", "valid_id")
    check("own upload accepted for its own field",
          owns_upload("mine.png", "valid_id"))
    check("own upload REJECTED for a different field",
          not owns_upload("mine.png", "photo_id"))
    check("foreign name is rejected",
          not owns_upload("0_trainee_Someone_Else_valid_id.jpg", "valid_id"))

print("\n6. Duplicate names do not collide")
os.makedirs(upload_folder, exist_ok=True)
saved = []
for _ in range(2):
    with app.test_request_context("/training/submit", method="POST",
                                  data=_post_env("valid_id", "id.png")):
        saved.append(save_file("valid_id"))
check("two uploads of the same source name get distinct files",
      saved[0] != saved[1] and all(saved), f"{saved[0]} vs {saved[1]}")
check("stored names are opaque (no registrant name embedded)",
      all(s and "_trainee_" not in s for s in saved))
for s in saved:
    p = os.path.join(upload_folder, s)
    if os.path.exists(p):
        os.remove(p)

print("\n7. Administrators can still read un-migrated documents")
# The regression this catches: pointing UPLOAD_FOLDER at the new directory
# makes every pre-Phase-0 document 404 in the review queue, silently breaking
# approvals for existing applicants.
check("LEGACY_UPLOAD_FOLDER is configured", bool(_legacy_dir), _legacy_dir or "")
from db import get_db, dict_cur

_c = get_db(); _cur = dict_cur(_c)
_cur.execute("SELECT id, valid_id FROM registrations "
             "WHERE valid_id IS NOT NULL AND valid_id <> '' LIMIT 1")
_row = _cur.fetchone(); _cur.close(); _c.close()

if _row and os.path.isfile(os.path.join(_legacy_dir, _row["valid_id"])):
    _url = f"/admin/registration/{_row['id']}/document/valid_id"
    _ac = app.test_client()
    with _ac.session_transaction() as s_:
        s_["user_id"], s_["user_role"] = 1, "admin"
    r = _ac.get(_url)
    check("admin CAN read an un-migrated legacy document",
          r.status_code == 200 and len(r.data) > 0, f"HTTP {r.status_code}")
    r2 = app.test_client().get(_url)
    check("the same document is NOT readable anonymously",
          r2.status_code in (301, 302) and "/auth" in r2.headers.get("Location", ""),
          f"HTTP {r2.status_code}")
    r3 = app.test_client().get("/static/uploads/" + _row["valid_id"])
    check("the same document is NOT reachable via /static/uploads",
          r3.status_code == 404, f"HTTP {r3.status_code}")
else:
    check("legacy fixture available to test against", False,
          "no un-migrated document found")

print("\n8. Migration consistency")
try:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
    import migrate_registration_uploads as mig
    items = mig.plan()
    unsafe = [i for i in items if i[4] == "SKIP:unsafe-name"]
    check("migration plan builds", True, f"{len(items)} referenced document(s)")
    check("no unsafe stored filenames", not unsafe,
          f"{len(unsafe)} unsafe" if unsafe else "")
    import inspect
    check("verify() requires an explicit manifest (no auto-pick)",
          inspect.signature(mig.verify).parameters["manifest_path"].default
          is inspect.Parameter.empty)
    check("verify() refuses to run without one",
          mig.verify(None) and "NO MANIFEST SPECIFIED" in mig.verify(None)[0])
except Exception as e:
    check("migration module checks", False, f"{type(e).__name__}: {e}")

print("\n9. Migration lifecycle rehearsal (sandbox — no real data touched)")
# Full apply -> verify -> purge -> quarantine cycle against temp directories
# and a stubbed row source, so the destructive paths are exercised for real
# without going near static/uploads or the registrations table.
import tempfile

try:
    import migrate_registration_uploads as mig

    sandbox = tempfile.mkdtemp(prefix="pw-phase0-")
    old_dir = os.path.join(sandbox, "static", "uploads")
    nested  = os.path.join(old_dir, "sub")
    os.makedirs(nested)

    # two referenced documents + two unreferenced orphans (one nested)
    for n in ("ref_a.jpg", "ref_b.jpg", "orphan_1.jpg"):
        with open(os.path.join(old_dir, n), "wb") as f:
            f.write(b"x" * 64)
    with open(os.path.join(nested, "orphan_nested.jpg"), "wb") as f:
        f.write(b"y" * 64)

    saved = (mig.OLD_DIR, mig.NEW_DIR, mig.BACKUP_ROOT, mig.QUARANTINE_DIR, mig._rows)
    mig.OLD_DIR        = old_dir
    mig.NEW_DIR        = os.path.join(sandbox, "uploads", "registrations")
    mig.BACKUP_ROOT    = os.path.join(sandbox, "backups")
    mig.QUARANTINE_DIR = os.path.join(sandbox, "uploads", "quarantine")
    mig._rows = lambda: [{"id": "SBX00001", "photo_id": "ref_a.jpg",
                          "resume": None, "expired_doe": None,
                          "valid_id": "ref_b.jpg", "selfie_with_id": None}]

    check("nested files are seen by the tree walk",
          "sub" + os.sep + "orphan_nested.jpg" in mig._walk_files(old_dir))

    items = mig.plan()
    bdir, manifest, failures = mig.backup(items, "sbx")
    mpath = os.path.join(bdir, "manifest.json")
    check("sandbox backup clean", not failures, "; ".join(failures))

    orph, _ = mig.orphans(mpath)
    check("orphans identified incl. nested", sorted(orph) ==
          sorted(["orphan_1.jpg", "sub" + os.sep + "orphan_nested.jpg"]), str(orph))

    # apply: copy files, then rewrite the stub's view of the DB
    copied, _updated, probs = mig.apply_migration(manifest)
    newnames = {m["column"]: m["new"] for m in manifest if m["status"] == "MIGRATE"}
    mig._rows = lambda: [{"id": "SBX00001", "photo_id": newnames["photo_id"],
                          "resume": None, "expired_doe": None,
                          "valid_id": newnames["valid_id"], "selfie_with_id": None}]
    check("sandbox apply copied both documents", copied == 2 and not probs,
          f"copied={copied} {probs}")
    check("integrity check clean after apply", not mig.integrity_only(mpath),
          str(mig.integrity_only(mpath)))

    res, probs = mig.purge_originals(mpath)
    check("purge removed exactly the 2 migrated originals",
          res and len(res["removed"]) == 2 and not probs, str(res))
    survivors = sorted(mig._walk_files(old_dir))
    check("PURGE LEFT BOTH ORPHANS INTACT (no unbacked deletion)",
          survivors == sorted(["orphan_1.jpg", "sub" + os.sep + "orphan_nested.jpg"]),
          str(survivors))
    check("purge reports the orphans as outstanding",
          len(res["orphans_left"]) == 2)

    # --- new safeguards -------------------------------------------------
    # (a) a changed original must never be deleted on the strength of a
    #     backup taken before the change
    sandbox2 = tempfile.mkdtemp(prefix="pw-phase0b-")
    old2 = os.path.join(sandbox2, "static", "uploads")
    os.makedirs(old2)
    with open(os.path.join(old2, "ref_c.jpg"), "wb") as f:
        f.write(b"original")
    mig.OLD_DIR     = old2
    mig.NEW_DIR     = os.path.join(sandbox2, "uploads", "registrations")
    mig.BACKUP_ROOT = os.path.join(sandbox2, "backups")
    mig._rows = lambda: [{"id": "SBX00002", "photo_id": "ref_c.jpg",
                          "resume": None, "expired_doe": None,
                          "valid_id": None, "selfie_with_id": None}]
    items2 = mig.plan()
    bdir2, man2, _ = mig.backup(items2, "sbx2")
    mpath2 = os.path.join(bdir2, "manifest.json")
    mig.apply_migration(man2)
    new2 = {m["column"]: m["new"] for m in man2 if m["status"] == "MIGRATE"}
    mig._rows = lambda: [{"id": "SBX00002", "photo_id": new2["photo_id"],
                          "resume": None, "expired_doe": None,
                          "valid_id": None, "selfie_with_id": None}]
    # someone re-uploads over the original after the backup was taken
    with open(os.path.join(old2, "ref_c.jpg"), "wb") as f:
        f.write(b"REPLACED CONTENT")
    res2, probs2 = mig.purge_originals(mpath2)
    check("purge REFUSES an original changed since backup",
          res2 is None and any("ORIGINAL CHANGED" in p for p in probs2),
          "; ".join(probs2)[:90])
    check("the changed original still exists (not deleted)",
          os.path.isfile(os.path.join(old2, "ref_c.jpg")))

    # (b) a file referenced by the CURRENT database but missing from the
    #     manifest must be reported as a stale manifest, never quarantined
    with open(os.path.join(old2, "late_submission.jpg"), "wb") as f:
        f.write(b"arrived after the backup")
    mig._rows = lambda: [{"id": "SBX00002", "photo_id": new2["photo_id"],
                          "resume": None, "expired_doe": None,
                          "valid_id": "late_submission.jpg",
                          "selfie_with_id": None}]
    orph2, oprob2 = mig.orphans(mpath2)
    check("live-but-unmanifested file triggers STALE MANIFEST",
          orph2 == [] and any("STALE MANIFEST" in p for p in oprob2),
          "; ".join(oprob2)[:90])
    qres2, qfail2 = mig.quarantine_orphans(mpath2, "sbx2")
    check("quarantine refuses to run on a stale manifest", qres2 is None)
    check("the late submission was NOT quarantined",
          os.path.isfile(os.path.join(old2, "late_submission.jpg")))

    mig.OLD_DIR, mig.NEW_DIR, mig.BACKUP_ROOT = old_dir, \
        os.path.join(sandbox, "uploads", "registrations"), \
        os.path.join(sandbox, "backups")
    mig._rows = lambda: [{"id": "SBX00001", "photo_id": newnames["photo_id"],
                          "resume": None, "expired_doe": None,
                          "valid_id": newnames["valid_id"], "selfie_with_id": None}]
    shutil.rmtree(sandbox2, ignore_errors=True)

    check("exit-code vocabulary is distinct",
          len({mig.EXIT_CLEAN, mig.EXIT_FAILED, mig.EXIT_OUTSTANDING}) == 3,
          f"{mig.EXIT_CLEAN}/{mig.EXIT_FAILED}/{mig.EXIT_OUTSTANDING}")

    # classify(): integrity failures must never be reported as mere cleanup
    f_, c_ = mig.classify([
        "X.valid_id -> CHECKSUM MISMATCH (corrupt or truncated copy)",
        "NO MANIFEST SPECIFIED — pass --manifest <path to manifest.json>",
        "A.photo_id -> ORIGINAL STILL IN static/uploads (public copy not removed)",
        "3 file(s) remain anywhere under static/uploads (referenced and/or orphaned)",
    ])
    check("checksum mismatch classified as INTEGRITY failure",
          any("CHECKSUM MISMATCH" in p for p in f_))
    check("missing manifest classified as INTEGRITY failure",
          any("NO MANIFEST" in p for p in f_))
    check("leftover originals classified as CLEANUP, not failure",
          len(c_) == 2 and len(f_) == 2, f"{len(f_)} fail / {len(c_)} cleanup")

    # stale-manifest advice must differ once a migration has been applied
    check("post-migration stale advice forbids a new snapshot",
          any("Do NOT take a new snapshot" in p for p in oprob2),
          "; ".join(oprob2)[:70])

    qres, qfail = mig.quarantine_orphans(mpath, "sbx")
    check("quarantine moved both orphans out of public storage",
          qres and len(qres["moved"]) == 2 and not qfail, str(qfail))
    check("public tree is now empty", mig._walk_files(old_dir) == [],
          str(mig._walk_files(old_dir)))
    check("quarantined orphans have a checksum inventory",
          os.path.isfile(os.path.join(qres["backup"], "orphan_inventory.json")))
    check("verify() is clean only at the very end", not mig.verify(mpath),
          str(mig.verify(mpath)))

    mig.OLD_DIR, mig.NEW_DIR, mig.BACKUP_ROOT, mig.QUARANTINE_DIR, mig._rows = saved
    shutil.rmtree(sandbox, ignore_errors=True)
except Exception as e:
    check("sandbox rehearsal", False, f"{type(e).__name__}: {e}")

failed = [r for r in results if not r[1]]
print(f"\n{'='*60}\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    for n, _, d in failed:
        print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
