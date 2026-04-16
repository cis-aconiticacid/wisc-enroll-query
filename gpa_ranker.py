import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

MADGRADES_BASE_URL = "https://api.madgrades.com/v1"

# Grade points for weighted GPA calculation
GRADE_POINTS: Dict[str, float] = {
    "aCount": 4.0,
    "abCount": 3.5,
    "bCount": 3.0,
    "bcCount": 2.5,
    "cCount": 2.0,
    "dCount": 1.0,
    "fCount": 0.0,
}


def _auth_headers() -> dict:
    token = os.getenv("MADGRADES_API_TOKEN")
    if not token:
        raise RuntimeError(
            "MADGRADES_API_TOKEN not set. Copy .env_example to .env and fill it in."
        )
    return {"Authorization": f"Token token={token}"}


# Cache subject abbreviation → subject code to avoid redundant lookups
_subject_code_cache: Dict[str, Optional[str]] = {}


def _get_subject_code(abbreviation: str) -> Optional[str]:
    """Return the numeric subject code for a given abbreviation (e.g. 'ECON' → '296')."""
    abbr_lower = abbreviation.strip().lower()
    if abbr_lower in _subject_code_cache:
        return _subject_code_cache[abbr_lower]

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

    _subject_code_cache[abbr_lower] = code
    return code


def _find_course_uuid(catalog_number: str) -> Optional[str]:
    """Resolve a catalog number like 'ECON 101' to a Madgrades course UUID.

    Strategy:
      1. Split into subject abbreviation + course number.
      2. Look up the numeric subject code.
      3. Query /courses with subject code and number.
      4. Return the UUID of the first result.
    """
    parts = catalog_number.strip().rsplit(" ", 1)
    if len(parts) != 2:
        return None
    subject_abbr, number = parts

    subject_code = _get_subject_code(subject_abbr)
    if not subject_code:
        return None

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


def _compute_average_gpa(course_uuid: str) -> Optional[float]:
    """Compute the cumulative weighted GPA for a course using its UUID.

    The /courses/{id}/grades endpoint returns a top-level ``cumulative``
    object with camelCase grade counts (aCount, abCount, …).
    """
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


def rank_courses_by_gpa(
    course_list_path: str,
) -> List[Dict]:
    """Read a course_list.json-style file, query Madgrades for each course's
    average GPA, and return a list of dicts sorted from highest GPA to lowest.

    Each dict has the shape:
        {
            "catalog_number": "ECON 101",
            "course_title":   "Principles of Microeconomics",
            "gpa":            3.456   # or null if data unavailable
        }

    Courses with no GPA data are appended at the end (in their original order).
    """
    path = Path(course_list_path).expanduser().resolve()
    with open(path, "r", encoding="utf-8") as f:
        courses = json.load(f)

    scored: List[Tuple[str, str, Optional[float]]] = []
    for course in courses:
        catalog_number = course.get("catalog_number", "").strip()
        course_title = course.get("course_title", "").strip()
        try:
            uuid = _find_course_uuid(catalog_number)
            gpa = _compute_average_gpa(uuid) if uuid else None
        except requests.RequestException:
            gpa = None
        scored.append((catalog_number, course_title, gpa))
        time.sleep(0.1)

    # Sort: highest GPA first; courses without GPA go to the end
    scored.sort(key=lambda x: (x[2] is None, -(x[2] or 0.0)))

    return [
        {
            "catalog_number": cat,
            "course_title": title,
            "gpa": gpa,
        }
        for cat, title, gpa in scored
    ]


def save_ranked_courses(ranked: List[Dict], output_name: str) -> str:
    """Save the ranked course list to a local JSON file. Returns the
    absolute path to the file that was written.
    """
    out_path = Path(output_name).expanduser().resolve()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ranked, f, indent=2, ensure_ascii=False)
    return str(out_path)
