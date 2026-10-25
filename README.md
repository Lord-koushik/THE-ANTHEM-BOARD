<div align="center">

# 🎪 The Anthem Board

### College fest management, with the rules enforced by the database.

Registrations, waitlists, scoring, check-ins, finance and audit trails for a multi-day college festival.
Built on **Flask** and **PostgreSQL**, where clash detection, refunds and conflict-of-interest checks are triggers and stored functions rather than app code.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Chart.js](https://img.shields.io/badge/Chart.js-dashboards-FF6384?logo=chartdotjs&logoColor=white)
![Deploy](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render&logoColor=black)

[Quick start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [Database design](#-database-design) · [Demo script](#-3-minute-viva-demo) · [Deploy](#-deploy-on-render)

</div>

---

## ✨ Why this project

Most fest apps keep their rules in the web layer, so one bad script or a second client can break them. **The Anthem Board does the opposite.** The Flask app is a thin layer, and PostgreSQL decides what is allowed.

| Rule | Enforced by |
|---|---|
| Two events can't share a venue at the same time | `events_guard` trigger |
| A participant can't join two overlapping events | `reg_validate` trigger |
| A full event puts new sign-ups on a waitlist automatically | `reg_validate` + `reg_inserted` triggers |
| Cancelling refunds the wallet and promotes the next person on the waitlist | `reg_status` trigger + `promote_waitlist()` |
| A judge can't score an entry that includes someone from their own college | `score_guard` trigger |
| A resource can't be over-allocated across overlapping events | `alloc_guard` trigger |
| Feedback only from people who actually attended | `feedback_guard` trigger |
| Every change to key tables is recorded (old vs new, and who) | `audit_row()` generic audit trigger |

---

## 🚀 Features

<table>
<tr>
<td width="50%" valign="top">

### 🎓 Participants
- Browse and search events, view the schedule by day and venue
- Wallet with top-up, solo and **team registration**, coupon codes
- **Auto-waitlist** with live queue position
- QR ticket, refund on cancel, in-app notifications
- Ratings and feedback (only after attending)
- Printable **certificates**
- Live leaderboards and "people who joined this also joined" recommendations

</td>
<td width="50%" valign="top">

### 🧭 Coordinators
- Create and edit events with **venue-clash detection**
- Assign judges, volunteer shifts and resources
- Track expenses, view the registrations table, export **CSV**
- Control event status (scheduled, live, completed, cancelled)
- Per-event **signed QR code** for posters

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚖️ Judges
- Multi-round scoring portal
- Conflict-of-interest entries are **locked by the database**

### 🙋 Volunteers
- Personal shift list
- **QR gate scanner** (camera or paste a token), entry and exit toggling

</td>
<td width="50%" valign="top">

### 🛠️ Admin
- Analytics dashboard (Chart.js) and **P&L per event**
- Sponsors, venues, resources, coupons, colleges
- User roles and **audit log** (old → new values)
- College championship points, CSV exports, print-to-PDF
- **Sessions page**: who is logged in, history, failed attempts, force logout
- **DB Lab**: ER diagram, trigger list, index benchmark, read-only SQL console

</td>
</tr>
</table>

---

## ⚡ Quick start

You only need Python. No database install is required.

```bash
# 1. Install (includes an embedded PostgreSQL)
pip install -r requirements-local.txt

# 2. Run
python app.py
```

Open **http://localhost:5000**. On first run the app starts an embedded PostgreSQL in `.pgdata/`, builds the schema and loads demo data.

### Demo logins

| Role | Email | Password |
|---|---|---|
| 🛠️ Admin | `admin@festverse.in` | `admin123` |
| 🧭 Coordinator | `priya@festverse.in` | `fest123` |
| ⚖️ Judge | `judge1@festverse.in` | `fest123` |
| 🙋 Volunteer | `volunteer1@festverse.in` | `fest123` |
| 🎓 Participant | `student@festverse.in` | `fest123` |

> The demo student starts with a ₹3,000 wallet. Seed dates are relative to *now*, so the fest always looks current. Use **Admin → Reset demo data** to refresh.

<details>
<summary><b>Already have PostgreSQL? Use it instead</b></summary>

The app looks for a database in this order:

1. `DATABASE_URL` environment variable
2. A server on `localhost:5432` with user `fest`, password `fest`, database `festverse`
3. An embedded PostgreSQL via `pgserver` (the default for first-time users)

```bash
docker compose up -d                                   # optional: PostgreSQL 16 in Docker
export DATABASE_URL=postgresql://user:pass@host:5432/dbname
python init_db.py --reset                              # wipe and rebuild demo data any time
```

If the database can't be reached, the site shows a help page with these steps instead of a raw error.
</details>

---

## 🏗️ Architecture

```mermaid
flowchart LR
    B[Browser<br/>Jinja templates · Chart.js] -->|HTTP + CSRF token| F[Flask app<br/>app.py]
    F -->|psycopg2 pool<br/>1 request = 1 transaction| P[(PostgreSQL)]
    P --- T[Triggers<br/>clash · waitlist · refund · COI · audit]
    P --- S[Stored functions<br/>register_for_event · cancel_registration · scan_checkin]
    P --- V[Views<br/>leaderboard · stats · sessions]
```

**How a request flows**

1. `before_request` checks the session against the `login_sessions` table (so admins can force-logout) and validates the CSRF token on every POST.
2. `db()` opens a pooled connection and calls `set_config('app.user_id', …)` so the audit trigger knows who is acting.
3. The route calls a stored function or runs SQL. If a trigger raises an error, `friendly()` turns the Postgres error code into a readable message.
4. `teardown_request` commits on success and rolls back on any exception, so each request is one ACID transaction.

---

## 🗄️ Database design

**22 tables · 10 views plus 2 session views · 18 triggers · 21 functions · 12+ indexes**, in third normal form.

```mermaid
erDiagram
    COLLEGES ||--o{ USERS : "belongs to"
    USERS ||--o{ REGISTRATIONS : makes
    EVENTS ||--o{ REGISTRATIONS : receives
    VENUES ||--o{ EVENTS : hosts
    EVENTS ||--o{ TEAMS : has
    TEAMS ||--o{ REGISTRATIONS : groups
    COUPONS ||--o{ REGISTRATIONS : discounts
    REGISTRATIONS ||--o{ PAYMENTS : "paid by"
    REGISTRATIONS ||--o{ SCORES : earns
    REGISTRATIONS ||--o{ CHECKINS : "scanned at"
    REGISTRATIONS ||--o| FEEDBACK : rates
    EVENTS ||--o{ JUDGE_ASSIGNMENTS : "judged by"
    EVENTS ||--o{ VOLUNTEER_SHIFTS : staffed
    EVENTS ||--o{ ALLOCATIONS : uses
    RESOURCES ||--o{ ALLOCATIONS : "allocated as"
    EVENTS ||--o{ EXPENSES : costs
    SPONSORS ||--o{ SPONSORSHIPS : funds
    EVENTS ||--o{ SPONSORSHIPS : "funded by"
    USERS ||--o{ NOTIFICATIONS : gets
    USERS ||--o{ LOGIN_SESSIONS : opens
```

Plus `audit_log` (JSONB old and new values) and `login_attempts`.

### Stored functions

| Function | What it does |
|---|---|
| `register_for_event(user, event, team, coupon)` | Validates, applies the coupon, charges the wallet and confirms or waitlists, all atomically |
| `cancel_registration(reg, user)` | Cancels and triggers the refund and waitlist promotion |
| `promote_waitlist(event)` | Confirms the next waitlisted person (`FOR UPDATE SKIP LOCKED`) |
| `topup_wallet(user, amount)` | Adds funds and logs the payment |
| `scan_checkin(token, by)` | Validates a QR token and toggles in/out, returns JSON |
| `fn_recommend(event, limit)` | Recommendations via self-join: what else did attendees of this event join? |
| `fn_has_conflict(judge, reg)` | Conflict-of-interest check |
| `fn_sync_event_status()` | Moves events through scheduled → live → completed by time |

### Triggers

<details>
<summary><b>Show all business-rule triggers</b></summary>

| Trigger | Table | Rule |
|---|---|---|
| `events_guard` | events | Venue capacity and venue-time clash detection |
| `events_after` | events | Reschedule notices, cancellation cascade, capacity growth promotes the waitlist |
| `reg_validate` | registrations | Participant clash, team size, seat limit → auto-waitlist |
| `reg_inserted` | registrations | Notifications on registration |
| `reg_status` | registrations | Cancellation → refund → notify → promote waitlist |
| `judge_assign` | judge_assignments | Role must be judge, no double-booking |
| `score_guard` | scores | Judge must be assigned, event live, valid round, confirmed entry, conflict of interest |
| `shift_guard` | volunteer_shifts | Role must be volunteer, no overlapping shifts |
| `alloc_guard` | allocations | Never allocate more than exists during overlapping events |
| `checkin_guard` | checkins | Confirmed only, minimum team size, sane IN/OUT order |
| `feedback_guard` | feedback | Only attendees can leave feedback |
| `audit_*` ×7 | events, registrations, users, scores, coupons, expenses, sponsorships | Generic audit trigger |
</details>

### Views

`v_event_stats` · `v_leaderboard` (uses `RANK() OVER`) · `v_certificates` · `v_college_points` · `v_college_participation` · `v_my_registrations` · `v_team_status` · `v_hourly_registrations` · `v_hourly_checkins` · `v_fest_summary` · `v_active_sessions` · `v_login_history`

### Role-based access (GRANT / REVOKE)

Three NOLOGIN Postgres roles (`fest_admin`, `fest_coordinator`, `fest_participant`) demonstrate least privilege, including **column-level grants** (for example, coordinators can read `users.name` but never `password_hash`) and `audit_log` locked to admins. Setup is wrapped so managed hosts that forbid `CREATE ROLE` don't break.

### Where each DBMS concept lives

| Concept | Where |
|---|---|
| 3NF schema, PK/FK/CHECK/UNIQUE, partial unique index | `schema.sql` §1 |
| Indexes and live benchmark | `schema.sql` §2, DB Lab page |
| Stored functions | `schema.sql` §3 |
| Triggers | `schema.sql` §4 |
| Views, window functions, CTEs | `schema.sql` §5 |
| GRANT / REVOKE, column-level privileges | `schema.sql` §6 |
| Transactions, rollback, `FOR UPDATE`, `SKIP LOCKED` | `register_for_event`, `promote_waitlist`, `teardown_request` in `app.py` |
| Audit via `set_config('app.user_id')` | `audit_row()` and `db()` in `app.py` |
| Session tracking | `sessions.sql` |

---

## 🔒 Security

- Passwords hashed with Werkzeug (`generate_password_hash`)
- CSRF token required on every POST
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` on Render; sessions expire after 8 hours
- Sessions are tracked in the database, so an admin can **force logout** a user instantly
- Failed and successful logins are recorded in `login_attempts`
- Staff roles can't be self-assigned: they need a role access code (see below)
- Event QR codes are signed, and ticket QRs use random UUID tokens
- DB Lab console accepts a single `SELECT` / `WITH` / `EXPLAIN`, runs in a **read-only transaction** with a 4 s timeout
- Request body capped at 1 MB

---

## 🎬 3-minute viva demo

1. **Clash trigger:** log in as coordinator → *New event* → same venue and time as "Hack the Fest" → the database rejects it.
2. **ACID:** as the student, register for an event that overlaps one you're in → error, and the wallet is unchanged (rolled back).
3. **Waitlist:** open "Valorant Showdown" (full). Cancel a confirmed team member as admin → the first waitlisted person is auto-confirmed and notified.
4. **Conflict of interest:** judge1 (PSG) opens "Code Sprint" scoring → PSG entries are locked.
5. **Leaderboard view:** DB Lab → console → `SELECT * FROM v_leaderboard ORDER BY event_id, rank LIMIT 10`.
6. **Index:** DB Lab → *Run benchmark* (300k-row table, full scan vs index scan, rolled back afterwards).
7. **Audit:** Admin → Audit log → see who changed what, old → new.

---

## 👀 See who is logged in

Every login is stored in `login_sessions`, and failed attempts go to `login_attempts`.

| Where | How |
|---|---|
| Website | Admin → **Sessions** (active users, history, failed attempts, *Force logout*) |
| Terminal | `python show_logins.py`, add `--watch` to refresh every 2 s |
| VS Code | Open `queries.sql` and run `SELECT * FROM v_active_sessions;` (SQLTools config is in `.vscode/`) |

> The embedded database has no TCP port, so with it use `show_logins.py` or the Sessions page. Docker or Homebrew PostgreSQL works with SQLTools.

---

## ☁️ Deploy on Render

1. Push this folder to a new GitHub repo.
2. Render dashboard → **New → Blueprint** → pick the repo. `render.yaml` creates the web service **and** a PostgreSQL database.
3. Click **Apply**. On first deploy `init_db.py` builds the schema and demo data (only when the database is empty, so redeploys are safe).
4. Open the URL and log in with the demo accounts.

> Free tier notes: the web service sleeps after ~15 minutes idle (the first request takes ~50 s, so open it before your demo). Free Render Postgres expires after 30 days.

### Configuration

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Local / embedded DB |
| `SECRET_KEY` | Flask session signing key | `dev-only-change-me` (Render generates one) |
| `PUBLIC_URL` | Public site URL so printed event QRs open on phones | none |
| `PORT` | Port for `python app.py` | `5000` |
| `ADMIN_SIGNUP_CODE` | Access code for admin sign-up | `ANTHEM-ADMIN` (local only) |
| `COORDINATOR_SIGNUP_CODE` | Access code for coordinator sign-up | `ANTHEM-COORD` (local only) |
| `JUDGE_SIGNUP_CODE` | Access code for judge sign-up | `ANTHEM-JUDGE` (local only) |
| `VOLUNTEER_SIGNUP_CODE` | Access code for volunteer sign-up | `ANTHEM-VOL` (local only) |

Students sign up at `/signup` (always a participant, college required). Staff use `/staff/signup` with a role access code.

---

## 📁 Project structure

```
festverse/
├── app.py               # Flask routes, auth, CSRF, error mapping (thin web layer)
├── schema.sql           # Tables, indexes, functions, triggers, views, grants
├── sessions.sql         # Login tracking tables and views
├── init_db.py           # Builds schema + seeds demo data (--reset to wipe)
├── local_db.py          # Finds DATABASE_URL, local server, or embedded PostgreSQL
├── show_logins.py       # Terminal view of who is logged in
├── queries.sql          # Handy queries to run from VS Code / psql
├── templates/           # 34 Jinja templates (base, dashboards, forms, DB Lab…)
├── static/style.css     # Single stylesheet
├── render.yaml          # Render Blueprint (web service + Postgres)
├── docker-compose.yml   # Optional PostgreSQL 16
├── requirements.txt     # Flask, psycopg2-binary, gunicorn, segno
└── requirements-local.txt  # + pgserver (embedded PostgreSQL)
```

**Stack:** Flask ≥3.0 · psycopg2 · gunicorn · segno (QR codes) · Chart.js · Jinja2

---

## 🌱 Demo data

- **8 colleges** (Kongu, PSG, CIT, CEG, NIT Trichy, TCE, SSN, Amrita) and **6 venues**
- **14 events** across Technical, Cultural, Sports, Literary, Gaming and Workshop, over 4 days (yesterday through day 3)
- Past, live and upcoming events, so leaderboards, certificates, waitlists and finance charts all have data
- 37 participants (36 plus the demo student), plus admin, 2 coordinators, 3 judges and 3 volunteers
- Coupons (`FEST20`, `EARLYBIRD`, `STUDENT10`, and an expired `OLD50`), sponsors, expenses and volunteer shifts

---

## ⚠️ Honest limits

- Wallet money is **simulated**; there is no payment gateway.
- Notifications are in-app (a trigger fills the `notifications` table). Email or SMS would be an add-on.
- Role checks on the website are enforced in Flask. The Postgres roles in `schema.sql` §6 demonstrate GRANT/REVOKE and are not used for per-request login.
- Local sign-up codes are public defaults. Set your own env vars before any real deployment, and change the demo passwords.

---

<div align="center">

**The Anthem Board** · a DBMS project · Flask + PostgreSQL

</div>
