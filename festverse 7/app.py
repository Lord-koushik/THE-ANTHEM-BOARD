"""The Anthem Board - college fest management. Flask + PostgreSQL.
All business rules live in the database (see schema.sql); this file is the thin web layer."""
import os, io, csv, json, time, secrets
from functools import wraps
from decimal import Decimal
from datetime import datetime, date

import psycopg2, psycopg2.extras, psycopg2.pool
import segno
from flask import (Flask, g, request, session, redirect, url_for, render_template, flash, jsonify, abort, Response)
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

import local_db
class DBUnavailable(Exception): pass
try:
    DB_URL = local_db.resolve_url()      # DATABASE_URL, local server, or an embedded PostgreSQL
    DB_PROBLEM = None
except RuntimeError as _e:
    DB_URL, DB_PROBLEM = None, str(_e)
app = Flask(__name__)
app.permanent_session_lifetime = __import__("datetime").timedelta(hours=8)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")), MAX_CONTENT_LENGTH=1 << 20)

CATS = ["Technical", "Cultural", "Sports", "Literary", "Gaming", "Workshop"]
STAFF = ("admin", "coordinator")

# ---------------------------------------------------------------- database plumbing
_pool = None
def pool():
    global _pool
    if _pool is None:
        if not DB_URL: raise DBUnavailable(DB_PROBLEM)
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 8, DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return _pool

def db():
    if "conn" not in g:
        p = pool(); conn = p.getconn()
        try:                                   # connection may have gone stale on a hosted DB
            with conn.cursor() as c: c.execute("SELECT 1")
        except psycopg2.Error:
            p.putconn(conn, close=True); conn = p.getconn()
        g.conn = conn
        if session.get("uid"):                 # lets the audit trigger know who is acting
            with conn.cursor() as c: c.execute("SELECT set_config('app.user_id', %s, true)", (str(session["uid"]),))
    return g.conn

def q(sql, args=None):
    with db().cursor() as c:
        c.execute(sql, args); return c.fetchall()
def q1(sql, args=None):
    r = q(sql, args); return r[0] if r else None
def x(sql, args=None):
    with db().cursor() as c:
        c.execute(sql, args); return c.rowcount

@app.teardown_request
def _release(exc):
    conn = g.pop("conn", None)
    if conn is not None:
        try:
            conn.rollback() if exc else conn.commit()   # one request = one ACID transaction
        except psycopg2.Error:
            pass
        pool().putconn(conn)

def friendly(e):
    code = getattr(e, "pgcode", None) or ""
    msg = (e.diag.message_primary if getattr(e, "diag", None) and e.diag.message_primary else str(e)).strip()
    con = getattr(getattr(e, "diag", None), "constraint_name", "") or ""
    if code == "P0001": return msg
    if code == "23505":
        if con == "uq_active_registration": return "You are already registered for this event."
        if "email" in con: return "That email is already registered."
        return "That already exists."
    if code == "23514": return "That value is outside the allowed range (%s)." % (con or "check failed")
    if code == "23503": return "This record is linked to other data, so the change was blocked."
    if code.startswith("22"): return "One of the values you entered is not valid."
    return "Database error: " + msg

@app.errorhandler(DBUnavailable)
@app.errorhandler(psycopg2.OperationalError)
def db_down(e):
    if request.path.startswith("/api/"): return jsonify(ok=False, message="Database is not reachable"), 503
    return render_template("dbdown.html", detail=str(e).strip()), 503

@app.errorhandler(psycopg2.Error)
def db_error(e):
    try: db().rollback()
    except Exception: pass
    msg = friendly(e)
    if request.path.startswith("/api/"): return jsonify(ok=False, message=msg), 400
    if request.method == "GET":      # never redirect a failed GET (could loop)
        info = type("E", (), {"code": 500, "name": "Something went wrong", "description": msg})()
        return render_template("error.html", e=info), 500
    flash(msg, "err")
    return redirect(request.referrer or url_for("home"))

@app.errorhandler(HTTPException)
def http_error(e):
    return render_template("error.html", e=e), e.code

# ---------------------------------------------------------------- auth, csrf, helpers
def client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "")[:60]

def start_session(uid):
    """Record the login in the database and remember the session id in the cookie."""
    row = q1("INSERT INTO login_sessions(user_id, ip_address, user_agent) VALUES (%s,%s,%s) RETURNING session_id",
             (uid, client_ip(), (request.user_agent.string or "")[:250]))
    session.clear(); session["uid"] = uid; session["sid"] = str(row["session_id"]); session.permanent = True; csrf_token()

@app.before_request
def load_user():
    g.user = None
    if request.endpoint == "static": return
    uid, sid = session.get("uid"), session.get("sid")
    if uid and sid:
        # the session must still be open in the login_sessions table (admins can force-logout)
        g.user = q1("""SELECT u.user_id,u.name,u.email,u.role,u.college_id,u.wallet_balance,
                              s.last_seen < fest_now() - INTERVAL '1 minute' AS stale
                       FROM users u JOIN login_sessions s ON s.user_id=u.user_id AND s.session_id=%s::uuid AND s.logged_out_at IS NULL
                       WHERE u.user_id=%s""", (sid, uid))
        if g.user and g.user["stale"]:
            x("UPDATE login_sessions SET last_seen=fest_now() WHERE session_id=%s::uuid", (sid,))
    if session.get("uid") and not g.user: session.clear()
    if request.method == "POST":
        tok = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if not tok or tok != session.get("csrf"):
            abort(400, "Your session expired. Please go back, refresh the page and try again.")

def csrf_token():
    if "csrf" not in session: session["csrf"] = secrets.token_hex(16)
    return session["csrf"]

@app.context_processor
def inject():
    unread = 0
    if g.get("user"):
        unread = q1("SELECT COUNT(*) AS n FROM notifications WHERE user_id=%s AND NOT is_read", (g.user["user_id"],))["n"]
    return dict(me=g.get("user"), unread=unread, csrf_token=csrf_token, CATS=CATS)

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.user: return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

def roles(*allowed):
    def deco(f):
        @wraps(f)
        @login_required
        def w(*a, **k):
            if g.user["role"] not in allowed: abort(403, "Your role does not have access to this page.")
            return f(*a, **k)
        return w
    return deco

@app.template_filter("money")
def money(v):
    v = Decimal(v or 0)
    return ("Rs." + f"{v:,.0f}") if v == v.to_integral() else ("Rs." + f"{v:,.2f}")
@app.template_filter("dt")
def fdt(v): return v.strftime("%a %d %b, %I:%M %p") if v else ""
@app.template_filter("day")
def fday(v): return v.strftime("%A, %d %B") if v else ""
@app.template_filter("hm")
def fhm(v): return v.strftime("%I:%M %p").lstrip("0") if v else ""
@app.template_filter("inp")
def finp(v): return v.strftime("%Y-%m-%dT%H:%M") if v else ""
@app.template_filter("stars")
def stars(v): n = int(round(float(v or 0))); return "★" * n + "☆" * (5 - n)

def can_manage(ev):
    return g.user["role"] == "admin" or (g.user["role"] == "coordinator" and ev["coordinator_id"] == g.user["user_id"])
def back(default="home"):
    return redirect(request.referrer or url_for(default))

# ---------------------------------------------------------------- public pages
@app.route("/")
def home():
    return render_template("home.html",
        summary=q1("SELECT * FROM v_fest_summary"),
        live=q("SELECT * FROM v_event_stats WHERE status='live' ORDER BY start_time"),
        nxt=q("SELECT * FROM v_event_stats WHERE status='scheduled' ORDER BY start_time LIMIT 5"),
        top=q("SELECT * FROM v_event_stats WHERE feedback_count>0 ORDER BY avg_rating DESC, feedback_count DESC LIMIT 3"),
        champs=q("SELECT * FROM v_college_points ORDER BY points DESC, golds DESC LIMIT 5"))

@app.route("/events")
def events():
    cond, args = ["status<>'cancelled'"], []
    cat, term, st = request.args.get("category", ""), request.args.get("q", "").strip(), request.args.get("status", "")
    if cat in CATS: cond.append("category=%s"); args.append(cat)
    if st in ("scheduled", "live", "completed"): cond.append("status=%s"); args.append(st)
    if term: cond.append("(name ILIKE %s OR description ILIKE %s)"); args += [f"%{term}%"] * 2
    rows = q("SELECT * FROM v_event_stats WHERE " + " AND ".join(cond) + " ORDER BY start_time", args)
    return render_template("events.html", rows=rows, cat=cat, term=term, st=st)

@app.route("/events/<int:eid>")
def event(eid):
    ev = q1("SELECT s.*, u.name AS coordinator FROM v_event_stats s LEFT JOIN users u ON u.user_id=s.coordinator_id WHERE s.event_id=%s", (eid,))
    if not ev: abort(404)
    my = q1("SELECT * FROM v_my_registrations WHERE user_id=%s AND event_id=%s AND status<>'cancelled'", (g.user["user_id"], eid)) if g.user else None
    return render_template("event.html", ev=ev, my=my,
        teams=q("SELECT * FROM v_team_status WHERE event_id=%s ORDER BY name", (eid,)),
        recs=q("SELECT * FROM fn_recommend(%s,3)", (eid,)),
        lb=q("SELECT * FROM v_leaderboard WHERE event_id=%s ORDER BY rank, entry_name", (eid,)),
        reviews=q("""SELECT f.rating, f.comment, u.name FROM feedback f JOIN registrations r ON r.reg_id=f.reg_id
                     JOIN users u ON u.user_id=r.user_id WHERE r.event_id=%s AND f.comment IS NOT NULL ORDER BY f.created_at DESC LIMIT 4""", (eid,)),
        judges=q("""SELECT u.name, c.name AS college FROM judge_assignments ja JOIN users u ON u.user_id=ja.judge_id
                    LEFT JOIN colleges c ON c.college_id=u.college_id WHERE ja.event_id=%s""", (eid,)))

@app.route("/schedule")
def schedule():
    ven = request.args.get("venue", type=int)
    rows = q("SELECT * FROM v_event_stats WHERE status<>'cancelled'" + (" AND venue_id=%s" if ven else "") + " ORDER BY start_time", (ven,) if ven else None)
    days = {}
    for r in rows: days.setdefault(r["start_time"].date(), []).append(r)
    return render_template("schedule.html", days=days, venues=q("SELECT * FROM venues ORDER BY name"), ven=ven)

@app.route("/leaderboard")
def leaderboard():
    rows = q("""SELECT l.*, e.name AS event_name, e.status FROM v_leaderboard l JOIN events e ON e.event_id=l.event_id
                WHERE l.rank<=3 ORDER BY e.start_time, l.rank""")
    by = {}
    for r in rows: by.setdefault((r["event_id"], r["event_name"], r["status"]), []).append(r)
    return render_template("leaderboard.html", by=by, champs=q("SELECT * FROM v_college_points ORDER BY points DESC, golds DESC"))

@app.route("/api/leaderboard/<int:eid>")
def api_leaderboard(eid):
    rows = q("SELECT rank, entry_name, college, total, best_round FROM v_leaderboard WHERE event_id=%s ORDER BY rank, entry_name", (eid,))
    return jsonify([{k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows])

def dbms_ctx():
    return dict(
        counts=q1("""SELECT (SELECT COUNT(*) FROM pg_tables WHERE schemaname='public') AS tables,
                            (SELECT COUNT(*) FROM pg_views WHERE schemaname='public') AS views,
                            (SELECT COUNT(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers,
                            (SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                               WHERE n.nspname='public' AND p.proname NOT LIKE 'trg\\_%%' AND p.proname<>'audit_row') AS functions,
                            (SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public') AS indexes"""),
        triggers=q("""SELECT c.relname AS tbl, t.tgname AS name, p.proname AS fn,
                      CASE WHEN t.tgtype & 2 = 2 THEN 'BEFORE' ELSE 'AFTER' END AS timing
                      FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid
                      WHERE NOT t.tgisinternal ORDER BY 1,2"""),
        grants=q("""SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privs
                    FROM information_schema.role_table_grants WHERE grantee LIKE 'fest\\_%%' AND table_schema='public'
                    GROUP BY 1,2 ORDER BY 1,2"""),
        indexes=q("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND indexname NOT LIKE '%%pkey' ORDER BY 1,2"))

@app.route("/dbms")
def dbms():
    return render_template("dbms.html", admin=bool(g.user and g.user["role"] == "admin"), bench=None, console=None, **dbms_ctx())

# ---------------------------------------------------------------- auth pages
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        u = q1("SELECT user_id, password_hash FROM users WHERE lower(email)=lower(%s)", (email,))
        ok = bool(u and check_password_hash(u["password_hash"], request.form.get("password", "")))
        x("INSERT INTO login_attempts(email, success, ip_address) VALUES (%s,%s,%s)", (email[:200], ok, client_ip()))
        if ok:
            start_session(u["user_id"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Wrong email or password.", "err")
    return render_template("login.html")

def valid_college(cid):
    return bool(cid and cid.isdigit() and q1("SELECT 1 AS ok FROM colleges WHERE college_id=%s", (int(cid),)))

def check_signup(f):
    """Shared validation for both sign-up forms. Returns {field: message}; empty dict means OK."""
    errs = {}
    if not f.get("name", "").strip(): errs["name"] = "Please enter your name."
    if not f.get("email", "").strip(): errs["email"] = "Please enter your email."
    if len(f.get("password", "")) < 6: errs["password"] = "Password must be at least 6 characters."
    if not valid_college(f.get("college_id", "")): errs["college_id"] = "Please select your college. This is required."
    return errs

def create_user(f, role="participant"):
    uid = q1("""INSERT INTO users(name,email,password_hash,role,college_id,phone) VALUES (%s,%s,%s,%s,%s,%s) RETURNING user_id""",
             (f["name"].strip(), f["email"].strip().lower(), generate_password_hash(f["password"]), role, int(f["college_id"]), f.get("phone", "").strip() or None))["user_id"]
    start_session(uid); return uid

@app.route("/signup", methods=["GET", "POST"])
def signup():
    errs, f = {}, request.form
    if request.method == "POST":
        errs = check_signup(f)
        if errs: flash("Please fix the highlighted fields: " + "; ".join(errs.values()), "err")
        else:
            create_user(f)                   # public sign-up can ONLY ever create a participant
            flash("Welcome to The Anthem Board! Top up your wallet to start registering.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("signup.html", colleges=q("SELECT * FROM colleges ORDER BY name"), errs=errs, f=f)

# Staff accounts need an access code, so students cannot sign themselves up as admin/coordinator/judge/volunteer.
# Set ADMIN_SIGNUP_CODE, COORDINATOR_SIGNUP_CODE, JUDGE_SIGNUP_CODE, VOLUNTEER_SIGNUP_CODE as environment variables.
# Local demo defaults exist only when not running on Render; on Render a role with no code set is switched off.
_DEMO_CODES = {"admin": "ANTHEM-ADMIN", "coordinator": "ANTHEM-COORD", "judge": "ANTHEM-JUDGE", "volunteer": "ANTHEM-VOL"}
def staff_codes():
    out = {}
    for role, demo in _DEMO_CODES.items():
        code = os.environ.get(role.upper() + "_SIGNUP_CODE") or (None if os.environ.get("RENDER") else demo)
        if code: out[role] = code
    return out

@app.route("/staff/signup", methods=["GET", "POST"])
def staff_signup():
    codes, errs, f = staff_codes(), {}, request.form
    if request.method == "POST":
        errs = check_signup(f)
        role = f.get("role", "")
        if role not in codes: errs["role"] = "Pick a role that is open for staff sign-up."
        elif not secrets.compare_digest(f.get("access_code", "").strip().encode(), codes[role].encode()):
            errs["access_code"] = "That access code is not valid for the " + role + " role. Ask the fest admin."
        if errs: flash("Could not create the staff account: " + "; ".join(errs.values()), "err")
        else:
            create_user(f, role)
            flash(f"Staff account created. You are signed in as {role}.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("staff_signup.html", colleges=q("SELECT * FROM colleges ORDER BY name"), roles=list(codes), errs=errs, f=f)

@app.post("/logout")
def logout():
    if session.get("sid"):
        x("UPDATE login_sessions SET logged_out_at=fest_now() WHERE session_id=%s::uuid AND logged_out_at IS NULL", (session["sid"],))
    session.clear(); flash("You have been logged out.", "ok"); return redirect(url_for("home"))

# ---------------------------------------------------------------- participant actions
@app.route("/dashboard")
@login_required
def dashboard():
    uid = g.user["user_id"]
    return render_template("dashboard.html",
        regs=q("SELECT * FROM v_my_registrations WHERE user_id=%s ORDER BY (status='cancelled'), start_time", (uid,)),
        notifs=q("SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC, notif_id DESC LIMIT 8", (uid,)),
        pays=q("SELECT * FROM payments WHERE user_id=%s ORDER BY created_at DESC, payment_id DESC LIMIT 8", (uid,)),
        certs=q("SELECT * FROM v_certificates WHERE user_id=%s ORDER BY start_time", (uid,)))

@app.post("/notifications/read")
@login_required
def notifs_read():
    x("UPDATE notifications SET is_read=TRUE WHERE user_id=%s", (g.user["user_id"],)); return back("dashboard")

@app.post("/wallet/topup")
@login_required
def topup():
    amt = request.form.get("amount", type=float)
    bal = q1("SELECT topup_wallet(%s,%s) AS b", (g.user["user_id"], amt))["b"]
    flash(f"Wallet topped up. New balance: {money(bal)}", "ok"); return redirect(url_for("dashboard"))

@app.post("/events/<int:eid>/register")
@login_required
def register(eid):
    mode, coupon, team_id = request.form.get("mode", "solo"), request.form.get("coupon", "").strip() or None, None
    uid = g.user["user_id"]
    if mode == "create":
        nm = request.form.get("team_name", "").strip()
        if not nm: flash("Give your team a name.", "err"); return back()
        team_id = q1("INSERT INTO teams(event_id,name,leader_id) VALUES (%s,%s,%s) RETURNING team_id", (eid, nm, uid))["team_id"]
    elif mode == "join":
        team_id = request.form.get("team_id", type=int)
    st = q1("SELECT register_for_event(%s,%s,%s,%s) AS reg_id", (uid, eid, team_id, coupon))
    reg = q1("SELECT status FROM registrations WHERE reg_id=%s", (st["reg_id"],))
    flash("You're in! Your QR ticket is on your dashboard." if reg["status"] == "confirmed" else "The event is full, so you've been added to the waitlist.", "ok")
    return redirect(url_for("dashboard"))

@app.post("/registrations/<int:rid>/cancel")
@login_required
def cancel(rid):
    staff = g.user["role"] in STAFF
    x("SELECT cancel_registration(%s,%s)", (rid, None if staff else g.user["user_id"]))
    flash("Registration cancelled and any fee refunded to the wallet.", "ok"); return back("dashboard")

@app.route("/ticket/<int:rid>")
@login_required
def ticket(rid):
    r = q1("SELECT * FROM v_my_registrations WHERE reg_id=%s", (rid,))
    if not r or (r["user_id"] != g.user["user_id"] and g.user["role"] not in STAFF): abort(404)
    owner = q1("SELECT name FROM users WHERE user_id=%s", (r["user_id"],))
    svg = segno.make("FV:" + str(r["qr_token"]), error="m").svg_inline(scale=7, dark="#1E1B3A", light="#ffffff", border=2)
    return render_template("ticket.html", r=r, svg=svg, owner=owner["name"])

@app.post("/registrations/<int:rid>/feedback")
@login_required
def feedback(rid):
    n = x("""INSERT INTO feedback(reg_id,rating,comment) SELECT reg_id,%s,%s FROM registrations WHERE reg_id=%s AND user_id=%s
             ON CONFLICT (reg_id) DO UPDATE SET rating=EXCLUDED.rating, comment=EXCLUDED.comment""",
          (request.form.get("rating", type=int), request.form.get("comment", "").strip() or None, rid, g.user["user_id"]))
    flash("Thanks for the feedback!" if n else "Registration not found.", "ok" if n else "err"); return back("dashboard")

@app.route("/certificate/<int:rid>")
@login_required
def certificate(rid):
    c = q1("SELECT * FROM v_certificates WHERE reg_id=%s AND user_id=%s", (rid, g.user["user_id"]))
    if not c: abort(404, "No certificate yet: you need to attend the event and it must be completed.")
    return render_template("certificate.html", c=c)

# ---------------------------------------------------------------- staff: events + check-in
@app.route("/scan")
@roles("admin", "coordinator", "volunteer")
def scan(): return render_template("scan.html")

@app.post("/api/checkin")
@roles("admin", "coordinator", "volunteer")
def api_checkin():
    tok = (request.get_json(silent=True) or {}).get("token", "").strip().replace("FV:", "")
    res = q1("SELECT scan_checkin(%s::uuid,%s) AS r", (tok, g.user["user_id"]))["r"]
    return jsonify(res)

@app.route("/manage")
@roles("admin", "coordinator")
def manage():
    rows = q("SELECT * FROM v_event_stats" + ("" if g.user["role"] == "admin" else " WHERE coordinator_id=%s") + " ORDER BY start_time",
             None if g.user["role"] == "admin" else (g.user["user_id"],))
    return render_template("manage.html", rows=rows)

@app.route("/manage/events/new", methods=["GET", "POST"])
@app.route("/manage/events/<int:eid>/edit", methods=["GET", "POST"])
@roles("admin", "coordinator")
def event_form(eid=None):
    ev = q1("SELECT * FROM events WHERE event_id=%s", (eid,)) if eid else None
    if eid and not ev: abort(404)
    if ev and not can_manage(ev): abort(403)
    if request.method == "POST":
        f = request.form
        coord = f.get("coordinator_id", type=int) if g.user["role"] == "admin" else g.user["user_id"]
        vals = (f["name"].strip(), f["category"], f.get("description"), f.get("venue_id", type=int), coord or g.user["user_id"], f["start_time"], f["end_time"],
                f.get("fee", 0, type=float), f.get("capacity", type=int), "is_team" in f, f.get("min_team", 1, type=int), f.get("max_team", 1, type=int), f.get("rounds", 1, type=int))
        if ev:
            x("""UPDATE events SET name=%s,category=%s,description=%s,venue_id=%s,coordinator_id=%s,start_time=%s,end_time=%s,fee=%s,capacity=%s,
                 is_team=%s,min_team=%s,max_team=%s,rounds=%s WHERE event_id=%s""", vals + (eid,))
            flash("Event updated.", "ok"); return redirect(url_for("manage_event", eid=eid))
        new = q1("""INSERT INTO events(name,category,description,venue_id,coordinator_id,start_time,end_time,fee,capacity,is_team,min_team,max_team,rounds)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id""", vals)
        flash("Event created. The database confirmed there is no venue clash.", "ok"); return redirect(url_for("manage_event", eid=new["event_id"]))
    return render_template("event_form.html", ev=ev, qr_url=event_qr_url(eid) if eid else None, venues=q("SELECT * FROM venues ORDER BY name"),
                           coords=q("SELECT user_id,name FROM users WHERE role IN ('admin','coordinator') ORDER BY name"))

# ---------------------------------------------------------------- per-event QR (gate / self check-in)
import hmac, hashlib
def event_sig(eid):
    return hmac.new(app.secret_key.encode(), f"event-qr:{eid}".encode(), hashlib.sha256).hexdigest()[:20]
def event_qr_url(eid):
    path = url_for("event_qr_scan", eid=eid, sig=event_sig(eid))
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")      # set this to your live site URL so printed QRs work on phones
    return base + path if base else url_for("event_qr_scan", eid=eid, sig=event_sig(eid), _external=True)

@app.route("/manage/events/<int:eid>/qr.<ext>")
@roles("admin", "coordinator")
def event_qr_image(eid, ext):
    ev = q1("SELECT * FROM events WHERE event_id=%s", (eid,))
    if not ev: abort(404)
    if not can_manage(ev): abort(403)
    if ext not in ("svg", "png"): abort(404)
    code, buf = segno.make(event_qr_url(eid), error="m"), io.BytesIO()
    if ext == "svg": code.save(buf, kind="svg", scale=10, border=3, dark="#1E1B3A")
    else: code.save(buf, kind="png", scale=12, border=3, dark="#1E1B3A")
    name = "".join(ch if ch.isalnum() else "_" for ch in ev["name"])
    return Response(buf.getvalue(), mimetype="image/svg+xml" if ext == "svg" else "image/png",
                    headers={"Content-Disposition": f"inline; filename=qr_{name}.{ext}"} if request.args.get("dl") is None else {"Content-Disposition": f"attachment; filename=qr_{name}.{ext}"})

@app.route("/e/<int:eid>/<sig>")
@login_required
def event_qr_scan(eid, sig):
    """Opened when someone scans an event's QR. A registered participant is checked in (or out) using their own ticket;
    staff see the event's manage page; anyone else lands on the event page to register."""
    ev = q1("SELECT * FROM events WHERE event_id=%s", (eid,))
    if not ev or not hmac.compare_digest(sig, event_sig(eid)): abort(404, "This event QR code is not valid.")
    if g.user["role"] in STAFF and can_manage(ev): return redirect(url_for("manage_event", eid=eid))
    reg = q1("SELECT qr_token FROM registrations WHERE event_id=%s AND user_id=%s AND status='confirmed'", (eid, g.user["user_id"]))
    if not reg:
        flash("You are not registered for this event yet. Register below, then scan again at the gate.", "err")
        return redirect(url_for("event", eid=eid))
    try: res = q1("SELECT scan_checkin(%s::uuid,%s) AS r", (str(reg["qr_token"]), g.user["user_id"]))["r"]
    except psycopg2.Error as e:
        db().rollback(); flash(friendly(e), "err"); return redirect(url_for("event", eid=eid))
    flash(("Entry recorded" if res["direction"] == "in" else "Exit recorded") + f" for {res['event']}.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/manage/events/<int:eid>")
@roles("admin", "coordinator")
def manage_event(eid):
    ev = q1("SELECT * FROM v_event_stats WHERE event_id=%s", (eid,))
    if not ev: abort(404)
    if not can_manage(ev): abort(403)
    return render_template("manage_event.html", ev=ev, qr_url=event_qr_url(eid),
        regs=q("""SELECT r.reg_id, u.name, u.email, c.name AS college, t.name AS team, r.status, r.amount_paid,
                  EXISTS (SELECT 1 FROM checkins k WHERE k.reg_id=r.reg_id AND k.direction='in') AS attended
                  FROM registrations r JOIN users u ON u.user_id=r.user_id LEFT JOIN colleges c ON c.college_id=u.college_id
                  LEFT JOIN teams t ON t.team_id=r.team_id WHERE r.event_id=%s ORDER BY (r.status='cancelled'), r.status, r.registered_at""", (eid,)),
        teams=q("SELECT * FROM v_team_status WHERE event_id=%s ORDER BY name", (eid,)),
        judges=q("""SELECT u.user_id, u.name, c.name AS college FROM judge_assignments ja JOIN users u ON u.user_id=ja.judge_id
                    LEFT JOIN colleges c ON c.college_id=u.college_id WHERE ja.event_id=%s""", (eid,)),
        all_judges=q("SELECT u.user_id, u.name, c.name AS college FROM users u LEFT JOIN colleges c ON c.college_id=u.college_id WHERE role='judge' ORDER BY u.name"),
        shifts=q("SELECT s.*, u.name FROM volunteer_shifts s JOIN users u ON u.user_id=s.volunteer_id WHERE event_id=%s ORDER BY shift_start", (eid,)),
        vols=q("SELECT user_id,name FROM users WHERE role='volunteer' ORDER BY name"),
        allocs=q("SELECT a.qty, r.resource_id, r.name, r.type FROM allocations a JOIN resources r ON r.resource_id=a.resource_id WHERE a.event_id=%s", (eid,)),
        resources=q("SELECT * FROM resources ORDER BY type, name"),
        exps=q("SELECT * FROM expenses WHERE event_id=%s ORDER BY spent_on DESC, expense_id DESC", (eid,)))

@app.post("/manage/events/<int:eid>/do")
@roles("admin", "coordinator")
def manage_do(eid):
    ev = q1("SELECT * FROM events WHERE event_id=%s", (eid,))
    if not ev: abort(404)
    if not can_manage(ev): abort(403)
    f, a = request.form, request.form.get("action")
    if a == "status":
        if f["status"] in ("scheduled", "live", "completed", "cancelled"):
            x("UPDATE events SET status=%s WHERE event_id=%s", (f["status"], eid)); flash("Status set to " + f["status"] + ".", "ok")
    elif a == "add_judge": x("INSERT INTO judge_assignments VALUES (%s,%s)", (eid, f.get("judge_id", type=int))); flash("Judge assigned.", "ok")
    elif a == "del_judge": x("DELETE FROM judge_assignments WHERE event_id=%s AND judge_id=%s", (eid, f.get("judge_id", type=int)))
    elif a == "add_shift":
        x("INSERT INTO volunteer_shifts(event_id,volunteer_id,task,shift_start,shift_end) VALUES (%s,%s,%s,%s,%s)",
          (eid, f.get("volunteer_id", type=int), f["task"].strip(), f["shift_start"], f["shift_end"])); flash("Shift added.", "ok")
    elif a == "del_shift": x("DELETE FROM volunteer_shifts WHERE shift_id=%s AND event_id=%s", (f.get("shift_id", type=int), eid))
    elif a == "add_alloc":
        x("INSERT INTO allocations VALUES (%s,%s,%s) ON CONFLICT (event_id,resource_id) DO UPDATE SET qty=EXCLUDED.qty",
          (eid, f.get("resource_id", type=int), f.get("qty", type=int))); flash("Resource allocated.", "ok")
    elif a == "del_alloc": x("DELETE FROM allocations WHERE event_id=%s AND resource_id=%s", (eid, f.get("resource_id", type=int)))
    elif a == "add_expense":
        x("INSERT INTO expenses(event_id,category,description,amount) VALUES (%s,%s,%s,%s)", (eid, f["category"].strip(), f.get("description"), f.get("amount", type=float))); flash("Expense recorded.", "ok")
    elif a == "del_expense": x("DELETE FROM expenses WHERE expense_id=%s AND event_id=%s", (f.get("expense_id", type=int), eid))
    return redirect(url_for("manage_event", eid=eid))

@app.route("/manage/events/<int:eid>/registrations.csv")
@roles("admin", "coordinator")
def event_csv(eid):
    ev = q1("SELECT * FROM events WHERE event_id=%s", (eid,))
    if not ev: abort(404)
    if not can_manage(ev): abort(403)
    rows = q("""SELECT u.name, u.email, u.phone, c.name AS college, t.name AS team, r.status, r.amount_paid, r.registered_at
                FROM registrations r JOIN users u ON u.user_id=r.user_id LEFT JOIN colleges c ON c.college_id=u.college_id
                LEFT JOIN teams t ON t.team_id=r.team_id WHERE r.event_id=%s ORDER BY r.registered_at""", (eid,))
    return csv_response(rows, f"registrations_event_{eid}.csv")

def csv_response(rows, filename):
    out = io.StringIO()
    if rows:
        w = csv.writer(out); w.writerow(rows[0].keys())
        for r in rows: w.writerow(r.values())
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

# ---------------------------------------------------------------- judges and volunteers
@app.route("/judge")
@roles("judge")
def judge_home():
    return render_template("judge_home.html", rows=q("""SELECT s.* FROM judge_assignments ja JOIN v_event_stats s ON s.event_id=ja.event_id
                                                       WHERE ja.judge_id=%s ORDER BY s.start_time""", (g.user["user_id"],)))

@app.route("/judge/events/<int:eid>", methods=["GET", "POST"])
@roles("judge")
def judge_event(eid):
    ev = q1("SELECT s.* FROM judge_assignments ja JOIN v_event_stats s ON s.event_id=ja.event_id WHERE ja.judge_id=%s AND ja.event_id=%s", (g.user["user_id"], eid))
    if not ev: abort(403, "You are not assigned to this event.")
    rd = min(max(request.values.get("round", 1, type=int), 1), ev["rounds"])
    if request.method == "POST":
        n = 0
        for k, v in request.form.items():
            if k.startswith("score_") and v.strip() != "":
                rid = int(k[6:])
                x("""INSERT INTO scores(reg_id,judge_id,round_no,score,remarks) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (reg_id,judge_id,round_no) DO UPDATE SET score=EXCLUDED.score, remarks=EXCLUDED.remarks, scored_at=fest_now()""",
                  (rid, g.user["user_id"], rd, float(v), request.form.get(f"remarks_{rid}") or None)); n += 1
        flash(f"Saved {n} score(s) for round {rd}.", "ok"); return redirect(url_for("judge_event", eid=eid, round=rd))
    entries = q("""SELECT r.reg_id, COALESCE(t.name,u.name) AS entry_name, c.name AS college, fn_has_conflict(%s, r.reg_id) AS conflict,
                   s.score, s.remarks FROM registrations r JOIN users u ON u.user_id=r.user_id LEFT JOIN teams t ON t.team_id=r.team_id
                   LEFT JOIN colleges c ON c.college_id=u.college_id
                   LEFT JOIN scores s ON s.reg_id=r.reg_id AND s.judge_id=%s AND s.round_no=%s
                   WHERE r.event_id=%s AND r.status='confirmed' AND (r.team_id IS NULL OR r.user_id=t.leader_id) ORDER BY entry_name""",
                (g.user["user_id"], g.user["user_id"], rd, eid))
    return render_template("judge_event.html", ev=ev, rd=rd, entries=entries)

@app.route("/volunteer")
@roles("volunteer")
def volunteer_home():
    return render_template("volunteer.html", shifts=q("""SELECT s.*, e.name AS event_name, v.name AS venue FROM volunteer_shifts s
        JOIN events e ON e.event_id=s.event_id JOIN venues v ON v.venue_id=e.venue_id WHERE s.volunteer_id=%s ORDER BY s.shift_start""", (g.user["user_id"],)))

# ---------------------------------------------------------------- admin
@app.route("/admin")
@roles("admin")
def admin():
    j = lambda rows: json.loads(json.dumps(rows, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)))
    hours = list(range(8, 24))
    regs_h = {r["hr"]: r["regs"] for r in q("SELECT * FROM v_hourly_registrations")}
    chk_h = {r["hr"]: r["entries"] for r in q("SELECT * FROM v_hourly_checkins")}
    return render_template("admin.html", s=q1("SELECT * FROM v_fest_summary"),
        popular=q("SELECT * FROM v_event_stats WHERE status<>'cancelled' ORDER BY confirmed+waitlisted DESC LIMIT 6"),
        rev=j(q("SELECT name, revenue FROM v_event_stats WHERE revenue>0 ORDER BY revenue DESC LIMIT 8")),
        cats=j(q("SELECT category, SUM(confirmed) AS n FROM v_event_stats GROUP BY category ORDER BY n DESC")),
        colleges=j(q("SELECT name, participants FROM v_college_participation ORDER BY participants DESC")),
        hours=[f"{h}:00" for h in hours], regs_h=[int(regs_h.get(h, 0)) for h in hours], chk_h=[int(chk_h.get(h, 0)) for h in hours])

EXPORTS = {
    "events": "SELECT event_id,name,category,venue,start_time,fee,capacity,confirmed,waitlisted,revenue,sponsorship,expenses,profit,avg_rating,status FROM v_event_stats ORDER BY start_time",
    "registrations": "SELECT r.reg_id,e.name AS event,u.name AS person,u.email,c.name AS college,r.status,r.amount_paid,r.registered_at FROM registrations r JOIN events e ON e.event_id=r.event_id JOIN users u ON u.user_id=r.user_id LEFT JOIN colleges c ON c.college_id=u.college_id ORDER BY r.reg_id",
    "payments": "SELECT p.payment_id,u.name AS person,p.kind,p.amount,p.note,p.created_at FROM payments p JOIN users u ON u.user_id=p.user_id ORDER BY p.payment_id",
    "colleges": "SELECT name,city,participants,entries FROM v_college_participation ORDER BY participants DESC",
    "leaderboard": "SELECT e.name AS event,l.rank,l.entry_name,l.college,l.total FROM v_leaderboard l JOIN events e ON e.event_id=l.event_id ORDER BY e.name,l.rank",
}
@app.route("/admin/export/<name>.csv")
@roles("admin")
def export(name):
    if name not in EXPORTS: abort(404)
    return csv_response(q(EXPORTS[name]), f"anthemboard_{name}.csv")

@app.route("/admin/finance", methods=["GET", "POST"])
@roles("admin")
def admin_finance():
    if request.method == "POST":
        f, a = request.form, request.form.get("action")
        ev = f.get("event_id", type=int) or None
        if a == "add_sponsor": x("INSERT INTO sponsors(name,tier,contact_email) VALUES (%s,%s,%s)", (f["name"].strip(), f["tier"], f.get("contact_email") or None))
        elif a == "add_sponsorship": x("INSERT INTO sponsorships(sponsor_id,event_id,amount) VALUES (%s,%s,%s)", (f.get("sponsor_id", type=int), ev, f.get("amount", type=float)))
        elif a == "add_expense": x("INSERT INTO expenses(event_id,category,description,amount) VALUES (%s,%s,%s,%s)", (ev, f["category"].strip(), f.get("description"), f.get("amount", type=float)))
        flash("Saved.", "ok"); return redirect(url_for("admin_finance"))
    return render_template("finance.html",
        ev=q("SELECT * FROM v_event_stats ORDER BY start_time"), events=q("SELECT event_id,name FROM events ORDER BY name"),
        sponsors=q("""SELECT s.*, COALESCE(SUM(sp.amount),0) AS total FROM sponsors s LEFT JOIN sponsorships sp ON sp.sponsor_id=s.sponsor_id
                      GROUP BY s.sponsor_id ORDER BY total DESC"""),
        summary=q1("SELECT * FROM v_fest_summary"),
        fest_exp=q("SELECT * FROM expenses WHERE event_id IS NULL ORDER BY expense_id DESC"))

@app.route("/admin/catalog", methods=["GET", "POST"])
@roles("admin")
def admin_catalog():
    if request.method == "POST":
        f, a = request.form, request.form.get("action")
        if a == "add_venue": x("INSERT INTO venues(name,location,capacity) VALUES (%s,%s,%s)", (f["name"].strip(), f.get("location"), f.get("capacity", type=int)))
        elif a == "add_resource": x("INSERT INTO resources(name,type,total_qty) VALUES (%s,%s,%s)", (f["name"].strip(), f["type"], f.get("total_qty", type=int)))
        elif a == "add_college": x("INSERT INTO colleges(name,city) VALUES (%s,%s)", (f["name"].strip(), f["city"].strip()))
        elif a == "add_coupon":
            x("INSERT INTO coupons(code,discount_pct,max_uses,valid_until) VALUES (upper(%s),%s,%s,%s)",
              (f["code"].strip(), f.get("discount_pct", type=int), f.get("max_uses", type=int), f.get("valid_until") or None))
        elif a == "toggle_coupon": x("UPDATE coupons SET active = NOT active WHERE coupon_id=%s", (f.get("coupon_id", type=int),))
        flash("Saved.", "ok"); return redirect(url_for("admin_catalog"))
    return render_template("catalog.html", venues=q("SELECT * FROM venues ORDER BY name"), resources=q("SELECT * FROM resources ORDER BY type,name"),
                           coupons=q("SELECT * FROM coupons ORDER BY coupon_id"), colleges=q("SELECT * FROM colleges ORDER BY name"))

@app.route("/admin/users")
@roles("admin")
def admin_users():
    term = request.args.get("q", "").strip()
    rows = q("""SELECT u.*, c.name AS college FROM users u LEFT JOIN colleges c ON c.college_id=u.college_id
                WHERE (%s='' OR u.name ILIKE %s OR u.email ILIKE %s) ORDER BY (u.role='participant'), u.role, u.name LIMIT 150""", (term, f"%{term}%", f"%{term}%"))
    return render_template("users.html", rows=rows, term=term)

@app.post("/admin/users/<int:uid>/role")
@roles("admin")
def user_role(uid):
    if uid == g.user["user_id"]: flash("You cannot change your own role.", "err"); return back("admin_users")
    x("UPDATE users SET role=%s WHERE user_id=%s", (request.form["role"], uid)); flash("Role updated.", "ok"); return back("admin_users")

@app.route("/admin/audit")
@roles("admin")
def admin_audit():
    tbl = request.args.get("table", "")
    rows = q("""SELECT a.*, u.name AS who FROM audit_log a LEFT JOIN users u ON u.user_id=a.changed_by
                WHERE (%s='' OR a.table_name=%s) ORDER BY a.log_id DESC LIMIT 150""", (tbl, tbl))
    for r in rows:
        r["diff"] = ""
        if r["action"] == "UPDATE" and r["old_data"] and r["new_data"]:
            r["diff"] = "; ".join(f"{k}: {r['old_data'].get(k)} → {v}" for k, v in r["new_data"].items() if r["old_data"].get(k) != v)[:240]
        elif r["action"] == "INSERT" and r["new_data"]:
            r["diff"] = "new " + (r["new_data"].get("name") or r["new_data"].get("code") or r["new_data"].get("category") or "row")
        elif r["action"] == "DELETE" and r["old_data"]:
            r["diff"] = "removed " + str(r["old_data"].get("name") or r["old_data"].get("code") or "row")
    tables = [r["table_name"] for r in q("SELECT DISTINCT table_name FROM audit_log ORDER BY 1")]
    return render_template("audit.html", rows=rows, tables=tables, tbl=tbl)

@app.route("/admin/sessions")
@roles("admin")
def admin_sessions():
    return render_template("sessions.html", my_sid=session.get("sid"),
        active=q("SELECT * FROM v_active_sessions"), history=q("SELECT * FROM v_login_history LIMIT 40"),
        attempts=q("SELECT * FROM login_attempts ORDER BY attempt_id DESC LIMIT 15"))

@app.post("/admin/sessions/<sid>/logout")
@roles("admin")
def force_logout(sid):
    n = x("UPDATE login_sessions SET logged_out_at=fest_now() WHERE session_id=%s::uuid AND logged_out_at IS NULL", (sid,))
    flash("That session was logged out." if n else "Session not found or already closed.", "ok" if n else "err"); return redirect(url_for("admin_sessions"))

@app.post("/admin/sync")
@roles("admin")
def admin_sync():
    n = q1("SELECT fn_sync_event_status() AS n")["n"]; flash(f"{n} event status(es) updated from the clock.", "ok"); return back("admin")

@app.post("/admin/reseed")
@roles("admin")
def admin_reseed():
    import init_db
    g.conn.commit()                        # release our own locks before DROP TABLE
    c = psycopg2.connect(DB_URL)
    try: init_db.build(c, reset=True)
    finally: c.close()
    session.clear(); flash("Demo data rebuilt. Please log in again.", "ok"); return redirect(url_for("login"))

# ---------------------------------------------------------------- DBMS lab (admin only)
@app.post("/dbms/benchmark")
@roles("admin")
def benchmark():
    """Index demo: build a 300k-row temp table, time a lookup before and after CREATE INDEX, then roll everything back."""
    conn = db(); cur = conn.cursor()
    def plan(sql):
        cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + sql)
        p = cur.fetchone()["QUERY PLAN"][0]
        node = p["Plan"]
        while "Plans" in node and "Scan" not in node["Node Type"]: node = node["Plans"][0]
        return dict(ms=round(p["Execution Time"], 3), scan=node["Node Type"], rows=node.get("Actual Rows"))
    cur.execute("""CREATE TEMP TABLE bench_reg AS SELECT g AS reg_id, (random()*500)::int AS event_id, (random()*20000)::int AS user_id,
                   now() - random()*interval '30 days' AS ts FROM generate_series(1,300000) g""")
    cur.execute("ANALYZE bench_reg")
    sql = "SELECT * FROM bench_reg WHERE user_id = 4242"
    before = plan(sql)
    cur.execute("CREATE INDEX bench_user ON bench_reg(user_id)"); cur.execute("ANALYZE bench_reg")
    after = plan(sql)
    conn.rollback()
    bench = dict(query=sql, before=before, after=after, speedup=round(before["ms"] / max(after["ms"], 0.001)))
    return render_template("dbms.html", admin=True, bench=bench, console=None, **dbms_ctx())

@app.post("/dbms/query")
@roles("admin")
def console():
    sql = request.form.get("sql", "").strip().rstrip(";").strip()
    res = dict(sql=sql)
    if not sql.lower().startswith(("select", "with", "explain")) or ";" in sql:
        res["error"] = "Only a single SELECT / WITH / EXPLAIN statement is allowed."
    else:
        c = psycopg2.connect(DB_URL, options="-c statement_timeout=4000", cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            c.set_session(readonly=True)         # enforced by PostgreSQL itself, not by string checks
            with c.cursor() as cur:
                t = time.perf_counter(); cur.execute(sql); rows = cur.fetchmany(100)
                res.update(cols=[d[0] for d in cur.description], rows=[list(r.values()) for r in rows], ms=round((time.perf_counter() - t) * 1000, 1))
        except psycopg2.Error as e:
            res["error"] = (e.diag.message_primary if e.diag and e.diag.message_primary else str(e))
        finally: c.close()
    res = json.loads(json.dumps(res, default=str))
    return render_template("dbms.html", admin=True, bench=None, console=res, **dbms_ctx())

if __name__ == "__main__":
    if DB_URL:
        import init_db
        try: init_db.ensure(DB_URL)          # builds + seeds on first run
        except psycopg2.Error as e: print("[The Anthem Board] Could not prepare the database:", e)
    else:
        print("[The Anthem Board]", DB_PROBLEM)
    app.run(debug=True, use_reloader=False, port=int(os.environ.get("PORT", 5000)))
