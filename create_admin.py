"""Create an administrator account (or promote an existing user to admin).

Run from the project folder with the virtual environment active:
    python create_admin.py
"""

import getpass
import re

from werkzeug.security import generate_password_hash

from app import create_app
from database import get_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        email = input("Admin email: ").strip().lower()
        if not EMAIL_RE.match(email):
            print("That is not a valid email address.")
            return

        existing = db.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            answer = input(f"{existing['name']} already has an account. Make them an admin? (y/n): ")
            if answer.strip().lower() == "y":
                with db:
                    db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (existing["id"],))
                print("Done. That account is now an administrator.")
            return

        name = input("Admin name: ").strip()
        password = getpass.getpass("Password (at least 8 characters): ")
        if not name or len(password) < 8:
            print("A name and a password of at least 8 characters are required.")
            return
        with db:
            db.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, 'admin')",
                (name, email, generate_password_hash(password)),
            )
        print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()
