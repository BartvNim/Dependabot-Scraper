import csv
import os
import requests
import time

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
url = "https://api.github.com/graphql"
QUERY = """
query($ecosystem: SecurityAdvisoryEcosystem!, $package: String!, $after: String) {
  securityVulnerabilities(ecosystem: $ecosystem, package: $package, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      vulnerableVersionRange
      firstPatchedVersion { identifier }
      severity
      advisory { ghsaId }
    }
  }
  rateLimit { remaining resetAt cost }
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


def request_api(eco, name):
    """Page through all vulnerabilities for one package.
    Returns (list_of_nodes, last_rate_limit, error_message_or_None)."""
    all_nodes = []
    after = None
    rate = None
    while True:
        variables = {
            "ecosystem": eco,
            "package": name,
            "after": after,
        }
        data = post_with_retries(url, {"query": QUERY, "variables": variables})

        if "errors" in data:
            msg = "; ".join(e.get("message", "") for e in data["errors"])
            return all_nodes, rate, msg

        payload = data["data"]["securityVulnerabilities"]
        rate = data["data"]["rateLimit"]
        all_nodes.extend(payload["nodes"])

        if payload["pageInfo"]["hasNextPage"]:
            after = payload["pageInfo"]["endCursor"]
        else:
            break

    return all_nodes, rate, None



if __name__ == "__main__":
    input_csv = os.path.join("packages.csv")
    output_csv = os.path.join("converted_prs/packages.csv")
    # resume_from = ("NPM", "@hpke/core")
    # found = False
    with open(output_csv, "w", encoding="utf-8", newline='') as o:
        writer = csv.writer(o)
        with open(input_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                eco = row["ecosystem"]
                name = row["package_name"]

                eco_not_in_securitylist = ["DOCKER", "TERRAFORM", "CONDA", "HELM", "SM"]
                if eco in eco_not_in_securitylist:
                    continue
                
                nodes, rate, error = request_api(eco, name)

                if error:
                    print(f"! error for {eco}/{name}: {error}")
                    continue

                for node in nodes:
                    fpv = node.get("firstPatchedVersion") or {}
                    writer.writerow([
                        eco,
                        name,
                        node["advisory"]["ghsaId"],
                        node["severity"],
                        node["vulnerableVersionRange"],
                        fpv.get("identifier", ""),
                    ])
                o.flush() 

                print(f"{eco}/{name}: {len(nodes)} vuln(s)  (remaining: {rate['remaining']})")
                if rate["remaining"] < 5:
                    print(f"Rate limit nearly exhausted, resets at {rate['resetAt']}. Sleeping 60s...")
                    time.sleep(1800)