FROM postgres:18
COPY schema.sql /docker-entrypoint-initdb.d/schema.sql
