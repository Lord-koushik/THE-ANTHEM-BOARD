"""Print who is logged in, straight from the database.
   python show_logins.py            one snapshot
   python show_logins.py --watch    refresh every 2 seconds (log in/out in the browser and watch it change)"""
import sys, time, psycopg2, psycopg2.extras
import local_db

def table(title, rows, cols):
    print(f"\n== {title} ({len(rows)}) ==")
    if not rows: print("  (none)"); return
    w = {c: max(len(c), *(len(str(r[c] if r[c] is not None else "")) for r in rows)) for c in cols}
    print("  " + "  ".join(c.upper().ljust(w[c]) for c in cols))
    for r in rows:
        print("  " + "  ".join(str(r[c] if r[c] is not None else "").ljust(w[c]) for c in cols))

def snapshot(cur):
    cur.execute("SELECT name, email, role, to_char(logged_in_at,'DD Mon HH24:MI:SS') AS logged_in, to_char(last_seen,'HH24:MI:SS') AS last_seen, minutes_online::int AS mins FROM v_active_sessions")
    table("LOGGED IN NOW", cur.fetchall(), ["name", "email", "role", "logged_in", "last_seen", "mins"])
    cur.execute("SELECT name, role, to_char(logged_in_at,'DD Mon HH24:MI:SS') AS logged_in, state, minutes::int AS mins FROM v_login_history LIMIT 10")
    table("RECENT LOGINS", cur.fetchall(), ["name", "role", "logged_in", "state", "mins"])
    cur.execute("SELECT email, CASE WHEN success THEN 'ok' ELSE 'FAILED' END AS result, to_char(attempted_at,'DD Mon HH24:MI:SS') AS at FROM login_attempts ORDER BY attempt_id DESC LIMIT 5")
    table("LAST LOGIN ATTEMPTS", cur.fetchall(), ["email", "result", "at"])

if __name__ == "__main__":
    conn = psycopg2.connect(local_db.resolve_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    cur = conn.cursor()
    while True:
        if "--watch" in sys.argv: print("\033[2J\033[H", end="")
        snapshot(cur)
        if "--watch" not in sys.argv: break
        print("\n(refreshing every 2s, Ctrl+C to stop)"); time.sleep(2)
