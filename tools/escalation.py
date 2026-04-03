#!/usr/bin/env python3
"""Escalation Engine — deterministic rules for Manager-to-CEO routing.

In the Manager/CEO architecture, the Manager (cheap model) handles routine
work directly. The CEO (expensive model) is consulted only when escalation
rules fire. This saves tokens without sacrificing quality on strategic
decisions.

Rules are defined in orchestra/config.json under "escalation". This engine
evaluates a task against those rules and returns a verdict.

How it works:
- ALWAYS rules: if ANY match, escalate. No exceptions.
- NEVER rules: if ANY match, handle locally. Overrides heuristics.
- If neither fires, apply heuristic scoring (file paths, keywords, dept count).
- Verdicts: ESCALATE, HANDLE_LOCALLY, or UNCERTAIN (let the manager decide).

Integrates with:
- Config: reads escalation rules from orchestra/config.json
- Hooks: can be wired as a PreToolUse hook to auto-gate expensive actions
- Budget: escalation count feeds into token economist reports

Usage:
    # Check if a task should escalate
    python3 tools/escalation.py check "Refactor the payment webhook handler"

    # Check with file context
    python3 tools/escalation.py check "Fix the login bug" --files auth.py

    # Check multi-department task
    python3 tools/escalation.py check "Redesign the dashboard" --depts frontend backend

    # Dry-run: show which rules would fire
    python3 tools/escalation.py explain "Add a new pricing tier"

    # Show current rules
    python3 tools/escalation.py rules

    # Format a CEO brief from a task description
    python3 tools/escalation.py brief "Add Stripe metered billing" \
        --context "User requested usage-based pricing" \
        --recommendation "Use Stripe meters API, add billing route"
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CONFIG_PATH = Path("orchestra/config.json")

# Keywords that suggest strategic/sensitive work
SENSITIVE_KEYWORDS = {
    "auth", "payment", "pricing", "billing", "security", "migration",
    "schema", "revenue", "positioning", "architecture", "breaking",
    "delete", "remove", "rollback", "credentials", "secret", "token",
}

# File patterns that suggest escalation
SENSITIVE_FILE_PATTERNS = [
    r"auth\.",
    r"payment",
    r"pricing",
    r"billing",
    r"migration",
    r"schema",
    r"\.env",
    r"secret",
    r"credential",
]


@dataclass
class EscalationResult:
    verdict: str  # ESCALATE, HANDLE_LOCALLY, UNCERTAIN
    reason: str
    matched_rules: list[str]
    score: float  # 0.0 (definitely local) to 1.0 (definitely escalate)

    def __str__(self) -> str:
        rules = ", ".join(self.matched_rules) if self.matched_rules else "none"
        return f"[{self.verdict}] {self.reason} (score={self.score:.2f}, rules=[{rules}])"


def load_config() -> dict:
    """Load escalation config from orchestra/config.json."""
    if not CONFIG_PATH.exists():
        return {"always": [], "never": [], "brief_max_tokens": 500}
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    return config.get("escalation", {"always": [], "never": [], "brief_max_tokens": 500})


def _rule_matches(rule: str, task: str, files: list[str], depts: list[str]) -> bool:
    """Check if a natural-language rule matches the given context."""
    rule_lower = rule.lower()
    task_lower = task.lower()

    # Multi-department rules
    if "multi-department" in rule_lower or "2+ department" in rule_lower:
        return len(depts) >= 2

    # Auth/payment file rules
    if "auth" in rule_lower and "payment" in rule_lower:
        return any("auth" in f.lower() or "payment" in f.lower() for f in files)
    if "auth" in rule_lower:
        if any("auth" in f.lower() for f in files):
            return True
    if "payment" in rule_lower:
        if any("payment" in f.lower() for f in files):
            return True

    # Revenue/positioning rules
    if "revenue" in rule_lower or "positioning" in rule_lower:
        return any(kw in task_lower for kw in ["revenue", "pricing", "positioning", "monetiz"])

    # Architecture rules
    if "architecture" in rule_lower:
        return any(kw in task_lower for kw in [
            "new table", "new route", "new mcp", "schema", "migration", "architecture"
        ])

    # User-explicit escalation
    if "user explicitly" in rule_lower or "ceo review" in rule_lower:
        return any(kw in task_lower for kw in ["ask the ceo", "get opus", "ceo review"])

    # Retry rules
    if "twice" in rule_lower and "failing" in rule_lower:
        return False  # Can't detect this from task description alone

    # File/search/status rules (for NEVER)
    if "file read" in rule_lower or "search" in rule_lower or "status check" in rule_lower:
        return any(kw in task_lower for kw in ["read", "search", "grep", "status", "check"])

    # Single-file edits
    if "single-file" in rule_lower:
        return len(files) <= 1 and len(depts) <= 1

    # Git operations
    if "git operation" in rule_lower:
        return any(kw in task_lower for kw in ["commit", "diff", "log", "push", "branch"])

    # Deploy/smoke test
    if "deploy" in rule_lower or "smoke test" in rule_lower:
        return any(kw in task_lower for kw in ["deploy", "smoke test"])

    # RAG/memory queries
    if "rag" in rule_lower or "factual question" in rule_lower:
        return any(kw in task_lower for kw in ["rag", "query", "what is", "how does"])

    # Subagent spawning
    if "subagent" in rule_lower:
        return "subagent" in task_lower or "spawn" in task_lower

    # Fallback: check if any words from the rule appear in the task
    rule_words = set(re.findall(r'\b\w{4,}\b', rule_lower))
    task_words = set(re.findall(r'\b\w{4,}\b', task_lower))
    overlap = rule_words & task_words
    return len(overlap) >= 2


def _heuristic_score(task: str, files: list[str], depts: list[str]) -> float:
    """Score 0.0–1.0 based on heuristics when no explicit rule fires."""
    score = 0.0
    task_lower = task.lower()

    # Keyword sensitivity
    task_words = set(re.findall(r'\b\w+\b', task_lower))
    sensitive_hits = task_words & SENSITIVE_KEYWORDS
    score += min(len(sensitive_hits) * 0.15, 0.45)

    # Sensitive file patterns
    for f in files:
        for pattern in SENSITIVE_FILE_PATTERNS:
            if re.search(pattern, f, re.IGNORECASE):
                score += 0.2
                break

    # Department count
    if len(depts) >= 3:
        score += 0.3
    elif len(depts) >= 2:
        score += 0.2

    return min(score, 1.0)


def evaluate(
    task: str,
    files: Optional[list[str]] = None,
    depts: Optional[list[str]] = None,
) -> EscalationResult:
    """Evaluate whether a task should be escalated to the CEO.

    Args:
        task: Description of the task.
        files: Files the task will touch.
        depts: Departments involved.

    Returns:
        EscalationResult with verdict, reason, matched rules, and score.
    """
    files = files or []
    depts = depts or []
    config = load_config()

    # Check ALWAYS rules first — they take priority over everything
    always_matches = []
    for rule in config.get("always", []):
        if _rule_matches(rule, task, files, depts):
            always_matches.append(rule)

    if always_matches:
        return EscalationResult(
            verdict="ESCALATE",
            reason=f"Matched ALWAYS rule: {always_matches[0]}",
            matched_rules=always_matches,
            score=1.0,
        )

    # Check NEVER rules (override heuristics but not ALWAYS)
    never_matches = []
    for rule in config.get("never", []):
        if _rule_matches(rule, task, files, depts):
            never_matches.append(rule)

    if never_matches:
        return EscalationResult(
            verdict="HANDLE_LOCALLY",
            reason=f"Matched NEVER rule: {never_matches[0]}",
            matched_rules=never_matches,
            score=0.0,
        )

    # Heuristic scoring
    score = _heuristic_score(task, files, depts)
    if score >= 0.6:
        return EscalationResult(
            verdict="ESCALATE",
            reason="Heuristic score above threshold",
            matched_rules=[],
            score=score,
        )
    elif score >= 0.3:
        return EscalationResult(
            verdict="UNCERTAIN",
            reason="Moderate sensitivity — manager should decide",
            matched_rules=[],
            score=score,
        )
    else:
        return EscalationResult(
            verdict="HANDLE_LOCALLY",
            reason="Low sensitivity — routine work",
            matched_rules=[],
            score=score,
        )


def format_brief(
    topic: str,
    context: str = "",
    recommendation: str = "",
    max_tokens: int = 500,
) -> str:
    """Format a CEO brief for escalation via claude-peers.

    Args:
        topic: What the brief is about.
        context: Bullet points of relevant context.
        recommendation: Manager's recommendation.
        max_tokens: Max length (chars * 4 rough estimate).
    """
    lines = [f"BRIEF: {topic}", "Decision needed: [one sentence]"]

    if context:
        lines.append("Context:")
        for line in context.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(f"- {line}" if not line.startswith("-") else f"  {line}")

    if recommendation:
        lines.append(f"My recommendation: {recommendation}")

    lines.append("RAG refs: [tags the CEO can query for deeper context]")

    text = "\n".join(lines)
    char_limit = max_tokens * 4
    if len(text) > char_limit:
        text = text[:char_limit] + "\n...[truncated]"
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 tools/escalation.py <command> [args]")
        print("Commands: check, explain, rules, brief")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "rules":
        config = load_config()
        print("ALWAYS escalate:")
        for r in config.get("always", []):
            print(f"  - {r}")
        print("\nNEVER escalate:")
        for r in config.get("never", []):
            print(f"  - {r}")
        print(f"\nBrief max tokens: {config.get('brief_max_tokens', 500)}")

    elif cmd in ("check", "explain"):
        if len(sys.argv) < 3:
            print(f"Usage: python3 tools/escalation.py {cmd} \"task description\" [--files f1 f2] [--depts d1 d2]")
            sys.exit(1)
        task = sys.argv[2]
        files = []
        depts = []
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--files":
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    files.append(sys.argv[i])
                    i += 1
            elif sys.argv[i] == "--depts":
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    depts.append(sys.argv[i])
                    i += 1
            else:
                i += 1

        result = evaluate(task, files, depts)
        print(result)
        if cmd == "explain":
            print(f"\nTask: {task}")
            print(f"Files: {files or 'none'}")
            print(f"Departments: {depts or 'none'}")
            config = load_config()
            print("\nALWAYS rules checked:")
            for r in config.get("always", []):
                matched = _rule_matches(r, task, files, depts)
                print(f"  {'✓' if matched else '✗'} {r}")
            print("\nNEVER rules checked:")
            for r in config.get("never", []):
                matched = _rule_matches(r, task, files, depts)
                print(f"  {'✓' if matched else '✗'} {r}")

    elif cmd == "brief":
        if len(sys.argv) < 3:
            print('Usage: python3 tools/escalation.py brief "topic" --context "..." --recommendation "..."')
            sys.exit(1)
        topic = sys.argv[2]
        context = ""
        recommendation = ""
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--context" and i + 1 < len(sys.argv):
                context = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--recommendation" and i + 1 < len(sys.argv):
                recommendation = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        print(format_brief(topic, context, recommendation))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
