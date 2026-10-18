"""Selenium end-to-end tests: a real Chrome browser drives the real application.

Each run starts the app on a temporary database, so no existing data is needed
and nothing you have saved locally is touched.

Run from the project folder (virtual environment active):
    python -m unittest tests.selenium_tests -v

Set HEADLESS=0 to watch the browser:      $env:HEADLESS = "0"      (PowerShell)
Requires Google Chrome. Selenium downloads the matching driver automatically
the first time, so an internet connection is needed on the first run.
"""

import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selenium import webdriver  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.support.ui import Select, WebDriverWait  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402
from database import get_db  # noqa: E402

PORT = 5055
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Password123"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


class SeleniumTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        cls.app = create_app(
            {"TESTING": True, "DATABASE": cls.db_path, "SECRET_KEY": "selenium-test-key"}
        )
        cls.server = make_server("127.0.0.1", PORT, cls.app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        options = webdriver.ChromeOptions()
        if os.environ.get("HEADLESS", "1") == "1":
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1280,900")
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.shutdown()
        os.close(cls.db_fd)
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass   # Windows may still hold the file for a moment; it is a temp file

    def setUp(self):
        self.driver.delete_all_cookies()

    # ------------------------------------------------------------------ helpers
    def unique(self, prefix):
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    def create_user(self, role="user"):
        """Insert a user straight into the test database and return the email."""
        email = f"{self.unique(role)}@uni.edu"
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute(
                    "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                    (f"Test {role}", email, generate_password_hash(PASSWORD), role),
                )
        return email

    def open(self, path):
        self.driver.get(BASE_URL + path)

    def type_into(self, element_id, text):
        field = self.driver.find_element(By.ID, element_id)
        field.clear()
        field.send_keys(text)

    def click(self, element_id):
        self.driver.find_element(By.ID, element_id).click()


    def wait_for_text(self, text, timeout=10):
        def text_is_present(driver):
            try:
                return text in driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                return False

        WebDriverWait(self.driver, timeout).until(text_is_present)





    def body_text(self):
        return self.driver.find_element(By.TAG_NAME, "body").text

    def log_in(self, email, password=PASSWORD):
        self.open("/login")
        self.type_into("email", email)
        self.type_into("password", password)
        self.click("login-button")

    def log_in_ok(self, email):
        self.log_in(email)
        self.wait_for_text("Welcome")

    def log_out(self):
        self.click("logout-button")
        self.wait_for_text("You have been logged out")

    def report_item(self, report_type, title, category="Wallet", location="Main library"):
        """Fill in and submit the report form. Returns the new item's URL."""
        self.open(f"/report/{report_type}")
        self.type_into("title", title)
        Select(self.driver.find_element(By.ID, "category")).select_by_visible_text(category)
        self.type_into("description", f"{title} - description with enough detail")
        self.type_into("location", location)
        # Date inputs are locale-dependent in Chrome, so set the value directly.
        self.driver.execute_script(
            "document.getElementById('event_date').value = arguments[0];", YESTERDAY
        )
        self.click("report-button")
        self.wait_for_text(f"Your {report_type} item report was submitted")
        return self.driver.current_url

    # -------------------------------------------------------------------- tests
    def test_01_register_new_user_and_reject_duplicate(self):
        email = f"{self.unique('new')}@uni.edu"
        for expected in ("Registration successful", "already exists"):
            self.open("/register")
            self.type_into("name", "Selenium Student")
            self.type_into("email", email)
            self.type_into("password", PASSWORD)
            self.type_into("confirm_password", PASSWORD)
            self.click("register-button")
            self.wait_for_text(expected)
        self.assertIn("/register", self.driver.current_url)   # second attempt stays on the form

    def test_02_login_with_valid_credentials_then_logout(self):
        email = self.create_user()
        self.log_in_ok(email)
        self.assertIn("Log out", self.body_text())
        self.log_out()
        self.assertIn("Log in", self.body_text())

    def test_03_invalid_credentials_are_rejected(self):
        email = self.create_user()
        self.log_in(email, "wrong-password")
        self.wait_for_text("Invalid email or password")
        self.assertNotIn("Log out", self.body_text())

    def test_04_report_lost_item(self):
        self.log_in_ok(self.create_user())
        title = self.unique("Lost umbrella")
        self.report_item("lost", title, category="Other")
        self.assertIn(title, self.body_text())
        self.assertIn("Lost", self.body_text())

    def test_05_report_found_item(self):
        self.log_in_ok(self.create_user())
        title = self.unique("Found calculator")
        self.report_item("found", title, category="Electronics")
        self.assertIn(title, self.body_text())
        self.assertIn("Found", self.body_text())

    def test_06_search_for_a_report(self):
        self.log_in_ok(self.create_user())
        title = self.unique("Zebra-lanyard")
        self.report_item("found", title, category="Other")

        self.open("/items")
        self.type_into("q", title)
        self.click("search-button")
        self.wait_for_text("1 report found")
        self.assertIn(title, self.body_text())

        self.open("/items")
        self.type_into("q", self.unique("nothing-matches-this"))
        self.click("search-button")
        self.wait_for_text("No reports match")

    def test_07_submit_claim_and_see_it_in_my_claims(self):
        finder = self.create_user()
        claimant = self.create_user()
        self.log_in_ok(finder)
        title = self.unique("Found wallet")
        item_url = self.report_item("found", title)
        self.log_out()

        self.log_in_ok(claimant)
        self.driver.get(item_url)
        self.type_into("message", "My student card is inside the wallet")
        self.click("claim-button")
        self.wait_for_text("Claim submitted")

        self.open("/my/claims")
        table = self.driver.find_element(By.ID, "claims-table").text
        self.assertIn(title, table)
        self.assertIn("Pending", table)

    def test_08_administrator_approves_a_claim(self):
        finder, claimant, admin = self.create_user(), self.create_user(), self.create_user("admin")
        self.log_in_ok(finder)
        title = self.unique("Found keys")
        item_url = self.report_item("found", title, category="Keys")
        self.log_out()

        self.log_in_ok(claimant)
        self.driver.get(item_url)
        self.type_into("message", "The keyring has a blue tag")
        self.click("claim-button")
        self.wait_for_text("Claim submitted")
        self.log_out()

        self.log_in_ok(admin)
        self.open("/admin/claims?status=Pending")
        row = self.driver.find_element(By.XPATH, f"//tr[contains(., '{title}')]")
        row.find_element(By.LINK_TEXT, "Open").click()
        self.click("approve-button")
        self.wait_for_text("Claim approved")
        self.log_out()

        self.log_in_ok(claimant)
        self.open("/my/claims")
        self.assertIn("Approved", self.driver.find_element(By.ID, "claims-table").text)

    def test_09_unauthorised_users_cannot_open_admin_pages(self):
        # Anonymous visitors are sent to the login page.
        self.open("/admin/")
        self.wait_for_text("Log in")
        self.assertIn("/login", self.driver.current_url)

        # Logged-in regular users are refused.
        self.log_in_ok(self.create_user())
        self.open("/admin/")
        self.wait_for_text("Access denied")
        self.open("/admin/claims")
        self.wait_for_text("Access denied")


if __name__ == "__main__":
    unittest.main()
