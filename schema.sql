-- Postgres schema for the PUBINFO "Codes" tables only.
-- Adapted from capublic.sql (MySQL DDL) distributed by the California Legislature.
-- Scope: codes_tbl, law_toc_tbl, law_toc_sections_tbl, law_section_tbl

CREATE TABLE IF NOT EXISTS codes_tbl (
    code   VARCHAR(5),
    title  VARCHAR(2000)
);

CREATE TABLE IF NOT EXISTS law_toc_tbl (
    law_code              VARCHAR(5),
    division              VARCHAR(100),
    title                 VARCHAR(100),
    part                  VARCHAR(100),
    chapter               VARCHAR(100),
    article               VARCHAR(100),
    heading               VARCHAR(2000),
    active_flg            VARCHAR(1)   DEFAULT 'Y',
    trans_uid             VARCHAR(30),
    trans_update          TIMESTAMP,
    node_sequence         NUMERIC(22, 0),
    node_level            NUMERIC(22, 0),
    node_position         NUMERIC(22, 0),
    node_treepath         VARCHAR(100),
    contains_law_sections VARCHAR(1),
    history_note          VARCHAR(350),
    op_statues            VARCHAR(10),
    op_chapter            VARCHAR(10),
    op_section            VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS law_toc_code_idx     ON law_toc_tbl (law_code);
CREATE INDEX IF NOT EXISTS law_toc_division_idx  ON law_toc_tbl (division);
CREATE INDEX IF NOT EXISTS law_toc_title_idx     ON law_toc_tbl (title);
CREATE INDEX IF NOT EXISTS law_toc_part_idx      ON law_toc_tbl (part);
CREATE INDEX IF NOT EXISTS law_toc_chapter_idx   ON law_toc_tbl (chapter);
CREATE INDEX IF NOT EXISTS law_toc_article_idx   ON law_toc_tbl (article);

CREATE TABLE IF NOT EXISTS law_toc_sections_tbl (
    id                     VARCHAR(100),
    law_code               VARCHAR(5),
    node_treepath          VARCHAR(100),
    section_num            VARCHAR(30),
    section_order          NUMERIC(22, 0),
    title                  VARCHAR(400),
    op_statues             VARCHAR(10),
    op_chapter             VARCHAR(10),
    op_section             VARCHAR(20),
    trans_uid              VARCHAR(30),
    trans_update           TIMESTAMP,
    law_section_version_id VARCHAR(100),
    seq_num                NUMERIC(22, 0)
);

CREATE INDEX IF NOT EXISTS law_toc_sections_node_idx
    ON law_toc_sections_tbl (law_code, node_treepath);

CREATE TABLE IF NOT EXISTS law_section_tbl (
    id                     VARCHAR(100),
    law_code               VARCHAR(5),
    section_num            VARCHAR(30),
    op_statues             VARCHAR(10),
    op_chapter             VARCHAR(10),
    op_section             VARCHAR(20),
    effective_date         TIMESTAMP,
    law_section_version_id VARCHAR(100),
    division               VARCHAR(100),
    title                  VARCHAR(100),
    part                   VARCHAR(100),
    chapter                VARCHAR(100),
    article                VARCHAR(100),
    history                VARCHAR(1000),
    content_xml            TEXT,
    active_flg             VARCHAR(1)   DEFAULT 'Y',
    trans_uid              VARCHAR(30),
    trans_update           TIMESTAMP
);

CREATE INDEX IF NOT EXISTS law_section_tbl_pk  ON law_section_tbl (id);
CREATE INDEX IF NOT EXISTS law_section_code_idx ON law_section_tbl (law_code);
CREATE INDEX IF NOT EXISTS law_section_id_idx   ON law_section_tbl (law_section_version_id);
CREATE INDEX IF NOT EXISTS law_section_sect_idx ON law_section_tbl (section_num);
