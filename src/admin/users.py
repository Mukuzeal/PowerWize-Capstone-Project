from flask import redirect, flash, session

from db import get_db, dict_cur, audit_log

from . import admin_bp


@admin_bp.route("/admin/user/archive/<int:user_id>", methods=["POST"])
def admin_archive_user(user_id):
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NOW() WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    audit_log(session.get("user_id"), "archive_user", "user", user_id, f"Archived {name}")
    flash(f"{name} has been archived.", "warning")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/unarchive/<int:user_id>", methods=["POST"])
def admin_unarchive_user(user_id):
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NULL WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    audit_log(session.get("user_id"), "unarchive_user", "user", user_id, f"Restored {name}")
    flash(f"{name} has been restored.", "success")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/delete/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT fname, lname, archived_at FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user or user["archived_at"] is None:
        cur.close(); conn.close()
        flash("Only archived users can be deleted.", "error")
        return redirect("/admin#users")
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cur.close(); conn.close()
    name = f"{user['fname']} {user['lname']}"
    audit_log(session.get("user_id"), "delete_user", "user", user_id, f"Permanently deleted {name}")
    flash(f"{name} has been permanently deleted.", "error")
    return redirect("/admin#users")
