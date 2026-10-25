"""Create the schema and load demo data.
   python init_db.py           -> only if the database is empty (safe to run on every deploy)
   python init_db.py --reset   -> wipe everything and re-seed (dates are relative to *now*)
"""
import os, sys, random
from datetime import datetime, timedelta, date, timezone
import psycopg2
from werkzeug.security import generate_password_hash

import local_db
HERE = os.path.dirname(os.path.abspath(__file__))

RESET_SQL = """
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT viewname FROM pg_views WHERE schemaname='public' LOOP
    EXECUTE 'DROP VIEW IF EXISTS public.'||quote_ident(r.viewname)||' CASCADE'; END LOOP;
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE 'DROP TABLE IF EXISTS public.'||quote_ident(r.tablename)||' CASCADE'; END LOOP;
  FOR r IN SELECT format('DROP FUNCTION IF EXISTS public.%I(%s) CASCADE', p.proname, pg_get_function_identity_arguments(p.oid)) AS s
           FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=p.oid AND d.deptype='e') LOOP
    EXECUTE r.s; END LOOP;
END $$;
"""

COLLEGES = [("Kongu Engineering College", "Perundurai"), ("PSG College of Technology", "Coimbatore"),
            ("Coimbatore Institute of Technology", "Coimbatore"), ("CEG, Anna University", "Chennai"),
            ("NIT Tiruchirappalli", "Tiruchirappalli"), ("Thiagarajar College of Engineering", "Madurai"),
            ("SSN College of Engineering", "Chennai"), ("Amrita Vishwa Vidyapeetham", "Coimbatore")]
VENUES = [("Main Auditorium", "Block A", 1200), ("Open Air Theatre", "Central Lawn", 2000), ("Seminar Hall", "Block B", 150),
          ("CS Lab 1", "Block C, Floor 1", 60), ("CS Lab 2", "Block C, Floor 2", 60), ("Sports Arena", "Ground", 800)]
NAMES = ["Aarav Kumar", "Divya Lakshmi", "Karthik Raja", "Meena Sundaram", "Rahul Menon", "Sneha Iyer", "Vignesh Pillai",
         "Harini Subramanian", "Arun Prakash", "Keerthana Nair", "Siddharth Rao", "Nandhini Venkat", "Surya Narayanan",
         "Pooja Krishnan", "Dinesh Babu", "Ishita Sharma", "Manoj Kumar", "Lavanya Ravi", "Gokul Anand", "Revathi Murugan",
         "Prakash Selvam", "Shruti Balaji", "Naveen Chandran", "Aishwarya Mohan", "Tarun Gupta", "Janani Natarajan",
         "Bharath Kannan", "Swetha Ramesh", "Yuvaraj Dev", "Anjali Thomas", "Mohamed Faisal", "Deepika Rangan",
         "Hari Vasudevan", "Kavya Reddy", "Sanjay Mathew", "Ritika Jain"]
QUOTES = ["Brilliantly organised!", "Loved the energy.", "Judges were fair and friendly.", "Could start on time, but great event.",
          "Best event of the fest.", "Great venue and crowd.", "Learned a lot, thanks!", "Well planned, smooth check-in."]


def connect(url=None):
    return psycopg2.connect(url or local_db.resolve_url())


def is_empty(cur):
    cur.execute("SELECT to_regclass('public.users') IS NULL")
    return cur.fetchone()[0]


def build(conn, reset=False):
    cur = conn.cursor()
    if reset:
        cur.execute(RESET_SQL)
    cur.execute(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    cur.execute(open(os.path.join(HERE, "sessions.sql"), encoding="utf-8").read())
    conn.commit()
    seed(conn)


def seed(conn):
    random.seed(7)
    cur = conn.cursor()
    pw = generate_password_hash("fest123")
    adminpw = generate_password_hash("admin123")
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)   # IST
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(day, hh, mm=0): return d0 + timedelta(days=day, hours=hh, minutes=mm)
    def one(sql, a=()): cur.execute(sql, a); return cur.fetchone()[0]

    for n, c in COLLEGES: cur.execute("INSERT INTO colleges(name, city) VALUES (%s,%s)", (n, c))
    for n, l, c in VENUES: cur.execute("INSERT INTO venues(name, location, capacity) VALUES (%s,%s,%s)", (n, l, c))

    def user(name, email, role, college, wallet=0, h=pw):
        return one("INSERT INTO users(name,email,password_hash,role,college_id,wallet_balance) VALUES (%s,%s,%s,%s,%s,%s) RETURNING user_id",
                   (name, email, h, role, college, wallet))

    admin = user("Fest Admin", "admin@festverse.in", "admin", 1, 0, adminpw)
    coords = [user("Priya Natarajan", "priya@festverse.in", "coordinator", 1), user("Arjun Menon", "arjun@festverse.in", "coordinator", 1)]
    judges = [user("Dr. Suresh Kumar", "judge1@festverse.in", "judge", 2), user("Prof. Anitha Ravi", "judge2@festverse.in", "judge", 5),
              user("Mr. Vikram Shah", "judge3@festverse.in", "judge", 4)]
    vols = [user("Ravi Teja", "volunteer1@festverse.in", "volunteer", 1), user("Nisha Paul", "volunteer2@festverse.in", "volunteer", 1),
            user("Kiran Das", "volunteer3@festverse.in", "volunteer", 1)]
    student = user("Demo Student", "student@festverse.in", "participant", 1, 3000)
    people = [student]
    for i, n in enumerate(NAMES):
        people.append(user(n, n.lower().replace(" ", ".") + "@mail.festverse.in", "participant", (i % 8) + 1, 3000))

    for code, pct, mx, valid, act in [("FEST20", 20, None, date.today() + timedelta(days=60), True),
                                      ("EARLYBIRD", 15, 50, date.today() + timedelta(days=60), True),
                                      ("STUDENT10", 10, None, None, True), ("OLD50", 50, 10, date.today() - timedelta(days=5), False)]:
        cur.execute("INSERT INTO coupons(code,discount_pct,max_uses,valid_until,active) VALUES (%s,%s,%s,%s,%s)", (code, pct, mx, valid, act))

    # name, cat, venue_id, day, h1, h2, fee, cap, team(min,max)|None, rounds, coord, desc
    EV = [
     ("Code Sprint", "Technical", 4, -1, 10, 13, 100, 40, None, 2, 0, "Solve algorithmic problems against the clock in a two-round contest."),
     ("Battle of Bands", "Cultural", 2, -1, 17, 20, 500, 24, (3, 5), 1, 1, "Original sets, 12 minutes each. Bring your own instruments."),
     ("Poetry Slam", "Literary", 3, -1, 14, 16, 50, 30, None, 1, 1, "Three minutes, one stage, no props."),
     ("Hack the Fest", "Technical", 5, 0, 9, 14, 300, 12, (2, 4), 2, 0, "Build something useful for campus life in five hours."),
     ("Valorant Showdown", "Gaming", 4, 0, 14, 18, 250, 10, (5, 5), 1, 1, "5v5 tactical shooter bracket. Limited seats, expect a waitlist."),
     ("Street Play", "Cultural", 2, 0, 15, 17, 200, 40, (4, 8), 1, 1, "A 15-minute nukkad natak on a social theme."),
     ("AI & ML Workshop", "Workshop", 3, 1, 10, 13, 150, 100, None, 1, 0, "Hands-on: train and deploy your first model."),
     ("Dance Off", "Cultural", 1, 1, 16, 19, 300, 60, (2, 6), 1, 1, "Group dance battle, any style."),
     ("Quiz Wizards", "Literary", 3, 1, 14, 16, 80, 60, (2, 3), 2, 1, "General, tech and pop-culture rounds."),
     ("Football 5v5", "Sports", 6, 1, 9, 13, 400, 50, (5, 8), 1, 1, "Knockout tournament on the turf."),
     ("Treasure Hunt", "Gaming", 6, 1, 14, 17, 60, 100, (2, 4), 1, 1, "Clues spread across the campus. First team back wins."),
     ("Robo Wars", "Technical", 6, 2, 10, 15, 600, 40, (2, 4), 2, 0, "Build it, bring it, break the other bot."),
     ("UI/UX Design Sprint", "Workshop", 5, 2, 11, 14, 120, 40, None, 1, 0, "Redesign a real app screen in three hours."),
     ("Fest Night Concert", "Cultural", 2, 2, 18, 22, 100, 1500, None, 1, 0, "Closing night. Headline act revealed at the gates."),
    ]
    eids = {}
    for name, cat, ven, day, h1, h2, fee, cap, team, rounds, ci, desc in EV:
        eids[name] = one("""INSERT INTO events(name,category,description,venue_id,coordinator_id,start_time,end_time,fee,capacity,is_team,min_team,max_team,rounds)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id""",
                         (name, cat, desc, ven, coords[ci], at(day, h1), at(day, h2), fee, cap, bool(team), team[0] if team else 1, team[1] if team else 1, rounds))

    def sp(sql, a):   # savepoint wrapper: ignore rule violations (clashes etc.) while seeding
        cur.execute("SAVEPOINT s")
        try:
            cur.execute(sql, a); r = cur.fetchone(); cur.execute("RELEASE SAVEPOINT s"); return r[0] if r else None
        except psycopg2.Error:
            cur.execute("ROLLBACK TO SAVEPOINT s"); return None

    pool = people[:]
    def solo(ev, k, must=()):
        chosen = list(must) + random.sample([p for p in pool if p not in must], k - len(must))
        for u in chosen: sp("SELECT register_for_event(%s,%s,NULL,NULL)", (u, eids[ev]))
    TEAMNAMES = ["Byte Bandits", "Null Pointers", "Stack Overflow", "Rhythm Rebels", "Blue Comets", "Neon Knights", "Vortex", "Phoenix",
                 "The Debuggers", "Alpha Squad", "Delta Force", "Thunder", "Mavericks", "Orbit", "Sparks", "Titans", "Zenith", "Echo"]
    tn = iter(TEAMNAMES * 4)
    def teams(ev, n, lo, hi, must_first=None):
        made = tries = 0
        while made < n and tries < n * 6:
            tries += 1
            size = random.randint(lo, hi); members = random.sample(pool, size)
            if must_first and made == 0: members = [must_first] + [m for m in members if m != must_first][:size - 1]
            cur.execute("SAVEPOINT t")
            try:
                tid = one("INSERT INTO teams(event_id,name,leader_id) VALUES (%s,%s,%s) RETURNING team_id", (eids[ev], next(tn), members[0]))
                if sp("SELECT register_for_event(%s,%s,%s,NULL)", (members[0], eids[ev], tid)) is None:
                    cur.execute("ROLLBACK TO SAVEPOINT t"); continue
                for m in members[1:]: sp("SELECT register_for_event(%s,%s,%s,NULL)", (m, eids[ev], tid))
                cur.execute("RELEASE SAVEPOINT t"); made += 1
            except psycopg2.Error:
                cur.execute("ROLLBACK TO SAVEPOINT t")

    solo("Code Sprint", 28, must=[student]); solo("Poetry Slam", 14); teams("Battle of Bands", 4, 3, 5)
    teams("Hack the Fest", 5, 2, 4); teams("Valorant Showdown", 3, 5, 5); teams("Street Play", 2, 4, 6)
    solo("AI & ML Workshop", 20, must=[student]); teams("Dance Off", 4, 2, 5); teams("Quiz Wizards", 6, 2, 3, must_first=student)
    teams("Football 5v5", 3, 5, 6); teams("Treasure Hunt", 4, 2, 4); teams("Robo Wars", 3, 2, 4)
    solo("UI/UX Design Sprint", 12); solo("Fest Night Concert", 25)

    # spread registration timestamps over the past 5 days, evening-heavy, keeping waitlist order
    cur.execute("SELECT reg_id FROM registrations ORDER BY reg_id"); ids = [r[0] for r in cur.fetchall()]
    hours = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]; wts = [2, 3, 4, 5, 4, 3, 3, 4, 5, 7, 8, 9, 7, 4]
    stamps = sorted(d0 - timedelta(days=random.randint(0, 5)) + timedelta(hours=random.choices(hours, wts)[0], minutes=random.randint(0, 59)) for _ in ids)
    for rid, ts in zip(ids, stamps): cur.execute("UPDATE registrations SET registered_at=%s WHERE reg_id=%s", (ts, rid))

    # judges
    J = {"Code Sprint": judges[:2], "Battle of Bands": judges, "Poetry Slam": judges[1:], "Hack the Fest": judges[:2]}
    for ev, js in J.items():
        for j in js: cur.execute("INSERT INTO judge_assignments VALUES (%s,%s)", (eids[ev], j))
    for ev in ("Quiz Wizards", "Dance Off"): cur.execute("INSERT INTO judge_assignments VALUES (%s,%s)", (eids[ev], judges[2]))

    # check-ins for finished + live events, then scores
    def run_event(ev, status_final, rounds_done):
        eid = eids[ev]
        cur.execute("SELECT reg_id, user_id FROM registrations WHERE event_id=%s AND status='confirmed' ORDER BY reg_id", (eid,))
        start = [e for e in EV if e[0] == ev][0]
        t0 = at(start[3], start[4])
        for rid, uid in cur.fetchall():
            if random.random() < 0.92 or uid == student:
                cur.execute("SAVEPOINT c")
                try:
                    cur.execute("SELECT scan_checkin((SELECT qr_token FROM registrations WHERE reg_id=%s), %s)", (rid, random.choice(vols)))
                    cur.execute("UPDATE checkins SET scanned_at=%s WHERE reg_id=%s", (t0 - timedelta(minutes=random.randint(0, 40)), rid))
                    cur.execute("RELEASE SAVEPOINT c")
                except psycopg2.Error: cur.execute("ROLLBACK TO SAVEPOINT c")
        cur.execute("UPDATE events SET status='live' WHERE event_id=%s", (eid,))
        cur.execute("""SELECT r.reg_id, r.user_id FROM registrations r LEFT JOIN teams t ON t.team_id=r.team_id
                       WHERE r.event_id=%s AND r.status='confirmed' AND (r.team_id IS NULL OR r.user_id=t.leader_id)""", (eid,))
        entries = cur.fetchall()
        for rd in range(1, rounds_done + 1):
            for rid, uid in entries:
                for j in J[ev]:
                    base = 96 if uid == student and ev == "Code Sprint" else random.uniform(52, 92)
                    sp("INSERT INTO scores(reg_id,judge_id,round_no,score,remarks) VALUES (%s,%s,%s,%s,%s) RETURNING score_id",
                       (rid, j, rd, round(base + random.uniform(-2, 3), 1) if base < 96 else base, None))
        if status_final != "live": cur.execute("UPDATE events SET status=%s WHERE event_id=%s", (status_final, eid))

    for ev in ("Code Sprint", "Battle of Bands", "Poetry Slam"): run_event(ev, "completed", 2 if ev == "Code Sprint" else 1)
    run_event("Hack the Fest", "live", 1)

    cur.execute("""SELECT f.reg_id FROM (SELECT DISTINCT c.reg_id FROM checkins c JOIN registrations r ON r.reg_id=c.reg_id
                   JOIN events e ON e.event_id=r.event_id WHERE e.status='completed') f""")
    for (rid,) in cur.fetchall():
        if random.random() < 0.7: cur.execute("INSERT INTO feedback(reg_id,rating,comment) VALUES (%s,%s,%s)", (rid, random.choice([3, 4, 4, 5, 5]), random.choice(QUOTES)))

    # sponsors, expenses, resources, volunteers
    spons = [("TechNova Systems", "Title", 150000), ("GreenLeaf Foods", "Gold", 60000), ("Brewline Cafe", "Silver", 25000), ("QuickPrint", "Bronze", 10000)]
    for n, tier, amt in spons:
        sid = one("INSERT INTO sponsors(name,tier,contact_email) VALUES (%s,%s,%s) RETURNING sponsor_id", (n, tier, n.split()[0].lower() + "@example.com"))
        cur.execute("INSERT INTO sponsorships(sponsor_id,event_id,amount) VALUES (%s,NULL,%s)", (sid, amt))
    cur.execute("INSERT INTO sponsorships(sponsor_id,event_id,amount) SELECT sponsor_id,%s,20000 FROM sponsors WHERE name='TechNova Systems'", (eids["Hack the Fest"],))
    cur.execute("INSERT INTO sponsorships(sponsor_id,event_id,amount) SELECT sponsor_id,%s,15000 FROM sponsors WHERE name='GreenLeaf Foods'", (eids["Football 5v5"],))
    for ev, cat, d, amt in [("Code Sprint", "Prizes", "Cash prizes", 6000), ("Code Sprint", "Equipment", "Lab setup", 1500), ("Battle of Bands", "Sound", "PA hire", 12000),
                            ("Battle of Bands", "Prizes", "Trophies", 4000), ("Hack the Fest", "Food", "Snacks for 5 hours", 7000), ("Hack the Fest", "Prizes", "Prize pool", 15000),
                            ("Poetry Slam", "Decor", "Stage props", 900), ("Robo Wars", "Arena", "Arena build", 18000), ("Football 5v5", "Equipment", "Balls and bibs", 5000),
                            (None, "Marketing", "Posters and banners", 8000), (None, "Security", "Fest-wide security", 10000)]:
        cur.execute("INSERT INTO expenses(event_id,category,description,amount) VALUES (%s,%s,%s,%s)", (eids.get(ev), cat, d, amt))
    res = [("Projector", "equipment", 10), ("Sound System", "equipment", 4), ("Stage Lights", "equipment", 6), ("Laptops", "equipment", 30),
           ("Footballs", "equipment", 12), ("Food Stalls", "stall", 8), ("Guest Rooms", "accommodation", 60), ("Shuttle Buses", "transport", 5)]
    rid_ = {n: one("INSERT INTO resources(name,type,total_qty) VALUES (%s,%s,%s) RETURNING resource_id", (n, t, q)) for n, t, q in res}
    for ev, rn, q in [("Battle of Bands", "Sound System", 3), ("Dance Off", "Sound System", 2), ("Battle of Bands", "Stage Lights", 4), ("AI & ML Workshop", "Projector", 2),
                      ("AI & ML Workshop", "Laptops", 25), ("Football 5v5", "Footballs", 6), ("Fest Night Concert", "Sound System", 4), ("Fest Night Concert", "Stage Lights", 6),
                      ("Quiz Wizards", "Projector", 2), ("Robo Wars", "Guest Rooms", 20), ("Hack the Fest", "Guest Rooms", 15)]:
        cur.execute("INSERT INTO allocations VALUES (%s,%s,%s)", (eids[ev], rid_[rn], q))
    for ev, task, v, a, b in [("Fest Night Concert", "Gate entry", 0, (18, 0), (20, 0)), ("Fest Night Concert", "Stage crew", 1, (18, 0), (22, 0)),
                              ("Dance Off", "Registration desk", 0, (15, 0), (17, 30)), ("Football 5v5", "Referee assistant", 2, (9, 0), (13, 0)),
                              ("Quiz Wizards", "Scorekeeping", 1, (14, 0), (16, 0)), ("Robo Wars", "Arena marshal", 2, (10, 0), (15, 0)),
                              ("AI & ML Workshop", "Lab support", 0, (10, 0), (13, 0))]:
        day = [e for e in EV if e[0] == ev][0][3]
        cur.execute("INSERT INTO volunteer_shifts(event_id,volunteer_id,task,shift_start,shift_end) VALUES (%s,%s,%s,%s,%s,%s)".replace("%s,%s,%s,%s,%s,%s)", "%s,%s,%s,%s,%s)"),
                    (eids[ev], vols[v], task, at(day, *a), at(day, *b)))
    conn.commit()


def ensure(url=None, reset=False):
    """Build + seed if empty; add the login-tracking tables to an older database."""
    conn = connect(url)
    with conn.cursor() as c:
        empty = is_empty(c)
    conn.commit()
    if empty or reset:
        print("Building The Anthem Board database (schema + demo data)...")
        build(conn, reset=reset)
        print("Done.")
    else:
        with conn.cursor() as c:
            c.execute(open(os.path.join(HERE, "sessions.sql"), encoding="utf-8").read())
        conn.commit()
        print("Database already initialised; skipping (use --reset to rebuild).")
    conn.close()


if __name__ == "__main__":
    ensure(reset="--reset" in sys.argv)
