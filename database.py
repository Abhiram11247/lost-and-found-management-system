"""Database helpers: connection handling, schema creation and safe migrations."""

import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    password   TEXT NOT NULL,                       -- password HASH, never plaintext
    role       TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'lost' CHECK (report_type IN ('lost', 'found')),
    status      TEXT NOT NULL DEFAULT 'Reported'
                CHECK (status IN ('Reported', 'Matched', 'Claim Submitted',
                                  'Claim Verified', 'Returned')),
    location    TEXT NOT NULL,
    date_lost   TEXT,                               -- the day the item was lost
    date_found  TEXT,                               -- the day the item was found
    reported_by INTEGER NOT NULL REFERENCES users (id),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP   -- when the report was submitted
);

CREATE TABLE IF NOT EXISTS claims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    message    TEXT,
    status     TEXT NOT NULL DEFAULT 'Pending'
               CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

"""

# Indexes are created AFTER migrate_schema(), because an old database may not
# have the report_type column until the migration has added it.
INDEXES = """
-- A user can claim a given item only once.
CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_item_user ON claims (item_id, user_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items (status);
CREATE INDEX IF NOT EXISTS idx_items_type ON items (report_type);
"""


def get_db():
    """Return this request's database connection (created on first use)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        # SQLite ignores foreign keys unless this is switched on for EVERY connection.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _column_names(db, table):
    return [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]


def migrate_schema(db):
    """Apply changes that CREATE TABLE IF NOT EXISTS cannot make to old databases."""
    if "report_type" not in _column_names(db, "items"):
        db.execute(
            "ALTER TABLE items ADD COLUMN report_type TEXT NOT NULL DEFAULT 'lost'"
        )
        db.commit()


def init_db():
    """Create all tables (if missing) and bring older databases up to date."""
    db = get_db()
    db.executescript(SCHEMA)     # creates missing tables only
    migrate_schema(db)           # adds missing columns to older tables
    db.executescript(INDEXES)    # now every column the indexes need exists


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
