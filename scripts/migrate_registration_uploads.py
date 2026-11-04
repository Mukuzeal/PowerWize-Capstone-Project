"""Phase 0 — move registration documents out of the public static tree.

Before: files sat in `static/uploads/`, which Flask serves to anyone at
/static/uploads/<name>, under names derived from the registrant
(`0_trainee_First_Last_valid_id.jpg`) — guessable, and colliding for two
people with the same name.

After: files sit in `uploads/registrations/` (outside static/, like the LMS
already does) under opaque random names, reachable only through
admin.admin_registration_document / admin_registration_selfie.

Deliberately conservative:
  * default mode is --dry-run; nothing is written without --apply
  * originals are COPIED, never moved or deleted
  * a manifest + a SQL rollback script are written before any DB change
  * --verify re-checks a completed migration
      exit 0 = clean, 1 = integrity failure, 2 = intact but cleanup outstanding
      (2 still stops an && chain; run the steps separately)

Run from anywhere:
    python scripts/migrate_registration_uploads.py            # dry run
    python scripts/migrate_registration_uploads.py --apply
    python scripts/migrate_registration_uploads.py --verify
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from _guard import require_local_db
from db import get_db, dict_cur

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OLD_DIR      = os.path.join(PROJECT_ROOT, 'static', 'uploads')
NEW_DIR      = os.path.join(PROJECT_ROOT, 'uploads', 'registrations')
BACKUP_ROOT  = os.path.join(PROJECT_ROOT, 'backups')
# Out of static/, so quarantined orphans stop being public the
# moment they move, without being destroyed.
QUARANTINE_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'quarantine')

# Exit codes.
#   NOTE: `&&` continues only on exit 0, so 2 does NOT keep a chain running.
#   Run each authorised step separately, or use an orchestrator that treats
#   2 as "proceed to the next step". The point of 2 is to let a human or a
#   script tell "succeeded, more to do" apart from "failed".
EXIT_CLEAN       = 0   # step succeeded and nothing is outstanding
EXIT_FAILED      = 1   # step refused or failed; operator must intervene
EXIT_OUTSTANDING = 2   # step succeeded, further authorised steps remain

DOC_COLUMNS = ("photo_id", "resume", "expired_doe", "valid_id", "selfie_with_id")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def _rows():
    conn = get_db(); cur = dict_cur(conn)
    cur.execute(
        "SELECT id, " + ", ".join(DOC_COLUMNS) + " FROM registrations ORDER BY id"
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def plan():
    """[(reg_id, column, old_name, new_name, status)] — status explains skips."""
    out = []
    for r in _rows():
        for col in DOC_COLUMNS:
            old = (r.get(col) or "").strip()
            if not old:
                continue
            if "/" in old or "\\" in old or old.startswith("."):
                out.append((r["id"], col, old, None, "SKIP:unsafe-name"))
                continue
            src = os.path.join(OLD_DIR, old)
            if not os.path.exists(src):
                out.append((r["id"], col, old, None, "SKIP:missing-on-disk"))
                continue
            ext = old.rsplit(".", 1)[-1].lower() if "." in old else "bin"
            out.append((r["id"], col, old, f"{uuid.uuid4().hex}.{ext}", "MIGRATE"))
    return out


def backup(items, stamp):
    """Copy every referenced file and dump the DB values. Returns the dir."""
    bdir = os.path.join(BACKUP_ROOT, f"phase0-{stamp}")
    fdir = os.path.join(bdir, "files")
    os.makedirs(fdir, exist_ok=True)

    manifest, failures = [], []
    for reg_id, col, old, new, status in items:
        if status != "MIGRATE":
            manifest.append({"reg_id": reg_id, "column": col, "old": old,
                             "new": None, "status": status})
            continue
        src = os.path.join(OLD_DIR, old)
        dst = os.path.join(fdir, old)
        try:
            shutil.copy2(src, dst)
            digest = _sha256(src)
            if _sha256(dst) != digest:
                failures.append(f"checksum mismatch backing up {old}")
            manifest.append({"reg_id": reg_id, "column": col, "old": old,
                             "new": new, "sha256": digest, "status": status})
        except Exception as e:
            failures.append(f"{old}: {type(e).__name__}: {e}")

    with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Plain SQL to put every column back exactly as it was.
    with open(os.path.join(bdir, "rollback.sql"), "w", encoding="utf-8") as f:
        f.write("-- Phase 0 rollback: restores registrations document columns.\n")
        f.write("-- Also copy backups/phase0-%s/files/* back into static/uploads/.\n"
                "BEGIN;\n" % stamp)
        for m in manifest:
            if m["status"] != "MIGRATE":
                continue
            val = m["old"].replace("'", "''")
            f.write("UPDATE registrations SET %s = '%s' WHERE id = '%s';\n"
                    % (m["column"], val, m["reg_id"].replace("'", "''")))
        f.write("COMMIT;\n")

    return bdir, manifest, failures


def apply_migration(manifest):
    os.makedirs(NEW_DIR, exist_ok=True)
    copied, updated, problems = 0, 0, []

    # Copy first; only touch the database once every file is safely in place.
    for m in manifest:
        if m["status"] != "MIGRATE":
            continue
        src = os.path.join(OLD_DIR, m["old"])
        dst = os.path.join(NEW_DIR, m["new"])
        try:
            shutil.copy2(src, dst)
            if _sha256(dst) != m["sha256"]:
                problems.append(f"checksum mismatch after copy: {m['old']}")
            else:
                copied += 1
        except Exception as e:
            problems.append(f"copy failed {m['old']}: {type(e).__name__}: {e}")

    if problems:
        return copied, 0, problems

    conn = get_db(); cur = conn.cursor()
    try:
        for m in manifest:
            if m["status"] != "MIGRATE":
                continue
            cur.execute(
                f"UPDATE registrations SET {m['column']} = %s "
                f"WHERE id = %s AND {m['column']} = %s",
                (m["new"], m["reg_id"], m["old"]))
            updated += cur.rowcount
        conn.commit()
    except Exception as e:
        conn.rollback()
        problems.append(f"DB update rolled back: {type(e).__name__}: {e}")
    finally:
        cur.close(); conn.close()

    return copied, updated, problems


def _contained(directory, name):
    """True if `name` resolves to a real file strictly inside `directory`."""
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, target]) != root:
        return False
    return os.path.isfile(target)


def _walk_files(directory):
    """Every file anywhere under `directory`, as paths relative to it.

    os.listdir() only sees the top level, so a nested folder of documents
    would pass a leftover sweep while still sitting in public storage.
    """
    out = []
    if not os.path.isdir(directory):
        return out
    for root, _dirs, files in os.walk(directory):
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), directory))
    return out


def _load_manifest(manifest_path):
    """(manifest, problems). The path is required — never guessed.

    Auto-picking "the newest backup" could silently verify against a later
    --backup-only run instead of the manifest the migration actually used,
    which is exactly the kind of mismatch verification exists to catch.
    """
    if not manifest_path:
        return [], ["NO MANIFEST SPECIFIED — pass --manifest <path to manifest.json>"]
    if not os.path.isfile(manifest_path):
        return [], [f"MANIFEST NOT FOUND: {manifest_path}"]
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f), []


def verify(manifest_path):
    """Confirm a finished migration actually moved the data and removed the
    public copies.

    Existence alone is not enough, so this checks four things:
      * every referenced document resolves INSIDE NEW_DIR (containment, so a
        stored '../x' cannot pass)
      * its bytes match the checksum recorded at backup time
      * the ORIGINAL file (old name, from the manifest) is gone from OLD_DIR
      * no file at all remains in OLD_DIR

    The last two are the point. An earlier version compared the *new* random
    name against OLD_DIR, which can never match, so it reported success while
    every original sensitive file was still sitting under static/.
    """
    manifest, problems = _load_manifest(manifest_path)
    by_new = {m["new"]: m for m in manifest if m.get("new")}

    for r in _rows():
        for col in DOC_COLUMNS:
            name = (r.get(col) or "").strip()
            if not name:
                continue
            ref = f"{r['id']}.{col}"
            if not _contained(NEW_DIR, name):
                problems.append(f"{ref} -> NOT a file inside uploads/registrations")
                continue
            m = by_new.get(name)
            if not m:
                problems.append(f"{ref} -> no manifest entry; checksum unverified")
                continue
            if _sha256(os.path.join(NEW_DIR, name)) != m["sha256"]:
                problems.append(f"{ref} -> CHECKSUM MISMATCH (corrupt or truncated copy)")
            # The real test: is the original still publicly placed?
            if os.path.exists(os.path.join(OLD_DIR, m["old"])):
                problems.append(f"{ref} -> ORIGINAL STILL IN static/uploads "
                                f"(public copy not removed)")

    # Whole tree, not just the top level.
    leftover = _walk_files(OLD_DIR)
    if leftover:
        problems.append(f"{len(leftover)} file(s) remain anywhere under "
                        f"static/uploads (referenced and/or orphaned)")

    return problems


# Problems that mean "migrated data is intact, cleanup is still outstanding".
# Anything NOT matching these is an integrity failure and must exit 1 — a
# checksum mismatch or a missing manifest is not a to-do item.
_CLEANUP_MARKERS = ("STILL IN static/uploads", "remain anywhere under")


def classify(problems):
    """(integrity_failures, outstanding_cleanup)."""
    cleanup = [p for p in problems if any(m in p for m in _CLEANUP_MARKERS)]
    failures = [p for p in problems if p not in cleanup]
    return failures, cleanup


def integrity_only(manifest_path):
    """verify() minus the 'originals removed' checks — the right bar straight
    after --apply, which deliberately leaves originals in place."""
    return [p for p in verify(manifest_path)
            if "STILL IN static/uploads" not in p and "remain anywhere under" not in p]


def _live_references():
    """Every filename any registration row currently points at, right now."""
    live = set()
    for r in _rows():
        for col in DOC_COLUMNS:
            v = (r.get(col) or "").strip()
            if v:
                live.add(v)
    return live


def orphans(manifest_path):
    """(orphan_relpaths, problems) — files under static/uploads that are
    unreferenced by the CURRENT database and absent from the manifest.

    Both conditions matter. The manifest is a snapshot: a registration
    submitted (or a document replaced) after the backup would be absent from
    it while being very much live. Classifying such a file as an orphan and
    quarantining it would break administrator access to a real applicant's
    document — so a file still referenced by the database is never an orphan,
    and its absence from the manifest is reported as a stale-manifest error
    rather than silently tolerated.

    These files are NOT backed up by backup(), which only walks
    database-referenced documents, so they must never reach the purge path.
    """
    manifest, problems = _load_manifest(manifest_path)
    if problems:
        return [], problems

    known = {m["old"] for m in manifest if m.get("old")}
    live  = _live_references()
    on_disk = set(_walk_files(OLD_DIR))

    # Referenced by the database but missing from the manifest => the
    # manifest no longer describes reality. Refuse rather than guess.
    stale = sorted((live & on_disk) - known)
    if stale:
        # Recovery advice depends on whether the migration has already run.
        # Before it has, a fresh snapshot is simply a better manifest. After
        # it has, taking a new snapshot would record the CURRENT state and
        # lose the old->new filename mapping the first manifest holds — which
        # is the only thing that can roll the migration back or finish it.
        migrated = any(m.get("new") and _contained(NEW_DIR, m["new"])
                       for m in manifest)
        if migrated:
            problems.append(
                f"STALE MANIFEST: {len(stale)} file(s) are referenced by the "
                f"database but absent from this manifest, and this migration "
                f"has ALREADY been applied. Do NOT take a new snapshot — it "
                f"would not preserve the old->new mapping needed to finish or "
                f"roll back. STOP and reconcile these files against the "
                f"existing manifest by hand.")
        else:
            problems.append(
                f"STALE MANIFEST: {len(stale)} file(s) are referenced by the "
                f"database but absent from this manifest, and no migration "
                f"has been applied from it yet. Pause submissions, re-run "
                f"--backup-only, and use the new manifest throughout.")
        return [], problems

    return sorted(on_disk - known - live), []


def quarantine_orphans(manifest_path, stamp):
    """Back up, inventory, then MOVE unreferenced files out of public storage.

    Deliberately a move into uploads/quarantine/<stamp>/ rather than a delete:
    nothing in the database points at these, but that is not the same as
    knowing they are worthless — they may be abandoned submissions containing
    real identity documents. Moving them ends the public exposure while the
    retention decision is still open.
    """
    items, problems = orphans(manifest_path)
    if problems:
        return None, problems
    if not items:
        return {"moved": [], "backup": None, "dest": None}, []

    bdir = os.path.join(BACKUP_ROOT, f"phase0-orphans-{stamp}")
    fdir = os.path.join(bdir, "files")
    dest = os.path.join(QUARANTINE_DIR, stamp)
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(dest, exist_ok=True)

    inventory, failures, moved = [], [], []

    # Back up and checksum-verify EVERY file first; move nothing until the
    # whole set is safely copied.
    for rel in items:
        src = os.path.join(OLD_DIR, rel)
        bdst = os.path.join(fdir, rel)
        os.makedirs(os.path.dirname(bdst), exist_ok=True)
        try:
            shutil.copy2(src, bdst)
            digest = _sha256(src)
            if _sha256(bdst) != digest:
                failures.append(f"checksum mismatch backing up orphan {rel}")
            inventory.append({"path": rel, "sha256": digest,
                              "bytes": os.path.getsize(src)})
        except Exception as e:
            failures.append(f"{rel}: {type(e).__name__}: {e}")

    with open(os.path.join(bdir, "orphan_inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)

    if failures:
        return None, failures

    # Re-check the live database per file, immediately before each move.
    #
    # This NARROWS the window between "confirmed unreferenced" and "moved";
    # it does not close it. A reference created between the check and the
    # move is still possible, so pausing registration submissions and
    # document edits for the whole sequence remains REQUIRED, not advisory.
    by_digest = {i["path"]: i["sha256"] for i in inventory}
    for rel in items:
        if rel in _live_references():
            failures.append(f"{rel}: became database-referenced since listing — not moved")
            continue
        src = os.path.join(OLD_DIR, rel)
        qdst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(qdst), exist_ok=True)
        try:
            shutil.move(src, qdst)
            # Verify the destination, not just the absence of an exception:
            # a short write or a crossed-device copy can leave a truncated
            # file behind while move() reports success.
            if _sha256(qdst) != by_digest.get(rel):
                failures.append(f"{rel}: MOVED BUT CHECKSUM MISMATCH at destination "
                                f"— backup copy in {bdir} is authoritative")
            moved.append(rel)
        except Exception as e:
            failures.append(f"move failed {rel}: {type(e).__name__}: {e}")

    return {"moved": moved, "backup": bdir, "dest": dest,
            "not_moved": [r for r in items if r not in moved]}, failures


def purge_originals(manifest_path):
    """Delete ONLY the migrated originals named in `manifest_path`, and only
    where a checksum-matching backup copy exists.

    Scoped this tightly on purpose. An earlier version deleted everything
    os.listdir() returned, while backup() had copied only the
    database-referenced documents — so every unreferenced orphan would have
    been destroyed with no backup at all. Orphans now go through
    quarantine_orphans() instead, and anything not individually verified here
    is left strictly alone.
    """
    problems = integrity_only(manifest_path)
    if problems:
        return None, problems

    manifest, mproblems = _load_manifest(manifest_path)
    if mproblems:
        return None, mproblems

    bdir = os.path.dirname(os.path.abspath(manifest_path))
    targets = [m for m in manifest if m.get("status") == "MIGRATE" and m.get("old")]

    # Every deletion target must satisfy THREE conditions, checked per file:
    #   a) a backup exists whose bytes match the manifest
    #   b) the original still resolves strictly inside OLD_DIR
    #   c) the original's CURRENT bytes still match the manifest
    #
    # (c) is the one that is easy to miss: verifying only the backup proves a
    # copy was taken at some point, not that the file about to be deleted is
    # that same copy. A document re-uploaded after the backup would otherwise
    # be destroyed with no backup of its current contents.
    unverified = []
    for m in targets:
        bcopy = os.path.join(bdir, "files", m["old"])
        if not os.path.isfile(bcopy):
            unverified.append(f"{m['old']}: no backup copy in {bdir}")
            continue
        if _sha256(bcopy) != m["sha256"]:
            unverified.append(f"{m['old']}: backup checksum mismatch")
            continue
        src = os.path.join(OLD_DIR, m["old"])
        if not os.path.exists(src):
            continue                       # already gone; nothing to delete
        if not _contained(OLD_DIR, m["old"]):
            unverified.append(f"{m['old']}: resolves outside static/uploads — refusing")
            continue
        if _sha256(src) != m["sha256"]:
            unverified.append(f"{m['old']}: ORIGINAL CHANGED since backup "
                              f"(current bytes are not backed up) — refusing")
    if unverified:
        return None, unverified

    removed, failures = [], []
    for m in targets:
        src = os.path.join(OLD_DIR, m["old"])
        if not os.path.isfile(src):
            continue           # already gone; nothing to do
        try:
            os.remove(src)
            removed.append(m["old"])
        except Exception as e:
            failures.append(f"delete failed {m['old']}: {type(e).__name__}: {e}")

    left, _ = orphans(manifest_path)
    return {"removed": removed, "orphans_left": left}, failures


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply",  action="store_true", help="perform the migration")
    g.add_argument("--verify", action="store_true", help="check a finished migration")
    g.add_argument("--backup-only", action="store_true",
                   help="take and checksum-verify a backup, change nothing else")
    g.add_argument("--purge-originals", action="store_true",
                   help="DELETE only the migrated originals named in --manifest "
                        "(orphans are never touched; use --quarantine-orphans)")
    g.add_argument("--quarantine-orphans", action="store_true",
                   help="back up, inventory and MOVE unreferenced files out of "
                        "static/uploads, pending a retention decision")
    ap.add_argument("--manifest", help="path to the migration's manifest.json "
                                       "(required by --verify / --purge-originals "
                                       "/ --quarantine-orphans)")
    args = ap.parse_args()

    needs_manifest = args.verify or args.purge_originals or args.quarantine_orphans
    if needs_manifest and not args.manifest:
        sys.exit("--manifest <path to manifest.json> is required for this "
                 "command. It is never guessed: verifying against a later "
                 "--backup-only run instead of the migration's own manifest "
                 "would hide exactly the mismatch this is meant to catch.")

    if args.quarantine_orphans:
        require_local_db()
        items, problems = orphans(args.manifest)
        if problems:
            for p in problems:
                print("  FAIL", p)
            sys.exit(1)
        print(f"unreferenced files to quarantine: {len(items)}")
        if not items:
            print("nothing to do.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        result, failures = quarantine_orphans(args.manifest, stamp)
        # Always report what actually moved, failure or not — a partial move
        # leaves the directory in a mixed state and the operator needs the
        # exact list to reason about it.
        if result:
            print(f"backed up + inventoried: {result['backup']}")
            print(f"moved {len(result['moved'])} file(s) to {result['dest']}")
            for rel in result["moved"]:
                print(f"    moved     {rel}")
            for rel in result.get("not_moved", []):
                print(f"    NOT moved {rel}")
        if failures:
            print("QUARANTINE INCOMPLETE:")
            for f in failures:
                print("   ", f)
            print("Backups are intact; re-run after resolving the above.")
            sys.exit(EXIT_FAILED)
        print("These are OUT of public storage but NOT deleted. Decide "
              "retention before removing them.")
        sys.exit(EXIT_CLEAN)

    if args.purge_originals:
        require_local_db()
        result, problems = purge_originals(args.manifest)

        # result is None  -> refused up front, genuinely nothing deleted.
        # result is a dict -> the deletion loop ran; `problems` may describe
        # individual failures AFTER some files were already removed. Saying
        # "nothing was deleted" in that case would be false and would send
        # the operator looking for files that are gone.
        if result is None:
            print("REFUSING to purge (nothing was deleted):")
            for p in problems:
                print("   ", p)
            sys.exit(EXIT_FAILED)

        if problems:
            print("PURGE PARTIALLY COMPLETED — state is mixed:")
            print(f"  deleted ({len(result['removed'])}):")
            for rel in result["removed"]:
                print(f"    {rel}")
            print(f"  failed to delete ({len(problems)}):")
            for p in problems:
                print(f"    {p}")
            print(f"  untouched orphans ({len(result['orphans_left'])}):")
            for rel in result["orphans_left"]:
                print(f"    {rel}")
            print(f"\nBackups remain in the manifest's directory. Re-run with "
                  f"the SAME --manifest to retry the failures; already-deleted "
                  f"files are skipped.")
            sys.exit(EXIT_FAILED)

        print(f"deleted {len(result['removed'])} migrated original(s), each "
              f"verified against its backup AND its current on-disk bytes.")
        if result["orphans_left"]:
            print(f"\n{len(result['orphans_left'])} unreferenced file(s) were "
                  f"NOT deleted — they have no backup and no retention "
                  f"decision. Run --quarantine-orphans next.")
        rfail, rcleanup = classify(verify(args.manifest))
        for p in rfail:
            print("  INTEGRITY:", p)
        for p in rcleanup:
            print("  OUTSTANDING:", p)
        if rfail:
            print("VERIFY: integrity failure after purge — stop and reconcile.")
            sys.exit(EXIT_FAILED)
        # The purge itself succeeded; remaining orphans are expected work, not
        # an error. The distinct code lets an orchestrator tell the two apart
        # — it does NOT make `&&` continue, since `&&` requires exit 0.
        if rcleanup:
            print(f"VERIFY: {len(rcleanup)} item(s) outstanding — purge "
                  f"succeeded, Phase 0 not yet complete.")
            sys.exit(EXIT_OUTSTANDING)
        print("VERIFY: OK — Phase 0 data migration complete")
        sys.exit(EXIT_CLEAN)

    if args.backup_only:
        items = plan()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bdir, manifest, failures = backup(items, stamp)
        migrated = [m for m in manifest if m["status"] == "MIGRATE"]
        print(f"backup: {bdir}")
        print(f"files backed up and checksum-verified: {len(migrated)}")
        print(f"rollback script: {os.path.join(bdir, 'rollback.sql')}")
        if failures:
            for f in failures:
                print("  FAIL", f)
            sys.exit(1)
        print("backup OK — no files or database rows were modified.")
        return

    if args.verify:
        problems = verify(args.manifest)
        for p in problems:
            print("  FAIL", p)
        failures, cleanup = classify(problems)
        if failures:
            print(f"VERIFY: {len(failures)} INTEGRITY FAILURE(S) — migrated "
                  f"data cannot be trusted. Do not proceed.")
            sys.exit(EXIT_FAILED)
        if cleanup:
            print(f"VERIFY: migration data intact; {len(cleanup)} cleanup "
                  f"item(s) outstanding.")
            sys.exit(EXIT_OUTSTANDING)
        print("VERIFY: OK — all references resolve privately")
        sys.exit(EXIT_CLEAN)

    items = plan()
    migrate = [i for i in items if i[4] == "MIGRATE"]
    skips   = [i for i in items if i[4] != "MIGRATE"]

    print(f"referenced documents : {len(items)}")
    print(f"  to migrate         : {len(migrate)}")
    print(f"  skipped            : {len(skips)}")
    for reg_id, col, old, _new, status in skips:
        print(f"    {status:24} {reg_id}.{col}")

    orphans = []
    if os.path.isdir(OLD_DIR):
        referenced = {i[2] for i in items}
        orphans = sorted(set(os.listdir(OLD_DIR)) - referenced)
    print(f"  unreferenced files in static/uploads: {len(orphans)} "
          f"(left untouched; review before deleting)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to migrate.")
        return

    require_local_db()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir, manifest, failures = backup(items, stamp)
    print(f"\nbackup: {bdir}")
    if failures:
        print("BACKUP INCOMPLETE — aborting before any change:")
        for f in failures:
            print("   ", f)
        sys.exit(1)
    print("backup verified by checksum.")

    copied, updated, problems = apply_migration(manifest)
    print(f"files copied: {copied}   db rows updated: {updated}")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("   ", p)
        print(f"Rollback: psql -f {os.path.join(bdir, 'rollback.sql')}")
        sys.exit(1)

    manifest_path = os.path.join(bdir, "manifest.json")
    remaining = integrity_only(manifest_path)
    if remaining:
        print("POST-VERIFY FAILED (copies are not trustworthy):")
        for p in remaining:
            print("   ", p)
        print(f"Rollback: psql -f {os.path.join(bdir, 'rollback.sql')}")
        sys.exit(1)
    print("integrity verify OK — every reference resolves privately and "
          "checksums match.")
    print("\nOriginals in static/uploads/ were NOT deleted, so the public "
          "copies still exist on disk (they are blocked at the web layer by "
          "app.py, not removed).")
    print("Phase 0 data security is NOT complete until you run:")
    print(f"    python scripts/migrate_registration_uploads.py "
          f"--purge-originals --manifest {manifest_path}")
    print(f"    python scripts/migrate_registration_uploads.py "
          f"--quarantine-orphans --manifest {manifest_path}")
    print(f"    python scripts/migrate_registration_uploads.py "
          f"--verify --manifest {manifest_path}")
    print("\nPause registration submissions for the whole sequence: the "
          "manifest is a snapshot, and a document uploaded midway would not "
          "be described by it.")


if __name__ == "__main__":
    main()
