import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

MADGRADES_BASE_URL = "https://api.madgrades.com/v1"

GRADE_POINTS: Dict[str, float] = {
    "aCount": 4.0,
    "abCount": 3.5,
    "bCount": 3.0,
    "bcCount": 2.5,
    "cCount": 2.0,
    "dCount": 1.0,
    "fCount": 0.0,
}

_MIN_INTERVAL = 0.1
_rate_lock = threading.Lock()
_last_request_ts = [0.0]


def _rate_limit() -> None:
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_request_ts[0])
        if wait > 0:
            time.sleep(wait)
        _last_request_ts[0] = time.monotonic()


def _auth_headers() -> dict:
    token = os.getenv("MADGRADES_API_TOKEN")
    if not token:
        raise RuntimeError(
            "MADGRADES_API_TOKEN not set. Copy .env_example to .env and fill it in."
        )
    return {"Authorization": f"Token token={token}"}


_subject_code_cache: Dict[str, Optional[str]] = {}
_subject_cache_lock = threading.Lock()

_gpa_cache: Dict[str, Optional[float]] = {}
_gpa_cache_lock = threading.Lock()
_GPA_CACHE_PATH = Path(__file__).resolve().parent / ".gpa_cache.json"


def load_gpa_cache(path: Optional[Path] = None) -> None:
    global _gpa_cache
    p = Path(path) if path else _GPA_CACHE_PATH
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            _gpa_cache = json.load(f)


def save_gpa_cache(path: Optional[Path] = None) -> str:
    p = Path(path) if path else _GPA_CACHE_PATH
    with _gpa_cache_lock:
        snapshot = dict(_gpa_cache)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return str(p)


try:
    load_gpa_cache()
except json.JSONDecodeError:
    _gpa_cache = {}


def get_subject_code(abbreviation: str) -> Optional[str]:
    abbr_lower = abbreviation.strip().lower()
    with _subject_cache_lock:
        if abbr_lower in _subject_code_cache:
            return _subject_code_cache[abbr_lower]

    _rate_limit()
    resp = requests.get(
        f"{MADGRADES_BASE_URL}/subjects",
        params={"query": abbreviation, "per_page": 10},
        headers=_auth_headers(),
        timeout=30,
    )
    code: Optional[str] = None
    if resp.status_code == 200:
        for s in resp.json().get("results", []):
            if (s.get("abbreviation") or "").strip().lower() == abbr_lower:
                code = s["code"]
                break

    with _subject_cache_lock:
        _subject_code_cache[abbr_lower] = code
    return code


def find_course_uuid(catalog_number: str) -> Optional[str]:
    """Resolve a catalog number like 'ECON 101' to a Madgrades course UUID."""
    parts = catalog_number.strip().rsplit(" ", 1)
    if len(parts) != 2:
        return None
    subject_abbr, number = parts

    subject_code = get_subject_code(subject_abbr)
    if not subject_code:
        return None

    _rate_limit()
    resp = requests.get(
        f"{MADGRADES_BASE_URL}/courses",
        params={"subject": subject_code, "number": number, "per_page": 5},
        headers=_auth_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    return results[0]["uuid"]


def compute_average_gpa(course_uuid: str) -> Optional[float]:
    """Cumulative weighted GPA from /courses/{uuid}/grades."""
    _rate_limit()
    resp = requests.get(
        f"{MADGRADES_BASE_URL}/courses/{course_uuid}/grades",
        headers=_auth_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        return None

    cumulative = resp.json().get("cumulative") or {}
    total_points = 0.0
    total_count = 0
    for key, points in GRADE_POINTS.items():
        count = cumulative.get(key) or 0
        total_points += count * points
        total_count += count

    if total_count == 0:
        return None
    return round(total_points / total_count, 4)


def get_gpa(catalog_number: str, refresh: bool = False) -> Optional[float]:
    """Cached entry point: catalog_number (e.g. 'MATH 221') -> GPA or None."""
    key = " ".join(catalog_number.strip().upper().split())
    if not refresh:
        with _gpa_cache_lock:
            if key in _gpa_cache:
                return _gpa_cache[key]

    try:
        uuid = find_course_uuid(key)
        gpa = compute_average_gpa(uuid) if uuid else None
    except requests.RequestException:
        return None

    with _gpa_cache_lock:
        _gpa_cache[key] = gpa
    return gpa


def rank_courses_by_gpa(course_list_path: str) -> List[Dict]:
    """File-based ranker: reads course_list.json, returns ranked list.

    Courses without GPA data are appended at the end (preserved for
    backward compatibility with main.py / average_gpa_ranks.json consumers).
    For the search-driven flow with separate no-data handling, see
    search_with_gpa.rank_hits_by_gpa.
    """
    path = Path(course_list_path).expanduser().resolve()
    with open(path, "r", encoding="utf-8") as f:
        courses = json.load(f)

    scored: List[Tuple[str, str, Optional[float]]] = []
    for course in courses:
        catalog_number = course.get("catalog_number", "").strip()
        course_title = course.get("course_title", "").strip()
        gpa = get_gpa(catalog_number) if catalog_number else None
        scored.append((catalog_number, course_title, gpa))

    scored.sort(key=lambda x: (x[2] is None, -(x[2] or 0.0)))

    return [
        {"catalog_number": cat, "course_title": title, "gpa": gpa}
        for cat, title, gpa in scored
    ]


def save_ranked_courses(ranked: List[Dict], output_name: str) -> str:
    out_path = Path(output_name).expanduser().resolve()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ranked, f, indent=2, ensure_ascii=False)
    return str(out_path)
