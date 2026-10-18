"""Administrator dashboard, claim review and item management."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from database import get_db
from helpers import CLAIM_STATUSES, ITEM_STATUSES, ITEM_TRANSITIONS, admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def dashboard():
    db = get_db()
    counts = db.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM items) AS total_items, "
        "(SELECT COUNT(*) FROM items WHERE report_type = 'lost') AS lost_items, "
        "(SELECT COUNT(*) FROM items WHERE report_type = 'found') AS found_items, "
        "(SELECT COUNT(*) FROM items WHERE status = 'Returned') AS returned_items, "
        "(SELECT COUNT(*) FROM claims WHERE status = 'Pending') AS pending_claims, "
        "(SELECT COUNT(*) FROM users) AS users"
    ).fetchone()
    by_status = {
        row["status"]: row["n"]
        for row in db.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status")
    }
    pending = db.execute(
        "SELECT c.id, c.created_at, i.title AS item_title, u.name AS claimant "
        "FROM claims c JOIN items i ON i.id = c.item_id JOIN users u ON u.id = c.user_id "
        "WHERE c.status = 'Pending' ORDER BY c.created_at, c.id LIMIT 5"
    ).fetchall()
    return render_template("admin_dashboard.html", counts=counts, by_status=by_status, pending=pending)


@bp.route("/items")
@admin_required
def items():
    status = request.args.get("status", "")
    sql = ("SELECT i.*, u.name AS reporter_name, "
           "(SELECT COUNT(*) FROM claims c WHERE c.item_id = i.id) AS claim_count "
           "FROM items i JOIN users u ON u.id = i.reported_by ")
    params = []
    if status in ITEM_STATUSES:
        sql += "WHERE i.status = ? "
        params.append(status)
    sql += "ORDER BY i.created_at DESC, i.id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("admin_items.html", items=rows, status=status, transitions=ITEM_TRANSITIONS)


@bp.route("/items/<int:item_id>/status", methods=("POST",))
@admin_required
def update_item_status(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)

    new_status = request.form.get("status", "")
    if new_status not in ITEM_TRANSITIONS[item["status"]]:
        flash(f"An item that is '{item['status']}' cannot be changed to '{new_status}'.", "error")
    else:
        with db:
            db.execute("UPDATE items SET status = ? WHERE id = ?", (new_status, item_id))
        flash(f"Item status updated to '{new_status}'.", "success")
    return redirect(url_for("admin.items"))


@bp.route("/items/<int:item_id>/delete", methods=("POST",))
@admin_required
def delete_item(item_id):
    db = get_db()
    if db.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        abort(404)
    with db:    # claims for the item are removed too (ON DELETE CASCADE)
        db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    flash("Item report deleted.", "success")
    return redirect(url_for("admin.items"))


@bp.route("/claims")
@admin_required
def claims():
    status = request.args.get("status", "")
    sql = ("SELECT c.*, i.title AS item_title, u.name AS claimant "
           "FROM claims c JOIN items i ON i.id = c.item_id JOIN users u ON u.id = c.user_id ")
    params = []
    if status in CLAIM_STATUSES:
        sql += "WHERE c.status = ? "
        params.append(status)
    sql += "ORDER BY (c.status = 'Pending') DESC, c.created_at DESC, c.id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("admin_claims.html", claims=rows, status=status)


@bp.route("/claims/<int:claim_id>")
@admin_required
def claim_detail(claim_id):
    db = get_db()
    claim = db.execute(
        "SELECT c.*, u.name AS claimant, u.email AS claimant_email "
        "FROM claims c JOIN users u ON u.id = c.user_id WHERE c.id = ?", (claim_id,)
    ).fetchone()
    if claim is None:
        abort(404)
    item = db.execute(
        "SELECT i.*, u.name AS reporter_name, "
        "CASE WHEN i.report_type = 'lost' THEN i.date_lost ELSE i.date_found END AS event_date "
        "FROM items i JOIN users u ON u.id = i.reported_by WHERE i.id = ?", (claim["item_id"],)
    ).fetchone()
    others = db.execute(
        "SELECT c.id, c.status, u.name AS claimant FROM claims c "
        "JOIN users u ON u.id = c.user_id WHERE c.item_id = ? AND c.id != ?",
        (claim["item_id"], claim_id),
    ).fetchall()
    return render_template("admin_claim_detail.html", claim=claim, item=item, others=others)


@bp.route("/claims/<int:claim_id>/decision", methods=("POST",))
@admin_required
def decide(claim_id):
    db = get_db()
    claim = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None:
        abort(404)
    item = db.execute("SELECT * FROM items WHERE id = ?", (claim["item_id"],)).fetchone()
    decision = request.form.get("decision", "")

    if decision not in ("approve", "reject"):
        flash("Invalid decision.", "error")
    elif claim["status"] != "Pending":
        flash("This claim has already been decided.", "error")
    elif decision == "approve":
        if item["status"] in ("Claim Verified", "Returned"):
            flash("Another claim has already been approved for this item.", "error")
        else:
            with db:    # one transaction: all three updates or none
                db.execute("UPDATE claims SET status = 'Approved' WHERE id = ?", (claim_id,))
                db.execute(
                    "UPDATE claims SET status = 'Rejected' "
                    "WHERE item_id = ? AND id != ? AND status = 'Pending'",
                    (item["id"], claim_id),
                )
                db.execute("UPDATE items SET status = 'Claim Verified' WHERE id = ?", (item["id"],))
            flash("Claim approved. Other pending claims for this item were rejected.", "success")
    else:
        with db:
            db.execute("UPDATE claims SET status = 'Rejected' WHERE id = ?", (claim_id,))
            pending_left = db.execute(
                "SELECT COUNT(*) FROM claims WHERE item_id = ? AND status = 'Pending'",
                (item["id"],),
            ).fetchone()[0]
            if pending_left == 0 and item["status"] == "Claim Submitted":
                db.execute("UPDATE items SET status = 'Reported' WHERE id = ?", (item["id"],))
        flash("Claim rejected.", "success")

    return redirect(url_for("admin.claim_detail", claim_id=claim_id))
