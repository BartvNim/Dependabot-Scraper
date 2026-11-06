import json
import csv
import os

def maxLength(text):
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= 30000:
        return text
    return text[: 30000 - len("...[REACHED MAXLENGTH]")] + "...[REACHED MAXLENGTH]"

def extract_event_data(event):
    etype = event.get("__typename")
    data = {}

    if etype in ("LabeledEvent", "UnlabeledEvent"):
        data["label"] = (event.get("label") or {}).get("name")

    elif etype == "MergedEvent":
        data["merge_commit_oid"] = (event.get("commit") or {}).get("oid")

    elif etype == "AssignedEvent":
        data["assignee_login"] = (event.get("assignee") or {}).get("login")

    elif etype == "ReviewRequestedEvent":
        data["requested_reviewer_login"] = (event.get("requestedReviewer") or {}).get("login")

    elif etype == "PullRequestCommit":
        commit = event.get("commit") or {}
        data["oid"] = commit.get("oid")
        data["committed_date"] = commit.get("committedDate")
        data["message"] = maxLength(commit.get("message"))
        data["commit_author_login"] = ((commit.get("author") or {}).get("user") or {}).get("login")

    elif etype == "ReferencedEvent":
        commit = event.get("commit") or {}
        data["referenced_commit_oid"] = commit.get("oid")
        data["referenced_commit_message"] = maxLength(commit.get("message"))

    elif etype == "CrossReferencedEvent":
        source = event.get("source") or {}
        data["source_number"] = source.get("number")
        data["source_title"] = source.get("title")
        data["source_state"] = source.get("state")
        data["source_merged"] = source.get("merged")
        data["source_head_ref"] = source.get("headRefName")

    return data


if __name__ == "__main__":
    input_path = os.path.join("./scraped_prs_2")
    output_path = os.path.join("./converted_prs")
    files = os.listdir(input_path)
    outputfile = os.path.join(output_path + "/prs.csv")
    outputfile_repo = os.path.join(output_path + "/repos.csv")
    outputfile_events = os.path.join(output_path + "/events.csv")
    outputfile_comments = os.path.join(output_path + "/comments.csv")
    count = 0
    with open(outputfile, "w", encoding="utf-8", newline='') as c, open(outputfile_repo, "w", encoding="utf-8", newline='' ) as v, open(outputfile_events, "w", encoding="utf-8", newline='') as e, open(outputfile_comments, "w", encoding="utf-8", newline='') as o:
        pr_writer = csv.writer(c)
        pr_writer.writerow(["pr_id", "repo", "pr_number", "pr_title", "pr_url", "pr_body", "pr_body_length",
                        "state", "is_merged", "is_draft", "mergeable", "merge_state_status",
                        "created_at", "closed_at", "merged_at", "updated_at",
                        "code_additions", "code_deletions", "changed_files",
                        "base_branch_name", "head_branch_name", "auto_merge"
                        ])
        
        repo_writer = csv.writer(v)
        repo_writer.writerow(["repo_name", "stars", "forks", "watchers", "diskusage",
                              "primary_language", "created_at", "last_commit", "issue_count", "pr_count"])

        event_writer = csv.writer(e)
        event_writer.writerow(["pr_id", "repo", "event_nr", "event_type", "event_author", "created_at", "data"])

        comment_writer = csv.writer(o)
        comment_writer.writerow(["pr_id", "comment_nr", "comment_author", "comment_author_type", "comment_body", "comment_body_length", "created_at"])

        for file in files:
            count += 1
            print(file + " " + str(count) + " / " + str(len(files)))
            with open(os.path.join("./scraped_prs_2/" + file), "r", encoding="utf-8") as f:
                data = json.load(f)

                for d in data:
                    node = d.get('data', {}).get('node', {})
                    if node is None:
                        continue
                    repo = node.get('repository', {})
                    commits = node.get("commits", {}).get("nodes", {}) or []
                    first_commit = commits[0].get("commit") if commits else {}
                    events = node.get("timelineItems", {}).get("nodes", []) or []
                    comments = node.get("comments", {}).get("nodes", []) or []


                    pr_writer.writerow([node.get("id"), repo.get("nameWithOwner"), node.get("number"), node.get("title"), node.get("url"), maxLength(node.get("body")), len(node.get("body")),
                                    node.get("state"), node.get("merged"), node.get("isDraft"), node.get("mergeable"), node.get("mergeStateStatus"),
                                    node.get("createdAt"), node.get("closedAt"), node.get("mergedAt"), node.get("updatedAt"),
                                    node.get("additions"), node.get("deletions"), node.get("changedFiles"),
                                    node.get("baseRefName"), node.get("headRefName"), node.get("autoMergeRequest") is not None])
                    
                    repo_writer.writerow([repo.get("nameWithOwner"), repo.get("stargazerCount"), repo.get("forkCount"), repo.get("watchers", {}).get("totalCount", 0), repo.get("diskUsage"), 
                                          (repo.get("primaryLanguage") or {}).get("name"), repo.get("createdAt"), repo.get("defaultBranchRef", {}).get("target", {}).get("history", {}).get("nodes", {})[0].get("committedDate", {}), repo.get("issues", {}).get("totalCount", 0), repo.get("pullRequests", {}).get("totalCount", 0)])

                    for id, event in enumerate(events):
                        if event is None:
                            continue
                        author = (event.get("actor") or {}).get("login")
                        created_at = event.get("createdAt")

                        if event.get("__typename") == "PullRequestCommit":
                            commit = event.get("commit") or {}
                            created_at = commit.get("committedDate")
                            author = ((commit.get("author") or {}).get("user") or {}).get("login")

                        event_writer.writerow([
                            node.get("id"),
                            repo.get("nameWithOwner"),
                            id,
                            event.get("__typename"),
                            author,
                            created_at,
                            json.dumps(extract_event_data(event)) 
                        ])

                    for id, comment in enumerate(comments):
                        if comment is None:
                            continue

                        author = comment.get("author") or {}
                        comment_writer.writerow([
                            node.get("id"),
                            id,
                            author.get("login"),
                            author.get("__typename"),
                            maxLength(comment.get("body")),
                            len(comment.get("body")),
                            comment.get("createdAt")
                        ])