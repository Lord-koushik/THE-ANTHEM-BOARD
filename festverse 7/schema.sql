-- =====================================================================
--  The Anthem Board  |  College Fest Management System  |  PostgreSQL schema
--  Contains: tables (3NF), constraints, indexes, triggers, stored
--  functions/procedures, views, audit logging and role-based grants.
-- =====================================================================

-- Fest runs on Indian Standard Time regardless of where the server lives
CREATE OR REPLACE FUNCTION fest_now() RETURNS TIMESTAMP LANGUAGE sql STABLE AS
$$ SELECT (now() AT TIME ZONE 'Asia/Kolkata') $$;

-- ---------------------------------------------------------------------
-- 1. TABLES
-- ---------------------------------------------------------------------
CREATE TABLE colleges (
    college_id SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    city       TEXT NOT NULL
);

CREATE TABLE users (
    user_id        SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    email          TEXT UNIQUE NOT NULL CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'participant'
                   CHECK (role IN ('admin','coordinator','judge','volunteer','participant')),
    college_id     INT REFERENCES colleges(college_id) ON DELETE SET NULL,
    phone          TEXT,
    wallet_balance NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (wallet_balance >= 0),
    created_at     TIMESTAMP NOT NULL DEFAULT fest_now()
);

CREATE TABLE venues (
    venue_id SERIAL PRIMARY KEY,
    name     TEXT UNIQUE NOT NULL,
    location TEXT,
    capacity INT NOT NULL CHECK (capacity > 0)
);

CREATE TABLE events (
    event_id       SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('Technical','Cultural','Sports','Literary','Gaming','Workshop')),
    description    TEXT,
    venue_id       INT NOT NULL REFERENCES venues(venue_id) ON DELETE RESTRICT,
    coordinator_id INT REFERENCES users(user_id) ON DELETE SET NULL,
    start_time     TIMESTAMP NOT NULL,
    end_time       TIMESTAMP NOT NULL,
    fee            NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    capacity       INT NOT NULL CHECK (capacity > 0),
    is_team        BOOLEAN NOT NULL DEFAULT FALSE,
    min_team       INT NOT NULL DEFAULT 1,
    max_team       INT NOT NULL DEFAULT 1,
    rounds         INT NOT NULL DEFAULT 1 CHECK (rounds BETWEEN 1 AND 5),
    status         TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','live','completed','cancelled')),
    created_at     TIMESTAMP NOT NULL DEFAULT fest_now(),
    CHECK (end_time > start_time),
    CHECK (min_team >= 1 AND max_team >= min_team)
);

CREATE TABLE teams (
    team_id   SERIAL PRIMARY KEY,
    event_id  INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    leader_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (event_id, name)
);

CREATE TABLE coupons (
    coupon_id    SERIAL PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    discount_pct INT NOT NULL CHECK (discount_pct BETWEEN 1 AND 100),
    max_uses     INT CHECK (max_uses > 0),
    used_count   INT NOT NULL DEFAULT 0,
    valid_until  DATE,
    active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE registrations (
    reg_id        SERIAL PRIMARY KEY,
    event_id      INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    user_id       INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    team_id       INT REFERENCES teams(team_id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed','waitlisted','cancelled')),
    amount_paid   NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    coupon_id     INT REFERENCES coupons(coupon_id) ON DELETE SET NULL,
    qr_token      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    registered_at TIMESTAMP NOT NULL DEFAULT fest_now()
);
-- one ACTIVE registration per person per event (cancelled ones don't count)
CREATE UNIQUE INDEX uq_active_registration ON registrations(event_id, user_id) WHERE status <> 'cancelled';

CREATE TABLE payments (
    payment_id SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    reg_id     INT REFERENCES registrations(reg_id) ON DELETE SET NULL,
    amount     NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    kind       TEXT NOT NULL CHECK (kind IN ('topup','registration','refund')),
    note       TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT fest_now()
);

CREATE TABLE sponsors (
    sponsor_id    SERIAL PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    tier          TEXT NOT NULL CHECK (tier IN ('Title','Gold','Silver','Bronze')),
    contact_email TEXT
);

CREATE TABLE sponsorships (
    sponsorship_id SERIAL PRIMARY KEY,
    sponsor_id     INT NOT NULL REFERENCES sponsors(sponsor_id) ON DELETE CASCADE,
    event_id       INT REFERENCES events(event_id) ON DELETE SET NULL,   -- NULL = fest-wide
    amount         NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    received_on    DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE expenses (
    expense_id  SERIAL PRIMARY KEY,
    event_id    INT REFERENCES events(event_id) ON DELETE SET NULL,      -- NULL = fest-wide
    category    TEXT NOT NULL,
    description TEXT,
    amount      NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    spent_on    DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE resources (
    resource_id SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('equipment','stall','food','accommodation','transport')),
    total_qty   INT NOT NULL CHECK (total_qty >= 0)
);

CREATE TABLE allocations (
    event_id    INT REFERENCES events(event_id) ON DELETE CASCADE,
    resource_id INT REFERENCES resources(resource_id) ON DELETE CASCADE,
    qty         INT NOT NULL CHECK (qty > 0),
    PRIMARY KEY (event_id, resource_id)
);

CREATE TABLE judge_assignments (
    event_id INT REFERENCES events(event_id) ON DELETE CASCADE,
    judge_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, judge_id)
);

CREATE TABLE volunteer_shifts (
    shift_id     SERIAL PRIMARY KEY,
    event_id     INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    volunteer_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    task         TEXT NOT NULL,
    shift_start  TIMESTAMP NOT NULL,
    shift_end    TIMESTAMP NOT NULL,
    CHECK (shift_end > shift_start)
);

CREATE TABLE scores (
    score_id  SERIAL PRIMARY KEY,
    reg_id    INT NOT NULL REFERENCES registrations(reg_id) ON DELETE CASCADE,
    judge_id  INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    round_no  INT NOT NULL CHECK (round_no >= 1),
    score     NUMERIC(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
    remarks   TEXT,
    scored_at TIMESTAMP NOT NULL DEFAULT fest_now(),
    UNIQUE (reg_id, judge_id, round_no)
);

CREATE TABLE checkins (
    checkin_id SERIAL PRIMARY KEY,
    reg_id     INT NOT NULL REFERENCES registrations(reg_id) ON DELETE CASCADE,
    direction  TEXT NOT NULL CHECK (direction IN ('in','out')),
    scanned_at TIMESTAMP NOT NULL DEFAULT fest_now(),
    scanned_by INT REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE TABLE feedback (
    feedback_id SERIAL PRIMARY KEY,
    reg_id      INT NOT NULL UNIQUE REFERENCES registrations(reg_id) ON DELETE CASCADE,
    rating      INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT fest_now()
);

CREATE TABLE notifications (
    notif_id   SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT fest_now()
);

CREATE TABLE audit_log (
    log_id     BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_id  TEXT,
    action     TEXT NOT NULL,
    old_data   JSONB,
    new_data   JSONB,
    changed_by INT,
    changed_at TIMESTAMP NOT NULL DEFAULT fest_now()
);

-- ---------------------------------------------------------------------
-- 2. INDEXES  (see the "DBMS Lab" page for a live before/after benchmark)
-- ---------------------------------------------------------------------
CREATE INDEX idx_events_venue_time   ON events(venue_id, start_time, end_time);
CREATE INDEX idx_events_start        ON events(start_time);
CREATE INDEX idx_reg_event_status    ON registrations(event_id, status);
CREATE INDEX idx_reg_user            ON registrations(user_id);
CREATE INDEX idx_reg_team            ON registrations(team_id);
CREATE INDEX idx_pay_user            ON payments(user_id, created_at DESC);
CREATE INDEX idx_scores_reg          ON scores(reg_id);
CREATE INDEX idx_checkins_reg        ON checkins(reg_id, checkin_id DESC);
CREATE INDEX idx_notif_user          ON notifications(user_id, is_read);
CREATE INDEX idx_audit_table_rec     ON audit_log(table_name, record_id);
CREATE INDEX idx_audit_time          ON audit_log(changed_at DESC);

-- ---------------------------------------------------------------------
-- 3. STORED FUNCTIONS (helper logic callable from triggers or the app)
-- ---------------------------------------------------------------------

-- Conflict of interest: a judge may not score an entry that includes
-- anyone from the judge's own college.
CREATE FUNCTION fn_has_conflict(p_judge INT, p_reg INT) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM registrations r
    JOIN registrations m ON m.status <> 'cancelled'
                        AND (m.reg_id = r.reg_id OR (r.team_id IS NOT NULL AND m.team_id = r.team_id))
    JOIN users u ON u.user_id = m.user_id
    JOIN users j ON j.user_id = p_judge
    WHERE r.reg_id = p_reg AND j.college_id IS NOT NULL AND u.college_id = j.college_id);
$$;

-- "Participants who joined X also joined Y"  (self-join recommendation)
CREATE FUNCTION fn_recommend(p_event INT, p_limit INT DEFAULT 3)
RETURNS TABLE (event_id INT, name TEXT, category TEXT, common_participants INT)
LANGUAGE sql STABLE AS $$
  SELECT e2.event_id, e2.name, e2.category, COUNT(*)::INT
  FROM registrations a
  JOIN registrations b ON a.user_id = b.user_id AND a.event_id <> b.event_id AND b.status <> 'cancelled'
  JOIN events e2 ON e2.event_id = b.event_id AND e2.status IN ('scheduled','live')
  WHERE a.event_id = p_event AND a.status <> 'cancelled'
  GROUP BY e2.event_id, e2.name, e2.category
  ORDER BY 4 DESC, 2
  LIMIT p_limit;
$$;

-- Promote waitlisted registrations (FIFO) while seats are free
CREATE FUNCTION promote_waitlist(p_event INT) RETURNS INT LANGUAGE plpgsql AS $$
DECLARE v_cap INT; v_status TEXT; v_name TEXT; v_conf INT; v_reg RECORD; n INT := 0;
BEGIN
  SELECT capacity, status, name INTO v_cap, v_status, v_name FROM events WHERE event_id = p_event;
  IF v_status IS DISTINCT FROM 'scheduled' THEN RETURN 0; END IF;
  LOOP
    SELECT COUNT(*) INTO v_conf FROM registrations WHERE event_id = p_event AND status = 'confirmed';
    EXIT WHEN v_conf >= v_cap;
    SELECT reg_id, user_id INTO v_reg FROM registrations
      WHERE event_id = p_event AND status = 'waitlisted'
      ORDER BY registered_at, reg_id LIMIT 1 FOR UPDATE SKIP LOCKED;
    EXIT WHEN NOT FOUND;
    UPDATE registrations SET status = 'confirmed' WHERE reg_id = v_reg.reg_id;
    INSERT INTO notifications(user_id, message)
      VALUES (v_reg.user_id, format('A seat opened up. You are now confirmed for "%s"!', v_name));
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- Move event statuses along with the clock
CREATE FUNCTION fn_sync_event_status() RETURNS INT LANGUAGE plpgsql AS $$
DECLARE a INT; b INT;
BEGIN
  UPDATE events SET status = 'live'
    WHERE status = 'scheduled' AND fest_now() >= start_time AND fest_now() < end_time;
  GET DIAGNOSTICS a = ROW_COUNT;
  UPDATE events SET status = 'completed'
    WHERE status IN ('scheduled','live') AND fest_now() >= end_time;
  GET DIAGNOSTICS b = ROW_COUNT;
  RETURN a + b;
END $$;

-- Wallet top-up (atomic: balance + ledger entry)
CREATE FUNCTION topup_wallet(p_user INT, p_amount NUMERIC) RETURNS NUMERIC LANGUAGE plpgsql AS $$
DECLARE v_bal NUMERIC;
BEGIN
  IF p_amount IS NULL OR p_amount < 10 OR p_amount > 20000 THEN
    RAISE EXCEPTION 'Top-up must be between 10 and 20000';
  END IF;
  UPDATE users SET wallet_balance = wallet_balance + p_amount WHERE user_id = p_user RETURNING wallet_balance INTO v_bal;
  INSERT INTO payments(user_id, amount, kind, note) VALUES (p_user, p_amount, 'topup', 'Wallet top-up');
  RETURN v_bal;
END $$;

-- THE core transaction: register (with coupon, payment, team, waitlist).
-- Everything below happens atomically -- if any trigger rejects the
-- registration (clash, full team, closed event) the wallet debit and
-- coupon usage are rolled back automatically.
CREATE FUNCTION register_for_event(p_user INT, p_event INT, p_team INT DEFAULT NULL, p_coupon TEXT DEFAULT NULL)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
  e events%ROWTYPE; c coupons%ROWTYPE; v_fee NUMERIC; v_bal NUMERIC; v_reg INT; v_coupon_id INT;
BEGIN
  SELECT * INTO e FROM events WHERE event_id = p_event FOR UPDATE;   -- serialise seat counting
  IF NOT FOUND THEN RAISE EXCEPTION 'Event not found'; END IF;
  v_fee := e.fee;

  IF p_coupon IS NOT NULL AND btrim(p_coupon) <> '' THEN
    SELECT * INTO c FROM coupons
      WHERE upper(code) = upper(btrim(p_coupon)) AND active
        AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
        AND (max_uses IS NULL OR used_count < max_uses)
      FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Coupon "%" is invalid, expired or fully used', upper(btrim(p_coupon)); END IF;
    v_fee := round(e.fee * (100 - c.discount_pct) / 100.0, 2);
    v_coupon_id := c.coupon_id;
  END IF;

  SELECT wallet_balance INTO v_bal FROM users WHERE user_id = p_user FOR UPDATE;
  IF v_bal < v_fee THEN
    RAISE EXCEPTION 'Wallet balance is Rs.% but the fee is Rs.%. Top up your wallet first.', v_bal, v_fee;
  END IF;

  INSERT INTO registrations(event_id, user_id, team_id, amount_paid, coupon_id)
    VALUES (p_event, p_user, p_team, v_fee, v_coupon_id) RETURNING reg_id INTO v_reg;  -- BEFORE trigger validates

  IF v_fee > 0 THEN
    UPDATE users SET wallet_balance = wallet_balance - v_fee WHERE user_id = p_user;
    INSERT INTO payments(user_id, reg_id, amount, kind, note) VALUES (p_user, v_reg, v_fee, 'registration', 'Registration: ' || e.name);
  END IF;
  IF v_coupon_id IS NOT NULL THEN UPDATE coupons SET used_count = used_count + 1 WHERE coupon_id = v_coupon_id; END IF;
  RETURN v_reg;
END $$;

-- Cancel (p_user = owner; NULL = staff override). Refund + waitlist
-- promotion are done by the trigger on registrations.
CREATE FUNCTION cancel_registration(p_reg INT, p_user INT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r registrations%ROWTYPE; e events%ROWTYPE;
BEGIN
  SELECT * INTO r FROM registrations WHERE reg_id = p_reg FOR UPDATE;
  IF NOT FOUND OR (p_user IS NOT NULL AND r.user_id <> p_user) THEN RAISE EXCEPTION 'Registration not found'; END IF;
  IF r.status = 'cancelled' THEN RAISE EXCEPTION 'Already cancelled'; END IF;
  SELECT * INTO e FROM events WHERE event_id = r.event_id;
  IF p_user IS NOT NULL AND e.status <> 'scheduled' THEN RAISE EXCEPTION 'You cannot cancel once the event has started'; END IF;
  UPDATE registrations SET status = 'cancelled' WHERE reg_id = p_reg;
END $$;

-- QR check-in: toggles IN / OUT automatically
CREATE FUNCTION scan_checkin(p_token UUID, p_by INT) RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE rec RECORD; v_last TEXT; v_dir TEXT;
BEGIN
  SELECT rg.reg_id, u.name, e.name AS event_name, t.name AS team_name INTO rec
    FROM registrations rg JOIN users u ON u.user_id = rg.user_id JOIN events e ON e.event_id = rg.event_id
    LEFT JOIN teams t ON t.team_id = rg.team_id
    WHERE rg.qr_token = p_token;
  IF NOT FOUND THEN RAISE EXCEPTION 'Invalid ticket: no registration matches this QR code'; END IF;
  SELECT direction INTO v_last FROM checkins WHERE reg_id = rec.reg_id ORDER BY checkin_id DESC LIMIT 1;
  v_dir := CASE WHEN v_last = 'in' THEN 'out' ELSE 'in' END;
  INSERT INTO checkins(reg_id, direction, scanned_by) VALUES (rec.reg_id, v_dir, p_by);   -- BEFORE trigger validates
  RETURN jsonb_build_object('ok', true, 'direction', v_dir, 'name', rec.name, 'event', rec.event_name, 'team', rec.team_name);
END $$;

-- ---------------------------------------------------------------------
-- 4. TRIGGERS (business rules enforced inside the database)
-- ---------------------------------------------------------------------

-- 4.1 Events: venue capacity + venue clash detection
CREATE FUNCTION trg_event_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_cap INT; v_clash RECORD;
BEGIN
  SELECT capacity INTO v_cap FROM venues WHERE venue_id = NEW.venue_id;
  IF NEW.capacity > v_cap THEN
    RAISE EXCEPTION 'Event capacity (%) exceeds the venue capacity (%)', NEW.capacity, v_cap;
  END IF;
  IF NEW.status <> 'cancelled' THEN
    SELECT name, start_time, end_time INTO v_clash FROM events
      WHERE venue_id = NEW.venue_id AND status <> 'cancelled' AND event_id IS DISTINCT FROM NEW.event_id
        AND start_time < NEW.end_time AND end_time > NEW.start_time LIMIT 1;
    IF FOUND THEN
      RAISE EXCEPTION 'Venue clash: "%" already uses this venue from % to %', v_clash.name,
        to_char(v_clash.start_time, 'DD Mon HH12:MI AM'), to_char(v_clash.end_time, 'HH12:MI AM');
    END IF;
  END IF;
  IF NOT NEW.is_team THEN NEW.min_team := 1; NEW.max_team := 1; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER events_guard BEFORE INSERT OR UPDATE ON events
  FOR EACH ROW EXECUTE FUNCTION trg_event_guard();

-- 4.2 Events: reschedule notices, cancellation cascade, capacity growth
CREATE FUNCTION trg_event_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.start_time <> OLD.start_time OR NEW.venue_id <> OLD.venue_id THEN
    INSERT INTO notifications(user_id, message)
      SELECT user_id, format('"%s" has been rescheduled to %s.', NEW.name, to_char(NEW.start_time, 'DD Mon, HH12:MI AM'))
      FROM registrations WHERE event_id = NEW.event_id AND status <> 'cancelled';
  END IF;
  IF NEW.status = 'cancelled' AND OLD.status <> 'cancelled' THEN
    UPDATE registrations SET status = 'cancelled' WHERE event_id = NEW.event_id AND status <> 'cancelled';  -- fires refund trigger
  END IF;
  IF NEW.capacity > OLD.capacity THEN PERFORM promote_waitlist(NEW.event_id); END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER events_after AFTER UPDATE ON events
  FOR EACH ROW EXECUTE FUNCTION trg_event_after();

-- 4.3 Registrations: clash detection, team size, seat limit -> auto-waitlist
CREATE FUNCTION trg_reg_validate() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e events%ROWTYPE; t teams%ROWTYPE; v_conf INT; v_clash TEXT; v_members INT;
BEGIN
  SELECT * INTO e FROM events WHERE event_id = NEW.event_id FOR UPDATE;
  IF e.status <> 'scheduled' THEN
    RAISE EXCEPTION 'Registrations are closed for "%" (status: %)', e.name, e.status;
  END IF;

  SELECT e2.name INTO v_clash FROM registrations r2 JOIN events e2 ON e2.event_id = r2.event_id
    WHERE r2.user_id = NEW.user_id AND r2.status <> 'cancelled' AND e2.event_id <> e.event_id
      AND e2.status <> 'cancelled' AND e2.start_time < e.end_time AND e2.end_time > e.start_time LIMIT 1;
  IF v_clash IS NOT NULL THEN
    RAISE EXCEPTION 'Time clash: you are already registered for "%" at an overlapping time', v_clash;
  END IF;

  IF e.is_team THEN
    IF NEW.team_id IS NULL THEN RAISE EXCEPTION 'This is a team event: create a team or join one'; END IF;
    SELECT * INTO t FROM teams WHERE team_id = NEW.team_id;
    IF NOT FOUND OR t.event_id <> e.event_id THEN RAISE EXCEPTION 'That team does not belong to this event'; END IF;
    SELECT COUNT(*) INTO v_members FROM registrations WHERE team_id = NEW.team_id AND status <> 'cancelled';
    IF v_members >= e.max_team THEN RAISE EXCEPTION 'Team "%" is full (max % members)', t.name, e.max_team; END IF;
  ELSIF NEW.team_id IS NOT NULL THEN
    RAISE EXCEPTION 'This is an individual event';
  END IF;

  SELECT COUNT(*) INTO v_conf FROM registrations WHERE event_id = e.event_id AND status = 'confirmed';
  NEW.status := CASE WHEN v_conf < e.capacity THEN 'confirmed' ELSE 'waitlisted' END;
  RETURN NEW;
END $$;
CREATE TRIGGER reg_validate BEFORE INSERT ON registrations
  FOR EACH ROW EXECUTE FUNCTION trg_reg_validate();

CREATE FUNCTION trg_reg_inserted() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_name TEXT;
BEGIN
  SELECT name INTO v_name FROM events WHERE event_id = NEW.event_id;
  INSERT INTO notifications(user_id, message) VALUES (NEW.user_id,
    CASE WHEN NEW.status = 'confirmed'
         THEN format('You are confirmed for "%s". Your QR ticket is ready.', v_name)
         ELSE format('"%s" is full, so you are on the waitlist. We will confirm you automatically if a seat opens.', v_name) END);
  RETURN NULL;
END $$;
CREATE TRIGGER reg_inserted AFTER INSERT ON registrations
  FOR EACH ROW EXECUTE FUNCTION trg_reg_inserted();

-- 4.4 Registrations: cancellation -> refund -> notify -> promote waitlist
CREATE FUNCTION trg_reg_status() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_name TEXT; v_leader INT;
BEGIN
  IF NEW.status = 'cancelled' AND OLD.status <> 'cancelled' THEN
    SELECT name INTO v_name FROM events WHERE event_id = NEW.event_id;
    IF NEW.amount_paid > 0 THEN
      UPDATE users SET wallet_balance = wallet_balance + NEW.amount_paid WHERE user_id = NEW.user_id;
      INSERT INTO payments(user_id, reg_id, amount, kind, note)
        VALUES (NEW.user_id, NEW.reg_id, NEW.amount_paid, 'refund', 'Refund: ' || v_name);
    END IF;
    INSERT INTO notifications(user_id, message) VALUES (NEW.user_id,
      format('Your registration for "%s" was cancelled.%s', v_name,
             CASE WHEN NEW.amount_paid > 0 THEN format(' Rs.%s was refunded to your wallet.', NEW.amount_paid) ELSE '' END));
    IF NEW.team_id IS NOT NULL THEN        -- a leader leaving disbands the team
      SELECT leader_id INTO v_leader FROM teams WHERE team_id = NEW.team_id;
      IF v_leader = NEW.user_id THEN
        UPDATE registrations SET status = 'cancelled' WHERE team_id = NEW.team_id AND status <> 'cancelled';
      END IF;
    END IF;
    IF OLD.status = 'confirmed' THEN PERFORM promote_waitlist(NEW.event_id); END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER reg_status AFTER UPDATE OF status ON registrations
  FOR EACH ROW EXECUTE FUNCTION trg_reg_status();

-- 4.5 Judges: role + no double-booking + conflict of interest on scoring
CREATE FUNCTION trg_judge_assign() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e events%ROWTYPE; v_clash TEXT;
BEGIN
  IF (SELECT role FROM users WHERE user_id = NEW.judge_id) <> 'judge' THEN
    RAISE EXCEPTION 'Only users with the judge role can be assigned as judges';
  END IF;
  SELECT * INTO e FROM events WHERE event_id = NEW.event_id;
  SELECT e2.name INTO v_clash FROM judge_assignments ja JOIN events e2 ON e2.event_id = ja.event_id
    WHERE ja.judge_id = NEW.judge_id AND e2.event_id <> e.event_id AND e2.status <> 'cancelled'
      AND e2.start_time < e.end_time AND e2.end_time > e.start_time LIMIT 1;
  IF v_clash IS NOT NULL THEN RAISE EXCEPTION 'Judge is already assigned to "%" at an overlapping time', v_clash; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER judge_assign BEFORE INSERT ON judge_assignments
  FOR EACH ROW EXECUTE FUNCTION trg_judge_assign();

CREATE FUNCTION trg_score_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r registrations%ROWTYPE; e events%ROWTYPE;
BEGIN
  SELECT * INTO r FROM registrations WHERE reg_id = NEW.reg_id;
  SELECT * INTO e FROM events WHERE event_id = r.event_id;
  IF e.status NOT IN ('live','completed') THEN RAISE EXCEPTION 'Scoring opens once the event is live'; END IF;
  IF NOT EXISTS (SELECT 1 FROM judge_assignments WHERE event_id = e.event_id AND judge_id = NEW.judge_id) THEN
    RAISE EXCEPTION 'You are not assigned to judge "%"', e.name;
  END IF;
  IF NEW.round_no > e.rounds THEN RAISE EXCEPTION '"%" has only % round(s)', e.name, e.rounds; END IF;
  IF r.status <> 'confirmed' THEN RAISE EXCEPTION 'Only confirmed entries can be scored'; END IF;
  IF r.team_id IS NOT NULL AND r.user_id <> (SELECT leader_id FROM teams WHERE team_id = r.team_id) THEN
    RAISE EXCEPTION 'Score a team through its leader entry';
  END IF;
  IF fn_has_conflict(NEW.judge_id, NEW.reg_id) THEN
    RAISE EXCEPTION 'Conflict of interest: this entry includes a participant from your own college';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER score_guard BEFORE INSERT OR UPDATE ON scores
  FOR EACH ROW EXECUTE FUNCTION trg_score_guard();

-- 4.6 Volunteers: role + no overlapping shifts
CREATE FUNCTION trg_shift_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_clash TEXT;
BEGIN
  IF (SELECT role FROM users WHERE user_id = NEW.volunteer_id) <> 'volunteer' THEN
    RAISE EXCEPTION 'Only users with the volunteer role can take shifts';
  END IF;
  SELECT task INTO v_clash FROM volunteer_shifts
    WHERE volunteer_id = NEW.volunteer_id AND shift_id IS DISTINCT FROM NEW.shift_id
      AND shift_start < NEW.shift_end AND shift_end > NEW.shift_start LIMIT 1;
  IF v_clash IS NOT NULL THEN RAISE EXCEPTION 'Volunteer already has an overlapping shift ("%")', v_clash; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER shift_guard BEFORE INSERT OR UPDATE ON volunteer_shifts
  FOR EACH ROW EXECUTE FUNCTION trg_shift_guard();

-- 4.7 Resources: never allocate more than exists during overlapping events
CREATE FUNCTION trg_alloc_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE e events%ROWTYPE; r resources%ROWTYPE; v_used INT;
BEGIN
  SELECT * INTO e FROM events WHERE event_id = NEW.event_id;
  SELECT * INTO r FROM resources WHERE resource_id = NEW.resource_id;
  SELECT COALESCE(SUM(a.qty), 0) INTO v_used FROM allocations a JOIN events e2 ON e2.event_id = a.event_id
    WHERE a.resource_id = NEW.resource_id AND a.event_id <> NEW.event_id AND e2.status <> 'cancelled'
      AND e2.start_time < e.end_time AND e2.end_time > e.start_time;
  IF v_used + NEW.qty > r.total_qty THEN
    RAISE EXCEPTION 'Only % of "%" free at that time (% already booked by overlapping events)',
      r.total_qty - v_used, r.name, v_used;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER alloc_guard BEFORE INSERT OR UPDATE ON allocations
  FOR EACH ROW EXECUTE FUNCTION trg_alloc_guard();

-- 4.8 Check-ins: confirmed only, min team size, sane IN/OUT sequence
CREATE FUNCTION trg_checkin_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r registrations%ROWTYPE; e events%ROWTYPE; v_last TEXT; v_members INT;
BEGIN
  SELECT * INTO r FROM registrations WHERE reg_id = NEW.reg_id;
  SELECT * INTO e FROM events WHERE event_id = r.event_id;
  IF r.status <> 'confirmed' THEN RAISE EXCEPTION 'Entry denied: registration is %', r.status; END IF;
  IF e.status NOT IN ('scheduled','live') THEN RAISE EXCEPTION 'Entry denied: "%" is %', e.name, e.status; END IF;
  IF e.is_team AND r.team_id IS NOT NULL THEN
    SELECT COUNT(*) INTO v_members FROM registrations WHERE team_id = r.team_id AND status = 'confirmed';
    IF v_members < e.min_team THEN
      RAISE EXCEPTION 'Entry denied: team has % of the % required members', v_members, e.min_team;
    END IF;
  END IF;
  SELECT direction INTO v_last FROM checkins WHERE reg_id = NEW.reg_id ORDER BY checkin_id DESC LIMIT 1;
  IF v_last IS NOT DISTINCT FROM NEW.direction THEN RAISE EXCEPTION 'Duplicate scan (already %)', NEW.direction; END IF;
  IF v_last IS NULL AND NEW.direction = 'out' THEN RAISE EXCEPTION 'Cannot check out before checking in'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER checkin_guard BEFORE INSERT ON checkins
  FOR EACH ROW EXECUTE FUNCTION trg_checkin_guard();

-- 4.9 Feedback only from people who actually attended
CREATE FUNCTION trg_feedback_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM checkins WHERE reg_id = NEW.reg_id AND direction = 'in') THEN
    RAISE EXCEPTION 'You can rate an event only after attending it (no check-in found)';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER feedback_guard BEFORE INSERT OR UPDATE ON feedback
  FOR EACH ROW EXECUTE FUNCTION trg_feedback_guard();

-- 4.10 Generic audit trigger: who changed what, when (old vs new as JSONB)
CREATE FUNCTION audit_row() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_old JSONB; v_new JSONB; v_uid INT;
BEGIN
  v_uid := NULLIF(current_setting('app.user_id', true), '')::INT;   -- set by the web app per request
  IF TG_OP IN ('UPDATE','DELETE') THEN v_old := to_jsonb(OLD) - 'password_hash'; END IF;
  IF TG_OP IN ('INSERT','UPDATE') THEN v_new := to_jsonb(NEW) - 'password_hash'; END IF;
  IF TG_OP = 'UPDATE' AND v_old = v_new THEN RETURN NULL; END IF;
  INSERT INTO audit_log(table_name, record_id, action, old_data, new_data, changed_by)
    VALUES (TG_TABLE_NAME, COALESCE(v_new, v_old) ->> TG_ARGV[0], TG_OP, v_old, v_new, v_uid);
  RETURN NULL;
END $$;
CREATE TRIGGER audit_events        AFTER INSERT OR UPDATE OR DELETE ON events        FOR EACH ROW EXECUTE FUNCTION audit_row('event_id');
CREATE TRIGGER audit_registrations AFTER INSERT OR UPDATE OR DELETE ON registrations FOR EACH ROW EXECUTE FUNCTION audit_row('reg_id');
CREATE TRIGGER audit_users         AFTER INSERT OR UPDATE OR DELETE ON users         FOR EACH ROW EXECUTE FUNCTION audit_row('user_id');
CREATE TRIGGER audit_scores        AFTER INSERT OR UPDATE OR DELETE ON scores        FOR EACH ROW EXECUTE FUNCTION audit_row('score_id');
CREATE TRIGGER audit_coupons       AFTER INSERT OR UPDATE OR DELETE ON coupons       FOR EACH ROW EXECUTE FUNCTION audit_row('coupon_id');
CREATE TRIGGER audit_expenses      AFTER INSERT OR UPDATE OR DELETE ON expenses      FOR EACH ROW EXECUTE FUNCTION audit_row('expense_id');
CREATE TRIGGER audit_sponsorships  AFTER INSERT OR UPDATE OR DELETE ON sponsorships  FOR EACH ROW EXECUTE FUNCTION audit_row('sponsorship_id');

-- ---------------------------------------------------------------------
-- 5. VIEWS (reports + role dashboards)
-- ---------------------------------------------------------------------
CREATE VIEW v_event_stats AS
SELECT e.event_id, e.name, e.category, e.description, e.start_time, e.end_time, e.fee, e.capacity, e.status,
       e.is_team, e.min_team, e.max_team, e.rounds, e.coordinator_id, e.venue_id,
       v.name AS venue, v.location AS venue_location,
       COALESCE(r.confirmed, 0)  AS confirmed,
       COALESCE(r.waitlisted, 0) AS waitlisted,
       e.capacity - COALESCE(r.confirmed, 0) AS seats_left,
       COALESCE(p.revenue, 0)    AS revenue,
       COALESCE(f.avg_rating, 0) AS avg_rating,
       COALESCE(f.n, 0)          AS feedback_count,
       COALESCE(s.amt, 0)        AS sponsorship,
       COALESCE(x.amt, 0)        AS expenses,
       COALESCE(p.revenue, 0) + COALESCE(s.amt, 0) - COALESCE(x.amt, 0) AS profit
FROM events e
JOIN venues v ON v.venue_id = e.venue_id
LEFT JOIN (SELECT event_id,
                  COUNT(*) FILTER (WHERE status = 'confirmed')  AS confirmed,
                  COUNT(*) FILTER (WHERE status = 'waitlisted') AS waitlisted
           FROM registrations GROUP BY event_id) r ON r.event_id = e.event_id
LEFT JOIN (SELECT rg.event_id,
                  SUM(CASE py.kind WHEN 'registration' THEN py.amount WHEN 'refund' THEN -py.amount END) AS revenue
           FROM payments py JOIN registrations rg ON rg.reg_id = py.reg_id
           WHERE py.kind IN ('registration','refund') GROUP BY rg.event_id) p ON p.event_id = e.event_id
LEFT JOIN (SELECT rg.event_id, ROUND(AVG(fb.rating), 1) AS avg_rating, COUNT(*) AS n
           FROM feedback fb JOIN registrations rg ON rg.reg_id = fb.reg_id GROUP BY rg.event_id) f ON f.event_id = e.event_id
LEFT JOIN (SELECT event_id, SUM(amount) AS amt FROM sponsorships WHERE event_id IS NOT NULL GROUP BY event_id) s ON s.event_id = e.event_id
LEFT JOIN (SELECT event_id, SUM(amount) AS amt FROM expenses    WHERE event_id IS NOT NULL GROUP BY event_id) x ON x.event_id = e.event_id;

-- Multi-round leaderboard: per-round average across judges, summed across
-- rounds; ties broken by best single round; RANK() lets true ties share a rank.
CREATE VIEW v_leaderboard AS
WITH round_avg AS (
  SELECT reg_id, round_no, AVG(score) AS avg_score FROM scores GROUP BY reg_id, round_no
), agg AS (
  SELECT reg_id, SUM(avg_score) AS total, MAX(avg_score) AS best_round, COUNT(*) AS rounds_done
  FROM round_avg GROUP BY reg_id
)
SELECT r.event_id, r.reg_id, r.team_id,
       COALESCE(t.name, u.name) AS entry_name,
       c.name AS college,
       ROUND(a.total, 2) AS total, ROUND(a.best_round, 2) AS best_round, a.rounds_done,
       RANK() OVER (PARTITION BY r.event_id ORDER BY ROUND(a.total, 2) DESC, ROUND(a.best_round, 2) DESC) AS rank
FROM agg a
JOIN registrations r ON r.reg_id = a.reg_id
JOIN users u ON u.user_id = r.user_id
LEFT JOIN teams t ON t.team_id = r.team_id
LEFT JOIN colleges c ON c.college_id = u.college_id;

CREATE VIEW v_certificates AS
SELECT rg.reg_id, rg.user_id, u.name AS person, e.event_id, e.name AS event_name, e.category, e.start_time,
       l.rank, CASE WHEN l.rank <= 3 THEN 'Winner' ELSE 'Participation' END AS cert_type
FROM registrations rg
JOIN users u  ON u.user_id = rg.user_id
JOIN events e ON e.event_id = rg.event_id AND e.status = 'completed'
LEFT JOIN v_leaderboard l ON l.event_id = rg.event_id
     AND ((rg.team_id IS NOT NULL AND l.team_id = rg.team_id) OR (rg.team_id IS NULL AND l.reg_id = rg.reg_id))
WHERE rg.status = 'confirmed'
  AND EXISTS (SELECT 1 FROM checkins ck WHERE ck.reg_id = rg.reg_id AND ck.direction = 'in');

CREATE VIEW v_college_points AS
SELECT l.college,
       SUM(CASE l.rank WHEN 1 THEN 10 WHEN 2 THEN 6 WHEN 3 THEN 3 END) AS points,
       COUNT(*) FILTER (WHERE l.rank = 1) AS golds,
       COUNT(*) FILTER (WHERE l.rank = 2) AS silvers,
       COUNT(*) FILTER (WHERE l.rank = 3) AS bronzes
FROM v_leaderboard l JOIN events e ON e.event_id = l.event_id
WHERE l.rank <= 3 AND e.status = 'completed' AND l.college IS NOT NULL
GROUP BY l.college;

CREATE VIEW v_college_participation AS
SELECT c.college_id, c.name, c.city, COUNT(DISTINCT r.user_id) AS participants, COUNT(r.reg_id) AS entries
FROM colleges c JOIN users u ON u.college_id = c.college_id
JOIN registrations r ON r.user_id = u.user_id AND r.status <> 'cancelled'
GROUP BY c.college_id, c.name, c.city;

CREATE VIEW v_my_registrations AS      -- participant dashboard
SELECT r.reg_id, r.user_id, r.status, r.amount_paid, r.qr_token, r.registered_at,
       e.event_id, e.name AS event_name, e.category, e.start_time, e.end_time, e.status AS event_status,
       vn.name AS venue, t.name AS team_name,
       EXISTS (SELECT 1 FROM checkins c WHERE c.reg_id = r.reg_id AND c.direction = 'in') AS attended,
       (SELECT rating FROM feedback f WHERE f.reg_id = r.reg_id) AS my_rating,
       CASE WHEN r.status = 'waitlisted' THEN
         (SELECT COUNT(*) FROM registrations w WHERE w.event_id = r.event_id AND w.status = 'waitlisted'
            AND (w.registered_at, w.reg_id) <= (r.registered_at, r.reg_id)) END AS waitlist_pos
FROM registrations r
JOIN events e ON e.event_id = r.event_id
JOIN venues vn ON vn.venue_id = e.venue_id
LEFT JOIN teams t ON t.team_id = r.team_id;

CREATE VIEW v_team_status AS
SELECT t.team_id, t.event_id, t.name, t.leader_id, u.name AS leader,
       COUNT(r.reg_id) FILTER (WHERE r.status <> 'cancelled') AS members,
       e.min_team, e.max_team,
       COUNT(r.reg_id) FILTER (WHERE r.status = 'confirmed') >= e.min_team AS ready
FROM teams t JOIN events e ON e.event_id = t.event_id JOIN users u ON u.user_id = t.leader_id
LEFT JOIN registrations r ON r.team_id = t.team_id
GROUP BY t.team_id, t.event_id, t.name, t.leader_id, u.name, e.min_team, e.max_team;

CREATE VIEW v_hourly_registrations AS
SELECT EXTRACT(HOUR FROM registered_at)::INT AS hr, COUNT(*) AS regs FROM registrations GROUP BY 1;

CREATE VIEW v_hourly_checkins AS
SELECT EXTRACT(HOUR FROM scanned_at)::INT AS hr, COUNT(*) AS entries FROM checkins WHERE direction = 'in' GROUP BY 1;

CREATE VIEW v_fest_summary AS      -- admin dashboard (single row)
SELECT (SELECT COUNT(*) FROM events WHERE status <> 'cancelled')                              AS events,
       (SELECT COUNT(DISTINCT user_id) FROM registrations WHERE status <> 'cancelled')        AS participants,
       (SELECT COUNT(*) FROM registrations WHERE status = 'confirmed')                        AS registrations,
       (SELECT COUNT(*) FROM v_college_participation)                                         AS colleges,
       (SELECT COALESCE(SUM(revenue), 0) FROM v_event_stats)                                  AS revenue,
       (SELECT COALESCE(SUM(amount), 0) FROM sponsorships)                                    AS sponsorship,
       (SELECT COALESCE(SUM(amount), 0) FROM expenses)                                        AS expenses,
       (SELECT COUNT(*) FROM checkins WHERE direction = 'in')                                 AS checkins;

-- ---------------------------------------------------------------------
-- 6. ROLE-BASED ACCESS CONTROL  (GRANT / REVOKE)
--    Wrapped so managed hosts that forbid CREATE ROLE don't break setup.
-- ---------------------------------------------------------------------
DO $rbac$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fest_admin')       THEN CREATE ROLE fest_admin       NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fest_coordinator') THEN CREATE ROLE fest_coordinator NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fest_participant') THEN CREATE ROLE fest_participant NOLOGIN; END IF;

  REVOKE ALL ON ALL TABLES IN SCHEMA public FROM fest_admin, fest_coordinator, fest_participant;

  -- admin: everything
  GRANT ALL ON ALL TABLES IN SCHEMA public TO fest_admin;
  GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO fest_admin;
  -- coordinator: run events, never touch money ledger or audit trail directly
  GRANT SELECT, INSERT, UPDATE ON events, teams, allocations, judge_assignments, volunteer_shifts, expenses TO fest_coordinator;
  GRANT SELECT ON venues, colleges, resources, registrations, checkins, v_event_stats, v_team_status, v_leaderboard TO fest_coordinator;
  GRANT SELECT (user_id, name, role, college_id) ON users TO fest_coordinator;
  GRANT INSERT ON checkins TO fest_coordinator;
  -- participant: browse + own data via views, leave feedback
  GRANT SELECT ON events, venues, colleges, v_event_stats, v_leaderboard, v_my_registrations, v_certificates TO fest_participant;
  GRANT INSERT, UPDATE ON feedback TO fest_participant;
  GRANT SELECT (user_id, name, college_id) ON users TO fest_participant;
  -- nobody but admin reads credentials or the audit log
  REVOKE ALL ON audit_log FROM fest_coordinator, fest_participant;
  REVOKE SELECT (password_hash) ON users FROM fest_coordinator, fest_participant;

  GRANT EXECUTE ON FUNCTION register_for_event(INT, INT, INT, TEXT), cancel_registration(INT, INT), topup_wallet(INT, NUMERIC)
    TO fest_participant, fest_coordinator, fest_admin;
  GRANT EXECUTE ON FUNCTION scan_checkin(UUID, INT) TO fest_coordinator, fest_admin;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'RBAC roles skipped: this database user cannot create roles';
END $rbac$;
