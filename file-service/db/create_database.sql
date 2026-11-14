SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'file_db_user', :'file_db_password')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'file_db_user'
)
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', 'file-service', :'file_db_user')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'file-service'
)
\gexec
