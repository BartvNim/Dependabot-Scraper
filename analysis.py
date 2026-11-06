import os
import json
import requests
import time

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
url = "https://api.github.com/graphql"

query = """
query ($id: ID!) {
  node(id: $id) {
    ... on PullRequest {
      id
      number
      url
      title
      body
      createdAt
      updatedAt
      closedAt
      mergedAt
      state
      merged
      isDraft
      mergeable
      mergeStateStatus
      additions
      deletions
      changedFiles
      baseRefName
      headRefName

      autoMergeRequest {
        enabledAt
        enabledBy { login }
        mergeMethod
      }

      author { login }

      labels(first: 10) {
        nodes { name }
      }

      participants(first: 20) {
        nodes { login }
      }

      repository {
        nameWithOwner
        stargazerCount
        isFork
        forkCount
        diskUsage
        createdAt
        primaryLanguage { name }
        watchers { totalCount }
        issues(states: OPEN) { totalCount }
        pullRequests(states: OPEN) { totalCount }
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 1) {
                nodes { committedDate }
              }
            }
          }
        }
        vulnerabilityAlerts(first: 10, states: [FIXED]) {
          nodes {
            createdAt
            fixedAt
            securityVulnerability {
              severity
              package { name }
              vulnerableVersionRange
            }
          }
        }
      }

      latestOpinionatedReviews(first: 5) {
        nodes {
          author { login }
          state
          submittedAt
        }
      }

      reviews(first: 20) {
        nodes {
          author { login }
          state
          submittedAt
        }
      }

      comments(first: 100) {
        nodes {
          author {
            __typename
            login
          }
          body
          createdAt
        }
      }

      commits(first: 20) {
        nodes {
          commit {
            oid
            committedDate
            message
            statusCheckRollup {
              state
              contexts(first: 10) {
                nodes {
                  ... on CheckRun {
                    name
                    conclusion
                    status
                  }
                  ... on StatusContext {
                    context
                    state
                  }
                }
              }
            }
          }
        }
      }

      timelineItems(first: 50) {
        nodes {
          __typename
          ... on ClosedEvent {
            createdAt
            actor { login }
          }
          ... on ReopenedEvent {
            createdAt
            actor { login }
          }
          ... on MergedEvent {
            createdAt
            actor { login }
            commit { oid }
          }
          ... on HeadRefForcePushedEvent {
            createdAt
            actor { login }
          }
          ... on LabeledEvent {
            createdAt
            actor { login }
            label { name }
          }
          ... on UnlabeledEvent {
            createdAt
            actor { login }
            label { name }
          }
          ... on AssignedEvent {
            createdAt
            actor { login }
            assignee {
              ... on User { login }
            }
          }
          ... on ReviewRequestedEvent {
            createdAt
            actor { login }
            requestedReviewer {
              ... on User { login }
            }
          }
          ... on PullRequestCommit {
            commit {
              oid
              committedDate
              message
              author {
                user { login }
              }
            }
          }
          ... on ReferencedEvent {
            createdAt
            commit {
              oid
              message
            }
          }
          ... on CrossReferencedEvent {
            createdAt
            source {
              ... on PullRequest {
                title
                number
                state
                merged
                headRefName
              }
            }
          }
        }
      }

      files(first: 100) {
        nodes {
          path
          additions
          deletions
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
    "Content-Type": "application/json"
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

if __name__ == "__main__":
    input_path = os.path.join("./filtered_days")
    output_path = os.path.join("./scraped_prs_2")

    files = sorted(os.listdir(input_path))
    for file in files:
      if os.path.isfile(os.path.join(output_path, file)):
          print(f"{file} already exists, Skipping")
          continue
      full_path = os.path.join(input_path, file)
      with open(full_path, "r", encoding="utf-8") as f:
          data = json.load(f)
          datalist = []
          ratelimit = 0
          count = 0
          
          total = len(data)
          print(f"Number of PRS for {file} is {len(data)}" )
          for pr in data:
              variables = {
                  "id": pr["id"]
              }
              count += 1
              print(f"requesting PR for {pr["id"]} - limit left: {ratelimit} - {count}/{total}")
              d = post_with_retries(url, {"query": query, "variables": variables})
              
              #remove ratelimt
              ratelimit = d["data"]["rateLimit"]["remaining"]
              d["data"].pop("rateLimit", None)
              datalist.append(d)

          out_file = os.path.join(output_path, file)
          with open(out_file, "w", encoding="utf-8") as out_f:
              json.dump(datalist, out_f, ensure_ascii=False, indent=2)