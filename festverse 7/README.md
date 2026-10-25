# The Anthem Board: College Fest Management System

A complete, deployable DBMS project. **Flask + PostgreSQL**, with the business rules enforced *inside the database* (triggers, stored functions, views, constraints, audit log, role-based grants).

## Features
**Participants:** browse/search events, schedule by day and venue, wallet with top-up, solo and team registration, coupons, auto-waitlist (with live queue position), QR ticket, refunds on cancel, notifications, feedback/ratings (only after attending), printable certificates, live leaderboards, "people who joined this also joined" recommendations.
**Coordinators:** create/edit events (venue-clash detection), assign judges, volunteer shifts, resources, expenses, registrations table, CSV export, status control.
**Judges:** multi-round scoring portal; conflict-of-interest locked by the database.
**Volunteers / staff:** shift list and QR gate scanner (camera or paste), entry/exit toggling.
**Admin:** analytics dashboard (Chart.js), P&L per event, sponsors, venues/resources/coupons/colleges, user roles, audit log, CSV exports, print-to-PDF, college championship points, **DB Lab** (ER diagram, trigger list, index benchmark, read-only SQL console).

## Demo logins
| Role | Email | Password |
|---|---|---|
| Admin | admin@festverse.in | admin123 |
| Coordinator | priya@festverse.in | fest123 |
| Judge | judge1@festverse.in | fest123 |
| Volunteer | volunteer1@festverse.in | fest123 |
| Participant | student@festverse.in | fest123 |

## Run locally (no database install needed)
```bash
pip install -r requirements-local.txt     # includes an embedded PostgreSQL
python app.py                             # http://localhost:5000
```
The first run starts an embedded PostgreSQL inside the project folder (`.pgdata/`), builds the schema and loads demo data automatically.
If you already run PostgreSQL (Homebrew, Docker, installer), the app uses it automatically when it finds user `fest` / password `fest` / database `festverse` on localhost, or whatever you put in `DATABASE_URL`:
```bash
docker compose up -d                      # optional: PostgreSQL in Docker
export DATABASE_URL=postgresql://user:pass@host:5432/dbname
python init_db.py --reset                 # wipe + rebuild the demo data any time
```
If the database can't be reached, the site shows a help page with these steps instead of a raw error.

## See who is logged in (from the database)
Every login is stored in the `login_sessions` table (failed attempts go to `login_attempts`):
- **Website:** log in as admin → Admin → **Sessions** (active users, history, failed attempts, *Force logout*).
- **Terminal:** `python show_logins.py` (add `--watch` to see it update live as you log in/out in the browser).
- **VS Code:** open `queries.sql` and run `SELECT * FROM v_active_sessions;`. With the SQLTools extension (recommended in `.vscode/extensions.json`) the connection in `.vscode/settings.json` works for Docker/Homebrew PostgreSQL. The embedded database has no TCP port, so with it use `show_logins.py` or the admin Sessions page.

## Deploy on Render (about 5 minutes)
1. Push this folder to a new GitHub repo.
2. Render dashboard → **New → Blueprint** → pick the repo. It reads `render.yaml` and creates the web service **and** the PostgreSQL database.
3. Click **Apply**. First deploy takes a few minutes; `init_db.py` builds the schema and demo data automatically (only when the DB is empty).
4. Open the URL, log in with the demo accounts above.

Notes: the free web service sleeps after ~15 min idle (first request takes ~50 s: open it before your demo). Free Render Postgres expires after 30 days.
If you ever want fresh demo data (dates are relative to *now*): log in as admin → Admin → **Reset demo data**.

## Where the DBMS concepts live
| Concept | Where |
|---|---|
| 3NF schema, PK/FK/CHECK/UNIQUE, partial unique index | `schema.sql` §1 |
| Indexes + live benchmark | `schema.sql` §2, DB Lab page |
| Stored functions (`register_for_event`, `cancel_registration`, `topup_wallet`, `scan_checkin`, `promote_waitlist`, `fn_recommend`, `fn_has_conflict`) | `schema.sql` §3 |
| Triggers: venue clash, participant clash, team size, seat limit + auto-waitlist, refund, waitlist promotion, judge COI, resource over-booking, check-in rules, audit | `schema.sql` §4 |
| Views, window functions (`RANK() OVER`), CTEs | `schema.sql` §5 |
| GRANT / REVOKE roles, column-level privileges | `schema.sql` §6 |
| Transactions / rollback (ACID), `FOR UPDATE`, `SKIP LOCKED` | `register_for_event`, `promote_waitlist`, request lifecycle in `app.py` |
| Audit via `set_config('app.user_id')` | `audit_row()` + `db()` in `app.py` |
| Session tracking (tables, views `v_active_sessions` / `v_login_history`) | `sessions.sql` |

## 3-minute viva demo script
1. **Clash trigger:** log in as coordinator → New event → same venue/time as "Hack the Fest" → the database rejects it.
2. **ACID:** as the student, register for an event that overlaps one you're in → error, and wallet is unchanged (rolled back).
3. **Waitlist:** open "Valorant Showdown" (full). Cancel a confirmed team member as admin → the first waitlisted person is auto-confirmed and notified.
4. **COI:** judge1 (PSG) opens "Code Sprint" scoring → PSG entries are locked.
5. **Leaderboard view:** DB Lab → console → `SELECT * FROM v_leaderboard ORDER BY event_id, rank LIMIT 10`.
6. **Index:** DB Lab → Run benchmark (full scan vs index scan).
7. **Audit:** Admin → Audit log → see who changed what, old → new.

## Honest limits
Wallet money is simulated (no payment gateway). Notifications are in-app (a trigger fills the `notifications` table); wiring email/SMS would be an add-on. App-level role checks are what the website enforces; the Postgres roles in §6 demonstrate GRANT/REVOKE and are not used for per-request login.


## Staff sign-up codes
Students sign up at `/signup` (always a participant, college required). Staff use `/staff/signup` with a role access code.
Set `ADMIN_SIGNUP_CODE`, `COORDINATOR_SIGNUP_CODE`, `JUDGE_SIGNUP_CODE`, `VOLUNTEER_SIGNUP_CODE` as environment variables.
Local defaults (not used on Render): `ANTHEM-ADMIN`, `ANTHEM-COORD`, `ANTHEM-JUDGE`, `ANTHEM-VOL`.

## Event QR codes
Manage > edit an event > "Event QR code". Each event has its own signed QR (no database change needed).
Set `PUBLIC_URL` (e.g. your Render URL) so the QR points at the live site instead of localhost.
