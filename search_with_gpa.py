"""
Bridge between CourseSearchClient (enroll.wisc.edu) and GPA Ranker (Madgrades).

Two modes:
  - enrich_hits_with_gpa(hits)           : in-place, adds 'gpa' field, no sort
  - rank_hits_by_gpa(hits, ignore_null)  : returns {ranked, no_data, warnings}
  - search_ranked_by_gpa(client, ...)    : search + rank in one call

Null handling: courses without Madgrades data are NOT pushed to the end.
They are returned in a separate `no_data` bucket with a warning so the
caller can display them explicitly or hide them via ignore_null=True.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from course_search import CourseSearchClient, SearchFilters
from gpa_ranker import get_gpa, save_gpa_cache


def _hit_catalog_number(hit: dict) -> str:
    return f"{hit['subject']['shortDescription']} {hit['catalogNumber']}"


def enrich_hits_with_gpa(hits: list[dict], max_workers: int = 5) -> list[dict]:
    """Attach 'gpa' (float | None) to each hit. Mutates in place, returns list."""
    def _lookup(hit: dict) -> None:
        try:
            hit["gpa"] = get_gpa(_hit_catalog_number(hit))
        except Exception:
            hit["gpa"] = None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_lookup, hits))
    return hits


def rank_hits_by_gpa(
    hits: list[dict],
    ignore_null: bool = False,
    max_workers: int = 5,
) -> dict:
    """Enrich + split + sort.

    Returns:
      {
        "ranked":   [hits with gpa, sorted high -> low],
        "no_data":  [hits without gpa]  (empty if ignore_null),
        "warnings": [str, ...],
        "total":    int,
      }
    """
    enrich_hits_with_gpa(hits, max_workers=max_workers)

    ranked = [h for h in hits if h.get("gpa") is not None]
    no_data = [h for h in hits if h.get("gpa") is None]
    ranked.sort(key=lambda h: -h["gpa"])

    warnings: list[str] = []
    if no_data and not ignore_null:
        warnings.append(
            f"{len(no_data)} course(s) have no Madgrades GPA data "
            f"(listed separately; pass ignore_null=True to suppress)"
        )

    return {
        "ranked": ranked,
        "no_data": [] if ignore_null else no_data,
        "warnings": warnings,
        "total": len(hits),
    }


def search_ranked_by_gpa(
    client: CourseSearchClient,
    filters: Optional[SearchFilters] = None,
    ignore_null: bool = False,
    paginate_all: bool = False,
    max_pages: int = 10,
    max_workers: int = 5,
    **kwargs,
) -> dict:
    """Search UW course API and rank results by GPA.

    paginate_all=False (default): single page (50 hits) — fast for UI.
    paginate_all=True:            walk up to max_pages pages via search_all.
    """
    if filters is None:
        filters = SearchFilters(**kwargs)

    if paginate_all:
        hits = client.search_all(filters, max_pages=max_pages)
        found = len(hits)
    else:
        result = client.search(filters)
        hits = result.get("hits", [])
        found = result.get("found", len(hits))

    ranked = rank_hits_by_gpa(hits, ignore_null=ignore_null, max_workers=max_workers)
    ranked["found"] = found
    return ranked


if __name__ == "__main__":
    client = CourseSearchClient()
    result = search_ranked_by_gpa(
        client,
        term="1264",
        keywords="calculus",
        ignore_null=False,
    )

    print(f"Total matched: {result['found']}   (sample page: {result['total']} hits)")

    for w in result["warnings"]:
        print(f"  [warning] {w}")

    print("\n=== Ranked by GPA ===")
    for hit in result["ranked"][:10]:
        short = hit["subject"]["shortDescription"]
        print(f"  {short:10s} {hit['catalogNumber']:6s}  GPA={hit['gpa']:.4f}  {hit['title']}")

    if result["no_data"]:
        print("\n=== No Madgrades data ===")
        for hit in result["no_data"]:
            short = hit["subject"]["shortDescription"]
            print(f"  {short:10s} {hit['catalogNumber']:6s}  {hit['title']}")

    save_gpa_cache()
