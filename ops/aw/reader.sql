\set ON_ERROR_STOP on
\getenv reader_password AW_READER_PASSWORD

SELECT length(:'reader_password') >= 32 AS password_valid \gset
\if :password_valid
\else
    \echo 'AW_READER_PASSWORD must contain at least 32 characters'
    \quit 1
\endif

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'aw_mock_reader'
          AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT 1 FROM pg_auth_members
        WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'aw_mock_reader')
    ) THEN
        RAISE EXCEPTION 'aw_mock_reader already has elevated privileges or memberships';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aw_mock_reader') THEN
        CREATE ROLE aw_mock_reader LOGIN;
    END IF;
END
$$;

SELECT format('ALTER ROLE aw_mock_reader LOGIN PASSWORD %L', :'reader_password') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO aw_mock_reader', current_database()) \gexec
GRANT USAGE ON SCHEMA aw_mock TO aw_mock_reader;
GRANT SELECT ON aw_mock.samples TO aw_mock_reader;
ALTER ROLE aw_mock_reader SET default_transaction_read_only = on;
ALTER ROLE aw_mock_reader SET statement_timeout = '30s';

COMMIT;
