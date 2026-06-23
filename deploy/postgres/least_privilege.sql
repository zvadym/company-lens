-- Run as a PostgreSQL administrator after creating the database.
-- Passwords are intentionally supplied by the deployment secret manager.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'company_lens_migrator') THEN
        CREATE ROLE company_lens_migrator LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'company_lens_app') THEN
        CREATE ROLE company_lens_app LOGIN;
    END IF;
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE company_lens TO company_lens_migrator, company_lens_app;
GRANT USAGE, CREATE ON SCHEMA public TO company_lens_migrator;
GRANT USAGE ON SCHEMA public TO company_lens_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO company_lens_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO company_lens_app;

ALTER DEFAULT PRIVILEGES FOR ROLE company_lens_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO company_lens_app;
ALTER DEFAULT PRIVILEGES FOR ROLE company_lens_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO company_lens_app;
