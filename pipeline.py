"""
PUBINFO pipeline for California legislative codes data.

Public entry points:
    run_backlog_load()          -- download current session zip and load codes tables
    run_daily_update(day=None)  -- download today's (or a named) daily zip and reload codes tables

Both functions are designed to be called by an external Celery Beat scheduler.

Database connection is configured via the DATABASE_URL environment variable:
    DATABASE_URL=postgresql://capublic:capublic@localhost:5432/capublic
"""

import csv
import datetime
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
import psycopg

BASE_URL = "https://downloads.leginfo.legislature.ca.gov"
DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://capublic:capublic@localhost:5432/capublic"
)

# Tables in the Codes scope, in dependency order (codes_tbl first since others reference it)
CODES_TABLES = [
    "codes_tbl",
    "law_toc_tbl",
    "law_toc_sections_tbl",
    "law_section_tbl",
]

# Column names in the order they appear in each table's .dat file.
# For law_section_tbl, column index 14 in the .dat is a LOB filename (@var1 in the
# MySQL load script), not the content_xml value itself. The pipeline reads the file
# and substitutes the content before inserting.
_DAT_COLUMNS: dict[str, list[str]] = {
    "codes_tbl": [
        "code",
        "title",
    ],
    "law_toc_tbl": [
        "law_code", "division", "title", "part", "chapter", "article",
        "heading", "active_flg", "trans_uid", "trans_update",
        "node_sequence", "node_level", "node_position", "node_treepath",
        "contains_law_sections", "history_note", "op_statues", "op_chapter", "op_section",
    ],
    "law_toc_sections_tbl": [
        "id", "law_code", "node_treepath", "section_num", "section_order",
        "title", "op_statues", "op_chapter", "op_section", "trans_uid",
        "trans_update", "law_section_version_id", "seq_num",
    ],
    # Column 14 is the LOB filename from the .dat file; it maps to content_xml in the DB.
    "law_section_tbl": [
        "id", "law_code", "section_num", "op_statues", "op_chapter", "op_section",
        "effective_date", "law_section_version_id", "division", "title", "part",
        "chapter", "article", "history", "content_xml",
        "active_flg", "trans_uid", "trans_update",
    ],
}

_LAW_SECTION_LOB_COL = 14  # 0-based index of the LOB filename column in law_section_tbl.dat

# Columns whose values are hierarchical numbers and should have trailing
# periods and spaces stripped on ingest (e.g. "3.5." → "3.5").
_STRIP_TRAILING_COLS: dict[str, set[str]] = {
    "law_toc_tbl": {"division", "title", "part", "chapter", "article"},
    "law_toc_sections_tbl": {"section_num"},
    "law_section_tbl": {"section_num", "division", "title", "part", "chapter", "article"},
}


def get_db_connection() -> psycopg.Connection:
    """Return a psycopg connection using DATABASE_URL."""
    return psycopg.connect(DATABASE_URL)


def download_file(url: str, dest_path: Path) -> Path:
    """Download url to dest_path, streaming to avoid large memory use."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {url} -> {dest_path.name}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    return dest_path


def extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract zip_path into dest_dir, return dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    return dest_dir


def _parse_dat(dat_path: Path):
    """Yield rows from a PUBINFO tab-delimited .dat file."""
    with open(dat_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter="\t", quotechar="`")
        yield from reader


def _coerce(val: str):
    """Convert MySQL null sentinels or empty string to Python None."""
    val = val.rstrip()
    return None if val in ("", "\\N", "NULL") else val


def _coerce_section_num(val: str | None) -> str | None:
    """Strip trailing periods and spaces from a section number.

    The PUBINFO .dat files store section numbers with a trailing period
    (e.g. ``"2019.210."``), and may also include trailing whitespace.
    This normalises them to bare form (``"2019.210"``).
    """
    return val.rstrip(". ") if val is not None else None


def _find_dat(extract_dir: Path, table: str) -> Path | None:
    """Locate the .dat file for a table (uppercase or lowercase)."""
    for name in (table.upper() + ".dat", table.lower() + ".dat"):
        p = extract_dir / name
        if p.exists():
            return p
    return None


def _load_standard_table(table: str, dat_path: Path, cursor: psycopg.Cursor) -> int:
    """TRUNCATE then INSERT all rows from dat_path into table. Returns row count."""
    columns = _DAT_COLUMNS[table]
    col_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"

    cursor.execute(f"TRUNCATE TABLE {table}")

    count = 0
    batch: list[tuple] = []
    for row in _parse_dat(dat_path):
        # Pad short rows (trailing nulls may be omitted in the file)
        if len(row) < len(columns):
            row += [""] * (len(columns) - len(row))
        values = [_coerce(v) for v in row[: len(columns)]]
        strip = _STRIP_TRAILING_COLS.get(table, set())
        for i, col in enumerate(columns):
            if col in strip:
                values[i] = _coerce_section_num(values[i])
        batch.append(tuple(values))
        if len(batch) >= 1000:
            cursor.executemany(insert_sql, batch)
            count += len(batch)
            batch = []
    if batch:
        cursor.executemany(insert_sql, batch)
        count += len(batch)
    return count


def _load_law_section(dat_path: Path, extract_dir: Path, cursor: psycopg.Cursor) -> int:
    """
    TRUNCATE then INSERT law_section_tbl rows, resolving LOB sidecar files.

    The MySQL load script stores a LOB filename in column 14 of the .dat file and
    uses LOAD_FILE() to read the actual content. Here we read the file in Python
    and supply the content directly.
    """
    columns = _DAT_COLUMNS["law_section_tbl"]
    col_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO law_section_tbl ({col_sql}) VALUES ({placeholders})"

    cursor.execute("TRUNCATE TABLE law_section_tbl")

    count = 0
    batch: list[tuple] = []
    for row in _parse_dat(dat_path):
        if len(row) < len(columns):
            row += [""] * (len(columns) - len(row))

        values = [_coerce(v) for v in row[: len(columns)]]
        strip = _STRIP_TRAILING_COLS["law_section_tbl"]
        for i, col in enumerate(_DAT_COLUMNS["law_section_tbl"]):
            if col in strip:
                values[i] = _coerce_section_num(values[i])

        # Resolve LOB sidecar for content_xml
        lob_filename = values[_LAW_SECTION_LOB_COL]
        if lob_filename:
            lob_path = extract_dir / lob_filename
            values[_LAW_SECTION_LOB_COL] = (
                lob_path.read_text(encoding="utf-8", errors="replace")
                if lob_path.exists()
                else None
            )
        else:
            values[_LAW_SECTION_LOB_COL] = None

        batch.append(tuple(values))
        if len(batch) >= 200:  # smaller batches: rows may contain large XML
            cursor.executemany(insert_sql, batch)
            count += len(batch)
            batch = []
    if batch:
        cursor.executemany(insert_sql, batch)
        count += len(batch)
    return count


def load_codes_tables(extract_dir: Path, conn: psycopg.Connection) -> None:
    """
    Load all four codes tables from an extracted PUBINFO directory.

    Strategy: TRUNCATE each table then insert all rows. Commits once at the end.
    """
    with conn.cursor() as cur:
        for table in CODES_TABLES:
            dat_path = _find_dat(extract_dir, table)
            if dat_path is None:
                print(f"  Warning: {table.upper()}.dat not found in {extract_dir}, skipping")
                continue

            if table == "law_section_tbl":
                count = _load_law_section(dat_path, extract_dir, cur)
            else:
                count = _load_standard_table(table, dat_path, cur)

            print(f"  {table}: {count} rows loaded")

    conn.commit()


def run_backlog_load() -> None:
    """
    Download the current session zip (pubinfo_2025.zip) and load codes tables.

    Entry point for the initial/backlog load. Safe to re-run — each table is
    truncated before loading.
    """
    zip_url = f"{BASE_URL}/pubinfo_2025.zip"
    zip_path = DOWNLOADS_DIR / "pubinfo_2025.zip"

    download_file(zip_url, zip_path)

    extract_dir = DOWNLOADS_DIR / "pubinfo_2025"
    print(f"  Extracting to {extract_dir.name}/")
    extract_zip(zip_path, extract_dir)

    print("  Loading codes tables...")
    with get_db_connection() as conn:
        load_codes_tables(extract_dir, conn)

    print("Backlog load complete.")


def run_daily_update(day: str | None = None) -> None:
    """
    Download today's incremental zip and reload codes tables.

    Args:
        day: Day abbreviation — 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', or 'Sat'.
             Defaults to today's weekday name. Sunday has no incremental file;
             pass an explicit day to override.

    Entry point for Celery Beat. Safe to re-run — each table is truncated
    before loading.
    """
    if day is None:
        day = datetime.datetime.now().strftime("%a")

    zip_url = f"{BASE_URL}/pubinfo_{day}.zip"
    zip_path = DOWNLOADS_DIR / f"pubinfo_{day}.zip"

    download_file(zip_url, zip_path)

    extract_dir = DOWNLOADS_DIR / f"pubinfo_{day}"
    print(f"  Extracting to {extract_dir.name}/")
    extract_zip(zip_path, extract_dir)

    print("  Loading codes tables...")
    with get_db_connection() as conn:
        load_codes_tables(extract_dir, conn)

    print(f"Daily update ({day}) complete.")


# ---------------------------------------------------------------------------
# CAML XML → Markdown converter
# ---------------------------------------------------------------------------
# Elements found in the PUBINFO corpus (empirically verified):
#   caml:Content — root wrapper
#   p            — paragraph (class attrs are layout hints, ignored for MD)
#   span         — inline: EnSpace/EmSpace/ThinSpace=space, SmallCaps=text,
#                          SpacedLeaders=dots, UnderlinedLeaders=underscores,
#                          DashedLeaders=dashes
#   b, i, u      — bold, italic, underline
#   br           — hard line break
#   sup, sub     — super/subscript
#   table/thead/tbody/tr/th/td/col/colgroup — tables
#   caml:Fraction / caml:Numerator / caml:Denominator — e.g. "1/2"
#   caml:LabelledField — form field label, rendered as plain text
#   caml:TipIn   — physical tip-in page insert (numPages attr), no text content

_CAML_NS = "http://lc.ca.gov/legalservices/schemas/caml.1#"

_SPAN_LEADERS: dict[str, str] = {
    "SpacedLeaders": "·····",
    "UnderlinedLeaders": "________",
    "DashedLeaders": "--------",
}

_SPAN_SPACES: set[str] = {"EnSpace", "ThinSpace", "EmSpace"}


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _node_to_md(elem: ET.Element) -> str:
    """Element content + its tail text."""
    return _elem_to_md(elem) + (elem.tail or "")


def _elem_to_md(elem: ET.Element) -> str:
    """Convert an element's own content (not its tail) to Markdown."""
    local = _local(elem.tag)
    text = elem.text or ""
    inner = text + "".join(_node_to_md(c) for c in elem)

    if local == "Content":
        return inner

    elif local == "p":
        stripped = inner.strip()
        return (stripped + "\n\n") if stripped else ""

    elif local == "span":
        cls = elem.get("class", "")
        if cls in _SPAN_SPACES:
            return " "
        if cls in _SPAN_LEADERS:
            return _SPAN_LEADERS[cls]
        # SmallCaps and anything else: render inner text
        return inner

    elif local == "b":
        s = inner.strip()
        return f"**{s}**" if s else ""

    elif local == "i":
        s = inner.strip()
        return f"*{s}*" if s else ""

    elif local == "u":
        return f"<u>{inner}</u>"

    elif local == "br":
        return "  \n"

    elif local in ("sup", "sub"):
        return f"<{local}>{inner}</{local}>"

    elif local == "Fraction":
        num = elem.find(f"{{{_CAML_NS}}}Numerator")
        den = elem.find(f"{{{_CAML_NS}}}Denominator")
        n = (num.text or "") if num is not None else ""
        d = (den.text or "") if den is not None else ""
        return f"{n}/{d}"

    elif local in ("Numerator", "Denominator"):
        return ""  # consumed by Fraction

    elif local == "LabelledField":
        return inner

    elif local == "TipIn":
        return ""  # physical page insert, no renderable text

    elif local == "table":
        return "\n" + _table_to_md(elem) + "\n"

    elif local in ("colgroup", "col"):
        return ""

    elif local in ("tbody", "thead"):
        return inner

    # td/th: content handled via _cell_text in table rendering
    else:
        return inner


def _cell_text(cell: ET.Element) -> str:
    """Flatten a td/th to a single line, escaping pipe characters."""
    text = cell.text or ""
    content = text + "".join(_node_to_md(c) for c in cell)
    return content.strip().replace("\n", " ").replace("|", "\\|")


def _table_to_md(table: ET.Element) -> str:
    """Convert a table element to a GFM Markdown table."""
    rows: list[list[str]] = []

    def collect_rows(container: ET.Element) -> None:
        for child in container:
            loc = _local(child.tag)
            if loc in ("thead", "tbody"):
                collect_rows(child)
            elif loc == "tr":
                cells = [
                    _cell_text(c)
                    for c in child
                    if _local(c.tag) in ("th", "td")
                ]
                rows.append(cells)

    collect_rows(table)

    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    padded = [r + [""] * (max_cols - len(r)) for r in rows]

    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    lines = [fmt(padded[0]), sep] + [fmt(r) for r in padded[1:]]
    return "\n".join(lines)


def _xml_to_markdown(content_xml: str) -> str:
    """Convert a caml:Content XML string to Markdown."""
    root = ET.fromstring(content_xml)
    md = _elem_to_md(root)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def section_to_markdown(law_code: str, section_num: str) -> str:
    """
    Fetch a California code section and return it formatted as Markdown.

    Args:
        law_code:    Code identifier, e.g. ``"CCP"``.
        section_num: Section number, e.g. ``"2019.210"`` (trailing period optional).

    Returns:
        Markdown string: a ``# heading`` followed by the section text.

    Raises:
        ValueError: Section not found or has no content.
    """
    display_num = section_num.rstrip(". ")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content_xml FROM law_section_tbl"
                " WHERE law_code = %s AND section_num = %s",
                (law_code, display_num),
            )
            row = cur.fetchone()

    if row is None:
        raise ValueError(f"Section {law_code} § {display_num} not found")
    if not row[0]:
        raise ValueError(f"Section {law_code} § {display_num} has no content")

    body = _xml_to_markdown(row[0])
    return f"# {display_num}\n\n{body}\n"


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "daily":
        day_arg = sys.argv[2] if len(sys.argv) > 2 else None
        run_daily_update(day_arg)
    else:
        run_backlog_load()
