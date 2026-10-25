-- =====================================================================
--  Login tracking: who is logged in right now, and the full login history.
--  Safe to run repeatedly (IF NOT EXISTS / OR REPLACE).
-- =====================================================================
CREATE TABLE IF NOT EXISTS login_sessions (
    session_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    logged_in_at  TIMESTAMP NOT NULL DEFAULT fest_now(),
    last_seen     TIMESTAMP NOT NULL DEFAULT fest_now(),
    logged_out_at TIMESTAMP,                      -- NULL while the session is open
    ip_address    TEXT,
    user_agent    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user   ON login_sessions(user_id, logged_in_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_open   ON login_sessions(last_seen DESC) WHERE logged_out_at IS NULL;

CREATE TABLE IF NOT EXISTS login_attempts (      -- includes failed logins
    attempt_id   SERIAL PRIMARY KEY,
    email        TEXT NOT NULL,
    success      BOOLEAN NOT NULL,
    ip_address   TEXT,
    attempted_at TIMESTAMP NOT NULL DEFAULT fest_now()
);

-- "Logged in" = session not logged out AND seen within the last 30 minutes
CREATE OR REPLACE VIEW v_active_sessions AS
SELECT s.session_id, u.user_id, u.name, u.email, u.role, c.name AS college,
       s.logged_in_at, s.last_seen, s.ip_address,
       ROUND(EXTRACT(EPOCH FROM (fest_now() - s.logged_in_at)) / 60) AS minutes_online
FROM login_sessions s
JOIN users u ON u.user_id = s.user_id
LEFT JOIN colleges c ON c.college_id = u.college_id
WHERE s.logged_out_at IS NULL AND s.last_seen > fest_now() - INTERVAL '30 minutes'
ORDER BY s.last_seen DESC;

CREATE OR REPLACE VIEW v_login_history AS
SELECT s.session_id, u.user_id, u.name, u.email, u.role,
       s.logged_in_at, s.logged_out_at, s.last_seen, s.ip_address,
       CASE WHEN s.logged_out_at IS NOT NULL THEN 'logged out'
            WHEN s.last_seen > fest_now() - INTERVAL '30 minutes' THEN 'active'
            ELSE 'expired' END AS state,
       ROUND(EXTRACT(EPOCH FROM (COALESCE(s.logged_out_at, s.last_seen) - s.logged_in_at)) / 60) AS minutes
FROM login_sessions s JOIN users u ON u.user_id = s.user_id
ORDER BY s.logged_in_at DESC;
