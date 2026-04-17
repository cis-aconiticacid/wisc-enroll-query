# UW-Madison Course Selection Toolkit

A toolkit for UW-Madison course selection. The core feature is bridging two independent data sources — **enroll.wisc.edu search** (the official enrollment API) and **Madgrades historical GPA** — so that every course returned by search automatically includes its historical average GPA, sorted from highest to lowest.

Four layers:

1. **GPA Ranker** (`gpa_ranker.py`) — Madgrades API client; input a course number to get a weighted GPA, with built-in caching and rate limiting.
2. **Course Search Client** (`course_search.py`) — An ES query client reverse-engineered from the enroll.wisc.edu frontend, supporting full filtering, course details, and enrollment packages.
3. **Bridge** (`search_with_gpa.py`) — Concurrently enriches search results with GPA data and sorts them into buckets (with data vs. without data).
4. **Web App** (`api/` + `web/`) — FastAPI backend + Vite/React/Tailwind frontend.

---

## Project Structure

```
course_selection/
├── gpa_ranker.py             # Madgrades client: find_course_uuid / compute_average_gpa / get_gpa
├── course_search.py          # enroll.wisc.edu search client + SearchFilters
├── search_with_gpa.py        # Bridge: enrich_hits_with_gpa / rank_hits_by_gpa / search_ranked_by_gpa
├── main.py                   # GPA Ranker CLI entry point (reads course_list.json)
├── course_list.json          # Input: list of courses to rank
├── average_gpa_ranks.json    # Output: courses sorted by GPA
├── aggreate.json             # Enrollment platform aggregate cache (terms / subjects / sessions)
├── madgrades_openapi.json    # Madgrades API spec (reference)
├── .gpa_cache.json           # Persisted GPA cache (auto-generated, gitignored)
├── .env                      # MADGRADES_API_TOKEN
├── requirements.txt
├── api/
│   └── server.py             # FastAPI: /api/terms, /api/subjects/{term}, /api/search
└── web/
    ├── package.json
    ├── vite.config.ts        # Proxies /api → http://localhost:8000
    └── src/
        ├── App.tsx
        ├── api.ts
        ├── types.ts
        └── components/{FilterPanel,ResultList,NoDataPanel}.tsx
```

---

## Quick Start

### 1. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# Frontend
cd web && npm install && cd ..
```

### 2. Configure Madgrades Token

```bash
cp .env_example .env
# Edit .env and set MADGRADES_API_TOKEN=your_token
```

Register for a free token at [api.madgrades.com](https://api.madgrades.com/).

### 3. Start the Web App (two terminals)

```bash
# Terminal 1 — Backend (port 8000)
uvicorn api.server:app --reload --port 8000

# Terminal 2 — Frontend (port 5173)
cd web && npm run dev
```

Open http://localhost:5173 in your browser. Select a term, enter keywords, apply filters, and click Search. Results are displayed in descending GPA order. Courses without Madgrades data appear in a collapsible warning panel at the top; check "Hide courses without Madgrades GPA data" to hide them entirely (corresponds to `ignore_null=True` on the backend).

---

## Three Ways to Use

### A. Web UI

Use the flow above. Best for exploratory course browsing.

### B. Python Library — Search + Ranking

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
    ignore_null=False,      # True: drop courses with no GPA entirely
    paginate_all=False,     # True: fetch all pages (default: single page of 50)
)

print(f"{result['found']} matched, {len(result['ranked'])} ranked")
for w in result["warnings"]:
    print(f"  warning: {w}")

for hit in result["ranked"][:10]:
    short = hit["subject"]["shortDescription"]
    print(f"  {short} {hit['catalogNumber']}: GPA={hit['gpa']:.2f} — {hit['title']}")

for hit in result["no_data"]:
    short = hit["subject"]["shortDescription"]
    print(f"  [no madgrades data] {short} {hit['catalogNumber']}: {hit['title']}")

save_gpa_cache()  # Persist GPA results fetched in this session
```

Return structure:

```python
{
    "ranked":   [...],   # Hits with GPA, sorted descending
    "no_data":  [...],   # Hits without GPA (empty if ignore_null=True)
    "warnings": [...],   # Human-readable notes
    "total":    int,     # Number of hits processed
    "found":    int,     # Total server-side matches
}
```

### C. Python Library — Batch File Ranking (original GPA Ranker flow)

Input `course_list.json`:

```json
[
  {"catalog_number": "SOC 343", "course_title": "Sociology of Health"},
  {"catalog_number": "ECON 101", "course_title": "Microeconomics"}
]
```

```bash
python main.py
# → average_gpa_ranks.json (sorted descending by GPA; courses with no data appended at the end)
```

---

## API Endpoints

### Backend (FastAPI, localhost:8000)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/terms` | `{termCode: longDescription}` |
| GET | `/api/subjects/{termCode}` | `{subjectCode: formalDescription}` |
| POST | `/api/search` | Search + GPA ranking. Body: `{filters, ignoreNull, paginateAll, maxPages}` |

### Upstream

| API | Docs |
|-----|------|
| enroll.wisc.edu | Reverse-engineered from frontend JS. See header of `course_search.py` |
| Madgrades | [api.madgrades.com](https://api.madgrades.com/) (OpenAPI in `madgrades_openapi.json`) |

---

## Implementation Details

### GPA Calculation

Uses the Madgrades `cumulative` field, weighted average on a 4.0 scale:

| Grade | Points |
|-------|--------|
| A | 4.0 |
| AB | 3.5 |
| B | 3.0 |
| BC | 2.5 |
| C | 2.0 |
| D | 1.0 |
| F | 0.0 |

Non-letter grades (S/U/CR/N/P/I/NW/NR, etc.) are excluded from the average.

### Caching + Rate Limiting

- `get_gpa(catalog_number)` reads from and writes to both in-memory storage and `.gpa_cache.json`; pass `refresh=True` to force a refresh.
- All Madgrades HTTP requests go through a global `_rate_limit()` (capped at 10 req/s), safe for use inside a `ThreadPoolExecutor(max_workers=5)`.
- Default concurrency is 5 workers; adjustable via `max_workers=`.

### Why No-Data Courses Aren't Just Ranked Last

No Madgrades data doesn't mean a low GPA — the course might be new, have a changed course number, or simply not yet indexed. Placing them in a separate `no_data` bucket with a collapsible UI panel lets users choose to ignore or review them separately. `ignore_null=True` provides a one-click way to hide them entirely.

---

## Development

Frontend commands:

```bash
cd web
npm run dev        # Dev server (proxied to port 8000)
npm run build      # Production build → web/dist
npm run preview    # Preview the production build
```

The `User-Agent` must appear browser-like, or enroll.wisc.edu will return 403. `CourseSearchClient.DEFAULT_HEADERS` already includes a Chrome UA — be careful when overriding it.
