"""Home page, item listing/search, item details, and lost/found reporting."""

from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from database import get_db
from helpers import (CATEGORIES, ITEM_STATUSES, REPORT_TYPES, can_claim,
                     login_required)

bp = Blueprint("items", __name__)

# One expression used everywhere so templates can show "the date it was lost/found".
EVENT_DATE_SQL = (
    "CASE WHEN i.report_type = 'lost' THEN i.date_lost ELSE i.date_found END AS event_date"
)
BASE_SELECT = (
    f"SELECT i.*, {EVENT_DATE_SQL}, u.name AS reporter_name "
    "FROM items i JOIN users u ON u.id = i.reported_by "
)


def like_pattern(text):
    """Build a LIKE pattern, escaping % and _ so users can't inject wildcards."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@bp.route("/")
def index():
    db = get_db()
    stats = db.execute(
        "SELECT "
        "COALESCE(SUM(report_type = 'lost'), 0) AS lost, "
        "COALESCE(SUM(report_type = 'found'), 0) AS found, "
        "COALESCE(SUM(status = 'Returned'), 0) AS returned "
        "FROM items"
    ).fetchone()
    recent = db.execute(BASE_SELECT + "ORDER BY i.created_at DESC, i.id DESC LIMIT 6").fetchall()
    return render_template("index.html", stats=stats, recent=recent)


@bp.route("/items")
def list_items():
    q = request.args.get("q", "").strip()
    report_type = request.args.get("type", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")

    conditions, params = [], []
    if q:
        pattern = like_pattern(q)
        conditions.append(
            "(i.title LIKE ? ESCAPE '\\' OR i.description LIKE ? ESCAPE '\\' "
            "OR i.location LIKE ? ESCAPE '\\' OR i.category LIKE ? ESCAPE '\\')"
        )
        params += [pattern] * 4
    if report_type in REPORT_TYPES:
        conditions.append("i.report_type = ?")
        params.append(report_type)
    if category in CATEGORIES:
        conditions.append("i.category = ?")
        params.append(category)
    if status in ITEM_STATUSES:
        conditions.append("i.status = ?")
        params.append(status)

    sql = BASE_SELECT
    if conditions:
        sql += "WHERE " + " AND ".join(conditions) + " "
    sql += "ORDER BY i.created_at DESC, i.id DESC"
    results = get_db().execute(sql, params).fetchall()

    filters = {"q": q, "type": report_type, "category": category, "status": status}
    return render_template("items_list.html", items=results, filters=filters)


@bp.route("/items/<int:item_id>")
def detail(item_id):
    db = get_db()
    item = db.execute(BASE_SELECT + "WHERE i.id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)

    existing_claim = None
    if g.user:
        existing_claim = db.execute(
            "SELECT * FROM claims WHERE item_id = ? AND user_id = ?",
            (item_id, g.user["id"]),
        ).fetchone()
    allowed, reason = can_claim(item, g.user, existing_claim)
    return render_template(
        "item_detail.html", item=item, claim=existing_claim,
        can_claim=allowed, claim_reason=reason,
    )


def validate_report(form, report_type):
    """Return (cleaned_values, errors) for a lost/found report form."""
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "")
    location = form.get("location", "").strip()
    date_text = form.get("event_date", "").strip()

    errors = []
    if not 3 <= len(title) <= 100:
        errors.append("Title must be between 3 and 100 characters.")
    if not 10 <= len(description) <= 1000:
        errors.append("Description must be between 10 and 1000 characters.")
    if category not in CATEGORIES:
        errors.append("Choose a category from the list.")
    if not 2 <= len(location) <= 150:
        errors.append("Location must be between 2 and 150 characters.")

    action = "lost" if report_type == "lost" else "found"
    try:
        event_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        if event_date > date.today():
            errors.append(f"The date the item was {action} cannot be in the future.")
    except ValueError:
        errors.append(f"Enter the date the item was {action}.")

    values = {
        "title": title, "description": description, "category": category,
        "location": location, "event_date": date_text,
    }
    return values, errors


@bp.route("/report/<report_type>", methods=("GET", "POST"))
@login_required
def report(report_type):
    if report_type not in REPORT_TYPES:
        abort(404)

    values = {"title": "", "description": "", "category": "", "location": "", "event_date": ""}
    if request.method == "POST":
        values, errors = validate_report(request.form, report_type)
        if not errors:
            date_lost = values["event_date"] if report_type == "lost" else None
            date_found = values["event_date"] if report_type == "found" else None
            db = get_db()
            with db:
                cursor = db.execute(
                    "INSERT INTO items (title, description, category, report_type, "
                    "status, location, date_lost, date_found, reported_by) "
                    "VALUES (?, ?, ?, ?, 'Reported', ?, ?, ?, ?)",
                    (values["title"], values["description"], values["category"],
                     report_type, values["location"], date_lost, date_found,
                     g.user["id"]),
                )
            flash(f"Your {report_type} item report was submitted.", "success")
            return redirect(url_for("items.detail", item_id=cursor.lastrowid))
        for message in errors:
            flash(message, "error")

    return render_template(
        "report.html", report_type=report_type, values=values,
        today=date.today().isoformat(),
    )


@bp.route("/my/items")
@login_required
def my_items():
    rows = get_db().execute(
        f"SELECT i.*, {EVENT_DATE_SQL}, "
        "(SELECT COUNT(*) FROM claims c WHERE c.item_id = i.id) AS claim_count "
        "FROM items i WHERE i.reported_by = ? ORDER BY i.created_at DESC, i.id DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("my_items.html", items=rows)
