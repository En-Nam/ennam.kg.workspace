-- Landed store bootstrap. Mounted into the postgres container's
-- /docker-entrypoint-initdb.d/, so it runs ONLY on a FRESH data volume.
-- Existing clusters: this does not re-run; create database ennam_landed and the roles
-- manually, and apply the REVOKEs below by hand (fresh-cluster step).
-- Passwords are read from the LANDED_*_PASSWORD env vars via psql \getenv
-- (not -v, so they never appear in a process argument list). Schema, tables and RLS live in ennam.kg.go/db/landed_migrations
-- (`make landed-migrate`), never here.
\set ON_ERROR_STOP on
\getenv maint_pw LANDED_MAINT_PASSWORD
\getenv writer_pw LANDED_WRITER_PASSWORD
\getenv engine_pw LANDED_ENGINE_PASSWORD

SELECT 'CREATE DATABASE ennam_landed OWNER ' || current_user
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'ennam_landed')\gexec

-- Roles are created NOLOGIN by the migration too; create here so LOGIN/passwords can be set.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'landed_maintenance') THEN CREATE ROLE landed_maintenance NOLOGIN NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'landed_writer')      THEN CREATE ROLE landed_writer NOLOGIN NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'landed_engine')      THEN CREATE ROLE landed_engine NOLOGIN NOBYPASSRLS; END IF;
END $$;

ALTER ROLE landed_maintenance LOGIN PASSWORD :'maint_pw';
ALTER ROLE landed_writer      LOGIN PASSWORD :'writer_pw';
ALTER ROLE landed_engine      LOGIN PASSWORD :'engine_pw';

-- Deploy step: stop the landed roles (and anyone else) reaching the other databases.
-- Fresh clusters only; skipped silently when a database does not exist yet.
SELECT format('REVOKE CONNECT, TEMP ON DATABASE %I FROM PUBLIC', datname)
FROM pg_database WHERE datname IN ('ennam_kg', 'pharmacy_demo')\gexec
