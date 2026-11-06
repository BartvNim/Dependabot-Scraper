import requests
import time
import csv
import os
import json
import re
from datetime import datetime, timezone

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise SystemExit("Set the GITHUB_TOKEN environment variable before running this script.")
url = "https://api.github.com/graphql"

query = """
query ($cursor: String, $searchQuery: String!) {
  search(
    query: $searchQuery
    type: ISSUE
    first: 50
    after: $cursor
  ) {
    issueCount
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on PullRequest {
        id
        number
        title
        body
        url
        createdAt
        state
        merged
        mergedAt
        headRefName
        repository {
          nameWithOwner
        }
      }
    }
  }
  rateLimit {
    limit
    remaining
    used
    resetAt
  }
}
"""

headers = {
  "Authorization": f"Bearer {GITHUB_TOKEN}",
  "Content-Type": "application/json",
}

REPOS_CSV = "repos_with_merged_pr.csv"
OUT_DIR = "revert_search"

MANIFEST_CSV = "revert_search_manifest.csv"

# GitHub's "Revert" button always creates a branch named revert-<N>-<original-branch>,
# where N is the reverted PR's number — the most reliable signal available.
BRANCH_REVERT_PATTERN = re.compile(r"^revert-(\d+)-", re.IGNORECASE)
# For a non-squash merge, the auto-generated body also says "Reverts owner/repo#N".
BODY_REVERT_PATTERN = re.compile(r"Reverts\s+[\w.\-]+/[\w.\-]+#(\d+)", re.IGNORECASE)
# For a squash merge, the body instead references the squash commit sha, not a PR number.
COMMIT_ONLY_PATTERN = re.compile(r"This reverts commit\s+[0-9a-f]{7,40}", re.IGNORECASE)


def post_with_retries(url, json_data, retries=5):
    for i in range(retries):
        try:
            response = requests.post(
                url,
                json=json_data,
                headers=headers,
                timeout=50
            )
            if response.status_code == 502:
                sleep_time = 5 if i == 0 else 30 * (i)  # 30s, 60s, 90s... instead of 1,2,4
                print(f"502 received, waiting {sleep_time}s before retry {i+1}/{retries}")
                time.sleep(sleep_time)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if i == retries - 1:
                raise
            sleep_time = 2 ** i
            time.sleep(sleep_time)


def load_repos_with_merged_pr(path):
    """repo -> set of merged PR numbers, so a hit can be checked against a known bump."""
    known = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numbers = row["merged_pr_numbers"]
            known[row["repo"]] = {int(n) for n in numbers.split(";") if n}
    return known


def fetch_repo_reverts(repo):
    search_query = f"repo:{repo} revert created:>=2025-01-01 is:pr"
    cursor = None
    results = []
    issue_count = None

    while True:
        variables = {
            "searchQuery": search_query,
            "cursor": cursor,
        }
        data = post_with_retries(url, {
            "query": query,
            "variables": variables
        })
        search_data = data["data"]["search"]
        rate_limit = data["data"]["rateLimit"]

        if issue_count is None:
            issue_count = search_data["issueCount"]

        # Continue automatically if rate limit is reset
        if rate_limit["remaining"] < 150:
            reset_time = datetime.fromisoformat(
                rate_limit["resetAt"].replace("Z", "+00:00")
            )
            now_utc = datetime.now(timezone.utc)
            sleep_seconds = (reset_time - now_utc).total_seconds()

            if sleep_seconds > 0:
                print(f"Waiting for rate limit to reset at {reset_time}")
                time.sleep(sleep_seconds + 5)

        results.extend(search_data["nodes"])

        if not search_data["pageInfo"]["hasNextPage"]:
            break

        cursor = search_data["pageInfo"]["endCursor"]

    return results, issue_count


def classify(pr, known_pr_numbers):
    body = pr.get("body") or ""
    branch = pr.get("headRefName") or ""

    reverted_number = None
    source = None

    m = BRANCH_REVERT_PATTERN.match(branch)
    if m:
        reverted_number = int(m.group(1))
        source = "branch"
    else:
        m = BODY_REVERT_PATTERN.search(body)
        if m:
            reverted_number = int(m.group(1))
            source = "body"
        elif COMMIT_ONLY_PATTERN.search(body):
            source = "commit_only"

    pr["reverted_pr_number"] = reverted_number
    pr["reverted_number_source"] = source
    pr["matches_known_bump"] = reverted_number in known_pr_numbers if reverted_number else False
    return pr


def scrape_repo(repo, known_pr_numbers, file_path):
    failures = 0
    while failures < 5:
        try:
            prs, issue_count = fetch_repo_reverts(repo)
            prs = [classify(pr, known_pr_numbers) for pr in prs]
            save_repo_file(file_path, prs)
            log_manifest(repo, issue_count, len(prs), "ok")
            return True
        except Exception as e:
            failures += 1
            print(f"[{repo}] failure {failures}/5: {e}")
            time.sleep(5 * failures)

    log_manifest(repo, None, 0, "failed")
    return False


def log_manifest(repo, issue_count, item_count, status):
    write_header = not os.path.exists(MANIFEST_CSV)
    with open(MANIFEST_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["repo", "issue_count", "item_count", "status"])
        writer.writerow([repo, issue_count, item_count, status])


def fetch_revert_prs():
    known_by_repo = load_repos_with_merged_pr(REPOS_CSV)
    repos = sorted(known_by_repo.keys())

    retry_queue = []

    for i, repo in enumerate(repos, 1):
        safe_name = repo.replace("/", "__")
        file_path = os.path.join(OUT_DIR, f"{safe_name}.json")

        if not os.path.exists(file_path):
            print(f"[{i}/{len(repos)}] {repo}")
            success = scrape_repo(repo, known_by_repo[repo], file_path)
            if not success:
                print(f"[{repo}] queued for retry")
                retry_queue.append(repo)

    retry_round = 1
    while retry_queue:
        print(f"\n--- Retry round {retry_round}: {len(retry_queue)} repo(s) remaining ---")
        time.sleep(60 * retry_round)
        still_failing = []
        for repo in retry_queue:
            safe_name = repo.replace("/", "__")
            file_path = os.path.join(OUT_DIR, f"{safe_name}.json")
            if os.path.exists(file_path):
                continue
            success = scrape_repo(repo, known_by_repo[repo], file_path)
            if not success:
                still_failing.append(repo)
        retry_queue = still_failing
        retry_round += 1


def save_repo_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"Saved {len(data)} pr(s) at {path}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    fetch_revert_prs()
