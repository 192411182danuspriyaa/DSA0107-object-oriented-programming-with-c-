# BloodLink — Hospital Blood Stock & Emergency Donor Coordination

A runnable MVP web application built with Flask + SQLite.

## Features
- Separate registration/login for hospitals and donors.
- Hospital staff can manually update blood stock.
- Low-stock and empty-stock status based on configurable thresholds.
- Emergency requests with staff-selected donor notification radius.
- Matching donor invitations with accept/reject responses.
- Nearby hospital stock search across all registered hospitals, ranked by distance.
- Blood transfer requests and status tracking.
- In-app notifications and an admin overview.

## Run locally (Windows)
1. Install Python 3.10+.
2. Extract the ZIP.
3. Open the `BloodLink` folder in VS Code.
4. Open Terminal and run:
   ```bash
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   py app.py
   ```
5. Open `http://127.0.0.1:5000`.

If `py` does not work, use `python` instead.

## Demo accounts
The database is seeded on first run:
- Admin: `admin@bloodlink.local` / `Admin@123`
- Demo hospital: `hospital@bloodlink.local` / `Hospital@123`
- Demo donor: `donor@bloodlink.local` / `Donor@123`

You can also register additional hospitals and donors from the login page.

## Important
This is a student-project MVP, not a certified blood-bank system. Use fictional data only.
- Donor notifications are in-app notifications; SMS/WhatsApp/push delivery is not configured.
- Distance uses coordinates entered during registration and straight-line Haversine distance, not road travel time.
- Stock updates are manual and audit-logged.
- Donor blood-group matching is a preliminary filter only. Actual donor eligibility, ABO/Rh and component compatibility, infectious-disease screening, crossmatching, collection, storage, and release must be handled by qualified blood-bank professionals under applicable rules.
- Never use this prototype to make clinical or transfusion decisions.
- Before real deployment, add HTTPS, stronger verification, privacy/security review, consent management, audit controls, backups, rate limits, and integration with authorized blood banks.

## Project structure
- `app.py` — Flask routes, database setup, matching and workflows
- `templates/` — HTML pages
- `static/style.css` — responsive styling
- `bloodlink.db` — created automatically at first run
