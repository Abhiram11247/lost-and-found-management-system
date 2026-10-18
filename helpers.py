"""Shared constants and small helper functions used by several modules."""

from functools import wraps

from flask import abort, flash, g, redirect, request, url_for

CATEGORIES = [
    "ID Card", "Wallet", "Books", "Electronics", "Keys",
    "Stationery", "Clothing", "Bags", "Other",
]
REPORT_TYPES = ("lost", "found")

ITEM_STATUSES = ["Reported", "Matched", "Claim Submitted", "Claim Verified", "Returned"]
CLAIM_STATUSES = ["Pending", "Approved", "Rejected"]

# Statuses an administrator may set BY HAND, keyed by the current status.
# "Claim Submitted" and "Claim Verified" are set automatically when a claim is
# submitted or approved, so they are not offered as manual choices.
ITEM_TRANSITIONS = {
    "Reported": ["Matched"],
    "Matched": ["Reported"],
    "Claim Submitted": [],          # resolved by approving/rejecting the claims
    "Claim Verified": ["Returned"],
    "Returned": [],
}


def login_required(view):
    """Redirect anonymous visitors to the login page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            next_url = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Allow administrators only. Enforced on the server, not just hidden in the UI."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            next_url = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=next_url))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def safe_next_url(target):
    """Only allow redirects to paths inside this site (prevents open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def can_claim(item, user, existing_claim):
    """Return (allowed, reason). `reason` explains a refusal."""
    if user is None:
        return False, "Log in to submit a claim."
    if user["role"] == "admin":
        return False, "Administrators review claims and cannot submit them."
    if item["report_type"] != "found":
        return False, "Claims can only be made on items that were reported as found."
    if item["reported_by"] == user["id"]:
        return False, "You cannot claim an item you reported yourself."
    if item["status"] in ("Claim Verified", "Returned"):
        return False, "This item is no longer open for claims."
    if existing_claim is not None:
        return False, "You have already submitted a claim for this item."
    return True, ""
