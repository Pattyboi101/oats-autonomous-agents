#!/usr/bin/env python3
"""Build in Public — translate git history + orchestrator logs into social content drafts.

Usage:
    python3 scripts/build_in_public.py

Output:
    /tmp/build_in_public_drafts.md — draft posts for human review before posting.

No external dependencies. Pat reviews and posts manually — this script never posts.
"""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLAYBOOK_PATH = REPO_ROOT / ".orchestra/memory/playbook.md"
OUTPUT_PATH = Path("/tmp/build_in_public_drafts.md")

# Conventional commit types ranked by "audience interest"
INTEREST = {
    "feat": 4,
    "fix": 3,
    "perf": 3,
    "refactor": 2,
    "docs": 1,
    "style": 0,
    "chore": 0,
    "test": 0,
    "ci": 0,
}

# Route files = user-facing, worth mentioning
USER_FACING_PATTERNS = [
    r"routes/",
    r"components\.py",
    r"mcp_server\.py",
    r"landing",
    r"explore",
    r"migrations",
    r"setup",
]

# Numbers in commit messages signal data/stats work
NUMBER_RE = re.compile(r"\b\d{3,}\b")

# Clean up conventional commit prefix for display
COMMIT_PREFIX_RE = re.compile(
    r"^(feat|fix|perf|refactor|docs|style|chore|test|ci)"
    r"(\([^)]+\))?:\s*",
    re.IGNORECASE,
)

SITE_URL = "your-project.ai"


def run(cmd: list[str], cwd=None) -> str:
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd or REPO_ROOT
    )
    return result.stdout.strip()


def get_commits(n: int = 10) -> list[dict]:
    """Return last n commits with hash, type, scope, subject, and file stats."""
    log = run(["git", "log", f"-{n}", "--format=%H\t%s"])
    commits = []
    for line in log.splitlines():
        if "\t" not in line:
            continue
        sha, subject = line.split("\t", 1)

        # Parse conventional commit
        m = re.match(
            r"^(feat|fix|perf|refactor|docs|style|chore|test|ci)"
            r"(\(([^)]+)\))?:\s*(.+)$",
            subject,
            re.IGNORECASE,
        )
        if m:
            ctype = m.group(1).lower()
            scope = m.group(3) or ""
            body = m.group(4)
        else:
            ctype = "other"
            scope = ""
            body = subject

        # Get changed files for this commit
        stat = run(["git", "show", "--stat", "--format=", sha])
        changed_files = [
            line.strip().split("|")[0].strip()
            for line in stat.splitlines()
            if "|" in line
        ]
        n_files = len(changed_files)

        # Score interestingness
        score = INTEREST.get(ctype, 0)
        if NUMBER_RE.search(body):
            score += 1  # data/stats work
        if n_files > 5:
            score += 1  # broad change
        if any(re.search(p, f) for p in USER_FACING_PATTERNS for f in changed_files):
            score += 1  # user-facing

        commits.append(
            {
                "sha": sha[:7],
                "type": ctype,
                "scope": scope,
                "body": body,
                "subject": subject,
                "files": changed_files,
                "n_files": n_files,
                "score": score,
            }
        )
    return commits


def human_oneliner(commit: dict) -> str:
    """Turn a commit into a plain-English one-liner."""
    body = commit["body"]
    ctype = commit["type"]
    scope = commit["scope"]

    prefix_map = {
        "feat": "Added",
        "fix": "Fixed",
        "perf": "Improved performance of",
        "refactor": "Refactored",
        "docs": "Updated docs for",
        "chore": "Maintenance:",
        "test": "Tests:",
        "ci": "CI:",
        "other": "Changed",
    }
    verb = prefix_map.get(ctype, "Changed")

    if scope:
        return f"{verb} {scope}: {body}"
    return f"{verb}: {body}"


def extract_playbook_lessons(text: str) -> list[str]:
    """Pull strategic lessons from the playbook (the numbered list section)."""
    lessons = []
    in_lessons = False
    for line in text.splitlines():
        if "Strategic Lessons" in line:
            in_lessons = True
            continue
        if in_lessons:
            # Stop at the next ## heading that isn't numbered items
            if line.startswith("## ") and "Strategic" not in line and "GOTCHA" not in line:
                break
            m = re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line)
            if m:
                lessons.append(m.group(1))
    return lessons


def extract_playbook_gotchas(text: str) -> list[str]:
    """Pull GOTCHA entries from playbook."""
    gotchas = []
    in_gotcha = False
    current = []
    for line in text.splitlines():
        if line.startswith("## GOTCHA:"):
            if current:
                gotchas.append(" ".join(current))
            current = [line.replace("## GOTCHA:", "").strip()]
            in_gotcha = True
        elif in_gotcha:
            if line.startswith("## "):
                in_gotcha = False
                if current:
                    gotchas.append(" ".join(current))
                current = []
            elif line.strip():
                current.append(line.strip())
    if current:
        gotchas.append(" ".join(current))
    return gotchas


def draft_posts(top_commits: list[dict], lessons: list[str], gotchas: list[str]) -> list[str]:
    """Draft 2-3 social posts from the most interesting material."""
    posts = []
    today = datetime.now().strftime("%Y-%m-%d")

    feat_commits = [c for c in top_commits if c["type"] == "feat"]
    fix_commits = [c for c in top_commits if c["type"] == "fix"]

    # Post 1: What we shipped (if there are feat commits)
    if feat_commits:
        best = feat_commits[0]
        body = best["body"]
        # Trim to fit with URL
        base = f"Shipped: {body}."
        if len(base) + len(f" {SITE_URL}") <= 275:
            post = f"{base} {SITE_URL}"
        else:
            truncated = body[: 230 - len(SITE_URL) - 12] + "..."
            post = f"Shipped: {truncated} {SITE_URL}"
        posts.append(post)

    # Post 2: Honest engineering note (fix or lesson)
    if fix_commits:
        best_fix = fix_commits[0]
        body = best_fix["body"]
        base = f"Bug we fixed: {body}. Every fix is a future gotcha avoided."
        if len(base) <= 280:
            posts.append(base)
        else:
            posts.append(f"Fixed: {body[:240]}.")
    elif gotchas:
        # Pull a gotcha from playbook as an honest lesson post
        gotcha = gotchas[0][:220]
        post = f"Lesson learned building Your Project: {gotcha}"
        if len(post) <= 280:
            posts.append(post)

    # Post 3: "Behind the scenes" — week in commits summary
    if len(top_commits) >= 3:
        feat_count = sum(1 for c in top_commits if c["type"] == "feat")
        fix_count = sum(1 for c in top_commits if c["type"] == "fix")
        parts = []
        if feat_count:
            parts.append(f"{feat_count} feature{'s' if feat_count > 1 else ''}")
        if fix_count:
            parts.append(f"{fix_count} fix{'es' if fix_count > 1 else ''}")
        if parts:
            summary = " and ".join(parts)
            post = f"Last {len(top_commits)} commits on Your Project: {summary}. Building in public. {SITE_URL}"
            if len(post) <= 280:
                posts.append(post)

    # Cap at 3
    return posts[:3]


def main():
    print("Reading git history...")
    commits = get_commits(10)
    if not commits:
        print("No commits found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(commits)} commits. Scoring...")
    commits_sorted = sorted(commits, key=lambda c: c["score"], reverse=True)
    top = commits_sorted[:5]

    # Read playbook
    lessons = []
    gotchas = []
    if PLAYBOOK_PATH.exists():
        print(f"Reading playbook at {PLAYBOOK_PATH}...")
        playbook_text = PLAYBOOK_PATH.read_text()
        lessons = extract_playbook_lessons(playbook_text)
        gotchas = extract_playbook_gotchas(playbook_text)
    else:
        print(f"Playbook not found at {PLAYBOOK_PATH}, skipping.")

    print("Drafting posts...")
    posts = draft_posts(top, lessons, gotchas)

    # Build output
    lines = [
        f"# Build in Public Drafts — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Drafts for human review. Pat posts manually — do not auto-post.",
        "",
        "---",
        "",
        "## Commit Digest (last 10, scored by audience interest)",
        "",
        "| # | SHA | Type | One-liner | Score | Files |",
        "|---|-----|------|-----------|-------|-------|",
    ]
    for i, c in enumerate(commits, 1):
        oneliner = human_oneliner(c)
        lines.append(
            f"| {i} | `{c['sha']}` | {c['type']} | {oneliner} | {c['score']} | {c['n_files']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Top Commits (by interest score)",
        "",
    ]
    for c in top:
        lines.append(f"**{c['sha']}** ({c['type']}, score {c['score']}): {c['body']}")
        if c["files"]:
            lines.append(f"  Files: {', '.join(c['files'][:5])}" + (" ..." if len(c["files"]) > 5 else ""))
        lines.append("")

    if lessons:
        lines += [
            "---",
            "",
            "## Strategic Lessons from Playbook",
            "",
        ]
        for lesson in lessons:
            lines.append(f"- {lesson}")
        lines.append("")

    if gotchas:
        lines += [
            "---",
            "",
            "## Gotchas from Playbook",
            "",
        ]
        for gotcha in gotchas[:3]:
            lines.append(f"- {gotcha[:200]}")
        lines.append("")

    lines += [
        "---",
        "",
        f"## Draft Posts ({len(posts)} total, all under 280 chars)",
        "",
        "Review these before posting. Edit freely — these are starting points.",
        "",
    ]
    for i, post in enumerate(posts, 1):
        lines.append(f"### Post {i} ({len(post)} chars)")
        lines.append("")
        lines.append(post)
        lines.append("")

    if not posts:
        lines.append("_No interesting commits found to draft posts from._")
        lines.append("")

    output = "\n".join(lines)
    OUTPUT_PATH.write_text(output)
    print(f"\nWrote {len(lines)} lines to {OUTPUT_PATH}")
    print(f"Drafted {len(posts)} posts.")
    for i, p in enumerate(posts, 1):
        print(f"\n--- Post {i} ({len(p)} chars) ---")
        print(p)


if __name__ == "__main__":
    main()
