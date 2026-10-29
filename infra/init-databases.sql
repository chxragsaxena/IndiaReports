-- One Postgres instance for local/demo use, but each service owns its own database.
-- In production each of these would be a separate cluster.
CREATE DATABASE reports_db;
CREATE DATABASE notifier_db;
CREATE DATABASE analytics_db;
\connect reports_db
CREATE EXTENSION IF NOT EXISTS postgis;
