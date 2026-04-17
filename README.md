# UW-Madison Course Selection Toolkit

The core of this project is a **complete reverse-engineering of the search API powering [public.enroll.wisc.edu/search](https://public.enroll.wisc.edu/search)** — the official UW-Madison enrollment portal.

The enrollment site provides no public API documentation. By reading the minified frontend JavaScript (specifically `chunk-PJYL2HPO.js`), I reconstructed the full request/response contract: the Elasticsearch query DSL it builds, every filter parameter, the URL query string format, and all reference data (terms, subjects, sessions, special groups). The result is `course_search.py`, a Python client that replicates the portal's search behavior exactly, without a browser.

On top of that foundation, I wired in **Madgrades historical GPA data** so every course returned by a search is automatically enriched with its historical average GPA and sorted accordingly.

---

## What Was Reverse-Engineered

### API Endpoints (confirmed via DevTools)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/search/v1` | Main course search |
| `GET` | `/api/search/v1/subjectsMap/{termCode}` | Subject list for a term |
| `GET` | `/api/search/v1/aggregate` | Terms, sessions, specialGroups, subjects |
| `GET` | `/api/search/v1/enrollmentPackages/{termCode}/{subjectCode}/{courseId}` | Sections/packages for a specific course |
| `GET` | `/api/search/v1/details/{termCode}/{subjectCode}/{courseId}` | Full course details |

### Request Body Format (`POST /api/search/v1`)

The portal builds an Elasticsearch bool query client-side. The reconstructed body:

```json
{
  "selectedTerm": "1264",
  "queryString": "calculus",
  "filters": [...],
  "page": 1,
  "pageSize": 50,
  "sortOrder": "SCORE"
}
```

`filters` is a list of ES filter clauses. All filter logic from the UI is fully mapped:

| UI Filter | ES Clause | Notes |
|-----------|-----------|-------|
| Seats (Open/Waitlisted/Closed) | `has_child enrollmentPackage` → `packageEnrollmentStatus.status` | Only when term is set |
| Subject | `term subject.subjectCode` | Uses numeric code, not abbreviation |
| Breadth (B/H/L/N/P/S) | `terms breadths.code` | |
| General Education | `terms generalEd.code` + `has_child` for COM-B | COM-B differs from COM-A |
| Ethnic Studies | `term ethnicStudies.code` | Separate from gen-ed |
| Level (E/I/A) | `terms levels.code` | |
| Mode of Instruction | `has_child enrollmentPackage` → `modesOfInstruction` | 6 modes: all/classroom/hybrid/async/sync/either |
| Credits | `range minimumCredits` / `range maximumCredits` | |
| Honors | `has_child enrollmentPackage` → `sections.honors` | 3 types |
| Foreign Language | `match foreignLanguage.code` | FL1–FL5 |
| Sessions | `has_child enrollmentPackage` → `sections.sessionCode` | |
| Reserved Sections | `has_child enrollmentPackage` → `sections.classAttributes` | 3 modes |
| Course Attributes | various top-level fields | gradCourseWork, workplaceExperience, etc. |
| Catalog Number Range | `range catalogSort` (zero-padded to 5 digits) | |

Key discovery: **multiple `has_child(enrollmentPackage)` filters get merged into a single `bool.must` clause** (the `vr` function in the JS). Without this, combined filters silently fail.

### Filter Value Mappings (extracted from JS constants)

```python
BREADTH_MAP   = {"biologicalSciences": "B", "humanities": "H", ...}
GEN_ED_MAP    = {"commA": "COM A", "commB": "COM B", "quantA": "QR-A", ...}
LEVEL_MAP     = {"elementary": "E", "intermediate": "I", "advanced": "A"}
LANGUAGE_MAP  = {"first": "FL1", "second": "FL2", ..., "fifth": "FL5"}
HONORS_MAP    = {"honorsOnly": "HONORS_ONLY", "acceleratedHonors": "HONORS_LEVEL", ...}
SORT_ORDER_MAP = {"relevance": "SCORE", "subject": "SUBJECT", "catalog-number": "CATALOG_NUMBER"}
```

### Subject Code Quirk

The UI lets users filter by abbreviation (e.g. `MATH`, `COMP SCI`). The API actually filters on a **numeric** `subjectCode` (e.g. `"600"`, `"266"`). `CourseSearchClient._resolve_subject_code()` handles this translation transparently.

### URL Query String Format

The portal encodes all filters as URL params (for shareable search links). `filters_to_url_params()` reconstructs this encoding, including the `credits=min-max` and `catalogNum=min-max` range formats.

### Response Structure

```
POST /api/search/v1 → {
  "found": int,        # total matching courses
  "hits": [CourseHit], # up to pageSize results
  "message": str|null,
  "success": bool
}
```

Each `CourseHit` contains 45 fields covering course metadata, prerequisites, designations, and enrollment state.

---

## Project Structure

```
course_selection/
├── course_search.py          # ← Reverse-engineered enroll.wisc.edu client
│                             #   SearchFilters, build_query, CourseSearchClient,
│                             #   filters_to_url_params, all filter maps
├── aggreate.json             # Aggregate cache (terms / subjects / sessions)
├── gpa_ranker.py             # Madgrades API client: GPA lookup with caching
├── search_with_gpa.py        # Bridge: enrich search hits with GPA, sort results
├── main.py                   # CLI: rank a list of courses by GPA
├── course_list.json          # Input for batch GPA ranking
├── average_gpa_ranks.json    # Output: courses sorted by GPA
├── madgrades_openapi.json    # Madgrades API spec
├── .env                      # MADGRADES_API_TOKEN
├── requirements.txt
├── api/
│   └── server.py             # FastAPI: /api/terms, /api/subjects/{term}, /api/search
└── web/
    └── src/
        └── components/{FilterPanel,ResultList,NoDataPanel}.tsx
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
cd web && npm install && cd ..
```

### 2. Configure Madgrades Token

```bash
cp .env_example .env
# Set MADGRADES_API_TOKEN=your_token
```

Get a free token at [api.madgrades.com](https://api.madgrades.com/).

### 3. Run the Search Client Directly

```python
from course_search import CourseSearchClient, SearchFilters

client = CourseSearchClient()

# Basic search
result = client.search(term="1264", keywords="calculus")
print(f"Found: {result['found']} courses")

# Filtered search — mirrors the UI exactly
filters = SearchFilters(
    term="1264",
    advanced=True,
    open=True,
    modeOfInstruction="classroom",
    commA=True,
)
result = client.search(filters)

# Get sections for a course
hit = result["hits"][0]
packages = client.get_packages_for_hit(hit)

# Generate a shareable search URL
from course_search import filters_to_url_params
params = filters_to_url_params(filters)
qs = "&".join(f"{k}={v}" for k, v in params.items())
print(f"https://public.enroll.wisc.edu/search?{qs}")
```

### 4. Search with GPA Ranking

```python
from course_search import CourseSearchClient, SearchFilters
from search_with_gpa import search_ranked_by_gpa
from gpa_ranker import save_gpa_cache

client = CourseSearchClient()
result = search_ranked_by_gpa(
    client,
    term="1264",
    keywords="calculus",
    advanced=True,
    ignore_null=False,
    paginate_all=False,
)

for hit in result["ranked"][:10]:
    short = hit["subject"]["shortDescription"]
    print(f"  {short} {hit['catalogNumber']}: GPA={hit['gpa']:.2f} — {hit['title']}")

save_gpa_cache()
```

### 5. Start the Web App

```bash
# Terminal 1 — Backend (port 8000)
uvicorn api.server:app --reload --port 8000

# Terminal 2 — Frontend (port 5173)
cd web && npm run dev
```

Open http://localhost:5173. Filters map 1:1 to the official enrollment portal. Results are sorted by historical GPA descending; courses with no Madgrades data appear in a separate collapsible panel.

---

## Implementation Notes

### 403 Avoidance

The enrollment API blocks requests without a browser-like `User-Agent`. `CourseSearchClient.DEFAULT_HEADERS` includes a Chrome UA and sets `Referer`/`Origin` to `public.enroll.wisc.edu`.

### GPA Calculation

Weighted average on 4.0 scale using Madgrades `cumulative` data. Non-letter grades (S/U/CR/N/P/I/NW/NR) are excluded.

| Grade | Points |
|-------|--------|
| A | 4.0 |
| AB | 3.5 |
| B | 3.0 |
| BC | 2.5 |
| C | 2.0 |
| D | 1.0 |
| F | 0.0 |

### Caching and Rate Limiting

GPA lookups are cached in `.gpa_cache.json`. All Madgrades requests go through a global rate limiter (10 req/s max), safe for use inside `ThreadPoolExecutor(max_workers=5)`.

### Why No-Data Courses Aren't Ranked Last

No Madgrades data doesn't mean a low GPA — the course may be new, recently renumbered, or not yet indexed. A separate `no_data` bucket with a collapsible UI panel lets users review or hide them independently. Pass `ignore_null=True` to exclude them entirely.

---

## Backend API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/terms` | `{termCode: longDescription}` |
| GET | `/api/subjects/{termCode}` | `{subjectCode: formalDescription}` |
| POST | `/api/search` | Search + GPA ranking. Body: `{filters, ignoreNull, paginateAll, maxPages}` |
