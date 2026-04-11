# Inferred Hierarchical Structure of California Code Tables

*Derived empirically from PUBINFO database as of 2026-04-10.*

---

## Overview of the Four Tables

| Table | Role |
|---|---|
| `codes_tbl` | Master list of 30 codes (code abbreviation + long title) |
| `law_toc_tbl` | Table of contents tree — one row per TOC node (division, part, chapter, article headings) |
| `law_toc_sections_tbl` | Links TOC nodes to individual law sections via `node_treepath` |
| `law_section_tbl` | The actual statutory text (one row per section), with inherited hierarchy columns |

---

## The `node_*` Columns in `law_toc_tbl`

These four columns together encode a tree structure over the TOC entries within each code.

### `node_level`

The **depth** of the node in the tree, with 1 being the topmost level (i.e., immediate children of the code root). Not a stable semantic mapping — a `node_level=2` entry means "two levels deep in this code's tree," but what named hierarchy level that corresponds to varies by code.

### `node_sequence`

A **pre-order (depth-first) traversal counter** assigned globally within each code. Used to read the TOC in document order. It is not a simple sequence of integers 1..N; gaps appear because the sequence is shared across the entire PUBINFO dataset and codes are traversed one after another.

### `node_position`

The **sibling position** of a node within its parent (1-based). A node's `node_position` is appended to its parent's `node_treepath` to form the child's `node_treepath`.

### `node_treepath`

A **materialized path** — a dot-separated string of `node_position` values from the root to the current node. Examples:

- `"6"` — the 6th top-level node in this code
- `"6.8"` — the 8th child of the 6th top-level node
- `"6.8.10"` — the 10th child of the above

This is consistent with a standard adjacency-list-to-materialized-path encoding. It enables:
- Subtree queries: `WHERE node_treepath LIKE '6.8.%'`
- Parent lookup: strip the last `.N` segment
- Depth computation: count the dots + 1

The treepath numbers are sequential child-ordinals, **not** the named identifiers (e.g., `division=8` does not mean the treepath contains `8` — the treepath position may differ from the named number).

### `contains_law_sections`

`'Y'` if the TOC node directly contains law sections (i.e., it is the container that `law_toc_sections_tbl` links sections to). `'N'` for structural-only nodes (divisions, parts, chapters that merely group lower nodes). Roughly 75–85% of TOC rows have `'Y'`.

---

## Hierarchy Columns: How They Work

The five named hierarchy columns — `division`, `title`, `part`, `chapter`, `article` — are **carried forward from parent to child**. A node at depth 4 retains the `division` value of its ancestor at depth 1, plus its own `chapter` or `article` value. This means you can read any `law_toc_tbl` row and know the full ancestor path just from that one row (no JOIN needed).

The "new" information introduced at each `node_level` is whichever column changes from its parent. By tracing which columns first become non-null as depth increases, the logical hierarchy can be reconstructed.

**Important:** multiple hierarchy columns may be null for any given node — the column is simply not applicable at that level or in that code.

---

## Structural Types by Code

### Depth 1 — Flat

**CONS (California Constitution)**

The only code with a single-level tree. All 33 TOC nodes are at `node_level=1`. There is no division, title, part, or chapter. The `article` column holds Roman numeral identifiers (I, II, III, …). The preamble appears as the first node with no `article` value.

```
article (e.g., "I", "II", "X A")
  └─ sections (e.g., SECTION 1, SEC. 2)
```

### Depth 3 — Division → Chapter → Article

**COM, EVID, FIN, VEH**

Three named levels. No `title` or `part` column is ever populated.

```
division
  └─ chapter
       └─ article
```

- COM (Commercial Code): structured around numbered Divisions matching UCC articles (Division 1 = General Provisions, Division 2 = Sales, etc.).
- EVID (Evidence Code): divisions are topical groupings; chapters and articles sub-divide them.
- FIN (Financial Code): 39 distinct divisions covering different types of financial institutions.
- VEH (Vehicle Code): 34 divisions, chapter immediately below, then article.

Note: VEH at `node_level=2` has 4 entries where `article` is already set (i.e., article directly under division, skipping chapter). This appears to be exceptional.

### Depth 4 — Division → Part → Chapter → Article (most codes)

**FAC, FAM, FGC, HNC, HSC, INS, LAB, MVC, PCC, PRC, PROB, PUC, RTC, SHC, UIC, WAT, WIC**

The most common pattern. All four named levels are used. The `title` column is never set.

```
division
  └─ part
       └─ chapter
            └─ article
```

Also **ELEC**: similar pattern but some chapters exist directly under division without a part, and some articles appear directly under division. Mixed — the structure is not fully uniform across the code.

Also **BPC (Business and Professions Code)**: mostly `division → chapter → article` (3 levels), but two divisions (Division 4: Real Estate, Division 7: General Business Regulations) introduce a `part` level between division and chapter, making those subtrees 4 levels deep. The `title` column is never used in BPC.

### Depth 4 — Part → Title → Chapter → Article

**CCP (Code of Civil Procedure), PEN (Penal Code)**

The top-level named grouping is `part`, not `division`. The `title` level sits between part and chapter. This is inverted from most codes (where `title` would sit above `part`).

```
part
  └─ title
       └─ chapter
            └─ article [→ sub-article at depth 5, occasional]
```

A small number of CCP entries have `division` set at lower levels (5 of 207 level-3 entries); and in `law_section_tbl`, 523 of 3,424 CCP sections carry a `division` value. This may indicate a minority of CCP sections that formally belong to a division within a part, or could be a data anomaly. More investigation needed.

Similarly, PEN has `division` set on some lower-level nodes (33 of 330 level-3 entries). These sections appear to belong to a division that exists inside a part/title context.

### Depth 4–5 — Title → Division → Chapter → Article (→ Article sub-levels)

**CORP (Corporations Code)**

The top-level is `title`, then `division`, then `chapter`, then `article`. Some subtrees go one level deeper with all five named levels (division → part → chapter → article under a title), reaching depth 5.

```
title
  └─ division
       └─ chapter [or part]
            └─ article [if chapter] / chapter → article [if part]
```

CORP has 7 titles, 8+ divisions, and the deepest subtrees introduce `part` between division and chapter.

### Depth 5 — Title → Division → Part → Chapter → Article

**EDC (Education Code), GOV (Government Code)**

The full five-level hierarchy with `title` at the top.

```
title
  └─ division
       └─ part
            └─ chapter
                 └─ article
```

Within GOV, some subtrees skip `part` and go directly title → division → chapter → article (4 levels). GOV is the largest code by TOC row count (2,934 rows) and has the most structural variation.

**CIV (Civil Code)** also reaches depth 5. Its structure is typically:

```
division
  └─ part
       └─ title [present in ~82% of level-3 entries]
            └─ chapter
                 └─ article
```

Some branches skip `title` and go directly division → part → chapter → article.

---

## Summary Table by Code

| Code | Name | Max Depth | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|---|---|---|
| BPC | Business and Professions | 4 | division | chapter (or part) | article (or chapter) | article | — |
| CCP | Code of Civil Procedure | 5 | part | title | chapter | article | sub-article |
| CIV | Civil Code | 5 | division | part | title or chapter | chapter or article | article |
| COM | Commercial Code | 3 | division | chapter | article | — | — |
| CONS | California Constitution | 1 | article | — | — | — | — |
| CORP | Corporations Code | 5 | title | division | chapter or part | article or chapter | article |
| EDC | Education Code | 5 | title | division | part | chapter | article |
| ELEC | Elections Code | 4 | division | chapter or part | chapter or article | article | — |
| EVID | Evidence Code | 3 | division | chapter | article | — | — |
| FAC | Food and Agricultural Code | 4 | division | part | chapter | article | — |
| FAM | Family Code | 4 | division | part | chapter | article | — |
| FGC | Fish and Game Code | 4 | division | chapter | article | — | — |
| FIN | Financial Code | 3 | division | chapter | article | — | — |
| GOV | Government Code | 5 | title | division | part or chapter | chapter or article | article |
| HNC | Harbors and Navigation Code | 4 | division | part or chapter | chapter or article | article | — |
| HSC | Health and Safety Code | 4 | division | part or chapter | chapter | article | — |
| INS | Insurance Code | 4 | division | part | chapter | article | — |
| LAB | Labor Code | 4 | division | part | chapter | article | — |
| MVC | Military and Veterans Code | 4 | division | chapter | article | — | — |
| PCC | Public Contract Code | 4 | division | part | chapter | article | — |
| PEN | Penal Code | 5 | part | title | chapter | article | sub-article |
| PRC | Public Resources Code | 4 | division | part or chapter | chapter or article | article | — |
| PROB | Probate Code | 4 | division | part | chapter | article | — |
| PUC | Public Utilities Code | 4 | division | part or chapter | chapter | article | — |
| RTC | Revenue and Taxation Code | 4 | division | part | chapter | article | — |
| SHC | Streets and Highways Code | 4 | division | part or chapter | chapter or article | article | — |
| UIC | Unemployment Insurance Code | 4 | division | part or chapter | chapter | article | — |
| VEH | Vehicle Code | 3 | division | chapter | article | — | — |
| WAT | Water Code | 4 | division | part | chapter | article | — |
| WIC | Welfare and Institutions Code | 4 | division | part or chapter | chapter or article | article | — |

*"or" indicates the level is not uniform across the code — some branches take one path, others another.*

---

## What Is the Same Across All Codes

1. The five column names (`division`, `title`, `part`, `chapter`, `article`) are the only named hierarchy identifiers available in the schema.
2. Columns carry forward from ancestor to descendant — a section row always contains the full ancestor context.
3. `node_treepath` is always a dot-separated materialized path of `node_position` values, enabling efficient subtree queries.
4. The named identifiers in columns (e.g., `division=3.6`, `chapter=5.5`) use decimal-suffix numbering (not integers) to represent inserted levels without renumbering.
5. The `heading` column in `law_toc_tbl` always encodes the human-readable name and section range (e.g., `"CHAPTER 3. Definitions [100. - 199.]"`).
6. `node_sequence` provides reading order and `node_position` provides sibling order — these are complementary, not redundant.

## What Differs Across Codes

1. **Top-level named unit**: most codes start with `division`; CCP and PEN start with `part`; CORP, EDC, and GOV start with `title`; CONS starts with `article`.
2. **Depth**: ranges from 1 (CONS) to 5 (CCP, CIV, CORP, EDC, GOV, PEN).
3. **Whether `title` is used**: only CCP, CIV, CORP, EDC, GOV, and PEN use `title`. The rest leave it null.
4. **Whether `part` is used**: COM, CONS, EVID, FIN, and VEH never use `part`. BPC uses it only in some divisions. Most others use it uniformly.
5. **Internal structure uniformity**: GOV and CIV allow the same node_level to represent different named levels in different branches. Most other codes are uniform.
6. **The position of `title` relative to `part`**: in CIV it sits below `part` (part → title → chapter); in CCP/PEN `title` sits below `part` as well but at a different level.

---

## Potential Alternative Conclusions / Open Questions

1. **`node_sequence` might be code-local, not global.** The data shows non-sequential gaps (e.g., CIV's `node_sequence` jumps from 518 to 639 at level-1). These could be global counters across the full 18-table PUBINFO database rather than per-code counters. Confirmed: sequences are code-local but the counter itself appears to be a global allocation.

2. **"Part" in CCP/PEN may actually be "Division" by another name.** CCP's top-level units (PART 1, PART 2, etc.) function structurally the same as what other codes call DIVISION. The naming choice may be a legacy of how these codes were originally drafted, not a meaningful structural distinction.

3. **CONS `article` column may not correspond to the same concept as `article` in other codes.** In CONS, `article` holds Roman numerals (I, II, …) for the constitutional Articles — which are top-level units. In other codes, `article` is the lowest named level, below chapter. The same column name is used for two distinct concepts.

4. **Some `(none)` at node_level=1 may be preambles, not structural irregularities.** Most codes have one or more `node_level=1` rows with no named columns set (just a `heading` like "GENERAL PROVISIONS" or "TITLE OF ACT"). These appear to be pre-division introductory entries, not indicators of a missing hierarchy level.

5. **`division` in CCP/PEN lower levels may be legitimate sub-structure or a data anomaly.** A small fraction of CCP and PEN TOC entries have `division` set even though the top of their tree is `part`. This could mean: (a) certain statutes formally denominate a sub-unit as a "division," (b) the PUBINFO export process inherited a division tag from an earlier version of the code, or (c) it is a data entry error. The law_section_tbl data (523 CCP sections with division) suggests it is intentional.

6. **`part` ordering relative to `title` may not be stable within CIV.** The dominant CIV pattern is division → part → title → chapter → article, but the `has_title` count at level 3 is only 145/176 (82%), suggesting ~18% of level-3 nodes are chapters under a part with no title intervening.

7. **`law_toc_sections_tbl.node_treepath` may point to non-leaf TOC nodes.** The join in the `law_toc_sections_tbl` links section numbers to TOC nodes by `node_treepath`. It is possible that sections are linked to intermediate (non-leaf) TOC nodes in some cases — i.e., a section appears directly under a chapter without belonging to a named article. The `contains_law_sections='Y'` flag on those non-leaf TOC nodes would be the indicator.
