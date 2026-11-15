-- Login for the free-question role landed_ai. Idempotent. On a real superuser it also sets
-- temp_file_limit (a superuser-only setting); on Amazon RDS (no superuser) that step only
-- raises a WARNING and the rest of the script still applies.
--   Existing clusters (runbook), after `make landed-migrate`:
--     LANDED_AI_PASSWORD=... psql -v ON_ERROR_STOP=1 -U <superuser or RDS master> -d postgres -f scripts/landed/ai-role.sql
--   Fresh clusters: scripts/landed/init.sql includes this file.
-- The role itself (NOLOGIN, caps, grants) is created/maintained by migration 000006; this file only
-- adds what a migration runner may not be allowed to do: LOGIN, the password, temp_file_limit.
-- The password is read from the environment (psql \getenv), never from the command line.
\set ON_ERROR_STOP on
\getenv ai_pw LANDED_AI_PASSWORD

SELECT (:'ai_pw' = '') AS ai_pw_empty \gset
\if :ai_pw_empty
  DO $$ BEGIN RAISE EXCEPTION 'LANDED_AI_PASSWORD is required'; END $$;
\endif

-- Same attributes as migration 000006, so either can run first.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'landed_ai') THEN
    CREATE ROLE landed_ai NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION
      CONNECTION LIMIT 20;
  END IF;
END $$;

ALTER ROLE landed_ai LOGIN PASSWORD :'ai_pw';
DO $$
BEGIN
  ALTER ROLE landed_ai SET temp_file_limit = '256MB';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE WARNING 'landed_ai temp_file_limit not set (needs a superuser; expected on Amazon RDS): %', SQLERRM;
END $$;

-- landed_ai can connect to every database whose CONNECT is still granted to PUBLIC, and
-- pg_stat_activity / pg_terminate_backend / advisory locks are cluster-wide: the revokes of
-- migration 000006 only cover the landed database. List what is still reachable (deploy step:
-- REVOKE CONNECT ON DATABASE <name> FROM PUBLIC, or restrict landed_ai in pg_hba.conf).
DO $$
DECLARE d text;
BEGIN
  FOR d IN SELECT datname FROM pg_database
           WHERE datallowconn AND datname NOT LIKE 'ennam\_landed%'
             AND has_database_privilege('landed_ai', datname, 'CONNECT')
  LOOP
    RAISE WARNING 'landed_ai can connect to database %: revoke CONNECT from PUBLIC there or restrict it in pg_hba.conf', d;
  END LOOP;
END $$;
