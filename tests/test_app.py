"""Automated tests that use Flask's test client (fast, no browser needed).

Run from the project folder:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from database import get_db  # noqa: E402

PASSWORD = "Password123"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "test-key"})
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    # ---- helpers ----
    def query(self, sql, params=()):
        with self.app.app_context():
            return get_db().execute(sql, params).fetchall()

    def make_user(self, email, name="Test User", role="user"):
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute(
                    "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                    (name, email, generate_password_hash(PASSWORD), role),
                )

    def token(self):
        html = self.client.get("/items").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, url, data=None, follow=True):
        data = dict(data or {})
        data["csrf_token"] = self.token()
        return self.client.post(url, data=data, follow_redirects=follow)

    def login(self, email, password=PASSWORD):
        return self.post("/login", {"email": email, "password": password})

    def logout(self):
        return self.post("/logout")

    def report(self, report_type="found", title="Black wallet", **overrides):
        data = {
            "title": title, "description": "Black leather wallet with a student card",
            "category": "Wallet", "location": "Main library", "event_date": YESTERDAY,
        }
        data.update(overrides)
        return self.post(f"/report/{report_type}", data)


class RegistrationTests(BaseTestCase):
    def register(self, **overrides):
        data = {"name": "Asha", "email": "asha@uni.edu", "password": PASSWORD, "confirm_password": PASSWORD}
        data.update(overrides)
        return self.post("/register", data)

    def test_successful_registration_hashes_password(self):
        response = self.register()
        self.assertIn(b"Registration successful", response.data)
        rows = self.query("SELECT * FROM users WHERE email = 'asha@uni.edu'")
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["password"], PASSWORD)
        self.assertTrue(rows[0]["password"].startswith(("scrypt:", "pbkdf2:")))
        self.assertEqual(rows[0]["role"], "user")

    def test_duplicate_email_rejected_case_insensitively(self):
        self.register()
        response = self.register(email="ASHA@uni.edu")
        self.assertIn(b"already exists", response.data)
        self.assertEqual(len(self.query("SELECT id FROM users")), 1)

    def test_invalid_input_rejected(self):
        cases = [
            ({"name": ""}, b"Name is required"),
            ({"email": "not-an-email"}, b"valid email"),
            ({"password": "short", "confirm_password": "short"}, b"at least 8"),
            ({"confirm_password": "Different123"}, b"do not match"),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                self.assertIn(expected, self.register(**overrides).data)
        self.assertEqual(len(self.query("SELECT id FROM users")), 0)

    def test_cannot_register_as_admin(self):
        self.register(role="admin")
        self.assertEqual(self.query("SELECT role FROM users")[0]["role"], "user")


class AuthTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("user@uni.edu")

    def test_login_logout(self):
        self.assertIn(b"Welcome", self.login("user@uni.edu").data)
        self.assertIn(b"Log out", self.client.get("/").data)
        self.assertIn(b"logged out", self.logout().data)
        self.assertIn(b"Log in", self.client.get("/").data)

    def test_invalid_credentials(self):
        self.assertIn(b"Invalid email or password", self.login("user@uni.edu", "wrong-password").data)
        self.assertIn(b"Invalid email or password", self.login("nobody@uni.edu").data)

    def test_protected_pages_redirect_to_login(self):
        for url in ("/report/lost", "/report/found", "/my/claims", "/my/items", "/admin/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])

    def test_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/login", data={"email": "user@uni.edu", "password": PASSWORD})
        self.assertEqual(response.status_code, 400)

    def test_open_redirect_is_blocked(self):
        self.token()
        response = self.client.post(
            "/login?next=//evil.example",
            data={"email": "user@uni.edu", "password": PASSWORD, "csrf_token": self.token()},
        )
        self.assertNotIn("evil.example", response.headers["Location"])


class RoleTests(BaseTestCase):
    def test_regular_user_cannot_use_admin_pages(self):
        self.make_user("user@uni.edu")
        self.login("user@uni.edu")
        for url in ("/admin/", "/admin/items", "/admin/claims"):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post("/admin/items/1/delete", follow=False).status_code, 403)

    def test_admin_can_open_dashboard(self):
        self.make_user("admin@uni.edu", role="admin")
        self.login("admin@uni.edu")
        self.assertEqual(self.client.get("/admin/").status_code, 200)


class ItemTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("owner@uni.edu", name="Owner")
        self.login("owner@uni.edu")

    def test_report_found_and_lost_store_correct_dates(self):
        self.assertIn(b"submitted", self.report("found", "Found wallet").data)
        self.report("lost", "Lost keys", category="Keys")
        found, lost = self.query("SELECT * FROM items ORDER BY id")
        self.assertEqual((found["report_type"], found["date_found"], found["date_lost"]), ("found", YESTERDAY, None))
        self.assertEqual((lost["report_type"], lost["date_lost"], lost["date_found"]), ("lost", YESTERDAY, None))
        self.assertEqual(found["status"], "Reported")
        self.assertIsNotNone(found["created_at"])
        self.assertEqual(found["reported_by"], 1)

    def test_report_validation(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for overrides, expected in [
            ({"title": ""}, b"Title must be"),
            ({"description": "short"}, b"Description must be"),
            ({"category": "Spaceship"}, b"Choose a category"),
            ({"location": ""}, b"Location must be"),
            ({"event_date": tomorrow}, b"cannot be in the future"),
            ({"event_date": "garbage"}, b"Enter the date"),
        ]:
            with self.subTest(overrides=overrides):
                self.assertIn(expected, self.report(**overrides).data)
        self.assertEqual(len(self.query("SELECT id FROM items")), 0)

    def test_unknown_report_type_is_404(self):
        self.assertEqual(self.client.get("/report/stolen").status_code, 404)

    def test_search_and_filters(self):
        self.report("found", "Black wallet")
        self.report("lost", "Blue backpack", category="Bags", location="Canteen", description="Blue backpack with laptop")
        self.report("found", "Calculus textbook", category="Books", location="Room 204",
                    description="Thick maths textbook with a green cover")

        def titles(qs):
            html = self.client.get("/items" + qs).get_data(as_text=True)
            return re.findall(r"<h3>(.*?)</h3>", html)

        self.assertEqual(len(titles("")), 3)
        self.assertEqual(titles("?q=wallet"), ["Black wallet"])
        self.assertEqual(titles("?q=canteen"), ["Blue backpack"])      # matches location
        self.assertEqual(titles("?q=laptop"), ["Blue backpack"])       # matches description
        self.assertEqual(sorted(titles("?type=found")), ["Black wallet", "Calculus textbook"])
        self.assertEqual(titles("?category=Books"), ["Calculus textbook"])
        self.assertEqual(len(titles("?status=Returned")), 0)
        self.assertIn(b"No reports match", self.client.get("/items?q=zzzz").data)
        self.assertEqual(len(titles("?q=%25")), 0)                     # % is not a wildcard

    def test_detail_page_and_404(self):
        self.report("found", "Black wallet")
        self.assertIn(b"Black wallet", self.client.get("/items/1").data)
        self.assertEqual(self.client.get("/items/999").status_code, 404)

    def test_search_is_safe_against_sql_injection(self):
        self.report("found", "Black wallet")
        response = self.client.get("/items?q=' OR '1'='1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No reports match", response.data)


class ClaimTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("finder@uni.edu", name="Finder")
        self.make_user("owner@uni.edu", name="Owner")
        self.make_user("other@uni.edu", name="Other")
        self.make_user("admin@uni.edu", name="Admin", role="admin")
        self.login("finder@uni.edu")
        self.report("found", "Black wallet")        # item 1 (found)
        self.report("lost", "Lost keys", category="Keys")   # item 2 (lost)
        self.logout()

    def claim(self, item_id=1, message="It has my student card inside"):
        return self.post(f"/items/{item_id}/claim", {"message": message})

    def test_claim_submission_and_status(self):
        self.login("owner@uni.edu")
        response = self.claim()
        self.assertIn(b"Claim submitted", response.data)
        self.assertIn(b"Pending", response.data)
        claim = self.query("SELECT * FROM claims")[0]
        self.assertEqual((claim["item_id"], claim["user_id"], claim["status"]), (1, 2, "Pending"))
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Claim Submitted")

    def test_claim_rules(self):
        self.login("finder@uni.edu")
        self.assertIn(b"cannot claim an item you reported", self.claim().data)
        self.logout()
        self.login("owner@uni.edu")
        self.assertIn(b"only be made on items that were reported as found", self.claim(2).data)
        self.claim()
        self.assertIn(b"already submitted a claim", self.claim().data)
        self.assertEqual(self.client.get("/items/999").status_code, 404)
        self.assertEqual(self.post("/items/999/claim", {}, follow=False).status_code, 404)
        self.assertEqual(len(self.query("SELECT id FROM claims")), 1)

    def test_anonymous_cannot_claim(self):
        response = self.post("/items/1/claim", {"message": "mine"}, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.query("SELECT id FROM claims")), 0)

    def test_users_see_only_their_own_claims(self):
        self.login("owner@uni.edu")
        self.claim()
        self.logout()
        self.login("other@uni.edu")
        self.assertIn(b"haven't submitted any claims", self.client.get("/my/claims").data)
        self.logout()
        self.login("owner@uni.edu")
        self.assertIn(b"Black wallet", self.client.get("/my/claims").data)

    def test_admin_approval_flow(self):
        self.login("owner@uni.edu"); self.claim(); self.logout()
        self.login("other@uni.edu"); self.claim(); self.logout()
        self.login("admin@uni.edu")
        self.assertIn(b"Claim approved", self.post("/admin/claims/1/decision", {"decision": "approve"}).data)
        statuses = [r["status"] for r in self.query("SELECT status FROM claims ORDER BY id")]
        self.assertEqual(statuses, ["Approved", "Rejected"])         # the other pending claim is auto-rejected
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Claim Verified")
        self.assertIn(b"already been decided", self.post("/admin/claims/1/decision", {"decision": "reject"}).data)
        self.post("/admin/items/1/status", {"status": "Returned"})
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Returned")
        self.logout()
        self.login("owner@uni.edu")
        self.assertIn(b"Approved", self.client.get("/my/claims").data)
        self.login("other@uni.edu")   # (already logged in -> no-op) and Returned items refuse claims
        self.logout(); self.login("other@uni.edu")
        self.assertIn(b"Rejected", self.client.get("/my/claims").data)

    def test_admin_rejection_reopens_item(self):
        self.login("owner@uni.edu"); self.claim(); self.logout()
        self.login("admin@uni.edu")
        self.assertIn(b"Claim rejected", self.post("/admin/claims/1/decision", {"decision": "reject"}).data)
        self.assertEqual(self.query("SELECT status FROM claims")[0]["status"], "Rejected")
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Reported")

    def test_regular_user_cannot_decide_claims(self):
        self.login("owner@uni.edu"); self.claim()
        response = self.post("/admin/claims/1/decision", {"decision": "approve"}, follow=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.query("SELECT status FROM claims")[0]["status"], "Pending")

    def test_item_status_transitions(self):
        self.login("admin@uni.edu")
        self.post("/admin/items/1/status", {"status": "Matched"})
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Matched")
        self.assertIn(b"cannot be changed", self.post("/admin/items/1/status", {"status": "Returned"}).data)
        self.assertIn(b"cannot be changed", self.post("/admin/items/1/status", {"status": "Nonsense"}).data)
        self.assertEqual(self.query("SELECT status FROM items WHERE id = 1")[0]["status"], "Matched")

    def test_returned_item_cannot_be_claimed(self):
        self.login("owner@uni.edu"); self.claim(); self.logout()
        self.login("admin@uni.edu")
        self.post("/admin/claims/1/decision", {"decision": "approve"})
        self.post("/admin/items/1/status", {"status": "Returned"})
        self.logout()
        self.login("other@uni.edu")
        self.assertIn(b"no longer open for claims", self.claim().data)

    def test_deleting_item_removes_its_claims(self):
        self.login("owner@uni.edu"); self.claim(); self.logout()
        self.login("admin@uni.edu")
        self.post("/admin/items/1/delete")
        self.assertEqual(len(self.query("SELECT id FROM items WHERE id = 1")), 0)
        self.assertEqual(len(self.query("SELECT id FROM claims")), 0)


class DatabaseTests(BaseTestCase):
    def test_foreign_keys_are_enforced(self):
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO claims (item_id, user_id, status) VALUES (999, 999, 'Pending')")

    def test_report_type_column_added_to_old_database(self):
        old_fd, old_path = tempfile.mkstemp(suffix=".db")
        try:
            conn = sqlite3.connect(old_path)
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
                         "category TEXT, status TEXT, location TEXT, date_lost TEXT, date_found TEXT, "
                         "reported_by INTEGER, created_at TEXT)")
            conn.execute("INSERT INTO items (title) VALUES ('old row')")
            conn.commit()
            conn.close()
            app = create_app({"TESTING": True, "DATABASE": old_path, "SECRET_KEY": "x"})
            with app.app_context():
                columns = [r["name"] for r in get_db().execute("PRAGMA table_info(items)")]
                self.assertIn("report_type", columns)
        finally:
            os.close(old_fd)
            os.unlink(old_path)


if __name__ == "__main__":
    unittest.main()
