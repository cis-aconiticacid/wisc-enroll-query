"""
UW-Madison Course Search API Client
====================================
Reverse-engineered from public.enroll.wisc.edu frontend JS chunks.

Usage:
    from uw_course_search import CourseSearchClient

    client = CourseSearchClient()
    results = client.search(term="1264", keywords="calculus", level=["advanced"])
    for course in results["hits"]:
        print(course)
"""

import json
import os
import requests
from typing import Optional, Literal
from dataclasses import dataclass, field

BASE_URL = "https://public.enroll.wisc.edu"
PAGE_SIZE = 50

# ─────────────────────────────────────────────
# Load aggregate data from local file (编码参考表)
# ─────────────────────────────────────────────
_AGGREGATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aggreate.json")

with open(_AGGREGATE_PATH, "r", encoding="utf-8") as _f:
    AGGREGATE_DATA = json.load(_f)

# { termCode: longDescription }  e.g. {"1264": "Spring 2025-2026"}
KNOWN_TERMS = {
    t["termCode"]: t["longDescription"] for t in AGGREGATE_DATA["terms"]
}

# { termCode: [session_dict, ...] }
SESSIONS_BY_TERM = {
    entry["termCode"]: entry["sessions"] for entry in AGGREGATE_DATA["sessions"]
}

# { termCode: { subjectCode: formalDescription } }
# e.g. {"1264": {"416": "GEOGRAPHY", ...}, "0000": {...}}
SUBJECTS_BY_TERM = {
    term_code: {s["subjectCode"]: s["formalDescription"] for s in subjects}
    for term_code, subjects in AGGREGATE_DATA["subjects"].items()
}

# specialGroups — 按 term 顺序排列的 list of list
SPECIAL_GROUPS = AGGREGATE_DATA["specialGroups"]

# ─────────────────────────────────────────────
# Filter value mappings (from JS source)
# ─────────────────────────────────────────────

# Breadth codes
BREADTH_MAP = {
    "biologicalSciences": "B",
    "humanities": "H",
    "literature": "L",
    "naturalSciences": "N",
    "physicalSciences": "P",
    "socialSciences": "S",
}

# General Education codes
GEN_ED_MAP = {
    "commA": "COM A",
    "commB": "COM B",
    "quantA": "QR-A",
    "quantB": "QR-B",
}

# Level codes
LEVEL_MAP = {
    "elementary": "E",
    "intermediate": "I",
    "advanced": "A",
}

# Foreign language codes
LANGUAGE_MAP = {
    "first": "FL1",
    "second": "FL2",
    "third": "FL3",
    "fourth": "FL4",
    "fifth": "FL5",
}

# Honors section types
HONORS_MAP = {
    "honorsOnly": "HONORS_ONLY",
    "acceleratedHonors": "HONORS_LEVEL",
    "honorsOptional": "INSTRUCTOR_APPROVED",
}

# Mode of instruction → Elasticsearch bool queries
MODE_OF_INSTRUCTION_QUERIES = {
    "all": None,
    "classroom": {
        "must": [{"match": {"modesOfInstruction": "Instruction"}}],
        "must_not": [
            {"match": {"modesOfInstruction": "some"}},
            {"match": {"modesOfInstruction": "Only"}},
            {"match": {"modesOfInstruction": "EMPTY"}},
        ],
    },
    "hybrid": {
        "must": [{"match": {"modesOfInstruction": "some"}}],
        "must_not": [
            {"match": {"modesOfInstruction": "Instruction"}},
            {"match": {"modesOfInstruction": "Only"}},
            {"match": {"modesOfInstruction": "EMPTY"}},
        ],
    },
    "async": {
        "must": [
            {"match": {"modesOfInstruction": "Only"}},
            {"match": {"isAsynchronous": True}},
        ],
        "must_not": [
            {"match": {"modesOfInstruction": "Instruction"}},
            {"match": {"modesOfInstruction": "some"}},
            {"match": {"isAsynchronous": False}},
            {"match": {"modesOfInstruction": "EMPTY"}},
        ],
    },
    "sync": {
        "must": [
            {"match": {"modesOfInstruction": "Only"}},
            {"match": {"isAsynchronous": False}},
        ],
        "must_not": [
            {"match": {"modesOfInstruction": "Instruction"}},
            {"match": {"modesOfInstruction": "some"}},
            {"match": {"isAsynchronous": True}},
            {"match": {"modesOfInstruction": "EMPTY"}},
        ],
    },
    "either": {
        "must": [{"match": {"modesOfInstruction": "Only"}}],
        "must_not": [
            {"match": {"modesOfInstruction": "Instruction"}},
            {"match": {"modesOfInstruction": "some"}},
            {"match": {"modesOfInstruction": "EMPTY"}},
        ],
    },
}

# Sort order
SORT_ORDER_MAP = {
    "relevance": "SCORE",
    "subject": "SUBJECT",
    "catalog-number": "CATALOG_NUMBER",
}


@dataclass
class SearchFilters:
    """
    All possible search filters, matching the frontend form state.
    Set a field to enable that filter; leave as default to skip it.
    """

    # ── Core ──
    term: Optional[str] = None          # e.g. "1264" for Spring 2026
    subject: Optional[str] = None       # e.g. "MATH", "COMP SCI"
    keywords: Optional[str] = None      # free text, default "*"

    # ── Seats (only effective when term is set) ──
    open: bool = False
    waitlisted: bool = False
    closed: bool = False

    # ── Breadth ──
    biologicalSciences: bool = False
    humanities: bool = False
    literature: bool = False
    naturalSciences: bool = False
    physicalSciences: bool = False
    socialSciences: bool = False

    # ── General Education ──
    commA: bool = False
    commB: bool = False
    quantA: bool = False
    quantB: bool = False
    ethnicStudies: bool = False

    # ── Level ──
    elementary: bool = False
    intermediate: bool = False
    advanced: bool = False

    # ── Mode of Instruction ──
    modeOfInstruction: Literal[
        "all", "classroom", "hybrid", "async", "sync", "either"
    ] = "all"

    # ── Credits ──
    creditsMin: Optional[int] = None
    creditsMax: Optional[int] = None

    # ── Honors ──
    honorsOnly: bool = False
    acceleratedHonors: bool = False
    honorsOptional: bool = False

    # ── Foreign Language ──
    language: Literal[
        "all", "first", "second", "third", "fourth", "fifth"
    ] = "all"

    # ── Session (list of session codes, e.g. ["YBB", "YCC"]) ──
    sessions: list[str] = field(default_factory=list)

    # ── Reserved Sections ──
    # "all"  = include all (default, no filter)
    # "none" = exclude reserved sections
    # {"attr": "RESH", "code": "BIO"} = specific reserved section
    # {"attr": "RESH", "code": None}  = all of that attribute type
    reservedSections: str | dict = "all"

    # ── Course Attributes ──
    graduateCourseworkRequirement: bool = False
    workplaceExperience: bool = False
    communityBasedLearning: bool = False
    repeatableForCredit: bool = False

    # ── Hidden filters (used by URL params, not visible in UI) ──
    courseId: Optional[str] = None
    topicId: Optional[str] = None
    catalogNumMin: Optional[str] = None
    catalogNumMax: Optional[str] = None

    # ── Sort ──
    orderBy: Literal["relevance", "subject", "catalog-number"] = "relevance"


def build_query(filters: SearchFilters, page: int = 1) -> dict:
    """
    Build the search API request body from filters.
    Mirrors the `be` function in chunk-PJYL2HPO.js.
    """
    es_filters = []

    has_term = filters.term is not None

    # ── 1. Seats (Sr) ──
    if has_term:
        statuses = []
        if filters.open:
            statuses.append("OPEN")
        if filters.waitlisted:
            statuses.append("WAITLISTED")
        if filters.closed:
            statuses.append("CLOSED")
        if statuses:
            es_filters.append({
                "has_child": {
                    "type": "enrollmentPackage",
                    "query": {
                        "match": {
                            "packageEnrollmentStatus.status": " ".join(statuses)
                        }
                    },
                }
            })

    # ── 2. Subject (br) ──
    if filters.subject:
        es_filters.append({"term": {"subject.subjectCode": filters.subject}})

    # ── 3. General Education (Tr) ──
    gen_ed_should = []
    gen_ed_codes = []
    for key, code in GEN_ED_MAP.items():
        if getattr(filters, key):
            gen_ed_codes.append(code)
    if gen_ed_codes:
        gen_ed_should.append({"terms": {"generalEd.code": [gen_ed_codes]}})
    if filters.ethnicStudies:
        gen_ed_should.append({"term": {"ethnicStudies.code": "ETHNIC ST"}})
    if filters.commB:
        gen_ed_should.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": {"match": {"sections.comB": True}},
            }
        })
    if gen_ed_should:
        es_filters.append({"bool": {"should": gen_ed_should}})

    # ── 4. Breadth (Ir) ──
    breadth_codes = [
        code for key, code in BREADTH_MAP.items() if getattr(filters, key)
    ]
    if breadth_codes:
        es_filters.append({"terms": {"breadths.code": breadth_codes}})

    # ── 5. Level (Or) ──
    level_codes = [
        code for key, code in LEVEL_MAP.items() if getattr(filters, key)
    ]
    if level_codes:
        es_filters.append({"terms": {"levels.code": level_codes}})

    # ── 6. Foreign Language (Er) ──
    if filters.language != "all":
        fl_code = LANGUAGE_MAP.get(filters.language)
        if fl_code:
            es_filters.append({
                "query": {"match": {"foreignLanguage.code": fl_code}}
            })

    # ── 7. Honors ($r) ──
    honors_queries = []
    for key, honor_type in HONORS_MAP.items():
        if getattr(filters, key):
            honors_queries.append([{"match": {"sections.honors": honor_type}}])
    if len(honors_queries) > 1:
        es_filters.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": {"bool": {"should": honors_queries}},
            }
        })
    elif len(honors_queries) == 1:
        es_filters.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": honors_queries[0],
            }
        })

    # ── 8. Reserved Sections (wr) ──
    if has_term and filters.reservedSections != "all":
        if filters.reservedSections == "none":
            es_filters.append({
                "has_child": {
                    "type": "enrollmentPackage",
                    "query": {
                        "bool": {
                            "should": [
                                {"bool": {"must_not": [{"exists": {"field": "sections.classAttributes"}}]}},
                                {"match": {"sections.classAttributes.attributeCode": "TEXT SVCL"}},
                            ]
                        }
                    },
                }
            })
        elif isinstance(filters.reservedSections, dict):
            attr = filters.reservedSections.get("attr")
            code = filters.reservedSections.get("code")
            if code is not None:
                q = {"match": {"sections.classAttributes.valueCode": code}}
            else:
                q = {"match": {"sections.classAttributes.attributeCode": attr}}
            es_filters.append({
                "has_child": {"type": "enrollmentPackage", "query": q}
            })

    # ── 9. Mode of Instruction (Cr) ──
    mode_query = MODE_OF_INSTRUCTION_QUERIES.get(filters.modeOfInstruction)
    if mode_query is not None:
        es_filters.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": {"bool": mode_query},
            }
        })

    # ── 10. Course Attributes (Fr, Ar, xr, _r) ──
    if filters.graduateCourseworkRequirement:
        es_filters.append({"term": {"gradCourseWork": True}})
    if filters.workplaceExperience:
        es_filters.append({"query": {"exists": {"field": "workplaceExperience"}}})
    if filters.communityBasedLearning:
        es_filters.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": {
                    "bool": {
                        "must": [{"match": {"sections.classAttributes.valueCode": "25 PLUS"}}]
                    }
                },
            }
        })
    if filters.repeatableForCredit:
        es_filters.append({"match": {"repeatable": "Y"}})

    # ── 11. Credits (kr, qr) ──
    if filters.creditsMin is not None:
        es_filters.append({"range": {"minimumCredits": {"gte": filters.creditsMin}}})
    if filters.creditsMax is not None:
        es_filters.append({"range": {"maximumCredits": {"lte": filters.creditsMax}}})

    # ── 12. Sessions (zr) ──
    if filters.sessions:
        session_matches = [
            {"match": {"sections.sessionCode": code}} for code in filters.sessions
        ]
        if len(session_matches) > 1:
            es_filters.append({
                "has_child": {
                    "type": "enrollmentPackage",
                    "query": {"bool": {"should": session_matches}},
                }
            })
        else:
            es_filters.append({
                "has_child": {
                    "type": "enrollmentPackage",
                    "query": session_matches[0],
                }
            })

    # ── 13. Course ID (Pr) ──
    if filters.courseId is not None:
        es_filters.append({"term": {"courseId": filters.courseId}})

    # ── 14. Catalog Number (Lr) ──
    cat_min = filters.catalogNumMin
    cat_max = filters.catalogNumMax
    if cat_min is not None and cat_max is not None:
        if cat_min == cat_max:
            es_filters.append({"term": {"catalogNumber": cat_min}})
        else:
            es_filters.append({
                "range": {
                    "catalogSort": {
                        "gte": cat_min.zfill(5),
                        "lte": cat_max.zfill(5),
                    }
                }
            })
    elif cat_min is not None:
        es_filters.append({"range": {"catalogSort": {"gte": cat_min.zfill(5)}}})
    elif cat_max is not None:
        es_filters.append({"range": {"catalogSort": {"lte": cat_max.zfill(5)}}})

    # ── 15. Topic ID (Rr) ──
    if filters.topicId is not None:
        es_filters.append({"term": {"topics.id": filters.topicId}})

    # ── 16. Published filter (jr) — only when term is set ──
    if has_term:
        es_filters.append({
            "has_child": {
                "type": "enrollmentPackage",
                "query": {"match": {"published": True}},
            }
        })

    # ── 17. Merge has_child filters (vr) ──
    es_filters = _merge_has_child_filters(es_filters)

    # ── Build final request body ──
    selected_term = filters.term if filters.term else "0000"
    query_string = (filters.keywords or "").strip() or "*"
    sort_order = SORT_ORDER_MAP.get(filters.orderBy, "SCORE")

    return {
        "selectedTerm": selected_term,
        "queryString": query_string,
        "filters": es_filters,
        "page": page,
        "pageSize": PAGE_SIZE,
        "sortOrder": sort_order,
    }


def _merge_has_child_filters(filters: list) -> list:
    """
    Merge multiple has_child(enrollmentPackage) filters into a single
    bool.must query. Mirrors the `vr` function.
    """
    non_child = []
    child_queries = []

    for f in filters:
        if (
            isinstance(f, dict)
            and "has_child" in f
            and isinstance(f["has_child"], dict)
            and f["has_child"].get("type") == "enrollmentPackage"
            and "query" in f["has_child"]
        ):
            child_queries.append(f["has_child"]["query"])
        else:
            non_child.append(f)

    if len(child_queries) > 1:
        return non_child + [{
            "has_child": {
                "type": "enrollmentPackage",
                "query": {"bool": {"must": child_queries}},
            }
        }]
    elif len(child_queries) == 1:
        return non_child + [{
            "has_child": {
                "type": "enrollmentPackage",
                "query": child_queries[0],
            }
        }]
    else:
        return filters


"""
Confirmed API response structure (from DevTools):

POST /api/search/v1 response:
{
  "found": int,           # total number of matching courses
  "hits": [CourseHit],    # array of course objects (pageSize per page)
  "message": str | null,
  "success": bool
}

CourseHit fields (45 total):
  termCode, courseId, subject, catalogNumber, approvedForTopics, topics,
  minimumCredits, maximumCredits, creditRange, firstTaught, lastTaught,
  typicallyOffered, coreGeneralEducation, generalEd, ethnicStudies,
  breadths, lettersAndScienceCredits, workplaceExperience, foreignLanguage,
  honors, levels, openToFirstYear, advisoryPrerequisites,
  enrollmentPrerequisites, allCrossListedSubjects, title, description,
  catalogPrintFlag, academicGroupCode, currentlyTaught, gradingBasis,
  repeatable, gradCourseWork, sustainability, instructorProvidedContent,
  courseRequirements, courseDesignation, courseDesignationRaw,
  fullCourseDesignation, fullCourseDesignationRaw, lastUpdated,
  catalogSort, subjectAggregate, titleSuggest, matched_queries

CourseHit.subject structure:
{
  "termCode": "1264",
  "subjectCode": "112",              # ← 数字 code，用于 API URL
  "description": "BIOLOGICAL SYSTEMS ENGINEERING",
  "shortDescription": "BSE",         # ← 字母缩写，UI 上显示的
  "formalDescription": "...",
  "undergraduateCatalogURI": "...",
  "graduateCatalogURI": "...",
  "departmentURI": "...",
  "schoolCollege": { ... },
  "footnotes": [...],
  "departmentOwnerAcademicOrgCode": "..."
}

Key: subject filter 用的是 shortDescription (如 "MATH", "COMP SCI")
     但 API URL 里用的是 subjectCode (数字，如 "207", "112")
"""


class CourseSearchClient:
    """
    Client for UW-Madison's course search API.

    API endpoints (all confirmed via DevTools):
      POST /api/search/v1
           — main course search
      GET  /api/search/v1/subjectsMap/{termCode}
           — get subjects for a term ("0000" = all terms)
      GET  /api/search/v1/aggregate
           — get terms, sessions, specialGroups, subjects
      GET  /api/search/v1/enrollmentPackages/{termCode}/{subjectCode}/{courseId}
           — get sections/packages for a specific course
           — subjectCode is NUMERIC (e.g. "207"), not abbreviation
      GET  /api/search/v1/details/{termCode}/{subjectCode}/{courseId}
           — get course details (triggered by clicking a course)
    """

    # Default headers that mimic a browser (required to avoid 403)
    DEFAULT_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, base_url: str = BASE_URL, headers: Optional[dict] = None):
        self.base_url = base_url
        self.session = requests.Session()
        # Start with defaults, then layer on Referer/Origin, then user overrides
        merged = {**self.DEFAULT_HEADERS, "Referer": f"{base_url}/search", "Origin": base_url}
        if headers:
            merged.update(headers)
        self.session.headers.update(merged)
        self._subject_cache: dict[str, dict] = {}  # shortDesc -> subject obj

    # ── Main search ──

    def search(
        self,
        filters: Optional[SearchFilters] = None,
        page: int = 1,
        **kwargs,
    ) -> dict:
        """
        Search for courses.

        Returns: {"found": int, "hits": [CourseHit], "message": ..., "success": bool}

        Can pass a SearchFilters object, or keyword args:
            client.search(term="1264", keywords="calculus")

        Note: `subject` in SearchFilters is the shortDescription (e.g. "MATH").
              It gets looked up to the numeric subjectCode for the ES query.
        """
        if filters is None:
            filters = SearchFilters(**kwargs)

        # Resolve subject abbreviation → numeric code if needed
        if filters.subject and not filters.subject.isdigit():
            resolved = self._resolve_subject_code(
                filters.subject, filters.term or "0000"
            )
            if resolved:
                filters = SearchFilters(
                    **{**filters.__dict__, "subject": resolved}
                )

        body = build_query(filters, page)
        resp = self.session.post(
            f"{self.base_url}/api/search/v1",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    def search_all(
        self,
        filters: Optional[SearchFilters] = None,
        max_pages: int = 100,
        **kwargs,
    ) -> list[dict]:
        """
        Search and paginate through all results.
        Returns a flat list of all CourseHit dicts.
        """
        if filters is None:
            filters = SearchFilters(**kwargs)
        all_hits = []
        for page_num in range(1, max_pages + 1):
            result = self.search(filters, page=page_num)
            hits = result.get("hits", [])
            all_hits.extend(hits)
            total = result.get("found", 0)
            if len(all_hits) >= total or not hits:
                break
        return all_hits

    # ── Reference data ──

    def get_subjects(self, term_code: str = "0000") -> dict:
        """Get all subjects for a term. Use "0000" for all terms."""
        resp = self.session.get(
            f"{self.base_url}/api/search/v1/subjectsMap/{term_code}"
        )
        resp.raise_for_status()
        return resp.json()

    def get_aggregate(self) -> dict:
        """Get terms, sessions, specialGroups, subjects (from local aggreate.json)."""
        return AGGREGATE_DATA

    # ── Course details ──

    def get_details(self, term_code: str, subject_code: str, course_id: str) -> dict:
        """
        Get detailed info for a specific course.
        subject_code is NUMERIC (e.g. "207"), from hit["subject"]["subjectCode"].
        """
        resp = self.session.get(
            f"{self.base_url}/api/search/v1/details/{term_code}/{subject_code}/{course_id}"
        )
        resp.raise_for_status()
        return resp.json()

    def get_enrollment_packages(
        self, term_code: str, subject_code: str, course_id: str
    ) -> list:
        """
        Get sections/enrollment packages for a specific course.
        subject_code is NUMERIC (e.g. "207"), from hit["subject"]["subjectCode"].
        """
        resp = self.session.get(
            f"{self.base_url}/api/search/v1/enrollmentPackages/{term_code}/{subject_code}/{course_id}"
        )
        resp.raise_for_status()
        return resp.json()

    # ── Convenience: from a search hit ──

    def get_details_for_hit(self, hit: dict) -> dict:
        """Get details for a course directly from a search result hit."""
        return self.get_details(
            hit["termCode"],
            hit["subject"]["subjectCode"],
            hit["courseId"],
        )

    def get_packages_for_hit(self, hit: dict) -> list:
        """Get enrollment packages for a course directly from a search result hit."""
        return self.get_enrollment_packages(
            hit["termCode"],
            hit["subject"]["subjectCode"],
            hit["courseId"],
        )

    # ── Internal helpers ──

    def _resolve_subject_code(self, abbreviation: str, term_code: str) -> Optional[str]:
        """
        Resolve a subject abbreviation (e.g. "MATH", "COMP SCI") to its
        numeric subjectCode (e.g. "600", "266") by looking up the subjects map.

        Note: the search API `subject.subjectCode` filter actually uses the
        numeric code, but users think in abbreviations. This bridges the gap.
        However, looking at the JS source more carefully, the filter actually
        uses `subject.subjectCode` which stores the NUMERIC code in ES.
        So we need this lookup.
        """
        cache_key = f"{term_code}:{abbreviation.upper()}"
        if cache_key in self._subject_cache:
            return self._subject_cache[cache_key]

        try:
            subjects = self.get_subjects(term_code)
            # subjectsMap returns a dict or list — need to find by shortDescription
            if isinstance(subjects, dict):
                for code, info in subjects.items():
                    short = info.get("shortDescription", "").upper()
                    if short == abbreviation.upper():
                        self._subject_cache[cache_key] = code
                        return code
            elif isinstance(subjects, list):
                for info in subjects:
                    short = info.get("shortDescription", "").upper()
                    code = info.get("subjectCode") or info.get("code")
                    if short == abbreviation.upper() and code:
                        self._subject_cache[cache_key] = code
                        return code
        except Exception:
            pass
        return None


# ─────────────────────────────────────────────
# URL query params ↔ filters (for building search URLs)
# ─────────────────────────────────────────────

def filters_to_url_params(filters: SearchFilters, include_defaults: bool = False) -> dict:
    """
    Convert SearchFilters to URL query parameters matching
    public.enroll.wisc.edu/search?... format.
    """
    params = {}

    if filters.term:
        params["term"] = filters.term
    if filters.subject:
        params["subject"] = filters.subject
    if filters.keywords:
        params["keywords"] = filters.keywords

    bool_fields = [
        "open", "waitlisted", "closed",
        "commA", "commB", "quantA", "quantB", "ethnicStudies",
        "biologicalSciences", "humanities", "literature",
        "naturalSciences", "physicalSciences", "socialSciences",
        "elementary", "intermediate", "advanced",
        "honorsOnly", "acceleratedHonors", "honorsOptional",
        "graduateCourseworkRequirement", "workplaceExperience",
        "communityBasedLearning", "repeatableForCredit",
    ]
    for f in bool_fields:
        val = getattr(filters, f)
        if val or include_defaults:
            params[f] = str(val).lower()

    if filters.modeOfInstruction != "all":
        params["modeOfInstruction"] = filters.modeOfInstruction
    if filters.language != "all":
        params["language"] = filters.language
    if filters.orderBy != "relevance":
        params["orderBy"] = filters.orderBy

    # Credits
    if filters.creditsMin is not None or filters.creditsMax is not None:
        min_s = str(filters.creditsMin) if filters.creditsMin is not None else ""
        max_s = str(filters.creditsMax) if filters.creditsMax is not None else ""
        params["credits"] = f"{min_s}-{max_s}"

    # Sessions
    if filters.sessions:
        params["sessions"] = ",".join(filters.sessions)

    # Reserved sections
    if filters.reservedSections == "none":
        params["reservedSections"] = "none"
    elif isinstance(filters.reservedSections, dict):
        attr = filters.reservedSections["attr"]
        code = filters.reservedSections.get("code")
        params["reservedSections"] = f"{attr}-{code}" if code else attr

    # Catalog number
    if filters.catalogNumMin or filters.catalogNumMax:
        min_c = filters.catalogNumMin or ""
        max_c = filters.catalogNumMax or ""
        if min_c == max_c and min_c:
            params["catalogNum"] = min_c
        else:
            params["catalogNum"] = f"{min_c}-{max_c}"

    if filters.courseId:
        params["courseId"] = filters.courseId
    if filters.topicId:
        params["topicId"] = filters.topicId

    return params


# ─────────────────────────────────────────────
# Quick demo
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json

    client = CourseSearchClient()

    # ──────────────────────────────────────
    # Example 1: Basic search
    # ──────────────────────────────────────
    print("=== Example 1: Search Spring 2026, all courses ===")
    result = client.search(term="1264")
    print(f"Found: {result['found']} courses")

    if result["hits"]:
        hit = result["hits"][0]
        short = hit["subject"]["shortDescription"]
        num_code = hit["subject"]["subjectCode"]
        print(f"First hit: {short} {hit['catalogNumber']} — {hit['title']}")
        print(f"  subject numeric code: {num_code}")
        print(f"  courseId: {hit['courseId']}")
        print(f"  credits: {hit['minimumCredits']}-{hit['maximumCredits']}")

    # ──────────────────────────────────────
    # Example 2: Filtered search
    # ──────────────────────────────────────
    print("\n=== Example 2: Advanced MATH courses, Spring 2026 ===")
    filters = SearchFilters(
        term="1264",
        keywords="analysis",
        advanced=True,
    )
    print(f"Request body:\n{json.dumps(build_query(filters), indent=2)}")

    result = client.search(filters)
    print(f"\nFound: {result['found']} courses")
    for hit in result["hits"][:5]:
        short = hit["subject"]["shortDescription"]
        print(f"  {short} {hit['catalogNumber']}: {hit['title']}")

    # ──────────────────────────────────────
    # Example 3: Get sections for a course
    # ──────────────────────────────────────
    if result["hits"]:
        hit = result["hits"][0]
        short = hit["subject"]["shortDescription"]
        print(f"\n=== Example 3: Sections for {short} {hit['catalogNumber']} ===")
        packages = client.get_packages_for_hit(hit)
        print(f"  {len(packages)} enrollment package(s)")

    # ──────────────────────────────────────
    # Example 4: URL params (for browser link)
    # ──────────────────────────────────────
    print("\n=== Example 4: Generate search URL ===")
    filters = SearchFilters(
        term="1264",
        open=True,
        advanced=True,
        modeOfInstruction="classroom",
    )
    params = filters_to_url_params(filters)
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    print(f"  https://public.enroll.wisc.edu/search?{qs}")
