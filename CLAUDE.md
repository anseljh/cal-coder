# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

cal-coder ingests the California Legislature's PUBINFO database (a publicly downloadable MySQL dump) into a local PostgreSQL database, scoped to the "Codes" subset — the current codified California statutory law (Civil Code, CCP, etc.). It also converts individual law sections from the source XML format (CAML) to Markdown.

## Commands

```bash
# Start the database
docker compose up -d

# Run the initial/backlog load (downloads ~pubinfo_2025.zip, large file)
DATABASE_URL=postgresql://capublic:capublic@localhost:5433/capublic uv run python pipeline.py

# Run a daily incremental update
DATABASE_URL=postgresql://capublic:capublic@localhost:5433/capublic uv run python pipeline.py daily [Mon|Tue|Wed|Thu|Fri|Sat]

# Connect to the database
docker exec cal-coder-db-1 psql -U capublic -d capublic
```

No test suite exists yet. No linter is configured.

## Architecture

Everything lives in `pipeline.py`. There is no package structure.

**Data flow — ingest:**
1. `run_backlog_load()` / `run_daily_update()` — public entry points (designed for Celery Beat)
2. `download_file()` → `extract_zip()` — fetch and unpack a PUBINFO zip into `downloads/`
3. `load_codes_tables()` → `_load_standard_table()` / `_load_law_section()` — TRUNCATE + INSERT each of the four tables

**Data flow — query:**
- `section_to_markdown(law_code, section_num)` — queries `law_section_tbl`, passes `content_xml` through `_xml_to_markdown()`, returns a Markdown string with a `#` heading.

**Key data quirks to know:**

- PUBINFO ships as a MySQL database. The `.dat` files are tab-delimited with optional backtick quoting; NULL is the bare word `NULL` (not `\N`). See `_coerce()`.
- `law_section_tbl` has a LOB sidecar mechanism: column 14 of the `.dat` file (`_LAW_SECTION_LOB_COL = 14`) holds a filename rather than the XML content itself. `_load_law_section()` reads those `.lob` files from the extract directory and substitutes the content inline.
- All hierarchical numbering columns (`section_num`, `division`, `title`, `part`, `chapter`, `article`) are stored in the source with a trailing period (e.g. `"2019.210."`). The pipeline strips trailing periods and spaces on ingest via `_coerce_section_num()`, controlled by `_STRIP_TRAILING_COLS`. Query these columns without a trailing period.
- The four loaded tables are scoped to Codes only: `codes_tbl`, `law_toc_tbl`, `law_toc_sections_tbl`, `law_section_tbl`. The full PUBINFO database has 18 tables; the others (bills, votes, legislators, etc.) are out of scope.

**CAML XML format:**

Section text is stored as XML in `content_xml` using a proprietary format (namespace `http://lc.ca.gov/legalservices/schemas/caml.1`). No public schema exists — the element inventory was derived empirically from the corpus. The converter (`_elem_to_md`, `_node_to_md`, `_table_to_md`) handles: `p`, `span` (EnSpace/EmSpace/ThinSpace/SmallCaps/SpacedLeaders/UnderlinedLeaders/DashedLeaders), `b`, `i`, `u`, `br`, `sup`, `sub`, tables, `caml:Fraction`, `caml:LabelledField`, `caml:TipIn`. A CPRA request for the official schema is tracked in GitHub issue #2.

## Database

- Host port: **5433** (5432 was already in use on this machine)
- Credentials: `capublic` / `capublic` / db `capublic`
- `schema.sql` is auto-applied by the Postgres container on first start (via `docker-entrypoint-initdb.d`). To reset: `docker compose down -v && docker compose up -d`
- The `pgdata` volume mounts at `/var/lib/postgresql` (not the usual `/var/lib/postgresql/data`) — required by the Postgres 18 image's new directory layout.
- Downloaded zips and extracted files live in `downloads/` (git-ignored). The pipeline creates this directory automatically.
