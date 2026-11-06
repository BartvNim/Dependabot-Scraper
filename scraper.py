import requests
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os
import json

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
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
        url
        createdAt
        repository {
          nameWithOwner
          stargazerCount
          isFork
          primaryLanguage {
            name
          }
          defaultBranchRef {
            target {
              ... on Commit {
                history(first: 1) {
                  totalCount
                }
              }  
            }
          }
        }
        author {
          login
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

def isValid(pr):
  repo = pr.get('repository', {})
  
  stars = repo.get('stargazerCount', 0)
  is_fork = repo.get('isFork', False)
  
  default_branch = repo.get('defaultBranchRef') or {}
  target = default_branch.get('target') or {}
  history = target.get('history') or {}
  total_commits = history.get('totalCount', 0)
  
  if stars > 10 and not is_fork and total_commits > 20:
      return True
  else:
      return False

def get_issue_count(search_query):
    data = post_with_retries(url, {
        "query": """
        query ($searchQuery: String!) {
          search(query: $searchQuery, type: ISSUE, first: 1) {
            issueCount
          }
          rateLimit {
            limit
            remaining
            used
            resetAt
          }
        }
        """,
        "variables": {
            "searchQuery": search_query
        }
    })

    return data["data"]["search"]["issueCount"]

def fetch(search_query):
    cursor = None
    results = []
    raw = []
    issue_count = None

    while True:
        variables = {
            "searchQuery": search_query,
            "cursor": cursor,
        }
        print('send post')
        data = post_with_retries(url, {
            "query": query,
            "variables": variables
        })
        search_data = data["data"]["search"]
        rate_limit = data["data"]["rateLimit"]
        print(f'recieved data {issue_count} + {search_query} + {rate_limit["remaining"]}')

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

        if issue_count is None:
            issue_count = search_data["issueCount"]

        # check if repository is allowed
        for pr in search_data["nodes"]:
            raw.append(pr)
            if isValid(pr):
                results.append(pr)

        if not search_data["pageInfo"]["hasNextPage"]:
            break

        cursor = search_data["pageInfo"]["endCursor"]

    return raw, results, issue_count

def fetch_range(start_time, end_time):
    def to_utc_iso(dt):
      return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    
    time_range = f"{to_utc_iso(start_time)}..{to_utc_iso(end_time)}"
    search_query = f"is:pr author:dependabot[bot] created:{time_range} language:JavaScript"

    issue_count = get_issue_count(search_query)

    print(
        f"{start_time} -> {end_time} | count={issue_count}"
    )

    if issue_count >= 500:
        delta = end_time - start_time

        if delta <= timedelta(minutes=1):
            return [], []

        mid = start_time + delta / 2

        raw_left, filt_left = fetch_range(start_time, mid)
        raw_right, filt_right = fetch_range(mid, end_time)

        return raw_left + raw_right, filt_left + filt_right
    
    raw, results, _ = fetch(search_query)
    return raw, results


def scrape_day(date_str, day_start, day_end):
    file_path = os.path.join("scraped_days", f"{date_str}.json")
    file_path_raw = os.path.join("scraped_days_raw", f"{date_str}.json")

    failures = 0
    while failures < 5:
        try:
            raw_prs, daily_prs = fetch_range(day_start, day_end)
            save_daily_file(file_path, daily_prs)
            save_daily_file(file_path_raw, raw_prs)
            return True
        except Exception as e:
            failures += 1
            print(f"[{date_str}] failure {failures}/5: {e}")
            time.sleep(5 * failures)

    return False


def fetch_dependabot_prs():
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 12, 31)

    retry_queue = []

    while start_date <= end_date:
        date_str = start_date.strftime("%Y-%m-%d")
        file_path = os.path.join("scraped_days", f"{date_str}.json")

        if not os.path.exists(file_path):
            day_start = start_date.replace(hour=0, minute=0, second=0)
            day_end = day_start + timedelta(days=1)
            success = scrape_day(date_str, day_start, day_end)
            if not success:
                print(f"[{date_str}] queued for retry")
                retry_queue.append((date_str, day_start, day_end))

        start_date += timedelta(days=1)

    retry_round = 1
    while retry_queue:
        print(f"\n--- Retry round {retry_round}: {len(retry_queue)} day(s) remaining ---")
        time.sleep(60 * retry_round)
        still_failing = []
        for date_str, day_start, day_end in retry_queue:
            file_path = os.path.join("scraped_days", f"{date_str}.json")
            if os.path.exists(file_path):
                continue
            success = scrape_day(date_str, day_start, day_end)
            if not success:
                still_failing.append((date_str, day_start, day_end))
        retry_queue = still_failing
        retry_round += 1
      
def save_daily_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"Saved {len(data)} pr at {path}")    

if __name__ == "__main__":
    fetch_dependabot_prs()
