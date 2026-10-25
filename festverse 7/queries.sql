-- =====================================================================
--  The Anthem Board: handy queries to run from VS Code (or psql / any SQL client)
--  Select a query and run it (SQLTools: Ctrl/Cmd+E, Ctrl/Cmd+E).
-- =====================================================================

-- ---------- WHO IS LOGGED IN ----------
-- Users logged in right now (open session, seen in the last 30 minutes)
SELECT * FROM v_active_sessions;

-- Full login history with state: active / logged out / expired
SELECT * FROM v_login_history LIMIT 50;

-- Failed and successful login attempts
SELECT * FROM login_attempts ORDER BY attempt_id DESC LIMIT 20;

-- How many times has each user logged in?
SELECT u.name, u.role, COUNT(*) AS logins, MAX(s.logged_in_at) AS last_login
FROM login_sessions s JOIN users u ON u.user_id = s.user_id
GROUP BY u.name, u.role ORDER BY logins DESC;

-- Force-logout someone (replace the e-mail). Their next click sends them to the login page.
-- UPDATE login_sessions SET logged_out_at = fest_now()
-- WHERE logged_out_at IS NULL AND user_id = (SELECT user_id FROM users WHERE email = 'student@festverse.in');

-- ---------- USERS ----------
SELECT user_id, name, email, role, wallet_balance FROM users ORDER BY role, name;
SELECT role, COUNT(*) FROM users GROUP BY role;

-- ---------- FEST DATA ----------
SELECT * FROM v_fest_summary;
SELECT name, status, confirmed, waitlisted, seats_left, revenue, profit FROM v_event_stats ORDER BY start_time;
SELECT * FROM v_leaderboard ORDER BY event_id, rank LIMIT 20;
SELECT * FROM v_college_points ORDER BY points DESC;
SELECT * FROM audit_log ORDER BY log_id DESC LIMIT 20;

-- ---------- DBMS CONCEPTS ----------
-- All triggers
SELECT c.relname AS table_name, t.tgname AS trigger_name, p.proname AS function
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid
WHERE NOT t.tgisinternal ORDER BY 1, 2;
-- Recommendation (self-join): what else did people in event 1 join?
SELECT * FROM fn_recommend(1, 5);
-- See an index being used
EXPLAIN ANALYZE SELECT * FROM registrations WHERE user_id = 5;
