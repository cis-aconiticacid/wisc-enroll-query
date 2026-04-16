from gpa_ranker import rank_courses_by_gpa, save_ranked_courses


def main() -> None:
    ranked = rank_courses_by_gpa("course_list.json")
    out_path = save_ranked_courses(ranked, "average_gpa_ranks.json")
    print(f"Wrote {len(ranked)} ranked courses to {out_path}\n")

    # Print top 10 and bottom 5 as a quick sanity check
    print("=== Top 10 by GPA ===")
    for item in ranked[:10]:
        gpa_str = f"{item['gpa']:.4f}" if item["gpa"] is not None else "null"
        print(f"  {item['catalog_number']:20s}  {item['course_title'][:45]:45s}  GPA={gpa_str}")

    print("\n=== Bottom 5 / No data ===")
    for item in ranked[-5:]:
        gpa_str = f"{item['gpa']:.4f}" if item["gpa"] is not None else "null"
        print(f"  {item['catalog_number']:20s}  {item['course_title'][:45]:45s}  GPA={gpa_str}")


if __name__ == "__main__":
    main()
