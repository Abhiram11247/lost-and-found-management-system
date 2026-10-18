"""Lost & Found Management System - application entry point."""

import hmac
import os
import secrets

from flask import Flask, abort, g, render_template, request, session

import database

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def load_secret_key(app):
    """Use SECRET_KEY from the environment, else a key stored in instance/secret.key.

    The key file is created automatically the first time and is git-ignored,
    so no secret is ever written into the source code.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(app.instance_path, exist_ok=True)
    key_path = os.path.join(app.instance_path, "secret.key")
    if os.path.exists(key_path):
        with open(key_path, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def get_csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.path.join(BASE_DIR, "lost_and_found.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app)

    database.init_app(app)
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    from helpers import CATEGORIES, ITEM_STATUSES
    app.jinja_env.globals["CATEGORIES"] = CATEGORIES
    app.jinja_env.globals["ITEM_STATUSES"] = ITEM_STATUSES

    import admin
    import auth
    import claims
    import items

    app.register_blueprint(auth.bp)
    app.register_blueprint(items.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(admin.bp)

    @app.before_request
    def load_logged_in_user():
        """Look the user up on every request so role changes apply immediately."""
        g.user = None
        if request.endpoint == "static":
            return
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = database.get_db().execute(
                "SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if g.user is None:          # account no longer exists
                session.clear()

    @app.before_request
    def csrf_protect():
        """Reject every POST that does not carry this session's CSRF token."""
        if request.method == "POST" and not app.config.get("CSRF_DISABLED"):
            expected = session.get("_csrf", "")
            sent = request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected, sent):
                abort(400)

    messages = {
        400: ("Bad request", "The form could not be verified. Go back, refresh the page and try again."),
        403: ("Access denied", "You do not have permission to view this page."),
        404: ("Page not found", "We could not find what you were looking for."),
        500: ("Something went wrong", "An unexpected error occurred. Please try again later."),
    }

    def make_handler(code):
        def handler(error):
            title, text = messages[code]
            return render_template("error.html", code=code, title=title, text=text), code
        return handler

    for code in messages:
        app.register_error_handler(code, make_handler(code))

    return app


if __name__ == "__main__":
    # debug=True is for local development only - never use it when deploying.
    create_app().run(debug=True)
