#!/usr/bin/env python3
"""Repository discovery for patuh.

Lists the owner's repositories, diffs them against the registry
(projects.json minus removed_repositories) and keeps ONE GitHub issue on
this repository up to date with whatever patuh has not enrolled yet, each
with a best-guess coverage tier. It reports and proposes - patuh never
enrolls a repository, writes a baseline or adds a gate workflow on its own;
Irvan gets the first word on what a new project is (WhatsApp 2026-11-23
13:13). The weekly patuh.yml run stays the loud backstop: an unregistered
repo fails registry-missing there.

Runs daily via .github/workflows/discover.yml and on demand. Needs
GITHUB_TOKEN with issues:write on this repository.
"""
import datetime
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import patuh  # noqa: E402

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUE_TITLE_PREFIX = "patuh discovery:"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def api_write(method, url, payload):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(payload).encode(),
        headers={"User-Agent": "patuh-discover",
                 "Accept": "application/vnd.github+json",
                 "Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def issue_body(rows, overdue=False, sched_runs=None):
    lines = []
    if overdue:
        last = max((r["created_at"] for r in (sched_runs or [])), default=None)
        lines += [
            "**Weekly audit overdue**: the `patuh consistency check` workflow has no",
            "scheduled run in the last 7 days (last: %s). The Monday 09:00 WIB cron"
            % (last or "never"),
            "may not be firing. Run it manually meanwhile: Actions -> patuh consistency",
            "check -> Run workflow with apk=true. This flag clears itself once a",
            "scheduled run lands.",
            "",
        ]
    if rows:
        lines += [
            "Patuh found %d repositor%s on the account that are not in its "
            "registry (`projects.json`)." % (len(rows), "y" if len(rows) == 1 else "ies"),
            "",
            "Discovery reports and proposes only - patuh does not enroll a repo,",
            "write a baseline or add a gate workflow on its own. Say what each",
            "project is (or edit `projects.json`) and it gets enrolled.",
            "",
            "| repo | proposed tier | why |",
            "| --- | --- | --- |",
        ]
        for name, tier, reason in rows:
            lines.append("| [%s](https://github.com/irvan-putra/%s) | %s | %s |"
                         % (name, name, tier, reason))
        lines += [
            "",
            "Tiers: `android-app` (full source + release + icon gate), `web-site`",
            "(hygiene and naming checks), `inventory-only` (presence watched,",
            "nothing qualified). The weekly patuh run also fails registry-missing",
            "while any of these stay unregistered.",
            "",
        ]
    else:
        lines += ["No unregistered repositories today.", ""]
    lines += [
        "This issue updates itself on the daily discovery run; it closes",
        "itself when nothing is flagged any more.",
    ]
    return "\n".join(lines)


def main():
    if not TOKEN:
        print("GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    conv = patuh.load_json(os.path.join(REPO_DIR, "conventions.json"))
    registry = patuh.load_json(os.path.join(REPO_DIR, "projects.json"))
    owner = conv["owner"]

    repositories = []
    page = 1
    while True:
        batch = patuh.api_get("%s/users/%s/repos?type=owner&per_page=100&page=%d"
                              % (patuh.GH_API, owner, page))
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    new_names = patuh.discovery_new_repos(registry["projects"],
                                          registry.get("removed_repositories", []),
                                          repositories)
    rows = []
    by_name = {r["name"]: r for r in repositories}
    for name in new_names:
        try:
            tree = patuh.api_get("%s/repos/%s/%s/git/trees/HEAD?recursive=1"
                                 % (patuh.GH_API, owner, name))
            paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
        except Exception as e:
            print("tree fetch failed for %s: %s" % (name, e))
            paths = []
        tier, reason = patuh.propose_coverage(by_name[name], paths)
        rows.append((name, tier, reason))
        print("unregistered: %s -> proposed %s (%s)" % (name, tier, reason))

    # catch-up: flag when the weekly audit's schedule never fires (his ok,
    # WhatsApp 2026-11-23 13:57, after the first Monday cron silently did
    # not run).
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        data = patuh.api_get("%s/repos/%s/patuh/actions/workflows/patuh.yml/runs"
                             "?event=schedule&per_page=5" % patuh.GH_API)
        sched_runs = data.get("workflow_runs", [])
    except Exception as e:
        sched_runs = []
        print("scheduled-run listing failed: %s" % e)
    overdue = patuh.weekly_audit_overdue(sched_runs, now)
    if overdue:
        last = max((r["created_at"] for r in sched_runs), default=None)
        print("weekly audit OVERDUE (last scheduled run: %s)" % (last or "never"))
    else:
        print("weekly audit schedule healthy")

    issues = patuh.api_get("%s/repos/%s/patuh/issues?state=open&per_page=100"
                           % (patuh.GH_API, owner))
    existing = [i for i in issues
                if i.get("title", "").startswith(ISSUE_TITLE_PREFIX)
                and "pull_request" not in i]

    if rows or overdue:
        parts = []
        if rows:
            parts.append("%d unregistered repositor%s" % (len(rows), "y" if len(rows) == 1 else "ies"))
        if overdue:
            parts.append("weekly audit overdue")
        title = "%s %s" % (ISSUE_TITLE_PREFIX, ", ".join(parts))
        body = issue_body(rows, overdue, sched_runs)
        if existing:
            issue = existing[0]
            api_write("PATCH", issue["url"], {"title": title, "body": body})
            print("updated issue #%s: %s" % (issue["number"], issue["html_url"]))
        else:
            issue = api_write("POST", "%s/repos/%s/patuh/issues" % (patuh.GH_API, owner),
                              {"title": title, "body": body})
            print("opened issue #%s: %s" % (issue["number"], issue["html_url"]))
        for extra in existing[1:]:
            api_write("PATCH", extra["url"], {"state": "closed"})
            print("closed duplicate issue #%s" % extra["number"])
    else:
        print("registry complete: %d owner repositories represented, weekly audit on time"
              % len(repositories))
        for issue in existing:
            api_write("PATCH", issue["url"], {"state": "closed"})
            print("closed issue #%s - registry complete" % issue["number"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
