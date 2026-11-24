#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -v identity="$IDENTITY_DB_PASSWORD" -v groups="$GROUPS_DB_PASSWORD" \
    -v catalog="$CATALOG_DB_PASSWORD" -v attempts="$ATTEMPTS_DB_PASSWORD" <<'SQL'
CREATE ROLE identity_app LOGIN PASSWORD :'identity';
CREATE ROLE groups_app LOGIN PASSWORD :'groups';
CREATE ROLE catalog_app LOGIN PASSWORD :'catalog';
CREATE ROLE attempts_app LOGIN PASSWORD :'attempts';
CREATE DATABASE identity_db OWNER identity_app;
CREATE DATABASE groups_db OWNER groups_app;
CREATE DATABASE catalog_db OWNER catalog_app;
CREATE DATABASE attempts_db OWNER attempts_app;
REVOKE CONNECT ON DATABASE identity_db, groups_db, catalog_db, attempts_db FROM PUBLIC;
GRANT CONNECT ON DATABASE identity_db TO identity_app;
GRANT CONNECT ON DATABASE groups_db TO groups_app;
GRANT CONNECT ON DATABASE catalog_db TO catalog_app;
GRANT CONNECT ON DATABASE attempts_db TO attempts_app;
SQL
