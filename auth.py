"""Registration, login and logout."""

import re
import sqlite3

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db
from helpers import safe_next_url

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("items.index"))

    form = {"name": "", "email": ""}
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        form = {"name": name, "email": email}

        errors = []
        if not name:
            errors.append("Name is required.")
        elif len(name) > 100:
            errors.append("Name must be 100 characters or fewer.")
        if not email:
            errors.append("Email is required.")
        elif len(email) > 254 or not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        elif password != confirm:
            errors.append("The two passwords do not match.")

        if not errors:
            db = get_db()
            try:
                with db:   # commits on success, rolls back on error
                    db.execute(
                        "INSERT INTO users (name, email, password, role) "
                        "VALUES (?, ?, ?, 'user')",
                        (name, email, generate_password_hash(password)),
                    )
            except sqlite3.IntegrityError:
                errors.append("An account with this email already exists.")
            else:
                flash("Registration successful. You can now log in.", "success")
                return redirect(url_for("auth.login"))

        for message in errors:
            flash(message, "error")

    return render_template("register.html", form=form)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("items.index"))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user is None or not check_password_hash(user["password"], password):
            # Same message for "no such user" and "wrong password" on purpose.
            flash("Invalid email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['name']}.", "success")
            next_url = safe_next_url(request.args.get("next"))
            if next_url:
                return redirect(next_url)
            if user["role"] == "admin":
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("items.index"))

    return render_template("login.html", email=email)


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("items.index"))
