# Campus Lost & Found Management System

A Flask + SQLite web application where students report lost and found items, search reports,
submit claims, and administrators verify claims. Built to the project SRS v1.0.

## Features

- Registration, login, logout (hashed passwords, sessions, CSRF protection)
- Roles: **user** and **admin** (enforced on the server)
- Report lost items and found items (title, description, category, location, date)
- Browse, search and filter reports (text, type, category, status); item detail pages
- Submit claims on found items; users track their own claims
- Admin dashboard: review claims, approve/reject, manage item statuses, delete reports
- Item status workflow: Reported → Matched → Claim Submitted → Claim Verified → Returned
  (claim statuses Pending / Approved / Rejected are stored separately)

## Setup (Windows PowerShell)

```powershell
cd path\to\lost-and-found-management-system
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activate script, run once:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

## Run

```powershell
python create_admin.py      # one time: creates the administrator account
python app.py               # starts the server
```

Open http://127.0.0.1:5000. The database file `lost_and_found.db` is created automatically.
Stop the server with `Ctrl+C`.

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v     # fast tests, no browser
python -m unittest tests.selenium_tests -v                  # browser tests (needs Chrome)
```

## Project structure

| File / folder | Purpose |
|---|---|
| `app.py` | Creates the app, secret key, CSRF check, error pages |
| `database.py` | Connection (foreign keys ON), schema, safe migration |
| `helpers.py` | Constants, login/admin decorators, claim rules |
| `auth.py` | Register, login, logout |
| `items.py` | Home, listing/search, details, lost/found reporting, my reports |
| `claims.py` | Claim submission, my claims |
| `admin.py` | Dashboard, claim review, item status, delete |
| `create_admin.py` | Creates (or promotes) an administrator |
| `templates/`, `static/` | HTML, CSS, JavaScript |
| `tests/` | Unit tests and Selenium tests |

## Business rules

- Claims can be made on **found** reports only, by users other than the reporter, once per item.
- Submitting a claim moves the item to *Claim Submitted*.
- Approving a claim moves the item to *Claim Verified* and rejects other pending claims for it.
- Rejecting the last pending claim returns the item to *Reported*.
- Admins can set *Reported ⇄ Matched* manually and mark a *Claim Verified* item as *Returned*.
- Returned items no longer accept claims.

## Security notes

- The secret key comes from the `SECRET_KEY` environment variable, or is generated into
  `instance/secret.key` (git-ignored). Never commit it.
- When deploying behind HTTPS set `COOKIE_SECURE=1` and run without `debug=True`.
