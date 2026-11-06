import csv

PRS_CSV = "converted_prs/prs.csv"
OUT_CSV = "repos_with_merged_pr.csv"


def main():
    merged_pr_numbers = {}
    with open(PRS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["is_merged"] == "True":
                merged_pr_numbers.setdefault(row["repo"], set()).add(row["pr_number"])

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["repo", "merged_pr_numbers"])
        for repo in sorted(merged_pr_numbers):
            numbers = ";".join(sorted(merged_pr_numbers[repo], key=int))
            writer.writerow([repo, numbers])

    print(f"Wrote {len(merged_pr_numbers)} repos to {OUT_CSV}")


if __name__ == "__main__":
    main()
