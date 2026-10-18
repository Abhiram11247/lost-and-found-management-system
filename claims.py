"""Claim submission and the logged-in user's claim list."""

import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from database import get_db
from helpers import can_claim, login_required

bp = Blueprint("claims", __name__)


@bp.route("/items/<int:item_id>/claim", methods=("POST",))
@login_required
def submit(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)

    existing = db.execute(
        "SELECT * FROM claims WHERE item_id = ? AND user_id = ?", (item_id, g.user["id"])
    ).fetchone()
    allowed, reason = can_claim(item, g.user, existing)
    if not allowed:
        flash(reason, "error")
        return redirect(url_for("items.detail", item_id=item_id))

    message = request.form.get("message", "").strip()
    if len(message) > 1000:
        flash("Your message must be 1000 characters or fewer.", "error")
        return redirect(url_for("items.detail", item_id=item_id))

    try:
        with db:    # both statements succeed together or not at all
            db.execute(
                "INSERT INTO claims (item_id, user_id, message, status) "
                "VALUES (?, ?, ?, 'Pending')",
                (item_id, g.user["id"], message or None),
            )
            db.execute(
                "UPDATE items SET status = 'Claim Submitted' "
                "WHERE id = ? AND status IN ('Reported', 'Matched')",
                (item_id,),
            )
    except sqlite3.IntegrityError:
        flash("Your claim could not be submitted. Please try again.", "error")
    else:
        flash("Claim submitted. An administrator will review it.", "success")
        return redirect(url_for("claims.my_claims"))
    return redirect(url_for("items.detail", item_id=item_id))


@bp.route("/my/claims")
@login_required
def my_claims():
    rows = get_db().execute(
        "SELECT c.*, i.title AS item_title, i.status AS item_status, i.location "
        "FROM claims c JOIN items i ON i.id = c.item_id "
        "WHERE c.user_id = ? ORDER BY c.created_at DESC, c.id DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("my_claims.html", claims=rows)
